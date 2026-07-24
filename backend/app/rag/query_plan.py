"""질문 계획(QueryPlan) — 규칙 기반 라우팅 (SPEC §9).

하나의 질문을 단일 종류로 분류하지 않고, 여러 작업 플래그를 동시에 켠다.
추가 LLM 호출 없이 신호어(규칙)로 판단한다. 특정 종목/항목 하드코딩 없음.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── 의도 신호 중앙 관리 (SPEC §9.1) ─────────────────────────────────────────
# 세 의도(financial / news / report)는 서로 독립이며 신호가 겹치지 않는다.
# 일반 어휘일 뿐 특정 종목/증권사/완성문장이 아니다. 동의어·복합표현을 함께 담는다.
#
# financial intent: 실제 재무 수치(확정/공식 값)를 가리키는 '구체 항목' 신호.
# '목표주가'는 증권사 예측치이므로 넣지 않는다(report intent).
# '얼마/몇' 같은 범용 수량어는 여기 넣지 않는다(어느 의도에나 붙는 수식어라
# 그 자체로 financial 을 켜면 '목표주가 얼마'처럼 report 질문을 오염시킨다).
_NUMBER_SIGNALS = (
    "매출",
    "매출액",
    "영업이익",
    "순이익",
    "당기순이익",
    "eps",
    "주당순이익",
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
# news/document intent: 원인·이유·최근 이슈·시장 반응 등 설명이 필요한 질문.
# '전망'은 report intent 로 옮겨 여기서 제외한다.
_EXPLAIN_SIGNALS = (
    "왜",
    "이유",
    "원인",
    "의미",
    "중요",
    "영향",
    "위험",
    "평가",
    "핵심",
    "배경",
    "설명",
    "이슈",
    "논란",
    "반응",
    "동향",
    "소식",
)
_TERM_SIGNALS = ("뭐야", "뜻", "정의", "무슨 말", "무슨말", "뭔가요", "무엇")
_PRICE_SIGNALS = ("주가", "현재가", "올랐", "내렸", "거래량", "시세")
_CORRECTION_SIGNALS = ("정정", "정정 전", "정정 후", "바뀐", "변경")
# report intent: 목표주가·투자의견·증권사 분석·리포트 전망.
_REPORT_SIGNALS = (
    "전망",
    "목표주가",
    "목표가",
    "투자의견",
    "증권사",
    "리포트",
    "레포트",
    "보고서",
    "애널리스트",
    "컨센서스",
    "매수의견",
    "매도의견",
    "상향",
    "하향",
    "목표 주가",
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

    # ── 세 의도를 서로 독립적으로 판정 ──────────────────────────────────────
    # 각 need_* 는 자기 의도 신호에만 반응한다. 한 신호가 여러 의도를 켜지 않는다.
    plan.need_financials = _hit(q, _NUMBER_SIGNALS)  # financial intent
    plan.need_reports = _hit(q, _REPORT_SIGNALS)  # report intent
    plan.need_terms = _hit(q, _TERM_SIGNALS)
    plan.need_price = _hit(q, _PRICE_SIGNALS)
    plan.need_correction = _hit(q, _CORRECTION_SIGNALS)
    explain = _hit(q, _EXPLAIN_SIGNALS)  # news/document intent

    # 뉴스(문서) 검색(need_documents)은 news/document intent 일 때만 켠다:
    #  - 설명/정정 신호가 있으면 켬(원인·이유·영향·최근이슈 등).
    #  - 어떤 의도 신호(financial/report/term/correction/explain)도 없는 순수 자연어
    #    질문은 기본 뉴스 검색으로 켬.
    #  - financial/report/term intent 만 있고 설명 신호가 없으면 뉴스를 켜지 않는다
    #    (목표주가·전망만 물으면 리포트만, 숫자만 물으면 SQL 만 — 과호출 방지).
    any_intent = (
        plan.need_financials or plan.need_reports or plan.need_terms or plan.need_correction
    )
    plan.need_documents = explain or plan.need_correction or (not any_intent)
    # 공시 관련 신호가 있으면 구조화 공시 값도 후보로.
    plan.need_disclosure_values = plan.need_correction or _hit(
        q, ("공시", "자기주식", "증자", "배당", "계약", "처분", "취득")
    )

    return plan
