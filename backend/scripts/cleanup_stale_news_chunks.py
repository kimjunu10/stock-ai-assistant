"""비현행 뉴스 문서에 남은 활성 청크를 안전하게 비활성화한다.

배경
----
뉴스 색인은 같은 사건(news_clusters.id)을 다시 색인할 때 이전 rag_documents 를
is_current=false 로 내리고 새 문서를 만든다(app/repositories/rag.py). 그런데 내려간
문서의 rag_chunks 는 is_active=true 로 남아 있어, 사건 하나에 활성 청크가 여러 세대
쌓인다.

검색 자체는 rag_search_hybrid / rag_search_semantic 이 `c.is_active AND d.is_current`
를 모두 강제하므로 이 청크들이 결과로 나오지는 않는다(= 검색 결함이 아니다).
다만 색인 상태가 사실과 어긋나 있어 통계·디버깅·향후 쿼리에서 혼동을 준다.

무엇을 하는가
-------------
- 대상: source_type='news_event' AND rag_documents.is_current=false 인 문서의
  is_active=true 청크.
- 처리: is_active=false 로 내리기만 한다(soft). 삭제하지 않는다.
- 건드리지 않는 것: 뉴스 원본(news_articles)·사건(news_clusters)·현행 문서와 그 청크.
- idempotent: 이미 비활성인 청크는 대상에서 빠지므로 반복 실행해도 결과가 같다
  (두 번째 실행부터 변경 0건).

실행
----
    cd backend
    .venv/bin/python scripts/cleanup_stale_news_chunks.py            # dry-run(기본)
    .venv/bin/python scripts/cleanup_stale_news_chunks.py --apply    # 실제 반영
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.client import get_supabase_client  # noqa: E402

BATCH = 500
PAGE = 1000
UPDATE_BATCH = 50


def _all_doc_ids(client, *, is_current: bool) -> list[str]:
    """뉴스 문서 id 를 전부 가져온다.

    PostgREST 는 한 번에 최대 1000행만 주므로 페이지네이션이 없으면 통계가 조용히
    잘린다(정리 대상 누락 → idempotent 도 깨진다).
    """
    ids: list[str] = []
    start = 0
    while True:
        rows = (
            client.table("rag_documents")
            .select("id")
            .eq("source_type", "news_event")
            .eq("is_current", is_current)
            .range(start, start + PAGE - 1)
            .execute()
            .data
            or []
        )
        ids.extend(r["id"] for r in rows)
        if len(rows) < PAGE:
            return ids
        start += PAGE


def _count_active_chunks(client, doc_ids: list[str]) -> int:
    total = 0
    for i in range(0, len(doc_ids), BATCH):
        res = (
            client.table("rag_chunks")
            .select("id", count="exact")
            .in_("document_id", doc_ids[i : i + BATCH])
            .eq("is_active", True)
            .execute()
        )
        total += res.count or 0
    return total


def _stats(client) -> dict:
    """현재 색인 상태 통계(현행/비현행 × 활성 청크 수)."""
    stale_ids = _all_doc_ids(client, is_current=False)
    cur_ids = _all_doc_ids(client, is_current=True)
    return {
        "stale_documents": len(stale_ids),
        "stale_active_chunks": _count_active_chunks(client, stale_ids),
        "current_documents": len(cur_ids),
        "current_active_chunks": _count_active_chunks(client, cur_ids),
    }


def _deactivate(client, *, apply: bool) -> int:
    """비현행 문서의 활성 청크를 비활성화하고 처리 건수를 돌려준다."""
    stale_ids = _all_doc_ids(client, is_current=False)
    changed = 0
    for i in range(0, len(stale_ids), BATCH):
        doc_slice = stale_ids[i : i + BATCH]
        chunk_ids: list[str] = []
        start = 0
        while True:  # select 도 1000행 제한이 있어 페이지네이션이 필요하다.
            rows = (
                client.table("rag_chunks")
                .select("id")
                .in_("document_id", doc_slice)
                .eq("is_active", True)
                .range(start, start + PAGE - 1)
                .execute()
                .data
                or []
            )
            chunk_ids.extend(r["id"] for r in rows)
            if len(rows) < PAGE:
                break
            start += PAGE
        if not chunk_ids:
            continue
        changed += len(chunk_ids)
        if apply:
            # update 는 select 보다 무겁다. 배치가 크면 statement timeout 이 난다.
            for j in range(0, len(chunk_ids), UPDATE_BATCH):
                client.table("rag_chunks").update({"is_active": False}).in_(
                    "id", chunk_ids[j : j + UPDATE_BATCH]
                ).execute()
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="실제 반영(기본은 dry-run)")
    args = ap.parse_args()

    client = get_supabase_client()

    before = _stats(client)
    print("[before]", json.dumps(before, ensure_ascii=False))

    target = _deactivate(client, apply=args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] 비활성화 대상 청크: {target}건 (삭제 아님, is_active=false)")

    after = _stats(client) if args.apply else before
    if args.apply:
        print("[after] ", json.dumps(after, ensure_ascii=False))
        # 현행 활성 청크가 "줄었다"면 이 스크립트가 건드리면 안 될 것을 건드린 것이다.
        # 늘어난 경우는 실행 중 뉴스 색인 파이프라인이 새 청크를 넣은 것으로, 정상이다
        # (이 스크립트는 is_active=false 로 내리기만 하므로 증가시킬 수 없다).
        if after["current_active_chunks"] < before["current_active_chunks"]:
            print("경고: 현행 활성 청크가 줄었다. 확인이 필요하다.", file=sys.stderr)
            return 1
        if after["stale_active_chunks"] != 0:
            print(
                f"경고: 비현행 활성 청크가 {after['stale_active_chunks']}건 남았다.",
                file=sys.stderr,
            )

    report = {
        "ran_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "before": before,
        "after": after,
        "deactivated": target if args.apply else 0,
        "would_deactivate": target,
    }
    out = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_8" / "eval"
    out.mkdir(parents=True, exist_ok=True)
    (out / "news_index_cleanup.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
