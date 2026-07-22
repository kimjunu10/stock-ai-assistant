"""경제금융용어 800선 canonical entry 789개를 rag_terms 에 적재 (Phase 4).

- search_text 를 passage 임베딩(solar-embedding-2-passage, 1024)해서 저장.
- content_hash 로 재실행 시 동일 항목 skip → 중복 임베딩·비용 0.
- 재시작 가능: 배치 단위로 진행, 이미 있는(동일 hash) 항목은 임베딩 없이 건너뜀.
- 기존 시드 6건(source_name IS NULL)은 term 충돌 시에도 덮어쓰지 않는다(skip).
- 특정 용어 하드코딩 없음.

실행:
  uv run --with pymupdf python scripts/load_bok_terms.py --dry-run   # 계획만
  uv run --with pymupdf python scripts/load_bok_terms.py --apply     # 실제 적재
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.db.client import get_supabase_client  # noqa: E402
from app.ml.embeddings import UpstageEmbedder  # noqa: E402
from scripts.parse_bok_terms import parse_terms  # noqa: E402

BATCH = 100  # Upstage 임베딩 배치 상한


def _content_hash(t) -> str:
    """항목 내용 해시(재실행 skip 기준). 임베딩 입력과 핵심 필드로 구성."""
    payload = "".join(
        [
            t.term,
            t.english_name or "",
            "|".join(t.aliases),
            "|".join(t.related_terms),
            t.official_definition,
            t.search_text,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    settings.validate_news_collection()  # UPSTAGE/SUPABASE 키 확인
    db = get_supabase_client()
    embedder = UpstageEmbedder(settings)

    terms, _toc = parse_terms()

    # 기존 rag_terms 상태
    existing = db.table("rag_terms").select("term,content_hash,source_name").execute().data or []
    seed_terms = {e["term"] for e in existing if not e.get("source_name")}
    hash_by_term = {e["term"]: e.get("content_hash") for e in existing}

    # 적재 대상 준비
    to_upsert = []  # 신규/변경 → 임베딩 필요
    skipped_seed = []  # 기존 시드와 term 충돌 → 보존(skip)
    skipped_same = []  # 동일 content_hash → skip(재임베딩 없음)
    for t in terms:
        if t.term in seed_terms:
            skipped_seed.append(t.term)
            continue
        ch = _content_hash(t)
        if hash_by_term.get(t.term) == ch:
            skipped_same.append(t.term)
            continue
        to_upsert.append((t, ch))

    print(
        f"파싱 {len(terms)} / 기존 {len(existing)}(시드 {len(seed_terms)}) | "
        f"적재대상 {len(to_upsert)} / 시드skip {len(skipped_seed)} / 동일skip {len(skipped_same)}"
    )
    if args.dry_run:
        est_tokens = int(sum(len(t.search_text) for t, _ in to_upsert) / 2.5)
        print(f"[dry-run] 임베딩 예상 토큰 ~{est_tokens:,}, 비용 ~${est_tokens/1_000_000*0.10:.4f}")
        return 0

    t0 = time.perf_counter()
    embedded = 0
    inserted = 0
    failures = []
    for start in range(0, len(to_upsert), BATCH):
        chunk = to_upsert[start : start + BATCH]
        texts = [t.search_text for t, _ in chunk]
        try:
            vectors = embedder.embed_passages(texts)
            embedded += len(vectors)
        except Exception as exc:  # noqa: BLE001 - 배치 실패 격리, 재시작 가능
            failures.append({"batch_start": start, "error": str(exc)[:200]})
            print(f"  배치 {start} 임베딩 실패: {str(exc)[:120]}")
            continue

        rows = []
        for (t, ch), vec in zip(chunk, vectors, strict=True):
            rows.append(
                {
                    "term": t.term,
                    "english_name": t.english_name,
                    "official_definition": t.official_definition,
                    "easy_definition": None,
                    "aliases": t.aliases,
                    "related_terms": t.related_terms,
                    "source_name": t.source_name,
                    "source_title": t.source_title,
                    "source_edition": t.source_edition,
                    "source_page": t.source_page,
                    "pdf_page": t.pdf_page,
                    "search_text": t.search_text,
                    "content_hash": ch,
                    "embedding": vec,
                    "is_active": True,
                }
            )
        try:
            db.table("rag_terms").upsert(rows, on_conflict="term").execute()
            inserted += len(rows)
        except Exception as exc:  # noqa: BLE001
            failures.append({"batch_start": start, "error": f"upsert: {str(exc)[:200]}"})
            print(f"  배치 {start} upsert 실패: {str(exc)[:120]}")
        print(f"  [{start + len(chunk)}/{len(to_upsert)}] embedded={embedded} inserted={inserted}")

    elapsed = round(time.perf_counter() - t0, 1)
    est_tokens = int(sum(len(t.search_text) for t, _ in to_upsert) / 2.5)
    print(
        f"완료: inserted={inserted} embedded={embedded} failures={len(failures)} "
        f"elapsed={elapsed}s 임베딩토큰~{est_tokens:,} 비용~${est_tokens/1_000_000*0.10:.4f}"
    )
    if failures:
        print(f"실패 배치: {failures}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
