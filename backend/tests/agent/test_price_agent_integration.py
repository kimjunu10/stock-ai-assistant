"""Phase 6 주가 Agent 통합 테스트 (실제 LLM·토스 API 없음).

create_agent 로 만든 실제 Agent 를 '가짜 모델'로 구동한다. 가짜 모델은 미리 정해진
tool_call 시퀀스를 방출하고, 실제 Tool·Service 배선(→ StockPriceService 가짜)·검증까지
end-to-end 로 흐르는지 확인한다. 확인 기준(prompt.md §6):
- 필요한 주가 Tool 호출 / 금지된 리포트 Tool 미호출
- Agent 직접 산술 0(수익률은 Tool 결과값)
- 실제 주가/목표주가 혼동 0
- no_data 추측 0
"""

from __future__ import annotations

from datetime import date, datetime

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.agent.context import QaRuntimeContext, ToolServices
from app.services.stock_prices import (
    DailyClose,
    EventHorizonReturn,
    EventWindowReturn,
    PeriodReturn,
    PriceQuote,
)


class ScriptedModel(GenericFakeChatModel):
    """정해진 (tool_calls or 최종답변) 시퀀스를 순서대로 방출하는 가짜 모델."""

    def bind_tools(self, tools, **kwargs):
        return self  # tool 바인딩은 무시(스크립트대로 방출)


def _model(script: list[AIMessage]) -> ScriptedModel:
    return ScriptedModel(messages=iter(script))


def _tool_call(name, args):
    return {"name": name, "args": args, "id": f"call_{name}", "type": "tool_call"}


class FakePriceSvc:
    DEFAULT_EVENT_HORIZONS = (1, 3, 5)

    def __init__(self, *, no_post_data=False):
        self.calls = []
        self.no_post_data = no_post_data

    def get_current_quote(self, stock_code):
        self.calls.append(("quote", stock_code))
        return PriceQuote(
            stock_code=stock_code,
            price=252500.0,
            previous_close=250000.0,
            change=2500.0,
            change_rate=1.0,
            currency="KRW",
            as_of=datetime.fromisoformat("2026-07-24T15:30:00+09:00"),
            trading_day=date(2026, 7, 24),
        )

    def get_period_return(
        self,
        stock_code,
        *,
        start,
        end,
        adjusted=True,
        live_quote=None,
        start_on_or_before=False,
    ):
        self.calls.append(("period", stock_code))
        return PeriodReturn(
            stock_code=stock_code,
            start_trading_day=date(2026, 6, 24),
            end_trading_day=date(2026, 7, 24),
            start_close=200000.0,
            end_close=250000.0,
            change=50000.0,
            return_pct=25.0,
            currency="KRW",
            adjusted=adjusted,
        )

    def get_daily_candles(self, stock_code, *, start, end, adjusted=True):
        return [
            DailyClose(
                trading_day=date(2026, 7, 23),
                close=250000.0,
                open=250000.0,
                high=250000.0,
                low=250000.0,
                volume=1000,
                currency="KRW",
            )
        ]

    def get_event_return(self, stock_code, *, event_date, pre_days, post_days, adjusted=True):
        self.calls.append(("event", stock_code))
        return PeriodReturn(
            stock_code=stock_code,
            start_trading_day=date(2026, 7, 21),
            end_trading_day=date(2026, 7, 23),
            start_close=102000.0,
            end_close=106000.0,
            change=4000.0,
            return_pct=3.92,
            currency="KRW",
            adjusted=adjusted,
        )

    def get_event_window_return(self, stock_code, *, event_date, horizons=None, adjusted=True):
        self.calls.append(("event_window", stock_code, event_date.isoformat()))
        if self.no_post_data:
            return EventWindowReturn(
                stock_code=stock_code,
                event_date=event_date,
                baseline_trading_day=date(2026, 7, 24),
                baseline_close=100000.0,
                horizons=[],
                currency="KRW",
                adjusted=adjusted,
            )
        return EventWindowReturn(
            stock_code=stock_code,
            event_date=event_date,
            baseline_trading_day=date(2026, 7, 21),
            baseline_close=100000.0,
            horizons=[
                EventHorizonReturn(
                    horizon_days=1,
                    trading_day=date(2026, 7, 23),
                    close=103000.0,
                    change=3000.0,
                    return_pct=3.0,
                ),
                EventHorizonReturn(
                    horizon_days=3,
                    trading_day=date(2026, 7, 27),
                    close=102000.0,
                    change=2000.0,
                    return_pct=2.0,
                ),
                EventHorizonReturn(
                    horizon_days=5,
                    trading_day=date(2026, 7, 29),
                    close=98000.0,
                    change=-2000.0,
                    return_pct=-2.0,
                ),
            ],
            currency="KRW",
            adjusted=adjusted,
        )


class FakeReports:
    def __init__(self):
        self.searched = False

    def search(self, *a, **k):
        self.searched = True
        return []


def _run(script, *, prices=None, reports=None, facts=None, retriever=None, event=None):
    """실제 build_agent 대신, runtime.build_tools() 를 create_agent 로 직접 조립한다.

    event 는 서버가 확정한 사건 문맥(dict). 사건 기준 Tool 은 이 문맥에서만 발표일을
    가져오므로, 문맥 없이 호출하면 계산이 거부되는지도 이 헬퍼로 검증한다.
    """
    from langchain.agents import create_agent

    from app.agent.runtime import build_tools

    svc = ToolServices(
        facts=facts or object(),
        retriever=retriever or object(),
        reports=reports or FakeReports(),
        prices=prices or FakePriceSvc(),
    )
    agent = create_agent(
        model=_model(script),
        tools=build_tools(),
        context_schema=QaRuntimeContext,
    )
    ctx = QaRuntimeContext(stock_code="005930", services=svc, **(event or {}))
    out = agent.invoke({"messages": [{"role": "user", "content": "q"}]}, context=ctx)
    return out


def _tool_payload(out, name):
    """해당 Tool 이 반환한 ToolResult(JSON) 를 파싱해 돌려준다."""
    import json

    for m in out["messages"]:
        if getattr(m, "type", "") == "tool" and getattr(m, "name", None) == name:
            return json.loads(m.content)
    return None


def _tool_names(out):
    names = []
    for m in out["messages"]:
        for tc in getattr(m, "tool_calls", []) or []:
            names.append(tc["name"])
    return names


# ── 현재 주가 → get_stock_prices ───────────────────────────────────
def test_current_price_calls_price_tool():
    prices = FakePriceSvc()
    script = [
        AIMessage(
            content="", tool_calls=[_tool_call("get_stock_prices", {"stock_code": "005930"})]
        ),
        AIMessage(content="삼성전자 현재 주가는 252,500원입니다."),
    ]
    out = _run(script, prices=prices)
    assert "get_stock_prices" in _tool_names(out)
    assert ("quote", "005930") in prices.calls


# ── 최근 한 달 수익률 → get_stock_prices(lookback) ─────────────────
def test_month_return_uses_price_tool_lookback():
    prices = FakePriceSvc()
    script = [
        AIMessage(
            content="",
            tool_calls=[_tool_call("get_stock_prices", {"stock_code": "005930", "lookback": "1m"})],
        ),
        AIMessage(content="최근 한 달 수익률은 25.0%입니다."),
    ]
    out = _run(script, prices=prices)
    assert "get_stock_prices" in _tool_names(out)
    assert ("period", "005930") in prices.calls


# ── "목표주가 말고 실제 주가" → 리포트 Tool 미호출 ─────────────────
def test_actual_price_not_target_does_not_call_reports():
    prices = FakePriceSvc()
    reports = FakeReports()
    script = [
        AIMessage(
            content="",
            tool_calls=[_tool_call("get_stock_prices", {"stock_code": "005930", "lookback": "1m"})],
        ),
        AIMessage(content="실제 주가는 최근 한 달 25.0% 올랐습니다."),
    ]
    out = _run(script, prices=prices, reports=reports)
    names = _tool_names(out)
    assert "get_stock_prices" in names
    assert "search_research_reports" not in names  # 금지된 리포트 Tool 미호출
    assert reports.searched is False


# ── 사건 전후 → calculate_event_return (서버 확정 문맥 사용) ────────
_RESOLVED_EVENT = {
    "event_status": "resolved",
    "event_id": "news:evt-1",
    "event_date": "2026-07-22",
    "event_title": "HBM 공급계약 체결",
    "event_stock_code": "005930",
}


def test_event_return_uses_event_tool():
    prices = FakePriceSvc()
    script = [
        AIMessage(
            content="",
            tool_calls=[_tool_call("calculate_event_return", {"stock_code": "005930"})],
        ),
        AIMessage(content="발표 이후 1거래일 3.0% 상승했습니다."),
    ]
    out = _run(script, prices=prices, event=_RESOLVED_EVENT)
    assert "calculate_event_return" in _tool_names(out)
    # 발표일은 문맥에서 왔다(모델이 넘긴 값이 아님).
    assert ("event_window", "005930", "2026-07-22") in prices.calls
    payload = _tool_payload(out, "calculate_event_return")
    assert payload["status"] == "ok"
    assert payload["data"]["basis"] == "event"
    assert payload["data"]["event_id"] == "news:evt-1"
    assert [h["horizon_days"] for h in payload["data"]["horizons"]] == [1, 3, 5]


def test_search_disclosure_then_event_return_rehydrates_event_ref():
    """같은 질문에서 찾은 공시 ID를 다음 Tool이 원문 재조회해 발표일을 확정한다."""

    class Facts:
        def get_latest_disclosures(self, stock_code, **kwargs):
            assert stock_code == "005930"
            return [
                {
                    "rcept_no": "20260722000123",
                    "title": "공급계약 체결",
                    "disclosed_at": "2026-07-22T09:00:00+09:00",
                    "correction_status": None,
                    "is_latest": True,
                }
            ]

        def get_disclosure_by_id(self, rcept_no, *, stock_code):
            if rcept_no != "20260722000123" or stock_code != "005930":
                return None
            return {
                "rcept_no": rcept_no,
                "title": "공급계약 체결",
                "disclosed_at": "2026-07-22T09:00:00+09:00",
            }

    prices = FakePriceSvc()
    script = [
        AIMessage(
            content="",
            tool_calls=[
                _tool_call(
                    "search_disclosures",
                    {"stock_code": "005930", "query": "", "limit": 1},
                )
            ],
        ),
        AIMessage(
            content="",
            tool_calls=[
                _tool_call(
                    "calculate_event_return",
                    {
                        "stock_code": "005930",
                        "event_source_type": "dart_document",
                        "event_source_id": "20260722000123",
                    },
                )
            ],
        ),
        AIMessage(content="공시 발표 이후 1거래일에 3.0% 상승했습니다."),
    ]
    out = _run(script, prices=prices, facts=Facts())

    search_payload = _tool_payload(out, "search_disclosures")
    assert search_payload["data"]["disclosures"][0]["event_ref"] == {
        "source_type": "dart_document",
        "source_id": "20260722000123",
        "stock_code": "005930",
    }
    assert ("event_window", "005930", "2026-07-22") in prices.calls
    event_payload = _tool_payload(out, "calculate_event_return")
    assert event_payload["status"] == "ok"
    assert event_payload["data"]["event"]["source_id"] == "20260722000123"
    assert event_payload["sources"][0]["source_type"] == "dart_document"


def test_event_tool_ignores_model_supplied_event_date():
    """모델이 발표일을 만들어 넘겨도 문맥의 확정 발표일만 쓴다."""
    prices = FakePriceSvc()
    script = [
        AIMessage(
            content="",
            tool_calls=[
                _tool_call(
                    "calculate_event_return",
                    {"stock_code": "005930", "event_date": "2020-01-01"},
                )
            ],
        ),
        AIMessage(content="발표 이후 1거래일 3.0% 상승했습니다."),
    ]
    _run(script, prices=prices, event=_RESOLVED_EVENT)
    assert ("event_window", "005930", "2026-07-22") in prices.calls
    assert not any(c[0] == "event_window" and c[2] == "2020-01-01" for c in prices.calls)


def test_event_tool_blocked_without_event_context():
    """사건 문맥이 없으면 계산을 거부하고 일반 기간으로 대체하지 않는다."""
    prices = FakePriceSvc()
    script = [
        AIMessage(
            content="",
            tool_calls=[_tool_call("calculate_event_return", {"stock_code": "005930"})],
        ),
        AIMessage(content="어떤 뉴스를 말하는지 확인이 필요합니다."),
    ]
    out = _run(script, prices=prices)
    payload = _tool_payload(out, "calculate_event_return")
    assert payload["status"] == "no_data"
    # 주가 계산 자체를 하지 않았다(기간 수익률 대체 없음).
    assert prices.calls == []


def test_event_tool_blocked_when_ambiguous():
    """서로 다른 사건이 여러 개면 임의 선택하지 않고 후보를 돌려준다."""
    from app.agent.event_reference import EventCandidate

    prices = FakePriceSvc()
    script = [
        AIMessage(
            content="",
            tool_calls=[_tool_call("calculate_event_return", {"stock_code": "005930"})],
        ),
        AIMessage(content="어떤 사건 기준인지 알려주세요."),
    ]
    out = _run(
        script,
        prices=prices,
        event={
            "event_status": "ambiguous",
            "event_candidates": [
                EventCandidate("news:a", "HBM 공급계약", "2026-07-22T09:00:00+09:00", "005930"),
                EventCandidate("news:b", "관세 발표", "2026-07-18T09:00:00+09:00", "005930"),
            ],
        },
    )
    payload = _tool_payload(out, "calculate_event_return")
    assert payload["status"] == "no_data"
    assert payload["data"]["event_status"] == "ambiguous"
    assert {c["event_id"] for c in payload["data"]["candidates"]} == {"news:a", "news:b"}
    assert prices.calls == []


def test_event_tool_no_post_trading_day_does_not_fall_back():
    """발표 후 확정 거래일이 없으면 no_data — 다른 기간 값을 만들지 않는다."""
    prices = FakePriceSvc(no_post_data=True)
    script = [
        AIMessage(
            content="",
            tool_calls=[_tool_call("calculate_event_return", {"stock_code": "005930"})],
        ),
        AIMessage(content="발표 이후 확정 거래일 데이터가 아직 없어 계산할 수 없습니다."),
    ]
    out = _run(script, prices=prices, event=_RESOLVED_EVENT)
    payload = _tool_payload(out, "calculate_event_return")
    assert payload["status"] == "no_data"
    assert payload["data"]["has_post_data"] is False
    assert "return_pct" not in payload["data"]
    # 기간 수익률로 대체 조회하지 않았다.
    assert not any(c[0] == "period" for c in prices.calls)


def test_event_tool_has_no_lookback_parameter():
    """Tool 스키마 수준에서 일반 기간 인자가 사라졌다(대체 경로 차단)."""
    from app.agent.runtime import build_tools

    tool = next(t for t in build_tools() if t.name == "calculate_event_return")
    assert "lookback" not in tool.args
    assert "event_date" not in tool.args  # 발표일은 문맥에서만 온다


# ── 목표주가와 실제 주가 비교 → 두 Tool ────────────────────────────
def test_compare_target_and_actual_calls_both():
    prices = FakePriceSvc()
    reports = FakeReports()
    script = [
        AIMessage(
            content="",
            tool_calls=[
                _tool_call("get_stock_prices", {"stock_code": "005930"}),
                _tool_call(
                    "search_research_reports",
                    {"stock_code": "005930", "query": "목표주가"},
                ),
            ],
        ),
        AIMessage(content="실제 주가 252,500원, 목표주가는 리포트를 확인하세요."),
    ]
    out = _run(script, prices=prices, reports=reports)
    names = _tool_names(out)
    assert "get_stock_prices" in names
    assert "search_research_reports" in names
    assert reports.searched is True


# ── 존재하지 않는 종목/데이터 없음 → no_data(Tool 이 반환) ─────────
def test_no_data_stock_returns_no_data_payload():
    class NoDataSvc(FakePriceSvc):
        def get_current_quote(self, stock_code):
            return None

    script = [
        AIMessage(
            content="", tool_calls=[_tool_call("get_stock_prices", {"stock_code": "005930"})]
        ),
        AIMessage(content="주가를 확인할 수 없습니다."),
    ]
    out = _run(script, prices=NoDataSvc())
    # tool 메시지에 no_data 상태가 담겨 흐르는지 확인
    tool_msgs = [m for m in out["messages"] if getattr(m, "type", "") == "tool"]
    assert any("no_data" in str(getattr(m, "content", "")) for m in tool_msgs)
