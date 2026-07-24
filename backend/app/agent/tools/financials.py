"""get_financial_facts Tool (Phase 5.5-B, SPEC §7.1).

정확한 재무 수치를 FactsService(SQL)로만 조회한다. Agent 는 자유 SQL 을 만들 수 없고,
검증된 인자(종목·계정·연도·보고기간·amount_type·fs_div)만 전달한다.

DART 공식 코드(인수인계 문서 §3): 11013=q1, 11012=half, 11014=q3, 11011=annual.
report_period(q1/half/q3/annual)을 Tool 내부에서 reprt_code 로 변환한다
(FactsService.REPRT_LABEL 이 과거 오매핑이더라도 Tool 계층에서 올바른 코드로 조회).

엄격 규칙:
- 정확히 일치하는 기간·amount_type 행이 없으면 no_data. 다른 기간으로 fallback 금지.
- CFS/OFS 혼합 금지(fs_div 로 단일 지정, 기본 CFS).
- 손익 계정과 재무상태표 계정의 amount_type 의미가 다름(아래 검증).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.agent.tools.common import SourceRef, ToolResult, error, no_data, ok, sanitize_exception
from app.services.facts import FactsService

# report_period → DART reprt_code (공식 매핑; 숫자 크기 순서 아님)
PERIOD_TO_REPRT = {"q1": "11013", "half": "11012", "q3": "11014", "annual": "11011"}
REPRT_LABEL = {"11013": "1분기", "11012": "반기", "11014": "3분기", "11011": "연간"}

INCOME_ACCOUNTS = {"매출액", "영업이익", "당기순이익"}
CASHFLOW_ACCOUNTS = {"영업활동현금흐름", "투자활동현금흐름", "재무활동현금흐름"}
BALANCE_ACCOUNTS = {"자산총계", "부채총계", "자본총계"}

AccountName = Literal[
    "매출액",
    "영업이익",
    "당기순이익",
    "자산총계",
    "부채총계",
    "자본총계",
    "영업활동현금흐름",
    "투자활동현금흐름",
    "재무활동현금흐름",
]


class FinancialFactsInput(BaseModel):
    stock_code: str = Field(pattern=r"^[0-9]{6}$")
    account_name: AccountName
    business_year: int | None = None
    report_period: Literal["q1", "half", "q3", "annual"] | None = None
    amount_type: Literal["quarter", "cumulative", "point_in_time"] | None = None
    fs_div: Literal["CFS", "OFS"] = "CFS"


def _default_amount_type(account: str, report_period: str | None) -> str | None:
    """계정 성격에 따른 amount_type 기본값(질문이 유형을 안 주면).

    - 재무상태표(자산·부채·자본): 항상 point_in_time.
    - 현금흐름: cumulative(누적만 저장).
    - 손익: annual→cumulative. 그 외 분기/반기는 유형을 지정하지 않으면 None(호출부가
      quarter/cumulative 를 명시하도록; 임의로 섞지 않기 위해 강제하지 않는다).
    """
    if account in BALANCE_ACCOUNTS:
        return "point_in_time"
    if account in CASHFLOW_ACCOUNTS:
        return "cumulative"
    if account in INCOME_ACCOUNTS and report_period == "annual":
        return "cumulative"
    return None


def run_get_financial_facts(facts: FactsService, inp: FinancialFactsInput) -> ToolResult:
    """검증된 인자로 재무 1건(또는 소수)을 조회한다. 없으면 no_data."""
    try:
        reprt_code = PERIOD_TO_REPRT[inp.report_period] if inp.report_period else None
        amount_type = inp.amount_type or _default_amount_type(inp.account_name, inp.report_period)

        rows = facts.get_financials(
            inp.stock_code,
            account_names=[inp.account_name],
            bsns_year=str(inp.business_year) if inp.business_year else None,
            reprt_code=reprt_code,
            amount_type=amount_type,
            fs_div=inp.fs_div,
            limit=8,
        )
    except TypeError:
        # 기존 FactsService 가 fs_div 인자를 아직 안 받는 경우(리팩터 전) 안전 처리.
        try:
            rows = facts.get_financials(
                inp.stock_code,
                account_names=[inp.account_name],
                bsns_year=str(inp.business_year) if inp.business_year else None,
                reprt_code=reprt_code,
                amount_type=amount_type,
                limit=8,
            )
            rows = [r for r in rows if r.basis in ("연결", "CFS") or inp.fs_div == "OFS"]
        except Exception as e:  # noqa: BLE001
            return error(sanitize_exception(e))
    except Exception as e:  # noqa: BLE001
        return error(sanitize_exception(e))

    if not rows:
        want = (
            f"{inp.business_year or '최근'} "
            f"{REPRT_LABEL.get(reprt_code, '(기간미지정)')} "
            f"{inp.account_name} ({amount_type or '유형미지정'}, {inp.fs_div})"
        )
        return no_data(f"요청한 재무 데이터가 없습니다: {want}. 다른 기간으로 대체하지 않았습니다.")

    from app.rag.prompting import format_won

    data = []
    sources = []
    for f in rows:
        data.append(
            {
                "label": f.label,
                "value_won": f.value,
                # 조/억 표기를 미리 계산해 제공한다(모델이 큰 숫자 변환에서 자릿수를
                # 틀리지 않도록). 답변에는 이 표기 또는 원 정수를 그대로 쓴다.
                "value_display": format_won(f.value),
                "unit": f.unit,
                "period": f.period,
                "basis": f.basis,
                "value_kind": f.value_kind,
            }
        )
        sources.append(
            SourceRef(
                source_id=f.source_key,
                source_type="financial",
                title=f"{f.label} · {f.period} · {f.basis}",
                value_kind=f.value_kind,
                locator={"source_type": f.source_type, "source_key": f.source_key},
            )
        )
    return ok({"facts": data}, sources=sources)
