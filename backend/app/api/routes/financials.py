"""Structured financial-data API routes."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from app.db.client import get_supabase_client
from app.schemas.fundamentals import FinancialSummary, FinancialSummaryItem
from app.sources.prices import SUPPORTED_STOCK_CODES

router = APIRouter(prefix="/stocks", tags=["financials"])

REPORT_RANK = {"11013": 1, "11012": 2, "11014": 3, "11011": 4}
REPORT_LABEL = {"11013": "1분기", "11012": "반기", "11014": "3분기", "11011": "연간"}
SUMMARY_ACCOUNTS = ("매출액", "영업이익", "당기순이익")


def _format_won(amount: int) -> str:
    """Format a won amount at the 억원 precision used by the UI."""

    sign = "-" if amount < 0 else ""
    eok = round(abs(amount) / 100_000_000)
    jo, remainder = divmod(eok, 10_000)
    if jo and remainder:
        return f"{sign}{jo:,}조 {remainder:,}억원"
    if jo:
        return f"{sign}{jo:,}조원"
    return f"{sign}{remainder:,}억원"


def _latest_report(rows: list[dict[str, Any]]) -> tuple[str, str] | None:
    reports = {
        (str(row["bsns_year"]), str(row["reprt_code"]))
        for row in rows
        if row.get("reprt_code") in REPORT_RANK
    }
    return max(reports, key=lambda item: (int(item[0]), REPORT_RANK[item[1]]), default=None)


def _build_items(
    rows: list[dict[str, Any]], year: str, report_code: str
) -> list[FinancialSummaryItem]:
    candidates = [
        row
        for row in rows
        if str(row.get("bsns_year")) == year
        and row.get("reprt_code") == report_code
        and row.get("account_nm") in SUMMARY_ACCOUNTS
    ]
    # 연결재무제표와 해당 분기 단독 수치를 우선한다. 없을 때만 누적/OFS를 사용한다.
    candidates.sort(
        key=lambda row: (
            row.get("fs_div") != "CFS",
            row.get("amount_type") != "quarter",
        )
    )
    by_account: dict[str, dict[str, Any]] = {}
    for row in candidates:
        by_account.setdefault(str(row["account_nm"]), row)

    note = f"{year}년 {REPORT_LABEL[report_code]}"
    items = []
    for account in SUMMARY_ACCOUNTS:
        row = by_account.get(account)
        if not row or row.get("thstrm_amount") is None:
            continue
        current = int(row["thstrm_amount"])
        previous = row.get("frmtrm_amount")
        yoy = None
        if previous not in (None, 0):
            yoy = round((current - int(previous)) / abs(int(previous)) * 100, 1)
        items.append(
            FinancialSummaryItem(
                account=account,
                display=_format_won(current),
                yoyPct=yoy,
                note=note,
            )
        )
    return items


@router.get("/{stock_code}/financial-summary", response_model=FinancialSummary)
def get_financial_summary(
    stock_code: str,
    client: Annotated[Client, Depends(get_supabase_client)],
) -> FinancialSummary:
    """Return the latest real DART reporting period for the three headline accounts."""

    if stock_code not in SUPPORTED_STOCK_CODES:
        raise HTTPException(status_code=404, detail="현재는 지정된 5개 종목만 제공하고 있어요.")

    response = (
        client.table("financials")
        .select("bsns_year,reprt_code,fs_div,account_nm,thstrm_amount,frmtrm_amount,amount_type")
        .eq("stock_code", stock_code)
        .execute()
    )
    rows = response.data or []
    latest = _latest_report(rows)
    if not latest:
        raise HTTPException(status_code=404, detail="DART 재무 데이터가 아직 없어요.")
    items = _build_items(rows, *latest)
    if not items:
        raise HTTPException(status_code=404, detail="표시할 DART 재무 항목이 아직 없어요.")
    return FinancialSummary(stockCode=stock_code, items=items)
