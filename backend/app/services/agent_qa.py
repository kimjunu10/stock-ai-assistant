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
import logging
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache

from app.agent.context import QaRuntimeContext, ToolServices
from app.agent.event_reference import (
    EventResolution,
    clarification_message,
    event_date_of,
    resolve_event,
)
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
from app.services.stock_context_safety import (
    StockContextDecision,
    validate_execution_stock_context,
    validate_input_source_stock_context,
    validate_question_stock_context,
)

logger = logging.getLogger(__name__)


@dataclass
class AgentToolCall:
    name: str
    status: str | None = None
    result_count: int | None = None
    stock_code: str | None = None


@dataclass
class AgentQaResult:
    answer: str
    tool_calls: list[AgentToolCall] = field(default_factory=list)
    model_calls: int = 0
    stop_reason: str = "completed"
    error: str | None = None
    error_code: str | None = None
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

    @lru_cache(maxsize=128)
    def _stock_name(self, stock_code: str) -> str | None:
        """기존 FactsService 연결로 공식 회사명을 조회하되 실패 시 추측하지 않는다."""

        resolver = getattr(getattr(self._services, "facts", None), "get_stock_name", None)
        if not callable(resolver):
            return None
        try:
            return resolver(stock_code)
        except Exception:  # noqa: BLE001 - 회사명 부가 문맥 실패가 QA 요청을 막지 않게
            return None

    def _context(
        self,
        stock_code,
        source_type,
        source_id,
        document_id,
        report_page,
        conversation_id,
        event_resolution: EventResolution | None = None,
        request_id: str | None = None,
        user_question: str | None = None,
    ):
        request_now = current_seoul_datetime()
        res = event_resolution or EventResolution(status="none")
        event = res.event
        event_day = event_date_of(event) if event is not None else None
        # 사건은 확정됐지만 발표일을 확인할 수 없으면 사건 기준 계산을 할 수 없다.
        # 날짜를 추정하지 않고 미확정으로 강등한다(§4 "정보가 불충분하면 호출하지 않기").
        resolved = res.status == "resolved" and event is not None and event_day is not None
        status = "resolved" if resolved else ("none" if res.status == "resolved" else res.status)
        return QaRuntimeContext(
            stock_code=stock_code,
            company_name=self._stock_name(stock_code) if stock_code else None,
            source_type=source_type,
            source_id=source_id,
            document_id=document_id,
            report_page=report_page,
            conversation_id=conversation_id,
            request_id=request_id,
            user_question=user_question,
            current_datetime=request_now.isoformat(timespec="seconds"),
            current_date=request_now.date().isoformat(),
            timezone=SEOUL_TIMEZONE_NAME,
            services=self._services,
            # 발표일을 확인할 수 없는 사건은 resolved 로 취급하지 않는다(날짜 추정 금지).
            event_status=status,
            event_id=event.event_id if resolved else None,
            event_date=event_day.isoformat() if resolved else None,
            event_title=event.title if resolved else None,
            event_stock_code=event.stock_code if resolved else None,
            event_candidates=res.candidates or None,
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
                    args = tc.get("args") if isinstance(tc, dict) else None
                    tool_calls.append(
                        AgentToolCall(
                            name=tc.get("name", ""),
                            stock_code=(
                                args.get("stock_code")
                                if isinstance(args, dict)
                                and isinstance(args.get("stock_code"), str)
                                else None
                            ),
                        )
                    )
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
        event_context: list | None = None,
        selected_event_id: str | None = None,
    ) -> AgentQaResult:
        request_id = request_id or uuid.uuid4().hex
        stock_decision = validate_question_stock_context(question, stock_code)
        if not stock_decision.allowed:
            logger.warning(
                "STOCK_CONTEXT_BLOCKED code=%s selected_stock_code=%s "
                "mentioned_stocks=%s correlation_id=%s",
                stock_decision.error_code,
                stock_code,
                [
                    {
                        "stock_code": mention.stock_code,
                        "supported": mention.supported,
                    }
                    for mention in stock_decision.mentions
                ],
                request_id or "unknown",
            )
            return self._blocked(request_id, stock_decision)

        input_source_violation = validate_input_source_stock_context(
            selected_stock_code=stock_code,
            event_context=event_context,
            source_id=source_id,
        )
        if input_source_violation is not None:
            logger.error(
                "STOCK_CONTEXT_CONTAMINATION code=%s failed_layer=%s "
                "selected_stock_code=%s observed_stock_codes=%s correlation_id=%s",
                input_source_violation.error_code,
                input_source_violation.failed_layer,
                stock_code,
                input_source_violation.observed_codes,
                request_id,
            )
            decision = StockContextDecision(
                allowed=False,
                error_code=input_source_violation.error_code,
                message=input_source_violation.message,
                selected_stock_code=stock_code,
                selected_stock_name=stock_decision.selected_stock_name,
            )
            return self._blocked(request_id, decision)

        # 사건 확정은 코드가 한다(§4). 모델은 사건을 고르지 않는다.
        resolution = resolve_event(list(event_context or []), selected_event_id=selected_event_id)
        ctx = self._context(
            stock_code,
            source_type,
            source_id,
            document_id,
            report_page,
            conversation_id,
            resolution,
            request_id,
            question,
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

        violation = validate_execution_stock_context(
            selected_stock_code=stock_code,
            runtime_stock_code=ctx.stock_code,
            tool_calls=tool_calls,
            tool_payloads=tool_payloads,
            runtime_events=ctx.stock_context_events,
        )
        if violation is not None:
            logger.error(
                "STOCK_CONTEXT_CONTAMINATION code=%s failed_layer=%s "
                "selected_stock_code=%s observed_stock_codes=%s correlation_id=%s",
                violation.error_code,
                violation.failed_layer,
                stock_code,
                violation.observed_codes,
                request_id or "unknown",
            )
            decision = StockContextDecision(
                allowed=False,
                error_code=violation.error_code,
                message=violation.message,
                selected_stock_code=stock_code,
                selected_stock_name=stock_decision.selected_stock_name,
            )
            return self._blocked(
                request_id,
                decision,
                tool_calls=tool_calls,
                model_calls=model_calls,
                input_tokens=in_tok,
                output_tokens=out_tok,
                t0=t0,
            )

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

        # 사건 근거가 없는 '사건 이후 수익률' 답변은 안전 답변으로 전환한다(§6).
        # 숫자를 고치거나 보충하지 않는다 — 잘못된 기간의 답을 통째로 대체한다.
        answer, switched = _safe_answer_for_unsupported_event_claim(
            answer, validation.errors, resolution, tool_payloads
        )
        if switched:
            # 잘못된 기간 근거로 만든 시각화도 함께 제거한다(데이터 없으면 시각화도 없음).
            visualizations = [v for v in visualizations if v.get("type") != "event_return"]

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

    @staticmethod
    def _event_grounding_failed(errors: list[str]) -> bool:
        return any("사건" in e and ("근거" in e or "표현함" in e) for e in errors)

    def _failed(self, request_id: str, reason: str, message: str, t0: float) -> AgentQaResult:
        total_ms = int((time.perf_counter() - t0) * 1000)
        trace = AgentTrace(request_id=request_id, stop_reason=reason, total_latency_ms=total_ms)
        return AgentQaResult(
            answer="", stop_reason=reason, error=message, trace=trace.to_log_dict()
        )

    @staticmethod
    def _blocked(
        request_id: str,
        decision: StockContextDecision,
        *,
        tool_calls: list[AgentToolCall] | None = None,
        model_calls: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        t0: float | None = None,
    ) -> AgentQaResult:
        message = decision.message or "종목 문맥을 확인할 수 없어 답변을 생성하지 않았습니다."
        total_ms = int((time.perf_counter() - t0) * 1000) if t0 is not None else 0
        calls = tool_calls or []
        trace = AgentTrace(
            request_id=request_id,
            model_calls=model_calls,
            tool_calls=[
                ToolTrace(name=c.name, status=c.status, result_count=c.result_count) for c in calls
            ],
            stop_reason="blocked",
            total_latency_ms=total_ms,
        )
        return AgentQaResult(
            answer=message,
            tool_calls=calls,
            model_calls=model_calls,
            stop_reason="blocked",
            error=message,
            error_code=decision.error_code,
            trace=trace.to_log_dict(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            sources=[],
            visualizations=[],
            report_opinions=[],
            warnings=[],
        )


def _safe_answer_for_unsupported_event_claim(
    answer: str,
    validation_errors: list[str],
    resolution: EventResolution,
    tool_payloads: list[dict],
) -> tuple[str, bool]:
    """사건 근거 없는 '사건 이후 수익률' 답변을 실제 상태에 맞는 안전 답변으로 바꾼다(§6).

    검증기는 숫자를 수정·보충하지 않는다. 대신 근거 부족이 확인되면 답변 전체를 실제
    상태(사건 미특정 / 여러 사건 / 발표 후 거래일 없음 / 계산 결과 없음)로 교체한다.
    """
    if not AgentQaService._event_grounding_failed(validation_errors):
        return answer, False

    # (1) 서로 다른 사건이 여러 개 → 선택 요청.
    if resolution.status == "ambiguous" and resolution.candidates:
        return clarification_message(resolution.candidates), True

    # (2) 발표 이후 확정 거래일이 없음 → 데이터 부족을 그대로 안내.
    for p in tool_payloads:
        data = p.get("data") if isinstance(p, dict) else None
        if not isinstance(data, dict) or data.get("basis") != "event":
            continue
        if p.get("status") == "no_data" and data.get("has_post_data") is False:
            day = data.get("event_date") or "발표일"
            return (
                f"{day} 발표 이후 확정 거래일 데이터가 아직 없어 계산할 수 없습니다. "
                "다른 기간의 주가 변화로 대체하지 않았습니다."
            ), True

    # (3) 사건 자체를 특정할 수 없음.
    if resolution.status == "none":
        return (
            "어떤 뉴스·공시를 말하는지 특정할 수 없어 사건 이후 주가 변화를 계산하지 "
            "못했습니다. 기준으로 삼을 뉴스를 선택해 주시면 발표 전후 주가를 확인해 "
            "드리겠습니다. (최근 한 달·일주일 수익률로 대체하지 않았습니다.)"
        ), True

    # (4) 그 외 — 필요한 계산 결과·출처가 없음.
    return (
        "사건 전후 주가 계산 결과를 확보하지 못해 이 뉴스 이후의 주가 변화를 답변할 수 "
        "없습니다. 다른 기간의 수익률로 대체하지 않았습니다."
    ), True


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
    timeline_inputs: list[tuple[str, dict, list[str]]] = []  # (tool_name, data, source_ids)

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
        if tool_name in ("search_news", "search_disclosures"):
            timeline_inputs.append((tool_name, data, source_ids))
        warnings.extend(_public_warnings(payload.get("warnings")))

    # 사건 타임라인: 같은 답변에서 뉴스·공시가 함께 조회됐을 때만, 이미 확정된
    # 사건(제목·발표시각)을 시간순으로 병합한다. 새 조회·재계산·답변 파싱 없음.
    timeline = _event_timeline(timeline_inputs)
    if timeline is not None:
        visualizations.append(timeline)

    return list(source_by_id.values()), visualizations, list(dict.fromkeys(warnings))


def _event_timeline(inputs: list[tuple[str, dict, list[str]]]) -> dict | None:
    """뉴스 사건 + 공시를 발표시각 기준 최신순 타임라인으로 병합한다.

    출처가 있는 확정 사건만 쓰고, 뉴스와 공시가 둘 다 있을 때만 만든다(단일 종류면
    각자 카드로 충분). 값·날짜를 새로 만들지 않는다.
    """
    kinds = {name for name, _, _ in inputs}
    if not ({"search_news", "search_disclosures"} <= kinds):
        return None

    events: list[dict] = []
    all_source_ids: list[str] = []
    for name, data, source_ids in inputs:
        all_source_ids.extend(source_ids)
        if name == "search_news":
            for it in data.get("news", []) or []:
                if isinstance(it, dict) and it.get("published_at"):
                    events.append(
                        {
                            "kind": "news",
                            "title": it.get("title"),
                            "at": it.get("published_at"),
                            "source_id": it.get("source_id"),
                            "publisher": it.get("publisher"),
                            "url": it.get("url"),
                        }
                    )
        else:  # search_disclosures
            for it in data.get("disclosures", []) or []:
                if isinstance(it, dict) and it.get("disclosed_at"):
                    events.append(
                        {
                            "kind": "disclosure",
                            "title": it.get("title"),
                            "at": it.get("disclosed_at"),
                            "source_id": it.get("rcept_no"),
                            "publisher": "DART",
                        }
                    )
    if len({e["kind"] for e in events}) < 2:
        return None  # 실제로 두 종류가 다 있을 때만 타임라인
    events.sort(key=lambda e: e["at"], reverse=True)
    return {
        "type": "event_timeline",
        "title": "관련 사건 타임라인",
        "data": {"events": events[:12]},
        "source_ids": list(dict.fromkeys(all_source_ids)),
    }


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
        # UI 선그래프는 거래일별 전체(daily_full, 최대 60)를 우선 사용하고, 없으면 요약(daily).
        points = data.get("daily_full")
        if not (isinstance(points, list) and len(points) >= 2):
            points = data.get("daily")
        if isinstance(points, list) and len(points) >= 2:
            first_day = points[0].get("trading_day") if isinstance(points[0], dict) else None
            last_day = points[-1].get("trading_day") if isinstance(points[-1], dict) else None
            title = (
                f"{first_day} ~ {last_day} 주가"
                if isinstance(first_day, str) and isinstance(last_day, str)
                else "실제 주가 흐름"
            )
            return {
                "type": "price_line",
                "title": title,
                "data": {
                    "points": points,
                    "quote": data.get("quote"),
                    "period": data.get("period"),
                    "sampled": data.get("daily_full_sampled", False),
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
