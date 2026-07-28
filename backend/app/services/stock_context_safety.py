"""Single-stock screen context safety policy.

The stock selected by the UI is authoritative.  A question may omit a company
or name that same company, but it must not silently switch to another company.
This module is the deterministic layer: known stock aliases, explicit tickers,
and runtime/tool/source codes are enforced here.  Ambiguous natural-language
candidates are only surfaced for a separate semantic classifier.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

from app.services.relevance import STOCK_MENTION_RULES, StockMentionRule
from app.sources.prices import SUPPORTED_STOCK_CODES

StockContextErrorCode = Literal[
    "STOCK_CONTEXT_MISMATCH",
    "UNSUPPORTED_STOCK",
    "MULTI_STOCK_NOT_SUPPORTED",
]

_FINANCIAL_TOPIC_RE = re.compile(
    r"실적|매출(?:액)?|영업이익|당기?순이익|자산|부채|자본|"
    r"주가|주식|뉴스|공시|배당|목표주가|리포트|전망|시가총액|수익률|호재|악재|비교",
    re.IGNORECASE,
)
_SUBJECT_QUESTION_RE = re.compile(
    r"(?P<name>[가-힣A-Za-z][가-힣A-Za-z0-9.$&·_-]{1,30})"
    r"(?:은|는)\s*(?:어때|어떻게|알려|궁금)",
    re.IGNORECASE,
)
_EXPLICIT_TICKER_RE = re.compile(r"(?:[$(]\s*)(?P<ticker>[A-Za-z]{2,10})(?:\s*\))?")
_DIRECT_COMPANY_REQUEST_RE = re.compile(
    r"(?P<name>[가-힣A-Za-z][가-힣A-Za-z0-9.$&·_-]{1,30})"
    r"(?:\s*정보)?\s*(?:알려|분석|설명|궁금)",
    re.IGNORECASE,
)
_SIX_DIGIT_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_CONJUNCTION_RE = re.compile(r"\s*(?:와|과|랑|이랑|및|vs\.?|대)\s*", re.IGNORECASE)
_SEPARATOR_RE = re.compile(r"[-‐‑‒–—_/]+")
_WHITESPACE_RE = re.compile(r"\s+")
_QUESTION_BOUNDARY_RE = re.compile(r"[?.!\n]")

# These are grammar/time/finance qualifiers, not company names.  Keeping this
# list domain-generic avoids a company-specific unsupported-name allow/blocklist.
_NON_COMPANY_TOKEN_RE = re.compile(
    r"(?:^|\s)(?:"
    r"혹시|그럼|그러면|그리고|또|현재|지금|오늘|어제|올해|금년|작년|지난해|"
    r"이번|최근|최신|연간|분기|반기|누적|당기|예상|실제|연결|별도|기준|"
    r"우리|회사|이|그|해당|선택한|종목|화면|정보|자료|상황|정도|"
    r"\d{4}년|\d{1,2}분기"
    r")(?:\s|$)",
    re.IGNORECASE,
)
_NON_COMPANY_PHRASES = {
    "",
    "이 종목",
    "그 종목",
    "선택 종목",
    "선택한 종목",
    "우리 회사",
    "관련",
    "관련된 공식",
    "공식",
    "시장",
    "업계",
    "산업",
    "반도체",
    "반도체 업황",
    "발표 전후",
    "다른 증권사 의견",
    "증권사 의견",
    "내용",
    "숫자",
}
_COMPANY_SUFFIX_RE = re.compile(
    r"(?:전자|자동차|모터스|테크|홀딩스|중공업|에너지|에너빌리티|"
    r"오션|바이오|제약|화학|건설|산업|상사|그룹|inc|corp|corporation|"
    r"company|holdings)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class StockMention:
    stock_code: str | None
    name: str
    supported: bool


@dataclass(frozen=True, slots=True)
class StockContextDecision:
    allowed: bool
    error_code: StockContextErrorCode | None = None
    message: str | None = None
    selected_stock_code: str | None = None
    selected_stock_name: str | None = None
    mentions: tuple[StockMention, ...] = ()


@dataclass(frozen=True, slots=True)
class StockExecutionViolation:
    error_code: StockContextErrorCode
    message: str
    observed_codes: tuple[str, ...]
    failed_layer: str


def _normalize(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = _SEPARATOR_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _term_pattern(term: str) -> re.Pattern[str]:
    normalized = _normalize(term)
    if normalized.isdecimal():
        return re.compile(rf"(?<!\d){re.escape(normalized)}(?!\d)")
    if normalized.isascii():
        return re.compile(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])")
    return re.compile(re.escape(normalized))


def stock_name(stock_code: str | None) -> str | None:
    rule = STOCK_MENTION_RULES.get(stock_code or "")
    return rule.name if rule else None


def _subject_particle(name: str) -> str:
    last = name[-1:] if name else ""
    if "가" <= last <= "힣":
        return "은" if (ord(last) - ord("가")) % 28 else "는"
    return "은(는)"


def _supported_mentions(question: str) -> list[tuple[int, StockMention]]:
    normalized = _normalize(question)
    found: list[tuple[int, StockMention]] = []
    for stock_code, rule in STOCK_MENTION_RULES.items():
        starts = [
            match.start()
            for term in rule.terms
            for match in _term_pattern(term).finditer(normalized)
        ]
        if starts:
            found.append(
                (
                    min(starts),
                    StockMention(stock_code=stock_code, name=rule.name, supported=True),
                )
            )
    return sorted(found, key=lambda item: item[0])


def _mask_supported_terms(question: str) -> str:
    masked = _normalize(question)
    terms = sorted(
        {term for rule in STOCK_MENTION_RULES.values() for term in rule.terms},
        key=lambda value: len(_normalize(value)),
        reverse=True,
    )
    for term in terms:
        masked = _term_pattern(term).sub(" ", masked)
    return _WHITESPACE_RE.sub(" ", masked).strip()


def _clean_candidate(value: str) -> str:
    cleaned = _NON_COMPANY_TOKEN_RE.sub(" ", _normalize(value))
    cleaned = _NON_COMPANY_TOKEN_RE.sub(" ", cleaned)
    cleaned = re.sub(r"^(?:와|과|랑|이랑|및)\s*", "", cleaned)
    cleaned = re.sub(r"\s*(?:의|에|에서)$", "", cleaned)
    cleaned = re.sub(r"(?:만|좀)$", "", cleaned)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip(" ,·")
    if cleaned in _NON_COMPANY_PHRASES or cleaned.isdecimal() or len(cleaned) < 2:
        return ""
    return cleaned


def _is_financial_topic_only(value: str) -> bool:
    return _FINANCIAL_TOPIC_RE.fullmatch(_normalize(value)) is not None


def _looks_like_company_candidate(value: str) -> bool:
    normalized = _normalize(value)
    if not normalized or normalized in _NON_COMPANY_PHRASES or _is_financial_topic_only(normalized):
        return False
    words = normalized.split()
    if len(words) == 1:
        return True
    if all(word.isascii() for word in words):
        return True
    return _COMPANY_SUFFIX_RE.search(normalized) is not None


def natural_company_candidates(question: str) -> tuple[str, ...]:
    """Find text that may be a natural-language company mention.

    The single-stock UI primarily receives financial questions.  A noun phrase
    before a financial topic ("Acme 올해 실적") or an explicit subject/ticker
    may be a company mention.  Pure context questions ("올해 실적") reduce to an
    empty candidate.  These candidates only decide whether semantic
    classification is needed; they never block a request by themselves.
    """

    masked = _mask_supported_terms(question)
    candidates: list[tuple[int, str]] = []

    topic = _FINANCIAL_TOPIC_RE.search(masked)
    if topic:
        prefix = _QUESTION_BOUNDARY_RE.split(masked[: topic.start()])[-1][-80:]
        offset = max(0, topic.start() - len(prefix))
        for part in _CONJUNCTION_RE.split(prefix):
            name = _clean_candidate(part)
            if _looks_like_company_candidate(name):
                candidates.append((offset + prefix.find(part), name))

    for match in _SUBJECT_QUESTION_RE.finditer(masked):
        name = _clean_candidate(match.group("name"))
        if _looks_like_company_candidate(name):
            candidates.append((match.start("name"), name))

    for match in _DIRECT_COMPANY_REQUEST_RE.finditer(masked):
        name = _clean_candidate(match.group("name"))
        if _looks_like_company_candidate(name):
            candidates.append((match.start("name"), name))

    unique: list[str] = []
    seen: set[str] = set()
    for _, name in sorted(candidates, key=lambda item: item[0]):
        key = _normalize(name)
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)
    return tuple(unique)


def _explicit_unsupported_identifiers(question: str) -> list[tuple[int, str]]:
    """Extract unambiguous unsupported tickers or six-digit stock codes."""

    masked = _mask_supported_terms(question)
    candidates: list[tuple[int, str]] = []
    for match in _EXPLICIT_TICKER_RE.finditer(masked):
        ticker = match.group("ticker")
        if ticker.casefold() not in {"ai", "per", "pbr", "roe", "mou", "etf"}:
            candidates.append((match.start("ticker"), ticker))

    for match in _SIX_DIGIT_CODE_RE.finditer(masked):
        code = match.group(1)
        if code not in SUPPORTED_STOCK_CODES:
            candidates.append((match.start(1), code))

    unique: list[tuple[int, str]] = []
    seen: set[str] = set()
    for position, name in sorted(candidates, key=lambda item: item[0]):
        key = _normalize(name)
        if key in seen:
            continue
        seen.add(key)
        unique.append((position, name))
    return unique


def validate_question_stock_context(
    question: str,
    selected_stock_code: str | None,
) -> StockContextDecision:
    selected_name = stock_name(selected_stock_code)
    if selected_stock_code and selected_stock_code not in SUPPORTED_STOCK_CODES:
        message = (
            "현재 선택된 종목은 지원하지 않는 종목입니다. 지원 종목을 선택한 뒤 다시 질문해 주세요."
        )
        return StockContextDecision(
            allowed=False,
            error_code="UNSUPPORTED_STOCK",
            message=message,
            selected_stock_code=selected_stock_code,
        )

    supported = _supported_mentions(question)
    unsupported = _explicit_unsupported_identifiers(question)
    mentions = tuple(
        [item[1] for item in supported]
        + [StockMention(stock_code=None, name=name, supported=False) for _, name in unsupported]
    )

    if len(mentions) >= 2:
        return StockContextDecision(
            allowed=False,
            error_code="MULTI_STOCK_NOT_SUPPORTED",
            message="현재 화면에서는 한 종목씩 조회할 수 있습니다.",
            selected_stock_code=selected_stock_code,
            selected_stock_name=selected_name,
            mentions=mentions,
        )

    if supported:
        requested = supported[0][1]
        if selected_stock_code and requested.stock_code != selected_stock_code:
            message = (
                f"현재 {selected_name or selected_stock_code}가 선택되어 있습니다.\n"
                f"{requested.name} 정보를 확인하려면 종목을 {requested.name}로 변경해 주세요."
            )
            return StockContextDecision(
                allowed=False,
                error_code="STOCK_CONTEXT_MISMATCH",
                message=message,
                selected_stock_code=selected_stock_code,
                selected_stock_name=selected_name,
                mentions=mentions,
            )

    if unsupported:
        requested_name = unsupported[0][1]
        message = (
            f"현재 {requested_name}{_subject_particle(requested_name)} 지원하지 않는 종목입니다.\n"
            "지원 종목을 선택한 뒤 다시 질문해 주세요."
        )
        return StockContextDecision(
            allowed=False,
            error_code="UNSUPPORTED_STOCK",
            message=message,
            selected_stock_code=selected_stock_code,
            selected_stock_name=selected_name,
            mentions=mentions,
        )

    return StockContextDecision(
        allowed=True,
        selected_stock_code=selected_stock_code,
        selected_stock_name=selected_name,
        mentions=mentions,
    )


def decision_from_semantic_stock_reference(
    *,
    relation: Literal["none", "selected", "other", "multiple"],
    company_names: list[str],
    selected_stock_code: str | None,
) -> StockContextDecision:
    """Convert semantic company-reference output into the existing safety contract."""

    selected_name = stock_name(selected_stock_code)
    names = [name.strip() for name in company_names if name and name.strip()]
    if relation in {"none", "selected"}:
        return StockContextDecision(
            allowed=True,
            selected_stock_code=selected_stock_code,
            selected_stock_name=selected_name,
        )

    if relation == "multiple":
        return StockContextDecision(
            allowed=False,
            error_code="MULTI_STOCK_NOT_SUPPORTED",
            message="현재 화면에서는 한 종목씩 조회할 수 있습니다.",
            selected_stock_code=selected_stock_code,
            selected_stock_name=selected_name,
            mentions=tuple(
                StockMention(stock_code=None, name=name, supported=False) for name in names
            ),
        )

    requested_name = names[0] if names else "다른 회사"
    supported = _supported_mentions(requested_name)
    if supported:
        requested = supported[0][1]
        if requested.stock_code == selected_stock_code:
            return StockContextDecision(
                allowed=True,
                selected_stock_code=selected_stock_code,
                selected_stock_name=selected_name,
                mentions=(requested,),
            )
        message = (
            f"현재 {selected_name or selected_stock_code}가 선택되어 있습니다.\n"
            f"{requested.name} 정보를 확인하려면 종목을 {requested.name}로 변경해 주세요."
        )
        return StockContextDecision(
            allowed=False,
            error_code="STOCK_CONTEXT_MISMATCH",
            message=message,
            selected_stock_code=selected_stock_code,
            selected_stock_name=selected_name,
            mentions=(requested,),
        )

    message = (
        f"현재 {requested_name}{_subject_particle(requested_name)} 지원하지 않는 종목입니다.\n"
        "지원 종목을 선택한 뒤 다시 질문해 주세요."
    )
    return StockContextDecision(
        allowed=False,
        error_code="UNSUPPORTED_STOCK",
        message=message,
        selected_stock_code=selected_stock_code,
        selected_stock_name=selected_name,
        mentions=(StockMention(stock_code=None, name=requested_name, supported=False),),
    )


def is_selected_stock_alias(value: str, selected_stock_code: str) -> bool:
    rule: StockMentionRule | None = STOCK_MENTION_RULES.get(selected_stock_code)
    if not rule:
        return False
    normalized = _normalize(value)
    return any(normalized == _normalize(term) for term in rule.terms)


def record_runtime_stock_violation(
    context: Any,
    *,
    code: StockContextErrorCode,
    tool_name: str,
    provided_stock_code: str | None,
) -> None:
    events = getattr(context, "stock_context_events", None)
    if isinstance(events, list):
        events.append(
            {
                "code": code,
                "tool_name": tool_name,
                "provided_stock_code": provided_stock_code,
                "selected_stock_code": getattr(context, "stock_code", None),
            }
        )


def _code_from_source_key(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    for pattern in (
        re.compile(r"^(\d{6})/"),
        re.compile(r"^price:(\d{6}):"),
    ):
        match = pattern.match(value)
        if match:
            return match.group(1)
    return None


def validate_input_source_stock_context(
    *,
    selected_stock_code: str | None,
    event_context: list[Any] | None,
    source_id: str | None,
) -> StockExecutionViolation | None:
    """Reject a stale UI event/source context before it reaches the Agent."""

    if not selected_stock_code:
        return None
    observed = {
        code
        for item in event_context or []
        if (
            code := (
                item.get("stock_code")
                if isinstance(item, dict)
                else getattr(item, "stock_code", None)
            )
        )
    }
    source_code = _code_from_source_key(source_id)
    if source_code:
        observed.add(source_code)
    if any(code != selected_stock_code for code in observed):
        return StockExecutionViolation(
            error_code="STOCK_CONTEXT_MISMATCH",
            message="선택 종목과 현재 자료의 종목이 일치하지 않아 답변을 생성하지 않았습니다.",
            observed_codes=tuple(sorted(str(code) for code in observed)),
            failed_layer="input_source_context",
        )
    return None


def _payload_stock_codes(value: Any) -> set[str]:
    codes: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "stock_code" or key.endswith("_stock_code"):
                if isinstance(item, str) and item:
                    codes.add(item)
            if key in {"source_id", "source_key"}:
                parsed = _code_from_source_key(item)
                if parsed:
                    codes.add(parsed)
            codes.update(_payload_stock_codes(item))
    elif isinstance(value, list):
        for item in value:
            codes.update(_payload_stock_codes(item))
    return codes


def validate_execution_stock_context(
    *,
    selected_stock_code: str | None,
    runtime_stock_code: str | None,
    tool_calls: list[Any],
    tool_payloads: list[dict],
    runtime_events: list[dict] | None = None,
) -> StockExecutionViolation | None:
    if not selected_stock_code:
        return None

    if runtime_stock_code != selected_stock_code:
        observed = tuple(
            sorted({code for code in (runtime_stock_code, selected_stock_code) if code})
        )
        return StockExecutionViolation(
            error_code="STOCK_CONTEXT_MISMATCH",
            message="요청한 종목과 실행 문맥이 일치하지 않아 답변을 생성하지 않았습니다.",
            observed_codes=observed,
            failed_layer="agent_runtime_context",
        )

    if runtime_events:
        observed = {
            str(event.get("provided_stock_code"))
            for event in runtime_events
            if event.get("provided_stock_code")
        }
        return StockExecutionViolation(
            error_code="STOCK_CONTEXT_MISMATCH",
            message="요청한 종목과 Tool 호출 종목이 일치하지 않아 답변을 생성하지 않았습니다.",
            observed_codes=tuple(sorted(observed)),
            failed_layer="tool_input_guard",
        )

    for call in tool_calls:
        if getattr(call, "name", "") == "lookup_financial_term":
            continue
        tool_stock_code = getattr(call, "stock_code", None)
        # Some Tool schemas allow the runtime context to inject a missing stock
        # code.  The runtime guard validates that resolved value.  Only an
        # explicitly supplied, conflicting value is a trace violation here.
        if tool_stock_code is not None and tool_stock_code != selected_stock_code:
            observed = tuple(
                sorted(
                    {
                        code
                        for code in (selected_stock_code, tool_stock_code)
                        if isinstance(code, str) and code
                    }
                )
            )
            return StockExecutionViolation(
                error_code="STOCK_CONTEXT_MISMATCH",
                message="요청한 종목과 Tool 호출 종목이 일치하지 않아 답변을 생성하지 않았습니다.",
                observed_codes=observed,
                failed_layer="tool_call_trace",
            )

    payload_codes = set()
    for payload in tool_payloads:
        payload_codes.update(_payload_stock_codes(payload))
    if any(code != selected_stock_code for code in payload_codes):
        return StockExecutionViolation(
            error_code="STOCK_CONTEXT_MISMATCH",
            message="요청한 종목과 조회 결과의 종목이 일치하지 않아 답변을 생성하지 않았습니다.",
            observed_codes=tuple(sorted(payload_codes)),
            failed_layer="tool_source_validation",
        )
    return None
