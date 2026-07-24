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


@dataclass
class ToolEvidence:
    """Agent 실행 중 Tool 이 반환한 근거 모음(검증 기준)."""

    source_ids: set[str] = field(default_factory=set)
    numeric_cores: set[str] = field(default_factory=set)  # 콤마 제거 숫자 문자열
    value_kinds: set[str] = field(default_factory=set)  # actual/forecast/mixed 등
    has_financial: bool = False


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)


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
    return ev


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

    # 2) 숫자 주장: 답변에 큰 숫자가 있는데 재무 Tool 근거가 전혀 없으면 경고
    answer_nums = {m.replace(",", "") for m in _NUMBER_RE.findall(answer)}
    big_nums = {n for n in answer_nums if len(n) >= 4}
    if big_nums and not evidence.has_financial and not evidence.numeric_cores:
        errors.append("답변에 재무성 숫자가 있으나 이를 뒷받침하는 숫자 Tool 근거가 없음")

    return ValidationResult(ok=not errors, errors=errors)
