"""AgentQaService (Phase 5.5-C, SPEC §12·§16).

단일 금융 QA Agent 실행 계층. create_agent 로 만든 Agent 를 호출하고,
- 전체 timeout(벽시계) 적용,
- 내부 추론 전문 비로그(Tool 호출·결과만 trace),
- 실패 시 안전한 오류 응답(legacy QueryPlan fallback 없음).

이 단계(5.5-C)에서는 API 라우트에 연결하지 않는다(5.5-D). 조립·실행 API 만 제공한다.
feature flag(agent_enabled)가 꺼져 있으면 Agent 를 구성하지 않는다.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from functools import lru_cache

from app.agent.context import QaRuntimeContext, ToolServices
from app.agent.runtime import build_agent
from app.core.config import Settings, settings


@dataclass
class AgentToolCall:
    name: str
    status: str | None = None
    result_count: int | None = None


@dataclass
class AgentQaResult:
    answer: str
    tool_calls: list[AgentToolCall] = field(default_factory=list)
    model_calls: int = 0
    stop_reason: str = "completed"
    error: str | None = None


class AgentQaService:
    """create_agent Agent 를 감싸 timeout·trace·안전 오류를 관리한다."""

    def __init__(self, cfg: Settings, services: ToolServices, *, api_key: str, base_url: str):
        self._cfg = cfg
        self._services = services
        self._agent = build_agent(cfg, api_key=api_key, base_url=base_url)

    def _context(
        self, stock_code, source_type, source_id, document_id, report_page, conversation_id
    ):
        return QaRuntimeContext(
            stock_code=stock_code,
            source_type=source_type,
            source_id=source_id,
            document_id=document_id,
            report_page=report_page,
            conversation_id=conversation_id,
            services=self._services,
        )

    @staticmethod
    def _extract(out: dict) -> AgentQaResult:
        """Agent 결과에서 최종 답변·Tool 호출 요약만 뽑는다. 내부 추론은 저장하지 않는다."""
        msgs = out.get("messages", []) if isinstance(out, dict) else []
        answer = ""
        tool_calls: list[AgentToolCall] = []
        model_calls = 0
        for m in msgs:
            mtype = getattr(m, "type", "")
            if mtype == "ai":
                model_calls += 1
                for tc in getattr(m, "tool_calls", []) or []:
                    tool_calls.append(AgentToolCall(name=tc.get("name", "")))
                content = getattr(m, "content", "")
                if isinstance(content, str) and content.strip():
                    answer = content  # 마지막 ai 텍스트가 최종 답변
        return AgentQaResult(
            answer=answer,
            tool_calls=tool_calls,
            model_calls=model_calls,
            stop_reason="completed",
        )

    def answer(
        self,
        question: str,
        *,
        stock_code: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        document_id: str | None = None,
        report_page: int | None = None,
        conversation_id: str | None = None,
    ) -> AgentQaResult:
        ctx = self._context(
            stock_code, source_type, source_id, document_id, report_page, conversation_id
        )
        payload = {"messages": [{"role": "user", "content": question}]}

        def _invoke() -> dict:
            return self._agent.invoke(payload, context=ctx)

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_invoke)
                out = fut.result(timeout=self._cfg.agent_timeout_seconds)
        except concurrent.futures.TimeoutError:
            return AgentQaResult(
                answer="",
                stop_reason="timeout",
                error="응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.",
            )
        except Exception as e:  # noqa: BLE001 - 내부 예외 비노출
            return AgentQaResult(
                answer="",
                stop_reason="error",
                error=f"일시적 오류({type(e).__name__})로 답변을 완료하지 못했습니다.",
            )
        return self._extract(out)


@lru_cache(maxsize=1)
def get_agent_qa_service() -> AgentQaService | None:
    """feature flag 가 켜져 있고 자격증명이 있으면 AgentQaService 를 구성한다.

    5.5-C 에서는 API 라우트에 연결하지 않는다(구성 가능성만 제공, 기본 flag=false).
    """
    cfg = settings
    if not cfg.agent_enabled:
        return None
    if not cfg.upstage_api_key:
        return None
    from app.db.client import get_supabase_client
    from app.ml.embeddings import UpstageEmbedder
    from app.rag.retrieval import HybridRetriever
    from app.services.facts import FactsService
    from app.services.research_reports import ResearchReportSearch

    client = get_supabase_client()
    embedder = UpstageEmbedder(cfg)
    retriever = HybridRetriever(client, cfg, embedder)
    services = ToolServices(
        facts=FactsService(client),
        retriever=retriever,
        reports=ResearchReportSearch(client, cfg, retriever),
    )
    return AgentQaService(cfg, services, api_key=cfg.upstage_api_key, base_url=cfg.upstage_base_url)
