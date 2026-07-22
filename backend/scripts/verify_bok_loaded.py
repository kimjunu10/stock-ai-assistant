"""적재된 rag_terms(한국은행 789) 검증 + 무작위 50개 원문 대조 (Phase 4).

DB 에 저장된 값과 PDF 원문을 대조하고, 검색 6종을 검증한다. DB 쓰기 없음(읽기만).
결과: docs/rag/phase_4/bok_load_verification.md
"""

from __future__ import annotations

import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz  # noqa: E402

from app.db.client import get_supabase_client  # noqa: E402
from app.services.facts import FactsService  # noqa: E402
from app.services.rag_qa_facts import _term_candidates  # noqa: E402

PDF = Path(__file__).resolve().parents[1] / "docs" / "rag" / "2026_경제금융용어 800선.pdf"
OUT = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_4" / "bok_load_verification.md"


def _norm(s: str) -> str:
    return re.sub(r"\s", "", s or "")


def main() -> int:
    db = get_supabase_client()
    facts = FactsService(db)
    doc = fitz.open(str(PDF))

    rows = []
    off = 0
    while True:
        b = (
            db.table("rag_terms")
            .select(
                "term,english_name,official_definition,easy_definition,aliases,"
                "related_terms,source_name,source_page,pdf_page,content_hash"
            )
            .eq("source_name", "한국은행")
            .range(off, off + 999)
            .execute()
            .data
            or []
        )
        rows.extend(b)
        if len(b) < 1000:
            break
        off += 1000

    n = len(rows)
    # NULL 임베딩은 벡터 컬럼을 select 하면 타임아웃 → count 로 별도 확인.
    null_emb = (
        db.table("rag_terms")
        .select("id", count="exact")
        .eq("source_name", "한국은행")
        .is_("embedding", "null")
        .execute()
        .count
    )
    null_def = sum(1 for r in rows if not (r.get("official_definition") or "").strip())
    null_sp = sum(1 for r in rows if r.get("source_page") is None)
    null_easy = sum(1 for r in rows if r.get("easy_definition") is not None)  # NULL 이어야
    mix = sum(1 for r in rows if set(r.get("aliases") or []) & set(r.get("related_terms") or []))

    # 무작위 50개 원문 대조(정의 앞부분이 pdf_page 원문에 존재하는가)
    rng = random.Random(7)
    sample = rng.sample(rows, min(50, n))
    boundary_ok = 0
    page_ok = 0
    fail = []
    for r in sample:
        pg = r.get("pdf_page")
        txt = _norm(doc[pg - 1].get_text()) if pg and 1 <= pg <= doc.page_count else ""
        txt += _norm(doc[pg].get_text()) if pg and pg < doc.page_count else ""
        head = _norm(r["official_definition"][:20])[:12]
        if head and head in txt:
            boundary_ok += 1
        else:
            fail.append(r["term"])
        # source_page = pdf_page - 18 규칙 성립?
        if r.get("source_page") == (pg - 18 if pg else None):
            page_ok += 1

    # 검색 6종
    search_cases = [
        ("정확일치", "가산금리", "가산금리"),
        ("약어(alias)", "HDRI", "가계부실위험지수"),
        ("영문명", "Virtual Asset", "가상자산"),
        ("슬래시구성어", "간접금융", "간접금융/직접금융"),
        ("자연어질문", "로렌츠곡선이 뭐야?", "로렌츠곡선"),
        ("자연어질문2", "가산금리가 뭐야?", "가산금리"),
    ]
    search_results = []
    for kind, q, expect in search_cases:
        hit = facts.lookup_term(_term_candidates(q) if "?" in q else q)
        got = hit["term"] if hit else None
        search_results.append((kind, q, expect, got, got == expect))

    lines = ["# Phase 4 — 경제금융용어 800선 적재 검증\n"]
    lines.append(f"- 신규(한국은행) rag_terms: **{n}**")
    lines.append(f"- NULL 임베딩(신규): {null_emb}")
    lines.append(f"- official_definition 누락: {null_def}")
    lines.append(f"- source_page 누락: {null_sp}")
    lines.append(f"- easy_definition 비-NULL(0이어야): {null_easy}")
    lines.append(f"- aliases↔related 혼입: {mix}\n")
    lines.append("## 무작위 50개 원문 대조\n")
    lines.append(f"- 정의 시작 경계 일치: {boundary_ok}/{len(sample)}")
    lines.append(f"- source_page = pdf_page-18 성립: {page_ok}/{len(sample)}")
    if fail:
        lines.append(f"- 경계 실패: {fail[:20]}")
    lines.append("\n## 검색 6종 검증\n")
    for kind, q, expect, got, ok in search_results:
        lines.append(f"- [{kind}] {q!r} → {got!r} (기대 {expect!r}) {'✅' if ok else '❌'}")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"신규 {n} | NULL임베딩 {null_emb} | def누락 {null_def} | sp누락 {null_sp} | 혼입 {mix}")
    print(f"원문대조 경계 {boundary_ok}/{len(sample)}, page규칙 {page_ok}/{len(sample)}")
    for kind, q, expect, got, ok in search_results:
        print(f"  [{kind}] {got} {'OK' if ok else 'FAIL(기대 ' + expect + ')'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
