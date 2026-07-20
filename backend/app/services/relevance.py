"""Deterministic stock relevance rules for collected news."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StockMentionRule:
    """Exact company name and deliberately conservative aliases for one stock."""

    stock_code: str
    name: str
    aliases: tuple[str, ...] = ()

    @property
    def terms(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass(frozen=True, slots=True)
class RelevanceDecision:
    relevance: str
    mention_count: int
    reason: str


# Avoid broad group names such as "삼성", "SK", "두산", "한화", and "현대".
# Historical legal names are included only where they identify the same listed company.
STOCK_MENTION_RULES = {
    "005930": StockMentionRule(
        stock_code="005930",
        name="삼성전자",
        aliases=("Samsung Electronics", "005930"),
    ),
    "000660": StockMentionRule(
        stock_code="000660",
        name="SK하이닉스",
        aliases=("하이닉스", "에스케이하이닉스", "SK Hynix", "000660"),
    ),
    "034020": StockMentionRule(
        stock_code="034020",
        name="두산에너빌리티",
        aliases=("두산중공업", "Doosan Enerbility", "034020"),
    ),
    "042660": StockMentionRule(
        stock_code="042660",
        name="한화오션",
        aliases=("대우조선해양", "Hanwha Ocean", "042660"),
    ),
    "005380": StockMentionRule(
        stock_code="005380",
        name="현대차",
        aliases=("현대자동차", "Hyundai Motor", "Hyundai Motor Company", "005380"),
    ),
}

_FIELD_ORDER = ("title", "body", "description")
_SEPARATOR_RE = re.compile(r"[-‐‑‒–—_/]+")
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    normalized = _SEPARATOR_RE.sub(" ", normalized)
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def _find_mentions(text: str, rule: StockMentionRule) -> list[tuple[int, int, str]]:
    """Find non-overlapping terms, preferring the longest term at the same position."""

    candidates: list[tuple[int, int, str]] = []
    for term in rule.terms:
        normalized_term = _normalize(term)
        if not normalized_term:
            continue
        if normalized_term.isdecimal():
            pattern = re.compile(rf"(?<!\d){re.escape(normalized_term)}(?!\d)")
        else:
            pattern = re.compile(re.escape(normalized_term))
        candidates.extend(
            (match.start(), match.end(), term)
            for match in pattern.finditer(text)
        )

    selected: list[tuple[int, int, str]] = []
    for candidate in sorted(candidates, key=lambda item: (item[0], -(item[1] - item[0]))):
        start, end, _ = candidate
        overlaps = any(
            start < chosen_end and end > chosen_start
            for chosen_start, chosen_end, _ in selected
        )
        if overlaps:
            continue
        selected.append(candidate)
    return selected


def classify_stock_relevance(
    *,
    stock_code: str,
    title: str | None,
    body: str | None,
    description: str | None,
) -> RelevanceDecision:
    """Label a stock link relevant when any configured term occurs in stored text."""

    try:
        rule = STOCK_MENTION_RULES[stock_code]
    except KeyError as exc:
        raise ValueError(f"No relevance rule configured for stock_code={stock_code}") from exc

    field_values = {
        "title": title,
        "body": body,
        "description": description,
    }
    mention_count = 0
    matched_fields: list[str] = []
    matched_terms: list[str] = []
    for field in _FIELD_ORDER:
        matches = _find_mentions(_normalize(field_values[field]), rule)
        if not matches:
            continue
        mention_count += len(matches)
        matched_fields.append(field)
        for _, _, term in matches:
            if term not in matched_terms:
                matched_terms.append(term)

    if mention_count:
        reason = (
            "stock_term_match_v1: terms="
            + ", ".join(matched_terms)
            + "; fields="
            + ", ".join(matched_fields)
        )
        return RelevanceDecision(
            relevance="relevant",
            mention_count=mention_count,
            reason=reason,
        )

    return RelevanceDecision(
        relevance="irrelevant",
        mention_count=0,
        reason="stock_term_match_v1: no exact stock name or safe alias in title/body/description",
    )
