"""Phase 8 자동 평가 지표 계산.

원칙(prompt §8): 자연어 표현이 다른 정답을 단순 문자열 완전 일치로 실패 처리하지 않는다.
숫자·기간·식별자는 정확 일치로 평가한다.

- 사실 포함 판정: 핵심어 기반 부분 일치(표현 차이 허용)
- 숫자 판정: 정규화 후 정확 일치(조·억 표기, 콤마, 단위 변형 허용)
- 식별자 판정: 문자열 완전 일치
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

# 조·억 한글 단위. 재무 숫자는 원 단위 정수로 저장돼 있고 답변은 "43조 6,010억원" 처럼 쓴다.
_UNIT_MULT = {"조": 10**12, "억": 10**8, "만": 10**4}


def percentile(values: list[float], pct: float) -> float:
    """P50/P95 계산(선형 보간 없이 nearest-rank)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round(pct / 100 * len(ordered) + 0.5)) - 1))
    return float(ordered[k])


def normalize_number_text(text: str) -> set[float]:
    """답변 텍스트에서 숫자를 원 단위 실수 집합으로 뽑는다.

    "43조 6,010억원" → 43_601_000_000_000 처럼 한글 단위 조합도 계산한다.
    퍼센트·배수는 그대로 값으로 담는다(단위 판정은 별도).
    """
    found: set[float] = set()
    cleaned = text.replace(",", "")

    # 1) 한글 단위 조합: "43조 6010억", "6010억", "1조"
    for m in re.finditer(r"(?:\d+(?:\.\d+)?\s*[조억만]\s*)+", cleaned):
        total = 0.0
        for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([조억만])", m.group()):
            total += float(num) * _UNIT_MULT[unit]
        if total:
            found.add(total)

    # 2) 맨 숫자(퍼센트·원·배 등)
    for m in re.finditer(r"-?\d+(?:\.\d+)?", cleaned):
        try:
            found.add(float(m.group()))
        except ValueError:
            continue
    return found


def number_matches(answer: str, value: float, tolerance: float = 0.0) -> bool:
    """기대 숫자가 답변에 정확히 나타나는지.

    tolerance 가 0 이면 완전 일치. 큰 금액은 답변이 반올림해 쓰는 경우가 있어
    (43,601,051,000,000 → "43조 6,010억") 유효숫자 상위 일치도 인정한다.
    """
    got = normalize_number_text(answer)
    if any(abs(g - value) <= tolerance for g in got):
        return True
    if value == 0:
        return False
    # 반올림 표기 허용: 조 단위 이상은 억 자리에서 반올림한 값과 비교
    for scale in (10**8, 10**12):
        if abs(value) >= scale:
            rounded = round(value / scale)
            if any(abs(g / scale - rounded) < 0.5 for g in got if g):
                return True
            if rounded in got:
                return True
    return False


def fact_covered(answer: str, fact: str) -> bool:
    """핵심 사실이 답변에 담겼는지(표현 차이 허용).

    fact 를 공백으로 끊어 핵심어를 만들고, 7할 이상 등장하면 포함으로 본다.
    조사·어미 차이를 흡수하려고 부분 문자열로 찾는다.
    """
    keys = [k for k in re.split(r"\s+", fact.strip()) if len(k) >= 2]
    if not keys:
        return False
    hit = sum(1 for k in keys if k in answer)
    return hit / len(keys) >= 0.7


@dataclass
class AgentMetrics:
    """Agent trajectory 지표(§8 Agent)."""

    n: int = 0
    required_hit: int = 0
    required_total: int = 0
    forbidden_cases: int = 0
    unnecessary_tool_calls: int = 0
    tool_calls_total: int = 0
    arg_hit: int = 0
    arg_total: int = 0
    multistep_done: int = 0
    multistep_total: int = 0
    duplicate_cases: int = 0

    def as_dict(self) -> dict:
        return {
            "required_tool_recall": _ratio(self.required_hit, self.required_total),
            "forbidden_tool_call_rate": _ratio(self.forbidden_cases, self.n),
            "unnecessary_tool_call_rate": _ratio(
                self.unnecessary_tool_calls, self.tool_calls_total
            ),
            "tool_argument_accuracy": _ratio(self.arg_hit, self.arg_total),
            "multistep_completion_rate": _ratio(self.multistep_done, self.multistep_total),
            "duplicate_call_rate": _ratio(self.duplicate_cases, self.n),
        }


@dataclass
class RetrievalMetrics:
    """검색 지표(§8 검색).

    문서 검색(뉴스·리포트)과 구조화 조회(용어·재무·공시)를 섞으면 의미가 없다.
    전자는 Retriever 순위 품질이고 후자는 DB 행을 정확히 집었는가의 문제다.
    한 숫자로 합치면 어느 계층을 고쳐야 할지 알 수 없어 분리한다.

    문서 검색(news/report)은 부모 문서 ID 기준 Recall@K/Hit@1/MRR 을
    grader.document_recall_stats() 가 별도로 계산해 as_dict() 호출 시
    news_stats/report_stats/page_stats 로 주입한다(청크 ID 합산이 아니라
    뉴스·리포트를 완전히 분리해 각자의 분모로 계산 — 감사 §1).
    """

    # 구조화 조회(term / financial / structured_disclosure)
    lookup_hit: int = 0
    lookup_total: int = 0
    # 공통
    other_stock_cases: int = 0
    n: int = 0
    # 문서 검색(뉴스/리포트 분리, aggregate() 가 document_recall_stats() 결과를 주입)
    news_stats: dict | None = None
    report_stats: dict | None = None
    page_stats: dict | None = None
    # Phase 8 뉴스 최종 교정 §4B/C: strict 와 별도로 보존하는 event-equivalent
    # Recall(사람 승인 필요)과 product failure rate(평가 데이터 문제 제외).
    news_event_equivalent: dict | None = None
    report_event_equivalent: dict | None = None
    news_product_failure: dict | None = None
    report_product_failure: dict | None = None

    def as_dict(self) -> dict:
        return {
            "news_retrieval": self.news_stats,
            "report_retrieval": self.report_stats,
            "report_page_accuracy": self.page_stats,
            "news_retrieval_event_equivalent": self.news_event_equivalent,
            "report_retrieval_event_equivalent": self.report_event_equivalent,
            "news_product_failure": self.news_product_failure,
            "report_product_failure": self.report_product_failure,
            "structured_lookup": {
                "row_hit_rate": _ratio(self.lookup_hit, self.lookup_total),
            },
            "other_stock_contamination_rate": _ratio(self.other_stock_cases, self.n),
        }


@dataclass
class NumberMetrics:
    """숫자·기간 지표(§8 숫자)."""

    exact_hit: int = 0
    exact_total: int = 0
    unit_hit: int = 0
    unit_total: int = 0
    period_hit: int = 0
    period_total: int = 0
    trading_day_hit: int = 0
    trading_day_total: int = 0
    value_kind_confusions: int = 0

    def as_dict(self) -> dict:
        return {
            "number_exact_match": _ratio(self.exact_hit, self.exact_total),
            "unit_accuracy": _ratio(self.unit_hit, self.unit_total),
            "period_accuracy": _ratio(self.period_hit, self.period_total),
            "trading_day_accuracy": _ratio(self.trading_day_hit, self.trading_day_total),
            "value_kind_confusions": self.value_kind_confusions,
        }


@dataclass
class AnswerMetrics:
    """답변·출처 지표(§8 답변·출처)."""

    fact_hit: int = 0
    fact_total: int = 0
    citation_precision_hit: int = 0
    citation_precision_total: int = 0
    citation_covered: int = 0
    citation_cov_total: int = 0
    nonexistent_citations: int = 0
    unsupported_numbers: int = 0
    exclusion_violations: int = 0
    overclaim_cases: int = 0
    false_answer_on_unanswerable: int = 0

    def as_dict(self) -> dict:
        return {
            "key_fact_coverage": _ratio(self.fact_hit, self.fact_total),
            "citation_precision": _ratio(
                self.citation_precision_hit, self.citation_precision_total
            ),
            "citation_coverage": _ratio(self.citation_covered, self.citation_cov_total),
            "nonexistent_citations": self.nonexistent_citations,
            "unsupported_numbers": self.unsupported_numbers,
            "exclusion_violations": self.exclusion_violations,
            "overclaim_cases": self.overclaim_cases,
            "false_answer_on_unanswerable": self.false_answer_on_unanswerable,
        }


@dataclass
class OpsMetrics:
    """운영 지표(§8 운영)."""

    latencies: list[float] = field(default_factory=list)
    tool_calls: list[int] = field(default_factory=list)
    model_calls: list[int] = field(default_factory=list)
    costs: list[float] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "latency_ms_p50": round(percentile(self.latencies, 50), 1),
            "latency_ms_p95": round(percentile(self.latencies, 95), 1),
            "avg_tool_calls": _avg(self.tool_calls),
            "avg_model_calls": _avg(self.model_calls),
            "cost_usd_per_query": round(sum(self.costs) / len(self.costs), 6)
            if self.costs
            else 0.0,
            "cost_usd_total": round(sum(self.costs), 6),
        }


def _ratio(hit: int, total: int) -> float | None:
    """분모가 0이면 None 을 돌려준다.

    해당 항목이 없어서 못 잰 것(None)과 재서 0점인 것(0.0)은 다르다.
    0.0 으로 뭉뚱그리면 '전부 틀렸다'로 오독된다.
    """
    return round(hit / total, 4) if total else None


def _avg(values: list[int]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def duplicate_call_count(tool_names: list[str]) -> int:
    """동일 Tool 을 3회 이상 부른 경우의 수(기존 evaluate_agent.py 기준 승계)."""
    return sum(1 for n in Counter(tool_names).values() if n >= 3)


# 과도한 인과 단정 표현(§8 '과도한 인과 단정 수').
_OVERCLAIM_PATTERNS = (
    "때문에 반드시",
    "확실히 오를",
    "확실히 내릴",
    "무조건",
    "반드시 상승",
    "반드시 하락",
    "보장",
    "틀림없",
)


def has_overclaim(answer: str) -> bool:
    return any(p in answer for p in _OVERCLAIM_PATTERNS)
