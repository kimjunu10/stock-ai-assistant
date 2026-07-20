"""fnlttSinglAcntAll 재무 응답 → financials 행 추출 (SPEC §4-2).

저장 계정 9종: 매출액, 영업이익, 당기순이익, 자산, 부채, 자본,
영업활동/투자활동/재무활동 현금흐름. 매핑은 account_id 우선, 없으면 account_nm 보조.

amount_type 규칙 (실제 API 응답으로 검증, 2026-07-20):
- 손익(IS/CIS): 분기·반기 보고서는 당기 3개월(`thstrm_amount`)과 누적
  (`thstrm_add_amount`)을 각각 quarter/cumulative 별도 행으로 저장. 사업보고서는
  `thstrm_add_amount`가 비어 있어 `thstrm_amount`(연간)만 cumulative 1행.
- 현금흐름(CF): add_amount가 없고 `thstrm_amount`가 누적 → cumulative 1행.
- 재무상태표(BS): 기간말 잔액 → point_in_time 1행.
SPEC §4-2: API가 제공하지 않는 4분기 단독 금액을 임의 계산하지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.sources.dart_parsing import parse_amount

logger = logging.getLogger(__name__)

# 계정 성격: income(손익) | cashflow(현금흐름) | balance(재무상태)
INCOME = "income"
CASHFLOW = "cashflow"
BALANCE = "balance"


@dataclass(frozen=True)
class AccountSpec:
    account_nm: str  # financials.account_nm 에 저장할 표준 계정명
    account_ids: tuple[str, ...]  # 우선 매칭할 XBRL account_id 목록
    nm_keywords: tuple[str, ...]  # 보조: account_nm 완전일치 후보
    category: str  # INCOME | CASHFLOW | BALANCE


# 실제 삼성전자 응답으로 account_id 검증 완료 (2026-07-20).
ACCOUNT_SPECS: tuple[AccountSpec, ...] = (
    AccountSpec("매출액", ("ifrs-full_Revenue",), ("매출액", "수익(매출액)", "영업수익"), INCOME),
    AccountSpec("영업이익", ("dart_OperatingIncomeLoss",), ("영업이익", "영업이익(손실)"), INCOME),
    AccountSpec(
        "당기순이익", ("ifrs-full_ProfitLoss",), ("당기순이익", "당기순이익(손실)"), INCOME
    ),
    AccountSpec("자산총계", ("ifrs-full_Assets",), ("자산총계",), BALANCE),
    AccountSpec("부채총계", ("ifrs-full_Liabilities",), ("부채총계",), BALANCE),
    AccountSpec("자본총계", ("ifrs-full_Equity",), ("자본총계",), BALANCE),
    AccountSpec(
        "영업활동현금흐름",
        ("ifrs-full_CashFlowsFromUsedInOperatingActivities",),
        ("영업활동현금흐름", "영업활동으로 인한 현금흐름"),
        CASHFLOW,
    ),
    AccountSpec(
        "투자활동현금흐름",
        ("ifrs-full_CashFlowsFromUsedInInvestingActivities",),
        ("투자활동현금흐름", "투자활동으로 인한 현금흐름"),
        CASHFLOW,
    ),
    AccountSpec(
        "재무활동현금흐름",
        ("ifrs-full_CashFlowsFromUsedInFinancingActivities",),
        ("재무활동현금흐름", "재무활동으로 인한 현금흐름"),
        CASHFLOW,
    ),
)


def _row(stock_code, bsns_year, reprt_code, fs_div, account_nm, thstrm, frmtrm, amount_type):
    return {
        "stock_code": stock_code,
        "bsns_year": bsns_year,
        "reprt_code": reprt_code,
        "fs_div": fs_div,
        "account_nm": account_nm,
        "thstrm_amount": thstrm,
        "frmtrm_amount": frmtrm,
        "amount_type": amount_type,
    }


def _income_rows(spec, matched, stock_code, bsns_year, reprt_code, fs_div) -> list[dict]:
    """손익 계정: 누적/3개월을 각각 별도 행으로. add_amount 유무로 판별."""

    thstrm = parse_amount(matched.get("thstrm_amount"))
    add = parse_amount(matched.get("thstrm_add_amount"))
    frmtrm_q = parse_amount(matched.get("frmtrm_q_amount"))
    frmtrm_add = parse_amount(matched.get("frmtrm_add_amount"))
    frmtrm_plain = parse_amount(matched.get("frmtrm_amount"))

    out: list[dict] = []
    if add is not None:
        # 분기·반기: thstrm_amount=당기 3개월(quarter), thstrm_add_amount=누적(cumulative)
        if thstrm is not None:
            out.append(
                _row(
                    stock_code,
                    bsns_year,
                    reprt_code,
                    fs_div,
                    spec.account_nm,
                    thstrm,
                    frmtrm_q,
                    "quarter",
                )
            )
        out.append(
            _row(
                stock_code,
                bsns_year,
                reprt_code,
                fs_div,
                spec.account_nm,
                add,
                frmtrm_add,
                "cumulative",
            )
        )
    else:
        # 사업보고서: 연간 단일 금액 = 누적
        if thstrm is not None:
            out.append(
                _row(
                    stock_code,
                    bsns_year,
                    reprt_code,
                    fs_div,
                    spec.account_nm,
                    thstrm,
                    frmtrm_plain,
                    "cumulative",
                )
            )
    return out


def extract_financial_rows(
    api_rows: list[dict[str, Any]], stock_code: str, bsns_year: str, reprt_code: str, fs_div: str
) -> list[dict[str, Any]]:
    """API list[] → financials upsert 행 리스트.

    account_id 우선 매칭, 실패 시 account_nm 완전일치 보조. 각 표준 계정당 첫 매칭만
    사용한다(중복 tag 방지). 매핑 실패한 대상 계정은 로그로 남긴다(SPEC §4-2).
    """

    rows: list[dict[str, Any]] = []
    used_specs: set[str] = set()

    by_id: dict[str, dict] = {}
    by_nm: dict[str, dict] = {}
    for r in api_rows:
        aid = (r.get("account_id") or "").strip()
        anm = (r.get("account_nm") or "").strip()
        if aid and aid not in by_id:
            by_id[aid] = r
        if anm and anm not in by_nm:
            by_nm[anm] = r

    for spec in ACCOUNT_SPECS:
        matched: dict | None = None
        for aid in spec.account_ids:
            if aid in by_id:
                matched = by_id[aid]
                break
        if matched is None:
            for nm in spec.nm_keywords:
                if nm in by_nm:
                    matched = by_nm[nm]
                    break
        if matched is None:
            continue

        if spec.category == INCOME:
            rows.extend(_income_rows(spec, matched, stock_code, bsns_year, reprt_code, fs_div))
        elif spec.category == BALANCE:
            rows.append(
                _row(
                    stock_code,
                    bsns_year,
                    reprt_code,
                    fs_div,
                    spec.account_nm,
                    parse_amount(matched.get("thstrm_amount")),
                    parse_amount(matched.get("frmtrm_amount")),
                    "point_in_time",
                )
            )
        else:  # CASHFLOW: thstrm_amount가 누적 잔액
            rows.append(
                _row(
                    stock_code,
                    bsns_year,
                    reprt_code,
                    fs_div,
                    spec.account_nm,
                    parse_amount(matched.get("thstrm_amount")),
                    parse_amount(matched.get("frmtrm_amount")),
                    "cumulative",
                )
            )
        used_specs.add(spec.account_nm)

    missing = [s.account_nm for s in ACCOUNT_SPECS if s.account_nm not in used_specs]
    if missing:
        logger.info(
            "재무 계정 매핑 실패(데이터 없음 가능) stock=%s %s/%s/%s: %s",
            stock_code,
            bsns_year,
            reprt_code,
            fs_div,
            ", ".join(missing),
        )
    return rows
