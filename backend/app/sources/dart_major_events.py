"""주요사항보고서 주요정보 구조화 API 36종 레지스트리 (SPEC §4-3).

각 엔드포인트명은 OpenDART 공식 개발가이드(그룹코드 DS005)와 대조·검증했으며,
실제 API 호출로 status 200/013/000 동작을 확인했다. `.json`을 뺀 순수 엔드포인트명이
`source_api`로 저장된다. `event_type`은 안정적인 영문 snake_case.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MajorEventSpec:
    event_type: str  # 내부 표준 snake_case (안정적)
    source_api: str  # 확장자 제외 엔드포인트명 (공식)
    name_ko: str  # 공식 한글명


# 순서/번호는 SPEC §4-3의 36종 목록과 1:1 대응.
MAJOR_EVENT_SPECS: tuple[MajorEventSpec, ...] = (
    MajorEventSpec("default_occurrence", "dfOcr", "부도발생"),
    MajorEventSpec("bond_transfer_decision", "stkrtbdTrfDecsn", "주권 관련 사채권 양도 결정"),
    MajorEventSpec("rehabilitation_filing", "ctrcvsBgrq", "회생절차 개시신청"),
    MajorEventSpec("dissolution_cause", "dsRsOcr", "해산사유 발생"),
    MajorEventSpec("paid_in_capital_increase", "piicDecsn", "유상증자 결정"),
    MajorEventSpec("free_capital_increase", "fricDecsn", "무상증자 결정"),
    MajorEventSpec("paid_free_capital_increase", "pifricDecsn", "유무상증자 결정"),
    MajorEventSpec("capital_reduction", "crDecsn", "감자 결정"),
    MajorEventSpec("creditor_bank_mgmt_start", "bnkMngtPcbg", "채권은행 등의 관리절차 개시"),
    MajorEventSpec("litigation_filed", "lwstLg", "소송 등의 제기"),
    MajorEventSpec("overseas_listing_decision", "ovLstDecsn", "해외 증권시장 주권등 상장 결정"),
    MajorEventSpec(
        "overseas_delisting_decision", "ovDlstDecsn", "해외 증권시장 주권등 상장폐지 결정"
    ),
    MajorEventSpec("overseas_listing", "ovLst", "해외 증권시장 주권등 상장"),
    MajorEventSpec("overseas_delisting", "ovDlst", "해외 증권시장 주권등 상장폐지"),
    MajorEventSpec("convertible_bond_issue", "cvbdIsDecsn", "전환사채권 발행결정"),
    MajorEventSpec("bond_with_warrant_issue", "bdwtIsDecsn", "신주인수권부사채권 발행결정"),
    MajorEventSpec("exchangeable_bond_issue", "exbdIsDecsn", "교환사채권 발행결정"),
    MajorEventSpec("creditor_bank_mgmt_stop", "bnkMngtPcsp", "채권은행 등의 관리절차 중단"),
    MajorEventSpec(
        "contingent_capital_bond_issue", "wdCocobdIsDecsn", "상각형 조건부자본증권 발행결정"
    ),
    MajorEventSpec(
        "asset_transfer_etc_putback", "astInhtrfEtcPtbkOpt", "자산양수도(기타), 풋백옵션"
    ),
    MajorEventSpec(
        "other_corp_stock_transfer", "otcprStkInvscrTrfDecsn", "타법인 주식 및 출자증권 양도결정"
    ),
    MajorEventSpec("tangible_asset_transfer", "tgastTrfDecsn", "유형자산 양도 결정"),
    MajorEventSpec("tangible_asset_acquisition", "tgastInhDecsn", "유형자산 양수 결정"),
    MajorEventSpec(
        "other_corp_stock_acquisition", "otcprStkInvscrInhDecsn", "타법인 주식 및 출자증권 양수결정"
    ),
    MajorEventSpec("business_transfer", "bsnTrfDecsn", "영업양도 결정"),
    MajorEventSpec("business_acquisition", "bsnInhDecsn", "영업양수 결정"),
    MajorEventSpec(
        "treasury_trust_terminate", "tsstkAqTrctrCcDecsn", "자기주식취득 신탁계약 해지 결정"
    ),
    MajorEventSpec(
        "treasury_trust_conclude", "tsstkAqTrctrCnsDecsn", "자기주식취득 신탁계약 체결 결정"
    ),
    MajorEventSpec("treasury_stock_disposal", "tsstkDpDecsn", "자기주식 처분 결정"),
    MajorEventSpec("treasury_stock_acquisition", "tsstkAqDecsn", "자기주식 취득 결정"),
    MajorEventSpec("stock_exchange_transfer", "stkExtrDecsn", "주식교환·이전 결정"),
    MajorEventSpec("division_merger", "cmpDvmgDecsn", "회사분할합병 결정"),
    MajorEventSpec("company_division", "cmpDvDecsn", "회사분할 결정"),
    MajorEventSpec("company_merger", "cmpMgDecsn", "회사합병 결정"),
    MajorEventSpec("bond_acquisition_decision", "stkrtbdInhDecsn", "주권 관련 사채권 양수 결정"),
    MajorEventSpec("business_suspension", "bsnSp", "영업정지"),
)

assert len(MAJOR_EVENT_SPECS) == 36, "주요사항보고서 36종이 모두 등록되어야 한다"
assert len({s.source_api for s in MAJOR_EVENT_SPECS}) == 36, "source_api 중복 없음"
assert len({s.event_type for s in MAJOR_EVENT_SPECS}) == 36, "event_type 중복 없음"
