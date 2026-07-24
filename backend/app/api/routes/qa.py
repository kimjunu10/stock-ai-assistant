"""RAG question-answering API routes (Phase 2)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from functools import lru_cache

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.db.client import get_supabase_client
from app.ml.embeddings import UpstageEmbedder
from app.ml.generation import SolarGenerator
from app.rag.retrieval import HybridRetriever
from app.schemas.qa import AgentExecution, AgentToolCallInfo, QaRequest, QaResponse
from app.services.agent_qa import get_agent_qa_service
from app.services.facts import FactsService
from app.services.rag_qa import validate_citations
from app.services.rag_qa_facts import FactsQaService
from app.services.research_reports import ResearchReportSearch

router = APIRouter(prefix="/qa", tags=["qa"])


@lru_cache(maxsize=1)
def get_qa_service() -> FactsQaService:
    """단일 QA 진입점.

    QueryPlan(규칙 기반)으로 질문 유형을 판정해 하나의 서비스가 처리한다:
    - 순수 뉴스 질문 → 기존 HybridRetriever 뉴스 검색만 사용(회귀 없음)
    - 숫자 질문 → FactsService SQL 결과(실제값, 단위·기간·출처 보존)
    - 용어 질문 → lookup_term 결과
    - 전망·목표주가·투자의견·증권사 질문 → search_research_reports(리포트 검색)
    - 혼합 질문 → 위를 병렬 결합
    """
    client = get_supabase_client()
    embedder = UpstageEmbedder(settings)
    retriever = HybridRetriever(client, settings, embedder)
    facts = FactsService(client)
    generator = SolarGenerator(settings)
    reports = ResearchReportSearch(client, settings, retriever)
    return FactsQaService(retriever, facts, generator, settings, reports=reports)


def _sse(event: str, data: dict | str) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _answer_agent(req: QaRequest) -> QaResponse | None:
    """Agent 경로. feature flag(agent_enabled)가 켜져 있을 때만 동작.

    꺼져 있거나 구성 불가면 None 을 반환해 호출부가 기존 결정론적 경로로 처리한다.
    (이는 legacy QueryPlan fallback 이 아니라, 아직 Agent 를 켜지 않은 상태의 기본 경로다.)
    """
    agent = get_agent_qa_service()
    if agent is None:
        return None
    r = agent.answer(
        req.question,
        stock_code=req.stock_code,
        source_id=req.context_source_id,
        source_type=req.context_source_type,
    )
    execution = AgentExecution(
        agent=True,
        tool_calls=[
            AgentToolCallInfo(name=c.name, status=c.status, result_count=c.result_count)
            for c in r.tool_calls
        ],
        model_calls=r.model_calls,
        stop_reason=r.stop_reason,
        validation_errors=r.validation_errors,
        source_ids=r.source_ids,
    )
    return QaResponse(
        answer=r.answer,
        sources=[],
        invalid_citations=[],
        latency_ms={},
        execution=execution,
    )


@router.post("", response_model=QaResponse)
def ask(req: QaRequest) -> QaResponse:
    """비스트리밍 QA. 스트리밍은 아래 /qa/stream 를 사용한다.

    feature flag(agent_enabled)가 켜져 있으면 단일 Agent 경로, 아니면 기존 결정론적 경로.
    운영 기본값은 flag=false(기존 경로 유지).
    """

    agent_resp = _answer_agent(req)
    if agent_resp is not None:
        return agent_resp

    service = get_qa_service()
    result = service.answer(
        req.question,
        stock_code=req.stock_code,
        context_source_id=req.context_source_id,
    )
    return QaResponse(
        answer=result.answer,
        sources=result.sources,
        numeric_sources=result.numeric_sources,
        report_sources=result.report_sources,
        term=result.term,
        invalid_citations=result.invalid_citations,
        latency_ms=result.latency_ms,
        query_plan=result.plan,  # deprecated: Agent 전환 완료 후 제거
    )


def _stream_agent(req: QaRequest) -> Iterator[str] | None:
    """Agent 경로 SSE. flag off/구성불가면 None(기존 경로로).

    5.5-D 에서는 Agent 결과를 받아 agent_start→(tool 요약)→delta→done 순으로 포장한다.
    토큰 단위 실시간 스트리밍·tool_start/end 세분화는 5.5-E/G 튜닝 영역이다.
    """
    agent = get_agent_qa_service()
    if agent is None:
        return None

    def gen() -> Iterator[str]:
        yield _sse("agent_start", {"question": req.question})
        r = agent.answer(
            req.question,
            stock_code=req.stock_code,
            source_id=req.context_source_id,
            source_type=req.context_source_type,
        )
        for c in r.tool_calls:
            yield _sse("tool_start", {"name": c.name})
            yield _sse("tool_end", {"name": c.name, "status": c.status})
        yield _sse("sources", {"sources": []})
        if r.error:
            yield _sse("error", {"message": r.error, "stop_reason": r.stop_reason})
            return
        yield _sse("delta", {"text": r.answer})
        yield _sse(
            "done",
            {
                "stop_reason": r.stop_reason,
                "model_calls": r.model_calls,
                "tool_calls": [c.name for c in r.tool_calls],
            },
        )

    return gen()


@router.post("/stream")
def ask_stream(req: QaRequest) -> StreamingResponse:
    """SSE 스트리밍 QA. feature flag 에 따라 Agent 경로 또는 기존 결정론적 경로.

    기존 경로: sources → token* → done. Agent 경로: agent_start → tool_* → delta → done.
    """

    agent_gen = _stream_agent(req)
    if agent_gen is not None:
        return StreamingResponse(agent_gen, media_type="text/event-stream")

    service = get_qa_service()
    sources, numeric_sources, report_sources, term, token_iter = service.stream(
        req.question,
        stock_code=req.stock_code,
        context_source_id=req.context_source_id,
    )

    def gen() -> Iterator[str]:
        yield _sse(
            "sources",
            {
                "sources": sources,
                "numeric_sources": numeric_sources,
                "report_sources": report_sources,
                "term": term,
            },
        )
        buffer: list[str] = []
        for token in token_iter:
            buffer.append(token)
            yield _sse("token", {"text": token})
        answer = "".join(buffer)
        invalid = validate_citations(answer, len(sources))
        yield _sse("done", {"invalid_citations": invalid})

    return StreamingResponse(gen(), media_type="text/event-stream")
