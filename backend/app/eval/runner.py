"""Phase 8 평가 실행기.

질문 1건을 실행하고 §7 이 요구하는 항목을 기록한다:
질문·문맥 / 호출한 기능 순서 / 기능 입력값 / 기능별 결과 상태 / 검색된 식별자 /
최종 답변 / 답변 출처 / 숫자 출처 / 전체 지연 / 기능별 지연 / 모델 호출 수 /
기능 호출 수 / 비용 / 종료 상태.

`/qa` 기준으로 구현한다 — 라우트가 호출하는 것과 같은 `AgentQaService.answer()` 를
같은 인자로 호출한다. HTTP 를 거치지 않는 이유는 `/api/qa` 응답이 지연시간(`latency_ms`
가 빈 dict)·토큰을 노출하지 않아 §7 의 기록 항목을 채울 수 없기 때문이다.
SSE 계약 검증은 대표 시나리오에서만 별도로 한다(scripts/phase8_dryrun.py).

운영 코드는 변경하지 않는다. Tool 인자·기능별 지연은 평가 전용 recorder 로 관찰한다.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app.eval.recorder import RecordedCall, ToolCallRecorder
from app.eval.schema import EvalCase

# gpt-4.1-mini 공개 단가(USD/1M tok). scripts/evaluate_agent.py 와 동일 값 유지.
PRICE_IN_PER_M = 0.40
PRICE_OUT_PER_M = 1.60


@dataclass
class RunRecord:
    """질문 1건 실행 기록(§7)."""

    case_id: str
    question: str
    context: dict[str, Any]
    # 이 문항이 실제로 실행된 시각(ISO, KST) — 상대 기간("최근 3일" 등)의 검색
    # 범위는 이 시각 기준으로 계산됐다. 채점 시점에 gold 라벨이 그 범위 밖으로
    # 밀려났는지(stale_gold) 판정하는 유일한 근거이므로, 실행기가 반드시 채운다.
    evaluation_run_at: str | None = None
    tool_sequence: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)  # name/args/status/latency_ms
    retrieved_ids: list[str] = field(default_factory=list)
    answer: str = ""
    sources: list[dict] = field(default_factory=list)
    numeric_sources: list[dict] = field(default_factory=list)
    total_latency_ms: int = 0
    model_calls: int = 0
    tool_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    stop_reason: str = ""
    validation_errors: list[str] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return input_tokens / 1_000_000 * PRICE_IN_PER_M + output_tokens / 1_000_000 * PRICE_OUT_PER_M


def _numeric_sources(sources: list[dict]) -> list[dict]:
    """숫자 출처 = 숫자를 직접 제공하는 출처 종류만 추린다.

    재무·주가·구조화 공시가 숫자 근거다(용어·뉴스 본문은 숫자 근거가 아니다).
    """
    kinds = {"financial", "price", "structured_disclosure"}
    return [s for s in sources if s.get("source_type") in kinds]


class EvalRunner:
    """평가 케이스를 실행해 RunRecord 를 만든다.

    agent 는 `AgentQaService` 인스턴스(또는 같은 `answer()` 시그니처를 가진 객체).
    recorder 는 있으면 Tool 인자·기능별 지연을 채운다(없으면 그 항목만 빈다).
    """

    def __init__(self, agent: Any, recorder: ToolCallRecorder | None = None) -> None:
        self._agent = agent
        self._recorder = recorder

    def run(self, case: EvalCase) -> RunRecord:
        from app.agent.time_context import current_seoul_datetime

        ctx = case.context
        # 케이스의 stock_code 와 화면 문맥 stock_code 중 문맥을 우선한다
        # (현재 화면 문맥 유형은 context 에만 종목이 있다).
        stock_code = ctx.stock_code or case.stock_code
        if self._recorder is not None:
            self._recorder.reset()

        # AgentQaService.answer() 내부에서도 이 직후 current_seoul_datetime() 을
        # 호출해 상대 기간을 계산한다 — 여기서 잰 값은 그 계산의 사실상 동일 시점
        # 근사치이며, 채점 시 stale_gold(§4) 판정의 유일한 근거가 된다.
        evaluation_run_at = current_seoul_datetime().isoformat(timespec="seconds")

        t0 = time.perf_counter()
        try:
            r = self._agent.answer(
                case.question,
                stock_code=stock_code,
                source_type=ctx.context_source_type,
                source_id=ctx.context_source_id,
                document_id=ctx.document_id,
                report_page=ctx.report_page,
                selected_event_id=ctx.selected_event_id,
                request_id=f"eval-{case.id}",
            )
        except Exception as exc:  # noqa: BLE001 - 한 문항 실패가 전체를 멈추지 않게
            return RunRecord(
                case_id=case.id,
                question=case.question,
                context=ctx.model_dump(),
                evaluation_run_at=evaluation_run_at,
                total_latency_ms=int((time.perf_counter() - t0) * 1000),
                stop_reason="runner_error",
                error=type(exc).__name__,
            )
        wall_ms = int((time.perf_counter() - t0) * 1000)

        recorded: list[RecordedCall] = list(self._recorder.calls) if self._recorder else []
        # recorder 가 없으면 운영 응답의 tool_calls(이름·상태)만으로 채운다.
        if recorded:
            calls = [
                {
                    "name": c.name,
                    "args": c.args,
                    "status": c.status,
                    "latency_ms": c.latency_ms,
                }
                for c in recorded
            ]
        else:
            calls = [
                {"name": c.name, "args": None, "status": c.status, "latency_ms": None}
                for c in r.tool_calls
            ]

        trace = r.trace if isinstance(r.trace, dict) else {}
        sources = list(r.sources or [])
        return RunRecord(
            case_id=case.id,
            question=case.question,
            context=ctx.model_dump(),
            evaluation_run_at=evaluation_run_at,
            tool_sequence=[c["name"] for c in calls],
            tool_calls=calls,
            retrieved_ids=list(r.source_ids or []),
            answer=r.answer or "",
            sources=sources,
            numeric_sources=_numeric_sources(sources),
            total_latency_ms=int(trace.get("total_latency_ms") or wall_ms),
            model_calls=r.model_calls,
            tool_call_count=len(calls),
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            cost_usd=round(estimate_cost(r.input_tokens, r.output_tokens), 6),
            stop_reason=r.stop_reason,
            validation_errors=list(r.validation_errors or []),
            error=r.error,
        )
