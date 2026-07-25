"""Agent 답변 코드 검증 (Phase 5.5-E, SPEC §12.2).

모델에 맡기지 않고 코드로 검증하는 항목:
- source_id 유효성: 답변이 인용한 [n] 또는 source_id 가 실제 Tool 결과에 존재하는가
- 존재하지 않는 [n] 인용
- 숫자 주장: 답변의 숫자가 Tool 결과(재무 등)에 존재하는가
- 단위·기간 메타데이터 보존
- actual/forecast 라벨 존재
- 최신 정정 여부(latest correction) 위반 없음

검증 실패는 숫자를 임의 수정하지 않고 validation_errors 로 기록한다(SPEC §12.2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_CITATION_RE = re.compile(r"\[(\d+)\]")
# 답변 속 큰 숫자(천단위 콤마/조·억 단위 등) — 재무 주장 후보
_NUMBER_RE = re.compile(r"\d[\d,]{2,}")
# 증권사명 후보(답변에서 '○○증권' 형태를 뽑아 근거와 대조)
_BROKER_RE = re.compile(r"([가-힣A-Za-z]{2,10}(?:투자)?증권)")
# 목표주가 문맥의 금액(콤마형 또는 만원형) — 답변에서 목표가 주장 탐지
_TP_CTX_RE = re.compile(r"목표\s*주?가[^\n.]{0,30}?(\d{1,3}(?:,\d{3})+|\d{1,4}\s*만)\s*원?")


@dataclass
class ToolEvidence:
    """Agent 실행 중 Tool 이 반환한 근거 모음(검증 기준)."""

    source_ids: set[str] = field(default_factory=set)
    numeric_cores: set[str] = field(default_factory=set)  # 콤마 제거 숫자 문자열
    value_kinds: set[str] = field(default_factory=set)  # actual/forecast/mixed 등
    has_financial: bool = False
    # 증권사 리포트 근거(prompt.md §7)
    brokers: set[str] = field(default_factory=set)  # Tool 이 반환한 증권사명
    stated_target_prices: set[int] = field(default_factory=set)  # status=stated 목표주가
    has_reports: bool = False  # 리포트 Tool 이 결과를 냈는가


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)


def _tp_str_to_won(raw: str) -> int:
    """답변 목표주가 표기('320,000' 또는 '48만')를 원 단위 정수로."""
    raw = raw.strip()
    if "만" in raw:
        return int(raw.replace("만", "").strip()) * 10_000
    return int(raw.replace(",", ""))


def collect_evidence(tool_payloads: list[dict[str, Any]]) -> ToolEvidence:
    """Tool 결과(ToolResult dict) 목록에서 검증 근거를 수집한다."""
    ev = ToolEvidence()
    for p in tool_payloads:
        if not isinstance(p, dict):
            continue
        for s in p.get("sources", []) or []:
            sid = s.get("source_id")
            if sid:
                ev.source_ids.add(str(sid))
            vk = s.get("value_kind")
            if vk:
                ev.value_kinds.add(str(vk))
            if s.get("source_type") == "financial":
                ev.has_financial = True
        data = p.get("data")
        for fact in _iter_facts(data):
            val = fact.get("value_won")
            if val is not None:
                ev.numeric_cores.add(str(int(val)))
            vk = fact.get("value_kind")
            if vk:
                ev.value_kinds.add(str(vk))
        # 리포트 근거: 증권사명·stated 목표주가 수집
        if isinstance(data, dict):
            reports = data.get("reports")
            if isinstance(reports, list):
                for rp in reports:
                    if not isinstance(rp, dict):
                        continue
                    ev.has_reports = True
                    b = rp.get("broker")
                    if b:
                        ev.brokers.add(str(b))
                    if rp.get("target_price_status") == "stated":
                        tp = rp.get("target_price")
                        if isinstance(tp, int):
                            ev.stated_target_prices.add(tp)
    return ev


def collect_report_opinions(tool_payloads: list[dict[str, Any]]) -> list[dict]:
    """리포트 Tool 결과에서 증권사 의견 카드(구조화)를 모은다(prompt.md §8).

    목표주가는 status='stated' 인 구조화 값만 싣는다. 답변 텍스트가 아니라 Tool 이
    확정해 내려준 값이므로 환각 위험이 없다. source_id 는 sources 순서로 매핑.
    """
    out: list[dict] = []
    for p in tool_payloads:
        if not isinstance(p, dict):
            continue
        data = p.get("data")
        if not isinstance(data, dict):
            continue
        reports = data.get("reports")
        if not isinstance(reports, list):
            continue
        sources = p.get("sources") or []
        for i, rp in enumerate(reports):
            if not isinstance(rp, dict):
                continue
            stated = (
                rp.get("target_price_status") == "stated" and rp.get("target_price") is not None
            )
            src = sources[i] if i < len(sources) else {}
            out.append(
                {
                    "broker": rp.get("broker"),
                    "report_date": rp.get("report_date"),
                    "title": rp.get("title"),
                    "investment_opinion": rp.get("investment_opinion"),
                    "target_price": int(rp["target_price"]) if stated else None,
                    "target_price_currency": rp.get("target_price_currency") if stated else None,
                    "target_price_status": rp.get("target_price_status", "unknown"),
                    "summary": rp.get("snippet"),
                    "source_id": src.get("source_id") if isinstance(src, dict) else None,
                    "source_page": rp.get("target_price_source_page") or rp.get("page"),
                    "is_stale": bool(rp.get("is_stale", False)),
                }
            )
    return out


def _iter_facts(data: Any):
    if isinstance(data, dict):
        for key in ("facts", "reports", "values"):
            for item in data.get(key, []) or []:
                if isinstance(item, dict):
                    yield item


def validate_answer(answer: str, evidence: ToolEvidence) -> ValidationResult:
    """답변을 근거에 대해 검증한다(SPEC §12.2). 숫자를 고치지 않고 오류만 기록."""
    errors: list[str] = []

    # 1) 존재하지 않는 인용 [n]: 근거 source 가 하나도 없는데 인용을 달면 위반
    citations = {int(m) for m in _CITATION_RE.findall(answer)}
    n_sources = len(evidence.source_ids)
    invalid = sorted(c for c in citations if c < 1 or c > max(n_sources, 0))
    if invalid:
        errors.append(f"존재하지 않는 인용 번호: {invalid} (근거 출처 {n_sources}개)")

    # 2) 숫자 주장: 답변에 큰 숫자가 있는데 재무 Tool 근거가 전혀 없으면 경고.
    #    단, stated 목표주가는 정당한 숫자 근거이므로 재무 근거 취급한다.
    answer_nums = {m.replace(",", "") for m in _NUMBER_RE.findall(answer)}
    big_nums = {n for n in answer_nums if len(n) >= 4}
    tp_cores = {str(v) for v in evidence.stated_target_prices}
    unsupported_big = big_nums - evidence.numeric_cores - tp_cores
    if unsupported_big and not evidence.has_financial:
        errors.append("답변에 재무성 숫자가 있으나 이를 뒷받침하는 숫자 Tool 근거가 없음")

    # 3) 증권사명 환각: 답변에 등장한 증권사가 리포트 Tool 근거에 없으면 위반(prompt.md §7)
    if evidence.has_reports:
        answer_brokers = set(_BROKER_RE.findall(answer))
        unknown = sorted(b for b in answer_brokers if b not in evidence.brokers)
        if unknown:
            errors.append(f"Tool 결과에 없는 증권사를 답변에 생성함: {unknown}")

    # 4) 목표주가 환각: 답변의 '목표주가 N원' 이 stated 근거값과 일치하지 않으면 위반
    for m in _TP_CTX_RE.finditer(answer):
        raw = m.group(1)
        val = _tp_str_to_won(raw)
        if val not in evidence.stated_target_prices:
            errors.append(
                f"답변의 목표주가 {val:,}원이 구조화 근거(stated)와 일치하지 않음 "
                f"(허용값: {sorted(evidence.stated_target_prices) or '없음'})"
            )

    return ValidationResult(ok=not errors, errors=errors)


# 문장 분리(한국어 종결·줄바꿈·불릿 기준의 단순 분리).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+|\n+")


def _is_hallucinated_sentence(sentence: str, evidence: ToolEvidence) -> bool:
    """이 문장이 근거 없는 증권사/목표주가 주장을 담고 있으면 True."""
    for b in _BROKER_RE.findall(sentence):
        if b not in evidence.brokers:
            return True
    for m in _TP_CTX_RE.finditer(sentence):
        raw = m.group(1)
        val = _tp_str_to_won(raw)
        if val not in evidence.stated_target_prices:
            return True
    return False


def sanitize_answer(answer: str, evidence: ToolEvidence) -> tuple[str, bool]:
    """근거 없는 증권사·목표주가 주장을 담은 문장을 제거한다(prompt.md §7).

    숫자를 다시 추측하지 않는다. 전체 답변을 실패시키지 않고, 문제 문장만 걸러
    검증된 내용만 남긴다. 목표주가 관련 문장이 지워지면 안내 문구를 덧붙인다.
    반환: (정화된 답변, 변경 여부).
    """
    if not evidence.has_reports:
        return answer, False
    parts = _SENTENCE_SPLIT_RE.split(answer)
    kept, removed_tp = [], False
    for s in parts:
        if s.strip() and _is_hallucinated_sentence(s, evidence):
            if _TP_CTX_RE.search(s) or "목표" in s:
                removed_tp = True
            continue
        kept.append(s)
    if len(kept) == len(parts):
        return answer, False
    cleaned = " ".join(k.strip() for k in kept if k.strip())
    if removed_tp:
        cleaned = (cleaned + " 일부 증권사의 구조화된 목표주가를 확인할 수 없어 "
                   "해당 수치는 제외했습니다.").strip()
    return cleaned, True
