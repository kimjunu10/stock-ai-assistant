"""동일사건 클러스터링 블라인드 평가용 표본 추출 (읽기 전용, 클러스터 중심).

DB는 SELECT만 한다(수정/삭제 없음). psql로 클러스터/기사를 조회한 뒤,
고정 seed로 대형·중형·소형 시스템 클러스터를 층화 선택하고, 미병합 확인을
위해 인접(같은 종목·±72h·임베딩 유사도 상위) 클러스터를 함께 담아 3개
산출물을 만든다.

  - clustering_eval_blind.csv       : 사람이 볼 블라인드 표본(정답 정보 없음)
  - clustering_eval_answer_key.csv  : 시스템 정답(cluster_id 등)
  - clustering_eval_manifest.md     : 추출 기준/통계 기록

평가 단위는 (article_id, stock_code) pair다. 72시간은 전체 기사를 긁는
범위가 아니라 인접 클러스터 탐색의 시간 범위로만 쓴다. 선택된 클러스터
내부 기사는 자르지 않고 전부 포함한다.

사용:
    python -m scripts.build_clustering_eval_sample
    python -m scripts.build_clustering_eval_sample --seed 42 --outdir docs/eval
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import subprocess
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from app.core.config import settings

NEIGHBOR_HOURS = 72  # 인접 클러스터 탐색 시간 범위(발행 시각 전후)
NEIGHBORS_PER_SEED = 2  # 시드 클러스터당 최대 인접 클러스터 수
NEIGHBOR_MIN_SIM = 0.5  # 인접으로 볼 최소 코사인 유사도
NEIGHBOR_MAX_ARTICLES = 15  # 인접 클러스터도 통째 포함하므로, 예산 잠식을 막기 위한 크기 상한
LARGE_MIN = 8  # 대형 클러스터 기준 (article_count)
LARGE_SEED_MAX = 15  # large seed로 뽑을 상한(더 크면 통째 포함 시 pair 예산을 초과)
MID_MIN = 4  # 중형 클러스터 기준 (4~7)
TARGET_MIN, TARGET_MAX = 180, 220
TARGET_SEEDS = {"large": 5, "mid": 10, "small": 10}  # 버킷별 시드 클러스터 목표 수
BODY_EXCERPT_CHARS = 400

# company + relevant + 배정 성공인 pair가 실제로 속한 클러스터만 후보로 본다.
# assignment_status(assigned_new/assigned_existing)와 배정 시각을 pair 단위로 함께 가져온다.
PAIRS_SQL = """
select
    a.article_id,
    a.stock_code,
    a.cluster_id,
    a.status              as assignment_status,
    a.assigned_at,
    st.name               as stock_name,
    ar.published_at,
    ar.title,
    ar.description,
    ar.body,
    ar.press,
    coalesce(ar.final_url, ar.original_url, ar.canonical_url) as article_url
from public.news_cluster_assignments a
join public.article_stocks s
    on s.article_id = a.article_id and s.stock_code = a.stock_code
join public.articles ar on ar.id = a.article_id
join public.stocks   st on st.code = a.stock_code
where a.kind = 'company'
  and a.status in ('assigned_new', 'assigned_existing')
  and a.cluster_id is not null
  and s.relevance = 'relevant'
;
"""

# 클러스터 메타(모든 company 클러스터). 인접 판정용 centroid/시간창 포함.
CLUSTERS_SQL = """
select
    c.id,
    c.stock_code,
    c.article_count,
    c.representative_article_id,
    c.summary_title,
    c.first_published_at,
    c.last_active_at,
    c.centroid
from public.news_clusters c
where c.kind = 'company'
;
"""


def psql_json(sql: str) -> list[dict]:
    """psql로 SELECT 결과를 JSON으로 읽는다(읽기 전용). 접속정보는 인자로만 전달."""
    wrapped = f"select coalesce(json_agg(t), '[]') from ({sql.rstrip().rstrip(';')}) t;"
    proc = subprocess.run(
        ["psql", settings.database_url, "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", wrapped],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"psql 실패: {proc.stderr.strip()}")
    return json.loads(proc.stdout.strip() or "[]")


def parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def bucket_of(size: int) -> str:
    if size >= LARGE_MIN:
        return "large"
    if size >= MID_MIN:
        return "mid"
    return "small"


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def pick_seed_clusters(clusters: dict[int, dict], eligible_ids: set[int],
                       rng: random.Random) -> list[int]:
    """버킷별로 시드 클러스터를 층화 선택. 최근/기존 배정 사례가 섞이도록,
    또 종목이 몰리지 않도록 종목·최신성 균형을 고려해 고른다."""
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for cid in eligible_ids:
        c = clusters[cid]
        by_bucket[bucket_of(c["article_count"])].append(c)

    latest = max(parse_ts(c["last_active_at"]) for c in clusters.values())
    recent_cut = latest - timedelta(days=7)

    chosen: list[int] = []
    for bucket, want in TARGET_SEEDS.items():
        pool = list(by_bucket.get(bucket, []))
        rng.shuffle(pool)
        # large는 통째 포함해도 pair 예산(≈200)을 지키도록 크기 상한(LARGE_SEED_MAX) 이하만
        # seed 후보로 두고, 그 안에서 셔플 순서로 뽑아 다양한 크기의 large가 섞이게 한다.
        if bucket == "large":
            pool = [c for c in pool if c["article_count"] <= LARGE_SEED_MAX]
        # 최근 클러스터와 기존 클러스터가 함께 들어가도록 최신/비최신을 번갈아 뽑는다.
        recent = [c for c in pool if parse_ts(c["last_active_at"]) >= recent_cut]
        older = [c for c in pool if parse_ts(c["last_active_at"]) < recent_cut]
        stock_counts: dict[str, int] = defaultdict(int)
        picked: list[int] = []
        toggle = 0
        while len(picked) < want and (recent or older):
            src = recent if (toggle % 2 == 0 and recent) or not older else older
            # 종목 편중 완화: 이 버킷에서 덜 뽑힌 종목 우선(large는 크기 우선이라 stable sort 유지).
            src.sort(key=lambda c: stock_counts[c["stock_code"]])
            c = src.pop(0)
            picked.append(c["id"])
            stock_counts[c["stock_code"]] += 1
            toggle += 1
        chosen.extend(picked)
    return chosen


def find_neighbors(seed: dict, clusters: dict[int, dict], centroids: dict[int, np.ndarray],
                   exclude: set[int]) -> list[tuple[int, float]]:
    """시드와 같은 stock_code이고 발행 시각 창이 ±72h 이내로 겹치며 centroid 유사도가
    높은 인접 클러스터를 최대 NEIGHBORS_PER_SEED개 반환한다(미병합 확인용)."""
    if seed["id"] not in centroids:
        return []
    s_vec = centroids[seed["id"]]
    s_start = parse_ts(seed["first_published_at"]) - timedelta(hours=NEIGHBOR_HOURS)
    s_end = parse_ts(seed["last_active_at"]) + timedelta(hours=NEIGHBOR_HOURS)
    cands: list[tuple[int, float]] = []
    for cid, c in clusters.items():
        if cid == seed["id"] or cid in exclude or cid not in centroids:
            continue
        if c["stock_code"] != seed["stock_code"]:
            continue
        if c["article_count"] > NEIGHBOR_MAX_ARTICLES:  # 거대 인접은 예산 잠식 방지 위해 제외
            continue
        c_start = parse_ts(c["first_published_at"])
        c_end = parse_ts(c["last_active_at"])
        if c_end < s_start or c_start > s_end:  # 시간창이 겹치지 않으면 제외
            continue
        sim = cosine(s_vec, centroids[cid])
        if sim >= NEIGHBOR_MIN_SIM:
            cands.append((cid, sim))
    cands.sort(key=lambda x: x[1], reverse=True)
    return cands[:NEIGHBORS_PER_SEED]


def excerpt(text: str | None) -> str:
    if not text:
        return ""
    t = " ".join(text.split())
    return t if len(t) <= BODY_EXCERPT_CHARS else t[:BODY_EXCERPT_CHARS].rstrip() + "…"


def main() -> None:
    ap = argparse.ArgumentParser(description="클러스터 중심 블라인드 평가 표본 추출 (읽기 전용)")
    ap.add_argument("--seed", type=int, default=20260721, help="고정 random seed (동일 표본 재현)")
    ap.add_argument("--outdir", default="docs", help="산출물 디렉토리 (기본 backend/docs)")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    extracted_at = datetime.now(UTC)

    pairs = psql_json(PAIRS_SQL)
    clusters_rows = psql_json(CLUSTERS_SQL)
    population = len(pairs)

    clusters = {c["id"]: c for c in clusters_rows}
    centroids = {
        c["id"]: np.asarray(c["centroid"], dtype=float)
        for c in clusters_rows
        if c.get("centroid")
    }

    # cluster_id -> 그 클러스터에 속한 (평가 대상) pair 목록.
    pairs_by_cluster: dict[int, list[dict]] = defaultdict(list)
    for p in pairs:
        pairs_by_cluster[p["cluster_id"]].append(p)
    # 실제로 평가 대상 pair를 가진 클러스터만 시드 후보로.
    eligible = {cid for cid, ps in pairs_by_cluster.items() if ps and cid in clusters}

    seed_ids = pick_seed_clusters(clusters, eligible, rng)

    # 시드 + 인접 클러스터를 모아 목표 pair 수(180~220)에 맞춘다.
    selected: dict[int, str] = {}  # cluster_id -> 'seed' | 'neighbor'

    def pairs_in(ids: set[int]) -> int:
        seen: set[tuple[int, str]] = set()
        for cid in ids:
            for p in pairs_by_cluster.get(cid, []):
                seen.add((p["article_id"], p["stock_code"]))
        return len(seen)

    # seed를 버킷 라운드로빈(large→mid→small 한 개씩 번갈아)으로 추가해 한 버킷이 pair 예산을
    # 독식하지 않게 한다. 개별 seed가 상한을 넘기면 그 seed만 건너뛰고(내부 기사는 자르지 않음)
    # 계속 진행해 large/mid/small이 모두 목표에 가깝게 섞이도록 한다.
    seeds_by_bucket: dict[str, list[int]] = {"large": [], "mid": [], "small": []}
    for sid in seed_ids:
        seeds_by_bucket[bucket_of(clusters[sid]["article_count"])].append(sid)

    def add_seed(sid: int) -> None:
        neigh = find_neighbors(clusters[sid], clusters, centroids, exclude=set(selected) | {sid})
        prospective = set(selected) | {sid} | {nid for nid, _ in neigh}
        if selected and pairs_in(prospective) > TARGET_MAX:
            return
        selected[sid] = "seed"
        for nid, _ in neigh:
            selected.setdefault(nid, "neighbor")

    order = ["large", "mid", "small"]
    idx = {b: 0 for b in order}
    remaining = True
    while remaining:
        remaining = False
        for b in order:
            if idx[b] < len(seeds_by_bucket[b]):
                add_seed(seeds_by_bucket[b][idx[b]])
                idx[b] += 1
                remaining = True

    # 확정 클러스터의 모든 pair 수집, 중복 pair 제거, 정렬(종목→시간→기사).
    sample_rows: list[dict] = []
    seen: set[tuple[int, str]] = set()
    cluster_order = sorted(
        selected, key=lambda cid: (clusters[cid]["stock_code"], parse_ts(clusters[cid]["first_published_at"]))
    )
    for cid in cluster_order:
        rows = sorted(
            pairs_by_cluster[cid], key=lambda p: (parse_ts(p["published_at"]), p["article_id"])
        )
        for p in rows:
            key = (p["article_id"], p["stock_code"])
            if key in seen:
                continue
            seen.add(key)
            sample_rows.append(p)
    for i, p in enumerate(sample_rows, start=1):
        p["sample_order"] = i

    # --- blind CSV (정답 정보 없음: system_cluster_id 제외) ---
    blind_path = outdir / "clustering_eval_blind.csv"
    with blind_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "sample_order", "article_id", "stock_code", "stock_name", "published_at",
            "title", "description", "body_excerpt", "press", "article_url", "gold_event_id",
        ])
        for p in sample_rows:
            w.writerow([
                p["sample_order"], p["article_id"], p["stock_code"], p["stock_name"],
                p["published_at"], p["title"], p.get("description") or "",
                excerpt(p.get("body")), p.get("press") or "", p.get("article_url") or "", "",
            ])

    # --- answer key CSV (시스템 정답: system_cluster_id 보존) ---
    key_path = outdir / "clustering_eval_answer_key.csv"
    with key_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "sample_order", "article_id", "stock_code", "system_cluster_id",
            "assignment_status", "cluster_article_count", "representative_article_id",
            "cluster_summary_title",
        ])
        for p in sample_rows:
            c = clusters[p["cluster_id"]]
            w.writerow([
                p["sample_order"], p["article_id"], p["stock_code"], p["cluster_id"],
                p["assignment_status"], c["article_count"],
                c["representative_article_id"], c.get("summary_title") or "",
            ])

    # --- manifest ---
    n = len(sample_rows)
    stocks = sorted({p["stock_code"] for p in sample_rows})
    stock_names = {p["stock_code"]: p["stock_name"] for p in sample_rows}
    seed_clusters = [cid for cid, role in selected.items() if role == "seed"]
    neighbor_clusters = [cid for cid, role in selected.items() if role == "neighbor"]
    seed_buckets = defaultdict(int)
    for cid in seed_clusters:
        seed_buckets[bucket_of(clusters[cid]["article_count"])] += 1
    pair_buckets = defaultdict(int)
    for p in sample_rows:
        pair_buckets[bucket_of(clusters[p["cluster_id"]]["article_count"])] += 1
    statuses = defaultdict(int)
    for p in sample_rows:
        statuses[p["assignment_status"]] += 1

    manifest = outdir / "clustering_eval_manifest.md"
    lines = [
        "# 동일사건 클러스터링 블라인드 평가 표본 매니페스트",
        "",
        f"- 평가 데이터 추출 시점(UTC): {extracted_at.isoformat()}",
        f"- random seed: {args.seed}",
        "",
        "## 표본 추출 기준",
        "- 대상: `kind='company'`, `article_stocks.relevance='relevant'`, 배정 성공"
        "(`status in ('assigned_new','assigned_existing')`, `cluster_id is not null`)한 pair.",
        "- 평가 단위: `(article_id, stock_code)` pair. 한 기사가 여러 종목에 연결되면 pair 각각 유지.",
        "- **클러스터 중심 추출**: 대형(article_count≥8)·중형(4~7)·소형(1~3) 시스템 클러스터를 "
        f"seed로 층화 선택(목표 large {TARGET_SEEDS['large']}·mid {TARGET_SEEDS['mid']}·small {TARGET_SEEDS['small']}). "
        "선택 클러스터 내부 기사는 자르지 않고 전부 포함.",
        f"- **미병합 확인용 인접 클러스터**: 각 seed와 같은 stock_code이고 발행 시각 창이 ±{NEIGHBOR_HOURS}시간 "
        f"이내로 겹치며 centroid 코사인 유사도 ≥{NEIGHBOR_MIN_SIM}인 클러스터 상위 {NEIGHBORS_PER_SEED}개까지 포함.",
        "- 72시간은 전체 기사를 긁는 범위가 아니라 인접 클러스터 탐색의 시간 범위로만 사용.",
        "- 최근 생성 클러스터와 기존 배정 사례가 함께 포함되도록 선택.",
        f"- 최소 5개 이상 종목 포함, 목표 pair 수 {TARGET_MIN}~{TARGET_MAX}, 동일 pair 중복 제거.",
        "",
        "## 통계",
        f"- 대상 전체 pair 수(모집단): {population}",
        f"- 추출 pair 수: {n}",
        f"- 포함된 종목 수: {len(stocks)} ({', '.join(f'{c}={stock_names[c]}' for c in stocks)})",
        f"- seed 클러스터 수: {len(seed_clusters)} "
        f"(large {seed_buckets['large']}, mid {seed_buckets['mid']}, small {seed_buckets['small']})",
        f"- 인접(neighbor) 클러스터 수: {len(neighbor_clusters)}",
        f"- 포함된 전체 클러스터 수: {len(selected)}",
        "- 배정 상태 분포: " + ", ".join(f"{k}={v}" for k, v in sorted(statuses.items())),
        "",
        "### pair의 클러스터 크기 분포 (속한 cluster_article_count 기준)",
        f"- 대형(≥8) 클러스터 pair: {pair_buckets['large']}",
        f"- 중형(4~7) 클러스터 pair: {pair_buckets['mid']}",
        f"- 소형(1~3) 클러스터 pair: {pair_buckets['small']}",
        "",
        "## 사용한 실제 테이블/컬럼",
        "- `public.news_cluster_assignments` (article_id, stock_code, cluster_id, kind, status, assigned_at)",
        "- `public.article_stocks` (article_id, stock_code, relevance)",
        "- `public.articles` (id, title, description, body, press, published_at, "
        "final_url/original_url/canonical_url)",
        "- `public.stocks` (code, name)",
        "- `public.news_clusters` (id, stock_code, kind, article_count, representative_article_id, "
        "summary_title, first_published_at, last_active_at, centroid)",
        "",
        "## 실행 방법",
        "```bash",
        "cd backend",
        f"python -m scripts.build_clustering_eval_sample --seed {args.seed}",
        "```",
        "DB는 SELECT만 수행하며(읽기 전용) 어떤 데이터도 수정하지 않는다.",
        "",
        "## 파일 병합",
        "`clustering_eval_blind.csv`(정답 정보 없음, system_cluster_id 제외)와 "
        "`clustering_eval_answer_key.csv`(system_cluster_id 보존)는 "
        "`(sample_order, article_id, stock_code)`로 정확히 join 가능.",
        "",
    ]
    manifest.write_text("\n".join(lines), encoding="utf-8")

    print(f"모집단 pair={population}, 추출 pair={n}, 클러스터={len(selected)}"
          f"(seed {len(seed_clusters)}/neighbor {len(neighbor_clusters)}), 종목={len(stocks)}")
    print(f"seed 버킷: large={seed_buckets['large']} mid={seed_buckets['mid']} small={seed_buckets['small']}")
    print(f"pair 버킷: large={pair_buckets['large']} mid={pair_buckets['mid']} small={pair_buckets['small']}")
    print(f"산출물: {blind_path}, {key_path}, {manifest}")


if __name__ == "__main__":
    main()
