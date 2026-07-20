"""EXP-5 [1~3] 클러스터링 파이프라인: 기사 로드 → BGE-M3 임베딩 → 종목별 시간순
online centroid 클러스터링.

운영 확정 설정(config.py)을 그대로 적용한다. 결과는 clustered_articles / cluster_sources
산출물의 입력이 되며, Supabase에는 아무것도 쓰지 않는다(오프라인 산출물 단계).

exp_a_clustering.clustering_lib 의 전처리·임베딩 함수를 재사용해 실험과 서비스가
동일한 임베딩 로직을 쓰도록 한다. online centroid 수식(온라인 평균 후 L2 normalize,
sliding 72h 활성창)도 clustering_lib 과 동일하되, 여기서는 배정 유사도·신규여부·
centroid·마지막 활성시각 같은 산출물용 메타데이터를 함께 기록한다.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent
EXP_A = BASE.parent / "exp_a_clustering"
sys.path.insert(0, str(EXP_A))
import clustering_lib as C  # noqa: E402

from . import config as CFG  # noqa: E402
from . import market_rules as MR  # noqa: E402


# --------------------------------------------------------------- 데이터 로드
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
    """article_stocks.relevance='relevant' 인 (기사, 종목) 연결을 로드.

    같은 기사가 여러 종목에 relevant면 종목별로 각각 하나의 행이 된다(클러스터링은
    종목 안에서만 수행하므로 이렇게 두는 것이 맞다). 반환 행 키:
    article_stock_id(=article_id:stock_code), article_id, stock_code, title,
    description, body, press, canonical_url, published_at.
    """

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


# --------------------------------------------------------------- 임베딩
def embed_articles(rows: list[dict], device: str, cache_dir: Path) -> np.ndarray:
    """title+description 을 BGE-M3 로 임베딩. exp_a 캐시 포맷 재사용."""

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
        vecs, _meta = C.embed_sentence_transformer(
            [prepared[i] for i in missing],
            CFG.EMBEDDING_MODEL,
            CFG.EMBEDDING_REVISION,
            device,
        )
        for j, i in enumerate(missing):
            cache.put(keys[i], vecs[j])
        cache.save(CFG.EMBEDDING_MODEL)
    mat = np.vstack([cache.get(k) for k in keys]).astype(np.float32)
    return C.l2_normalize(mat)


# --------------------------------------------------------------- 클러스터링
@dataclass
class _Cluster:
    local_id: int
    stock_code: str
    centroid: np.ndarray
    member_idx: list[int] = field(default_factory=list)
    first_h: float = 0.0
    last_h: float = 0.0
    kind: str = "company"  # 'company' | 'market' | 'info' (보호 기능 켰을 때만 의미)
    day: str = ""  # market/info 클러스터의 거래일(YYYY-MM-DD)


def cluster_stock(
    rows: list[dict],
    vecs: np.ndarray,
    idxs: list[int],
    stock_code: str,
    next_cluster_id: int,
    *,
    block_market_bridge: bool = False,
    market_day_boundary: bool = True,
    separate_info: bool = True,
    kinds: list[str] | None = None,
) -> tuple[dict[int, dict], dict[int, dict], int]:
    """한 종목 내 시간순 online centroid. SPEC Step 5 확정 로직과 동일.

    반환:
      assign: idx -> {cluster_id, assigned_similarity, is_new}
      next_cluster_id: 다음 종목에 이어 쓸 전역 cluster_id
      clusters: cluster_id -> {stock_code, member_idxs, centroid, first_h, last_h, kind}
    threshold/window 는 config 값. 활성창은 클러스터 '마지막 기사 시각' 기준(sliding).

    over-merge 보호(block_market_bridge=True):
      - 각 기사를 kinds[i]='market'(시황)|'info'(비사건형 투자정보)|'company'(기업 사건)로 판별.
      - kind 가 다른 클러스터에는 붙이지 않는다(시장·정보 뉴스가 종목 사건의 다리 역할 차단).
      - market/info 클러스터는 market_day_boundary=True 면 같은 거래일 안에서만 묶인다.
      - separate_info=False 면 info 를 company 로 되돌린다(시황만 분리).
    block_market_bridge=False 면 kind 는 항상 'company' 로 동작해 기존과 100% 동일하다.
    """

    thr = CFG.COSINE_THRESHOLD
    win = CFG.ACTIVE_WINDOW_HOURS
    order = sorted(idxs, key=lambda i: C.parse_hours(rows[i]["published_at"]))

    live: list[_Cluster] = []
    cid_counter = next_cluster_id
    assign: dict[int, dict] = {}
    for i in order:
        t = C.parse_hours(rows[i]["published_at"])
        v = vecs[i]
        kind_i = kinds[i] if (block_market_bridge and kinds) else "company"
        if kind_i == "info" and not separate_info:
            kind_i = "company"
        day_i = MR.market_day_bucket(rows[i]["published_at"])
        non_company = kind_i in ("market", "info")
        best, best_sim = None, thr
        for cl in live:
            if t - cl.last_h > win:
                continue
            if block_market_bridge:
                # kind 불일치면 붙이지 않음(시장·정보↔종목 브리지 차단)
                if cl.kind != kind_i:
                    continue
                # market/info 클러스터는 같은 거래일만
                if non_company and market_day_boundary and cl.day != day_i:
                    continue
            sim = float(np.dot(v, cl.centroid))  # 둘 다 정규화됨 → cosine
            if sim >= best_sim:
                best_sim, best = sim, cl
        if best is None:
            cl = _Cluster(
                cid_counter,
                stock_code,
                v.copy(),
                [i],
                t,
                t,
                kind=kind_i,
                day=(day_i if non_company else ""),
            )
            live.append(cl)
            assign[i] = {"cluster_id": cid_counter, "assigned_similarity": 1.0, "is_new": True}
            cid_counter += 1
        else:
            n = len(best.member_idx)
            best.centroid = (best.centroid * n + v) / (n + 1)
            nrm = np.linalg.norm(best.centroid)
            if nrm:
                best.centroid = best.centroid / nrm
            best.member_idx.append(i)
            best.last_h = max(best.last_h, t)
            assign[i] = {
                "cluster_id": best.local_id,
                "assigned_similarity": round(best_sim, 6),
                "is_new": False,
            }

    clusters = {
        cl.local_id: {
            "stock_code": cl.stock_code,
            "member_idxs": cl.member_idx,
            "centroid": cl.centroid,
            "first_h": cl.first_h,
            "last_h": cl.last_h,
            "kind": cl.kind,
        }
        for cl in live
    }
    return assign, clusters, cid_counter


def cluster_all(
    rows: list[dict],
    vecs: np.ndarray,
    *,
    block_market_bridge: bool | None = None,
    market_day_boundary: bool | None = None,
    separate_info: bool | None = None,
) -> tuple[dict[int, dict], dict[int, dict]]:
    """전 종목 클러스터링. cluster_id 는 전역 유일(종목 간 오프셋).

    보호 옵션 기본값은 config(BLOCK_MARKET_BRIDGE / MARKET_DAY_BOUNDARY /
    SEPARATE_INFO)를 따른다. 명시 인자로 덮어쓸 수 있다(CLI/테스트용). 끄면 기존과 100% 동일.
    """

    if block_market_bridge is None:
        block_market_bridge = CFG.BLOCK_MARKET_BRIDGE
    if market_day_boundary is None:
        market_day_boundary = CFG.MARKET_DAY_BOUNDARY
    if separate_info is None:
        separate_info = CFG.SEPARATE_INFO

    kinds = None
    if block_market_bridge:
        kinds = [MR.classify_kind(r.get("title", ""), r.get("description", "")) for r in rows]

    by_stock: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        by_stock.setdefault(r["stock_code"], []).append(i)

    all_assign: dict[int, dict] = {}
    all_clusters: dict[int, dict] = {}
    next_id = 1
    for code in CFG.STOCKS:
        idxs = by_stock.get(code, [])
        if not idxs:
            continue
        assign, clusters, next_id = cluster_stock(
            rows,
            vecs,
            idxs,
            code,
            next_id,
            block_market_bridge=block_market_bridge,
            market_day_boundary=market_day_boundary,
            separate_info=separate_info,
            kinds=kinds,
        )
        all_assign.update(assign)
        all_clusters.update(clusters)
    return all_assign, all_clusters


def pick_representative(rows: list[dict], vecs: np.ndarray, cluster: dict) -> int:
    """대표 기사: (1) centroid 최고 유사도 (2) 더 이른 published_at (3) article_id 오름차순."""

    cen = cluster["centroid"]
    best_i, best_key = None, None
    for i in cluster["member_idxs"]:
        sim = float(np.dot(vecs[i], cen))
        key = (-sim, C.parse_hours(rows[i]["published_at"]), rows[i]["article_id"])
        if best_key is None or key < best_key:
            best_key, best_i = key, i
    return best_i
