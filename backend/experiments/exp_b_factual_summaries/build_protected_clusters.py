"""보호(실험 A: 시장 뉴스 브리지 차단) 켠 최종 클러스터 결과 생성.

prompt.md 8·10절:
 - 실제 서비스 코드(pipeline.cluster_all)를 그대로 사용해 보호 ON 으로 클러스터링.
 - Solar 요약은 만들지 않는다.
 - 기존 artifacts/ 를 덮어쓰지 않고 overmerge_fix/ 아래 새 경로에만 쓴다.
 - 새 버전명(CFG.CLUSTERING_VERSION_PROTECTED) 사용.

패키지 상대 import(pipeline: from . import config) 때문에 반드시 모듈로 실행한다:
  python -m experiments.exp_b_factual_summaries.build_protected_clusters --device mps
(백엔드 루트 backend/ 에서. 또는 아래 __main__ 의 경로 보정으로 파일 직접 실행도 지원)
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config as CFG
from . import market_rules as MR
from . import pipeline as P

BASE = Path(__file__).resolve().parent
OUT = BASE / "overmerge_fix"
DEFAULT_ENV = BASE.parent.parent / ".env"
CACHE_DIR = OUT / "emb_cache"


def _write_clustered(rows, assign, kinds, path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for i, r in enumerate(rows):
            a = assign[i]
            f.write(
                json.dumps(
                    {
                        "article_id": r["article_id"],
                        "stock_code": r["stock_code"],
                        "url": r["canonical_url"],
                        "publisher": r["press"],
                        "title": r["title"],
                        "description": r["description"],
                        "published_at": r["published_at"],
                        "cluster_id": a["cluster_id"],
                        "assigned_similarity": a["assigned_similarity"],
                        "is_new_cluster": a["is_new"],
                        "article_kind": kinds[i],  # company | market | info
                        "embedding_model": CFG.EMBEDDING_MODEL,
                        "embedding_revision": CFG.EMBEDDING_REVISION,
                        "preprocessing_version": CFG.PREPROCESS_VERSION,
                        "clustering_version": CFG.CLUSTERING_VERSION_PROTECTED,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def _write_sources(rows, vecs, clusters, path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for cid, c in sorted(clusters.items()):
            members = c["member_idxs"]
            rep = P.pick_representative(rows, vecs, c)
            pubs = sorted({rows[i]["press"] for i in members if rows[i]["press"]})
            times = sorted(rows[i]["published_at"] for i in members)
            f.write(
                json.dumps(
                    {
                        "cluster_id": cid,
                        "stock_code": c["stock_code"],
                        "kind": c.get("kind", "company"),
                        "size": len(members),
                        "article_ids": [rows[i]["article_id"] for i in members],
                        "publishers": pubs,
                        "n_publishers": len(pubs),
                        "urls": [rows[i]["canonical_url"] for i in members],
                        "representative_article_id": rows[rep]["article_id"],
                        "representative_title": rows[rep]["title"],
                        "active_from": times[0],
                        "active_to": times[-1],
                        "clustering_version": CFG.CLUSTERING_VERSION_PROTECTED,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def main(device: str, env_path: Path) -> None:
    OUT.mkdir(exist_ok=True)
    env = P._load_env(env_path)
    print("[1] DB 로드…")
    rows = P.load_relevant_articles(env, CFG.STOCKS)
    print(f"    기사={len(rows)}")
    print("[2] 임베딩(캐시 재사용)…")
    vecs = P.embed_articles(rows, device, CACHE_DIR)
    print(f"    shape={vecs.shape}")

    kinds = [MR.classify_kind(r.get("title", ""), r.get("description", "")) for r in rows]
    from collections import Counter

    print(f"    kind 분포={dict(Counter(kinds))}")

    print("[3] 클러스터링(보호 ON: market+info 브리지 차단)…")
    assign, clusters = P.cluster_all(
        rows, vecs, block_market_bridge=True, market_day_boundary=True, separate_info=True
    )
    print(f"    클러스터={len(clusters)}")

    cpath = OUT / "clustered_articles_protected.jsonl"
    spath = OUT / "cluster_sources_protected.jsonl"
    _write_clustered(rows, assign, kinds, cpath)
    _write_sources(rows, vecs, clusters, spath)
    print(f"[4] 산출: {cpath.name}, {spath.name}")


if __name__ == "__main__":
    import argparse
    import sys

    # 파일 직접 실행 지원(상대 import 를 위해 부모를 sys.path 에 넣고 패키지로 재실행하지 않음)
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="mps")
    ap.add_argument("--env", default=str(DEFAULT_ENV))
    args = ap.parse_args()
    if __package__ in (None, ""):
        print(
            "이 스크립트는 패키지 상대 import 를 쓰므로 모듈로 실행하세요:\n"
            "  cd backend && python -m experiments.exp_b_factual_summaries."
            "build_protected_clusters --device mps",
            file=sys.stderr,
        )
        sys.exit(2)
    main(args.device, Path(args.env))
