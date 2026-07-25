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
from app.agent.time_context import SEOUL_TIMEZONE_NAME, current_seoul_datetime
from app.agent.trace import AgentTrace, ToolTrace
from app.agent.validator import (
    collect_evidence,
    collect_report_opinions,
    sanitize_answer,
    validate_answer,
)
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
    # prompt.md §8: 증권사 의견 카드(구조화, stated 목표주가만). 답변과 분리 제공.
    report_opinions: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    visualizations: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class AgentQaService:
    """create_agent Agent 를 감싸 timeout·trace·안전 오류를 관리한다."""

    def __init__(self, cfg: Settings, services: ToolServices, *, api_key: str, base_url: str):
        self._cfg = cfg
        self._services = services
        self._agent = build_agent(cfg, api_key=api_key, base_url=base_url)

    def _context(
        self, stock_code, source_type, source_id, document_id, report_page, conversation_id
    ):
        request_now = current_seoul_datetime()
        return QaRuntimeContext(
            stock_code=stock_code,
            source_type=source_type,
            source_id=source_id,
            document_id=document_id,
            report_page=report_page,
            conversation_id=conversation_id,
            current_datetime=request_now.isoformat(timespec="seconds"),
            current_date=request_now.date().isoformat(),
            timezone=SEOUL_TIMEZONE_NAME,
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
                    payload["_tool_name"] = getattr(m, "name", None)
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
        # 근거 없는 증권사·목표주가 문장은 제거(prompt.md §7). 숫자 재추측 없음.
        answer, sanitized = sanitize_answer(answer, evidence)
        if sanitized:
            validation.errors.append("근거 없는 증권사·목표주가 문장을 답변에서 제거함")
        # 증권사 의견 카드(구조화): Tool 이 확정한 stated 목표주가만. 답변과 분리 제공.
        report_opinions = collect_report_opinions(tool_payloads)
        ui_sources, visualizations, warnings = _build_ui_payload(tool_payloads)

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
            report_opinions=report_opinions,
            sources=ui_sources,
            visualizations=visualizations,
            warnings=warnings,
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
        prices=_build_stock_price_service(cfg),
    )
    return AgentQaService(cfg, services, api_key=api_key, base_url=base_url)


def _build_stock_price_service(cfg: Settings):
    """Phase 6 주가 Tool 서비스. 토스 자격증명이 있으면 실제 클라이언트를 재사용한다.

    자격증명이 없으면 None 을 넣고, Tool 은 컨텍스트 오류로 안전히 error 를 반환한다
    (Agent 경로 전체를 막지 않는다).
    """
    from app.services.stock_prices import StockPriceService

    if not (cfg.toss_client_id and cfg.toss_client_secret):
        return None
    # 프로세스 공유 TossInvestClient(토큰·캐시 공유)를 재사용한다(중복 클라이언트 금지).
    from app.api.routes.stocks import get_toss_client

    return StockPriceService(
        get_toss_client(),
        cache_seconds=cfg.stock_price_cache_seconds,
        rate_limit_retries=cfg.stock_price_rate_limit_retries,
        rate_limit_backoff_seconds=cfg.stock_price_rate_limit_backoff_seconds,
        max_candle_pages=cfg.stock_price_max_candle_pages,
    )


def _build_ui_payload(tool_payloads: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    """ToolResult를 공개 UI view model로 변환한다.

    자연어 답변을 파싱하거나 값을 다시 계산하지 않는다. Tool이 확정해 반환한 data와
    SourceRef만 복사하고, 출처가 없는 시각화는 만들지 않는다.
    """
    source_by_id: dict[str, dict] = {}
    visualizations: list[dict] = []
    warnings: list[str] = []

    for payload in tool_payloads:
        public_sources = [
            source
            for source in payload.get("sources", [])
            if isinstance(source, dict) and source.get("source_id")
        ]
        for source in public_sources:
            source_by_id.setdefault(source["source_id"], source)
        source_ids = [source["source_id"] for source in public_sources]
        if not source_ids or payload.get("status") != "ok":
            warnings.extend(_public_warnings(payload.get("warnings")))
            continue

        data = payload.get("data")
        if not isinstance(data, dict):
            continue
        tool_name = payload.get("_tool_name")
        view = _visualization_for_tool(tool_name, data, source_ids)
        if view is not None:
            visualizations.append(view)
        warnings.extend(_public_warnings(payload.get("warnings")))

    return list(source_by_id.values()), visualizations, list(dict.fromkeys(warnings))


def _public_warnings(value) -> list[str]:
    if not isinstance(value, list):
        return []
    warnings: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            continue
        if "내부 조회 오류" in item:
            warnings.append("데이터를 불러오는 중 문제가 발생했습니다.")
        elif (
            "이 주제에 해당하는 근거는 답변에서 제외할 것" in item
            or item.startswith("포함 요청 주제:")
            or "target_price_status='stated'" in item
        ):
            continue
        else:
            warnings.append(item[:300])
    return warnings


def _visualization_for_tool(
    tool_name: str | None, data: dict, source_ids: list[str]
) -> dict | None:
    """Tool 이름은 라우팅이 아니라 이미 실행된 typed 결과의 view 종류만 결정한다."""
    if tool_name == "search_news" and isinstance(data.get("news"), list):
        filters = data.get("applied_filters")
        return {
            "type": "news_cards",
            "title": "최근 뉴스",
            "data": {
                "items": data["news"],
                "date_from": filters.get("date_from") if isinstance(filters, dict) else None,
                "date_to": filters.get("date_to") if isinstance(filters, dict) else None,
            },
            "source_ids": source_ids,
        }

    if tool_name == "get_stock_prices":
        daily = data.get("daily")
        if isinstance(daily, list) and len(daily) >= 2:
            return {
                "type": "price_line",
                "title": "실제 주가 흐름",
                "data": {
                    "points": daily,
                    "quote": data.get("quote"),
                    "period": data.get("period"),
                },
                "source_ids": source_ids,
            }
        return {
            "type": "price_snapshot",
            "title": "실제 주가",
            "data": {"quote": data.get("quote"), "period": data.get("period")},
            "source_ids": source_ids,
        }

    if tool_name == "calculate_event_return":
        return {
            "type": "event_return",
            "title": "발표 전후 주가 변화",
            "data": data,
            "source_ids": source_ids,
        }

    if tool_name == "get_financial_facts" and isinstance(data.get("facts"), list):
        return {
            "type": "financial_series",
            "title": "DART 공식 재무정보",
            "data": {"items": data["facts"]},
            "source_ids": source_ids,
        }

    if tool_name == "get_disclosure_values" and isinstance(data.get("values"), list):
        return {
            "type": "disclosure_metrics",
            "title": "공시 핵심 정보",
            "data": {"items": data["values"]},
            "source_ids": source_ids,
        }

    if tool_name == "search_research_reports" and isinstance(data.get("reports"), list):
        targets = [
            report
            for report in data["reports"]
            if isinstance(report, dict)
            and report.get("target_price_status") == "stated"
            and report.get("target_price") is not None
        ]
        if targets:
            return {
                "type": "broker_targets",
                "title": "증권사 목표주가",
                "data": {"items": targets},
                "source_ids": source_ids,
            }

    if tool_name == "lookup_financial_term" and data.get("term"):
        return {
            "type": "term_definition",
            "title": "금융용어",
            "data": data,
            "source_ids": source_ids,
        }
    return None
