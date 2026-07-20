"""over-merge 완화 실험 러너 — baseline / A / B / C 동일 데이터로 비교.

절차:
 1. DB 에서 relevant 기사 로드(exp_b/pipeline.load_relevant_articles 재사용)
 2. BGE-M3 임베딩 1회 생성 + 캐시(emb_cache/), 이후 4개 실험 모두 캐시 재사용
 3. baseline/A/B/C 클러스터링 → 동일 지표 계산
 4. 산출물:
      overmerge_experiment_comparison.csv  (4개 지표 표)
      overmerge_case_comparison.md         (검증 케이스가 어떻게 분리됐나)
      variant_labels.json                  (각 변형의 article_id -> cluster_id, 후속용)

큰 원문은 대화에 출력하지 않는다. 요약 수치와 대표 제목만 stdout.
Solar/Supabase/감성 미사용. threshold 0.74 고정.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent
EXP_B = BASE.parent
EXP_A = EXP_B.parent / "exp_a_clustering"
sys.path.insert(0, str(EXP_A))
sys.path.insert(0, str(EXP_B))
sys.path.insert(0, str(BASE))

import clustering_lib as C  # noqa: E402
import config as CFG  # noqa: E402
import market_rules as MR  # noqa: E402
from cluster_variants import VariantConfig, cluster_all_variant  # noqa: E402


# pipeline.py 는 패키지 상대 import(from . import config)라 스크립트에서 직접
# 못 불러온다. 동일 로직을 여기 재현한다(로더/임베딩만; 클러스터링은 variant 사용).
def _load_env(env_path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    with env_path.open(encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                env[k] = v.strip().strip('"').strip("'")
    return env


def load_relevant_articles(env: dict[str, str], stocks: list[str]) -> list[dict]:
    import psycopg2

    conn = psycopg2.connect(env["DATABASE_URL"])
    try:
        cur = conn.cursor()
        cur.execute(
            """
            select a.id, s.stock_code, a.title, a.description, a.body, a.press,
                   a.canonical_url, a.published_at
            from article_stocks s
            join articles a on a.id = s.article_id
            where s.relevance = 'relevant' and s.stock_code = any(%s)
              and a.published_at is not null
            order by s.stock_code, a.published_at
            """,
            (stocks,),
        )
        rows = []
        for aid, code, title, desc, body, press, url, pub in cur.fetchall():
            rows.append(
                {
                    "article_stock_id": f"{aid}:{code}",
                    "article_id": aid,
                    "stock_code": code,
                    "title": title or "",
                    "description": desc or "",
                    "body": body or "",
                    "press": press or "",
                    "canonical_url": url or "",
                    "published_at": pub.isoformat(),
                }
            )
        return rows
    finally:
        conn.close()


def embed_articles(rows: list[dict], device: str, cache_dir: Path) -> np.ndarray:
    prepared = [
        C.format_for_model(C.build_input_text(r, CFG.INPUT_TYPE), CFG.EMBEDDING_MODEL) for r in rows
    ]
    cache = C.EmbeddingCache(cache_dir=cache_dir)
    cache.load(CFG.EMBEDDING_MODEL)
    keys = [
        cache.key(CFG.EMBEDDING_MODEL, CFG.EMBEDDING_REVISION, CFG.INPUT_TYPE, C.text_sha256(t))
        for t in prepared
    ]
    missing = [i for i, k in enumerate(keys) if cache.get(k) is None]
    if missing:
        vecs_new, _meta = C.embed_sentence_transformer(
            [prepared[i] for i in missing],
            CFG.EMBEDDING_MODEL,
            CFG.EMBEDDING_REVISION,
            device,
        )
        for j, i in enumerate(missing):
            cache.put(keys[i], vecs_new[j])
        cache.save(CFG.EMBEDDING_MODEL)
    mat = np.vstack([cache.get(k) for k in keys]).astype(np.float32)
    return C.l2_normalize(mat)


CACHE_DIR = BASE / "emb_cache"

# 검증 케이스는 (라벨, 종목, 대표제목조각) 로 정의하고, 이번 실행의 baseline
# 클러스터 안에서 제목으로 다시 찾는다. cluster_id 는 실행마다 바뀌므로 저장된 ID를
# 신뢰하지 않는다. 조각은 OVER_MERGE_ANALYSIS.md 기록 제목에서 안정적인 부분.
CASE_NEEDLES = {
    "overmerge": [
        ("om_600", "034020", "8300선 하락 마감"),
        ("om_997", "005380", "6% 급락"),
        ("om_371", "000660", "패닉"),
        ("om_26", "005930", "동반 급락"),
        ("om_364", "000660", "뉴욕증시 브리핑"),
    ],
    "normal": [
        ("nm_992", "005380", "부분 파업"),
        ("nm_881", "042660", "신안우이 해상풍력"),
        ("nm_1008", "005380", "보스턴다이내믹스"),
        ("nm_663", "034020", "발전기 모니터링"),
    ],
}


def _metrics(assign: dict, clusters: dict, rows: list, is_market: list) -> dict:
    sizes = {cid: len(c["member_idxs"]) for cid, c in clusters.items()}
    n = len(clusters)
    singal = sum(1 for s in sizes.values() if s == 1)
    ge50 = sum(1 for s in sizes.values() if s >= 50)
    return {
        "n_clusters": n,
        "singleton_ratio": round(singal / n, 4) if n else 0,
        "max_cluster_size": max(sizes.values()) if sizes else 0,
        "clusters_ge_50": ge50,
    }


def _cluster_titles(clusters: dict, cid: int, rows: list, limit: int = 3) -> list[str]:
    c = clusters.get(cid)
    if not c:
        return []
    ms = sorted(c["member_idxs"], key=lambda i: rows[i]["published_at"])
    return [rows[i]["title"] for i in ms[:limit]]


def _map_article_to_cluster(assign: dict, rows: list) -> dict[str, int]:
    return {rows[i]["article_stock_id"]: a["cluster_id"] for i, a in assign.items()}


def main() -> None:
    env_path = EXP_B.parent.parent / ".env"
    env = _load_env(env_path)
    device = sys.argv[1] if len(sys.argv) > 1 else "mps"

    print("[1] DB 로드…")
    rows = load_relevant_articles(env, CFG.STOCKS)
    print(f"    기사(종목링크)={len(rows)}")

    print("[2] 임베딩(캐시 재사용)…")
    t0 = time.time()
    vecs = embed_articles(rows, device, CACHE_DIR)
    print(f"    임베딩 shape={vecs.shape} ({time.time() - t0:.1f}s)")

    is_market = [MR.is_market_wide(r.get("title", ""), r.get("description", "")) for r in rows]
    print(f"    시황 기사={sum(is_market)} ({sum(is_market) / len(rows):.3f})")

    variants = {
        "baseline": VariantConfig(),
        "A_market_bridge": VariantConfig(block_market_bridge=True),
        "B_drift_guard": VariantConfig(drift_guard=True),
        "C_combined": VariantConfig(block_market_bridge=True, drift_guard=True),
    }

    results = {}
    art_to_cid = {}
    for name, cfg in variants.items():
        t0 = time.time()
        assign, clusters = cluster_all_variant(rows, vecs, CFG.STOCKS, cfg)
        dt = time.time() - t0
        m = _metrics(assign, clusters, rows, is_market)
        m["seconds"] = round(dt, 2)
        results[name] = {"metrics": m, "assign": assign, "clusters": clusters}
        art_to_cid[name] = _map_article_to_cluster(assign, rows)
        print(f"[3] {name}: {m}")

    # ---- 비교 CSV ----
    cols = ["n_clusters", "singleton_ratio", "max_cluster_size", "clusters_ge_50", "seconds"]
    with (BASE / "overmerge_experiment_comparison.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        w = csv.writer(f)
        w.writerow(["variant", *cols])
        for name in variants:
            m = results[name]["metrics"]
            w.writerow([name, *[m[c] for c in cols]])

    # ---- 케이스 분리 분석 ----
    # 이번 실행의 baseline 클러스터 안에서 대표 제목(needle)으로 케이스를 다시 찾는다.
    # (저장된 cluster_id 는 실행마다 달라 신뢰할 수 없음.)
    base_clusters = results["baseline"]["clusters"]

    def find_case_cid(stock: str, needle: str) -> int | None:
        """baseline 클러스터 중 (해당 종목 & 제목에 needle 포함) 멤버가
        가장 많은 클러스터의 cid. 그 클러스터가 그 사건의 대표."""
        hit: dict[int, int] = defaultdict(int)
        for cid, c in base_clusters.items():
            if c["stock_code"] != stock:
                continue
            for i in c["member_idxs"]:
                if needle in rows[i].get("title", ""):
                    hit[cid] += 1
        if not hit:
            return None
        return max(hit, key=lambda c: hit[c])

    # baseline cid -> [article_stock_id]
    base_members: dict[int, list[str]] = defaultdict(list)
    for i, a in results["baseline"]["assign"].items():
        base_members[a["cluster_id"]].append(rows[i]["article_stock_id"])

    def split_report(base_cid: int, name: str) -> dict:
        members = base_members.get(base_cid, [])
        if not members:
            return {"found": False}
        vmap = art_to_cid[name]
        buckets: dict[int, int] = defaultdict(int)
        for asid in members:
            if asid in vmap:
                buckets[vmap[asid]] += 1
        if not buckets:
            return {"found": False}
        largest = max(buckets.values())
        return {
            "found": True,
            "orig_size": len(members),
            "n_pieces": len(buckets),
            "largest_piece": largest,
            "largest_ratio": round(largest / len(members), 3),
        }

    lines = ["# over-merge 케이스 분리 비교\n"]
    lines.append(
        "각 baseline 검증 클러스터가 A/B/C 에서 몇 조각으로 나뉘고, 가장 큰 조각이 "
        "원래 기사 대비 몇 %를 유지하는지. (이번 실행 baseline 에서 제목으로 재식별)\n"
    )
    case_resolved: dict[str, dict] = {}

    def section(title: str, cases: list) -> None:
        lines.append(f"\n## {title}\n")
        for label, stock, needle in cases:
            base_cid = find_case_cid(stock, needle)
            if base_cid is None:
                lines.append(f"\n### {label}: 매칭 실패 (needle='{needle}')\n")
                continue
            size = len(base_members.get(base_cid, []))
            reps = _cluster_titles(base_clusters, base_cid, rows, 1)
            rep = reps[0] if reps else "?"
            case_resolved[label] = {"cid": base_cid, "size": size, "rep": rep}
            lines.append(f"\n### {label} (baseline cid={base_cid}, {size}건)")
            lines.append(f"- 대표(최이른 기사): {rep}")
            lines.append("")
            lines.append("| 변형 | 조각수 | 최대조각 | 최대조각비율 |")
            lines.append("|---|---:|---:|---:|")
            for name in variants:
                sr = split_report(base_cid, name)
                if sr["found"]:
                    lines.append(
                        f"| {name} | {sr['n_pieces']} | {sr['largest_piece']} | "
                        f"{sr['largest_ratio']} |"
                    )
            lines.append("")

    section("over-merge 의심 (조각으로 잘 나뉘어야 좋음)", CASE_NEEDLES["overmerge"])
    section("정상 대형 단일사건 (그대로 유지돼야 좋음)", CASE_NEEDLES["normal"])
    (BASE / "case_resolved.json").write_text(
        json.dumps(case_resolved, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (BASE / "overmerge_case_comparison.md").write_text("\n".join(lines), encoding="utf-8")

    # ---- article->cluster 매핑 저장 (후속 최종 결과 생성용) ----
    (BASE / "variant_labels.json").write_text(
        json.dumps(art_to_cid, ensure_ascii=False), encoding="utf-8"
    )

    print("\n=== 요약 ===")
    for name in variants:
        print(name, results[name]["metrics"])
    print(
        "\n산출: overmerge_experiment_comparison.csv, overmerge_case_comparison.md, variant_labels.json"
    )


if __name__ == "__main__":
    main()
