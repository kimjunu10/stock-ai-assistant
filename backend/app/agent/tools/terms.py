"""lookup_financial_term Tool (Phase 5.5-B, SPEC §7.2).

금융용어를 rag_terms 에서 조회한다(정확일치 → 별칭 → trigram). FactsService.lookup_term 재사용.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.agent.tools.common import (
    SourceRef,
    ToolResult,
    clamp_text,
    error,
    no_data,
    ok,
    sanitize_exception,
)
from app.services.facts import FactsService


class FinancialTermInput(BaseModel):
    term: str


def run_lookup_financial_term(facts: FactsService, inp: FinancialTermInput) -> ToolResult:
    try:
        row = facts.lookup_term(inp.term)
    except Exception as e:  # noqa: BLE001
        return error(sanitize_exception(e))
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
        locator={"source_title": row.get("source_title"), "source_page": row.get("source_page")},
    )
    return ok(data, sources=[src])
