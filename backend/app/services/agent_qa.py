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
import json
import time
from dataclasses import dataclass, field
from functools import lru_cache

from app.agent.context import QaRuntimeContext, ToolServices
from app.agent.runtime import build_agent
from app.agent.trace import AgentTrace, ToolTrace
from app.agent.validator import collect_evidence, validate_answer
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
    source_ids: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    trace: dict = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0


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
    def _extract(out: dict) -> tuple[str, list[AgentToolCall], int, list[dict], int, int]:
        """Agent 결과에서 최종 답변·Tool 호출 요약·Tool payload·토큰 usage 를 뽑는다.

        내부 추론(chain-of-thought)은 저장하지 않는다. Tool payload 는 검증·trace 용
        메타/근거 dict 만 수집(원문 본문 아님).
        """
        msgs = out.get("messages", []) if isinstance(out, dict) else []
        answer = ""
        tool_calls: list[AgentToolCall] = []
        tool_payloads: list[dict] = []
        model_calls = 0
        in_tok = out_tok = 0
        for m in msgs:
            mtype = getattr(m, "type", "")
            if mtype == "ai":
                model_calls += 1
                um = getattr(m, "usage_metadata", None) or {}
                in_tok += int(um.get("input_tokens", 0) or 0)
                out_tok += int(um.get("output_tokens", 0) or 0)
                for tc in getattr(m, "tool_calls", []) or []:
                    tool_calls.append(AgentToolCall(name=tc.get("name", "")))
                content = getattr(m, "content", "")
                if isinstance(content, str) and content.strip():
                    answer = content  # 마지막 ai 텍스트가 최종 답변
            elif mtype == "tool":
                content = getattr(m, "content", "")
                payload = None
                if isinstance(content, str):
                    try:
                        payload = json.loads(content)
                    except (ValueError, TypeError):
                        payload = None
                if isinstance(payload, dict):
                    tool_payloads.append(payload)
                    # Tool 결과 status·result_count 를 마지막 동일이름 호출에 반영
                    name = getattr(m, "name", None)
                    for c in reversed(tool_calls):
                        if c.name == name and c.status is None:
                            c.status = payload.get("status")
                            data = payload.get("data")
                            if isinstance(data, dict):
                                for key in ("facts", "reports", "values", "news", "disclosures"):
                                    if isinstance(data.get(key), list):
                                        c.result_count = len(data[key])
                                        break
                            break
        return answer, tool_calls, model_calls, tool_payloads, in_tok, out_tok

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
        request_id: str = "",
    ) -> AgentQaResult:
        ctx = self._context(
            stock_code, source_type, source_id, document_id, report_page, conversation_id
        )
        payload = {"messages": [{"role": "user", "content": question}]}
        # LangGraph 스텝 하드 상한: 모델·Tool loop 폭주를 그래프 레벨에서 차단(GraphRecursionError).
        # (모델호출 + Tool 호출) 여유분. ThreadPoolExecutor timeout 이 못 끊는 무한 loop 방지.
        recursion_limit = 2 * (self._cfg.agent_max_model_calls + self._cfg.agent_max_tool_calls) + 2
        config = {"recursion_limit": recursion_limit}

        def _invoke() -> dict:
            return self._agent.invoke(payload, context=ctx, config=config)

        t0 = time.perf_counter()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_invoke)
                out = fut.result(timeout=self._cfg.agent_timeout_seconds)
        except concurrent.futures.TimeoutError:
            return self._failed(request_id, "timeout", "응답 시간이 초과되었습니다.", t0)
        except Exception as e:  # noqa: BLE001 - 내부 예외 비노출
            # LangGraph 스텝 상한 초과는 Tool loop 폭주 → 명확한 stop_reason 으로 구분.
            if type(e).__name__ == "GraphRecursionError":
                return self._failed(
                    request_id,
                    "step_limit",
                    "조회 단계 한도를 초과해 답변을 마치지 못했습니다.",
                    t0,
                )
            return self._failed(
                request_id, "error", f"일시적 오류({type(e).__name__})로 답변하지 못했습니다.", t0
            )

        answer, tool_calls, model_calls, tool_payloads, in_tok, out_tok = self._extract(out)

        # ── 코드 검증(SPEC §12.2): 숫자를 고치지 않고 오류만 기록 ──
        evidence = collect_evidence(tool_payloads)
        validation = validate_answer(answer, evidence)

        total_ms = int((time.perf_counter() - t0) * 1000)
        trace = AgentTrace(
            request_id=request_id,
            model_calls=model_calls,
            tool_calls=[
                ToolTrace(name=c.name, status=c.status, result_count=c.result_count)
                for c in tool_calls
            ],
            source_ids=sorted(evidence.source_ids),
            stop_reason="completed",
            validation_errors=validation.errors,
            total_latency_ms=total_ms,
        )
        return AgentQaResult(
            answer=answer,
            tool_calls=tool_calls,
            model_calls=model_calls,
            stop_reason="completed",
            source_ids=sorted(evidence.source_ids),
            validation_errors=validation.errors,
            trace=trace.to_log_dict(),
            input_tokens=in_tok,
            output_tokens=out_tok,
        )

    def _failed(self, request_id: str, reason: str, message: str, t0: float) -> AgentQaResult:
        total_ms = int((time.perf_counter() - t0) * 1000)
        trace = AgentTrace(request_id=request_id, stop_reason=reason, total_latency_ms=total_ms)
        return AgentQaResult(
            answer="", stop_reason=reason, error=message, trace=trace.to_log_dict()
        )


@lru_cache(maxsize=1)
def get_agent_qa_service() -> AgentQaService | None:
    """feature flag 가 켜져 있고 자격증명이 있으면 AgentQaService 를 구성한다.

    5.5-C 에서는 API 라우트에 연결하지 않는다(구성 가능성만 제공, 기본 flag=false).
    """
    cfg = settings
    if not cfg.agent_enabled:
        return None
    api_key, base_url = cfg.agent_model_credentials()
    if not api_key:
        return None
    from app.db.client import get_supabase_client
    from app.ml.embeddings import UpstageEmbedder
    from app.rag.retrieval import HybridRetriever
    from app.services.facts import FactsService
    from app.services.research_reports import ResearchReportSearch

    client = get_supabase_client()
    embedder = UpstageEmbedder(cfg)  # 임베딩은 Upstage 유지(Agent 모델과 별개)
    retriever = HybridRetriever(client, cfg, embedder)
    services = ToolServices(
        facts=FactsService(client),
        retriever=retriever,
        reports=ResearchReportSearch(client, cfg, retriever),
    )
    return AgentQaService(cfg, services, api_key=api_key, base_url=base_url)
