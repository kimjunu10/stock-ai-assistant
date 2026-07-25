"""RAG question-answering API routes.

Phase 5.5-G 종료: 모든 정상 QA 요청은 단일 Agent(create_agent)만 처리한다.
legacy QueryPlan/FactsQaService fallback 은 제거됐다. Agent 를 구성할 수 없으면
(AGENT_ENABLED=false 또는 자격증명 없음) QueryPlan 으로 돌아가지 않고 503 으로
"QA 비활성" 을 명확히 알린다(조용한 규칙 기반 fallback 금지).
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.qa import (
    AgentExecution,
    AgentToolCallInfo,
    BrokerOpinion,
    QaRequest,
    QaResponse,
    Source,
    Visualization,
)
from app.services.agent_qa import get_agent_qa_service

router = APIRouter(prefix="/qa", tags=["qa"])

# Agent 미구성(flag off/자격증명 없음) 시 반환할 명확한 비활성 응답.
_QA_DISABLED_DETAIL = "QA 서비스가 현재 비활성화되어 있습니다(Agent 미구성)."


def _sse(event: str, data: dict | str) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _broker_opinions_from_agent(report_opinions: list[dict]) -> list[BrokerOpinion]:
    """Agent 결과의 구조화 증권사 의견 카드를 스키마 모델로 변환한다."""
    return [BrokerOpinion(**o) for o in report_opinions or []]


@router.post("", response_model=QaResponse)
def ask(req: QaRequest) -> QaResponse:
    """비스트리밍 QA. 단일 Agent 경로만 사용한다(legacy fallback 없음).

    Agent 미구성 시 503(QA 비활성). QueryPlan 으로 돌아가지 않는다.
    """
    agent = get_agent_qa_service()
    if agent is None:
        raise HTTPException(status_code=503, detail=_QA_DISABLED_DETAIL)

    r = agent.answer(
        req.question,
        stock_code=req.stock_code,
        source_id=req.context_source_id,
        source_type=req.context_source_type,
        document_id=req.document_id,
        report_page=req.report_page,
        conversation_id=req.conversation_id,
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
    ui_sources = getattr(r, "sources", [])
    visualizations = getattr(r, "visualizations", [])
    warnings = getattr(r, "warnings", [])
    return QaResponse(
        answer=r.answer,
        sources=[Source(**source) for source in ui_sources],
        invalid_citations=[],
        latency_ms={},
        execution=execution,
        broker_opinions=_broker_opinions_from_agent(getattr(r, "report_opinions", [])),
        visualizations=[Visualization(**item) for item in visualizations],
        warnings=warnings,
    )


@router.post("/stream")
def ask_stream(req: QaRequest) -> StreamingResponse:
    """SSE 스트리밍 QA. 단일 Agent 경로만 사용한다(legacy fallback 없음).

    Agent 미구성 시 503(QA 비활성). 이벤트 순서:
    agent_start → (tool_start/tool_end)* → sources → delta → done.
    """
    agent = get_agent_qa_service()
    if agent is None:
        raise HTTPException(status_code=503, detail=_QA_DISABLED_DETAIL)

    def gen() -> Iterator[str]:
        yield _sse("agent_start", {"question": req.question})
        r = agent.answer(
            req.question,
            stock_code=req.stock_code,
            source_id=req.context_source_id,
            source_type=req.context_source_type,
            document_id=req.document_id,
            report_page=req.report_page,
            conversation_id=req.conversation_id,
        )
        for c in r.tool_calls:
            yield _sse("tool_start", {"name": c.name})
            yield _sse("tool_end", {"name": c.name, "status": c.status})
        ui_sources = getattr(r, "sources", [])
        visualizations = getattr(r, "visualizations", [])
        warnings = getattr(r, "warnings", [])
        yield _sse(
            "sources",
            {
                "sources": ui_sources,
                "visualizations": visualizations,
                "warnings": warnings,
            },
        )
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
                "visualizations": visualizations,
                "warnings": warnings,
            },
        )

    return StreamingResponse(gen(), media_type="text/event-stream")
