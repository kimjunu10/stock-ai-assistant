"""lookup_financial_term Tool (Phase 5.5-B, SPEC §7.2).

금융용어를 rag_terms 에서 조회한다(정확일치 → 별칭 → trigram). FactsService.lookup_term 재사용.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from app.agent.tools.common import (
    SourceRef,
    ToolResult,
    clamp_text,
    error,
    log_tool_exception,
    no_data,
    ok,
    sanitize_exception,
)
from app.services.facts import FactsService


class FinancialTermInput(BaseModel):
    term: str


def _normalized_term(value: object) -> str:
    """표제어 비교용 정규화. 공백·가운뎃점·괄호 차이만 제거한다."""

    return re.sub(
        r"[^0-9a-z가-힣]",
        "",
        unicodedata.normalize("NFKC", str(value or "")).casefold(),
    )


@lru_cache(maxsize=1)
def _disclosure_glossary() -> dict[str, dict]:
    """공식 출처가 있는 공시 용어 데이터셋을 표제어·별칭으로 색인한다."""

    path = Path(__file__).resolve().parents[1] / "data" / "disclosure_terms.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    indexed: dict[str, dict] = {}
    for row in rows:
        for label in [row.get("term"), *(row.get("aliases") or [])]:
            key = _normalized_term(label)
            if key:
                indexed[key] = row
    return indexed


def _lookup_disclosure_term(term: str) -> dict | None:
    return _disclosure_glossary().get(_normalized_term(term))


def run_lookup_financial_term(facts: FactsService, inp: FinancialTermInput) -> ToolResult:
    try:
        row = facts.lookup_term(inp.term)
    except Exception as e:  # noqa: BLE001
        log_tool_exception(e, layer="FactsService.lookup_term")
        return error(sanitize_exception(e))
    # 한국은행 금융용어 DB와 공시 양식 용어는 출처가 다르다. DB에 없는 공시 표제어만
    # 금융감독원 공식 출처 기반의 별도 데이터 사전에서 조회한다.
    row = row or _lookup_disclosure_term(inp.term)
    if not row:
        return no_data(f"'{inp.term}' 용어를 찾지 못했습니다.")
    data = {
        "term": row.get("term"),
        "english_name": row.get("english_name"),
        "official_definition": clamp_text(row.get("official_definition")),
        "easy_definition": clamp_text(row.get("easy_definition")) or None,
    }
    src = SourceRef(
        source_id=f"term:{row.get('term')}",
        source_type="term",
        title=row.get("term"),
        publisher=row.get("source_name"),
        url=row.get("source_url"),
        locator={"source_title": row.get("source_title"), "source_page": row.get("source_page")},
    )
    return ok(data, sources=[src])
