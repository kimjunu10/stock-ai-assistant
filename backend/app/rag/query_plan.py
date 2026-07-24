"""질문 계획(QueryPlan) — 규칙 기반 라우팅 (SPEC §9).

하나의 질문을 단일 종류로 분류하지 않고, 여러 작업 플래그를 동시에 켠다.
추가 LLM 호출 없이 신호어(규칙)로 판단한다. 특정 종목/항목 하드코딩 없음.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 신호어(SPEC §9.1). 일반 어휘일 뿐 특정 종목/공시/항목이 아니다.
_NUMBER_SIGNALS = (
    "얼마",
    "몇",
    "매출",
    "영업이익",
    "순이익",
    "목표주가",
    "발행주식",
    "계약금액",
    "전환가액",
    "수익률",
    "등락률",
    "배당",
    "자산",
    "부채",
    "자본",
    "현금흐름",
    "주식수",
)
_EXPLAIN_SIGNALS = ("왜", "의미", "중요", "영향", "위험", "전망", "평가", "핵심", "배경", "설명")
_TERM_SIGNALS = ("뭐야", "뜻", "정의", "무슨 말", "무슨말", "뭔가요", "무엇")
_PRICE_SIGNALS = ("주가", "현재가", "올랐", "내렸", "거래량", "시세")
_CORRECTION_SIGNALS = ("정정", "정정 전", "정정 후", "바뀐", "변경")
# 증권사 리포트 신호: 전망·목표주가·투자의견·증권사·리포트 관련 질문에서만 리포트 검색.
_REPORT_SIGNALS = (
    "전망",
    "목표주가",
    "투자의견",
    "증권사",
    "리포트",
    "레포트",
    "애널리스트",
    "컨센서스",
    "매수의견",
    "매도의견",
)

_STOCK_CODE_RE = re.compile(r"\b(\d{6})\b")


@dataclass
class QueryPlan:
    stock_code: str | None = None
    need_financials: bool = False
    need_disclosure_values: bool = False
    need_terms: bool = False
    need_price: bool = False
    need_documents: bool = False
    need_correction: bool = False
    need_reports: bool = False
    requested_source_types: list[str] = field(default_factory=list)
    current_document_id: str | None = None
    actual_or_forecast: str | None = None


def _hit(text: str, signals) -> bool:
    return any(s in text for s in signals)


def build_query_plan(
    question: str,
    *,
    stock_code: str | None = None,
    current_document_id: str | None = None,
    current_stock_code: str | None = None,
) -> QueryPlan:
    """질문 텍스트와 UI 컨텍스트로 QueryPlan을 만든다.

    종목 결정 우선순위(SPEC §9.2): UI stock_code > 현재 문서 종목 > 질문 내 6자리 코드.
    회사명→코드 매핑은 stocks 테이블 기반으로 서비스 계층에서 보강한다(여기선 코드만).
    """
    q = question or ""
    plan = QueryPlan(current_document_id=current_document_id)

    # 종목 결정 (임의 선택 금지)
    if stock_code:
        plan.stock_code = stock_code
    elif current_stock_code:
        plan.stock_code = current_stock_code
    else:
        m = _STOCK_CODE_RE.search(q)
        if m:
            plan.stock_code = m.group(1)

    plan.need_financials = _hit(q, _NUMBER_SIGNALS)
    plan.need_terms = _hit(q, _TERM_SIGNALS)
    plan.need_price = _hit(q, _PRICE_SIGNALS)
    plan.need_correction = _hit(q, _CORRECTION_SIGNALS)
    explain = _hit(q, _EXPLAIN_SIGNALS)

    # 리포트 검색은 전망·목표주가·투자의견·증권사·리포트 신호가 있을 때만 켠다.
    # 순수 뉴스/숫자/용어 질문에서는 켜지 않는다(신호 기반, 문장 하드코딩 없음).
    plan.need_reports = _hit(q, _REPORT_SIGNALS)

    # 문서 검색(RAG)은 "설명이 필요한 질문"에만 켠다. 의도 신호로만 구분한다.
    #  - 순수 숫자 질문(숫자 신호만, 설명 없음)  → 문서 검색 끔(SQL 만; 뉴스 검색·임베딩 호출 안 함)
    #  - 숫자 + 설명(왜/영향/전망 등)           → 문서 검색 켬
    #  - 정정공시 질문                          → 문서 검색 켬(정정 설명 근거)
    #  - 순수 용어 질문                         → 문서 검색 끔(용어 조회만)
    #  - 그 외(뉴스성 자연어 질문)              → 문서 검색 켬(기본 뉴스 하이브리드 검색)
    #
    # 판정 순서: 설명/정정이면 항상 켬. 아니면 "숫자 또는 용어 신호가 있는" 사실조회형
    # 질문은 문서 검색을 끄고(그 신호에 맞는 SQL/용어만 실행), 어떤 사실 신호도 없는
    # 자연어 질문만 기본 뉴스 검색으로 보낸다.
    fact_lookup_only = (plan.need_financials or plan.need_terms) and not explain
    plan.need_documents = (
        explain or plan.need_correction or (not fact_lookup_only and not plan.need_terms)
    )
    # 공시 관련 신호가 있으면 구조화 공시 값도 후보로.
    plan.need_disclosure_values = plan.need_correction or _hit(
        q, ("공시", "자기주식", "증자", "배당", "계약", "처분", "취득")
    )

    return plan
