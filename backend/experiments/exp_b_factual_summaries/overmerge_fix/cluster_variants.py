"""over-merge 완화 실험용 클러스터링 변형 — baseline / A / B / C.

baseline 로직(exp_b/pipeline.py cluster_stock)과 동일한 online centroid 를 기준으로,
prompt.md 6절 실험만 옵션으로 추가한다. 옵션을 모두 끄면 baseline 과 동일하게 동작한다.

실험 A(market bridge 차단):
  - 각 기사를 시황(market_wide) 여부로 판별.
  - 클러스터에 kind('company'|'market') 를 둔다. company 기사는 market 클러스터에,
    market 기사는 company 클러스터에 붙지 못한다(브리지 차단).
  - market 클러스터는 같은 거래일(published_at[:10]) 안에서만 이어붙는다(날짜 경계).

실험 B(centroid drift 보호):
  - centroid cosine >= threshold 를 통과해도, 그 클러스터의 최근 N개 멤버 중
    적어도 하나와의 cosine 이 recency_min 이상이어야 배정을 허용한다.
  - 징검다리(중간 기사로 centroid 가 서서히 이동해 처음과 다른 사건이 붙는 것)를 막는다.

실험 C: A + B 동시 적용.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent
EXP_A = BASE.parent.parent / "exp_a_clustering"
sys.path.insert(0, str(EXP_A))
sys.path.insert(0, str(BASE))
import clustering_lib as C  # noqa: E402
import market_rules as MR  # noqa: E402


@dataclass
class VariantConfig:
    threshold: float = 0.74
    window_hours: float = 72.0
    # 실험 A
    block_market_bridge: bool = False
    market_day_boundary: bool = True  # market/info 클러스터는 같은 거래일만
    separate_info: bool = True  # 비사건형 투자정보(info)를 별도 유형으로 분리
    # 실험 B
    drift_guard: bool = False
    recent_n: int = 5
    recency_min: float = 0.68


@dataclass
class _Cluster:
    local_id: int
    stock_code: str
    centroid: np.ndarray
    kind: str  # 'company' | 'market' | 'info'
    day: str  # market/info 클러스터의 거래일(company 는 "")
    member_idx: list[int] = field(default_factory=list)
    recent_vecs: list[np.ndarray] = field(default_factory=list)
    first_h: float = 0.0
    last_h: float = 0.0


def cluster_stock_variant(
    rows: list[dict],
    vecs: np.ndarray,
    idxs: list[int],
    stock_code: str,
    next_cluster_id: int,
    cfg: VariantConfig,
    kinds: list[str],
) -> tuple[dict[int, dict], dict[int, dict], int]:
    """한 종목 내 시간순 online centroid + (옵션) A/B 보호.

    kinds[i] 는 'company'|'market'|'info'. block_market_bridge=False 면 전부 company로
    취급(기존과 동일). market/info 는 company 클러스터에 붙지 못한다(브리지 차단).

    반환: (assign, clusters, next_cluster_id)
    """

    thr = cfg.threshold
    win = cfg.window_hours
    order = sorted(idxs, key=lambda i: C.parse_hours(rows[i]["published_at"]))

    live: list[_Cluster] = []
    cid = next_cluster_id
    assign: dict[int, dict] = {}

    for i in order:
        t = C.parse_hours(rows[i]["published_at"])
        v = vecs[i]
        kind_i = kinds[i] if cfg.block_market_bridge else "company"
        # 비사건형 분리를 끄면 info 는 company 로 되돌린다.
        if kind_i == "info" and not cfg.separate_info:
            kind_i = "company"
        day_i = MR.market_day_bucket(rows[i]["published_at"])
        non_company = kind_i in ("market", "info")

        best, best_sim = None, thr
        for cl in live:
            if t - cl.last_h > win:
                continue
            # 실험 A: kind 불일치면 붙이지 않음(브리지 차단)
            if cfg.block_market_bridge and cl.kind != kind_i:
                continue
            # market/info 클러스터는 같은 거래일만(다른 날 시황·정보 연결 차단)
            if cfg.block_market_bridge and non_company and cfg.market_day_boundary:
                if cl.day != day_i:
                    continue
            sim = float(np.dot(v, cl.centroid))
            if sim < best_sim:
                continue
            # 실험 B: 최근 멤버 recency 조건
            if cfg.drift_guard:
                recent = cl.recent_vecs[-cfg.recent_n :]
                if recent:
                    rmax = max(float(np.dot(v, rv)) for rv in recent)
                    if rmax < cfg.recency_min:
                        continue
            best_sim, best = sim, cl

        if best is None:
            cl = _Cluster(
                cid,
                stock_code,
                v.copy(),
                kind_i,
                day_i if non_company else "",
                [i],
                [v.copy()],
                t,
                t,
            )
            live.append(cl)
            assign[i] = {"cluster_id": cid, "assigned_similarity": 1.0, "is_new": True}
            cid += 1
        else:
            n = len(best.member_idx)
            best.centroid = (best.centroid * n + v) / (n + 1)
            nrm = np.linalg.norm(best.centroid)
            if nrm:
                best.centroid = best.centroid / nrm
            best.member_idx.append(i)
            best.recent_vecs.append(v.copy())
            if len(best.recent_vecs) > max(cfg.recent_n, 10):
                best.recent_vecs = best.recent_vecs[-max(cfg.recent_n, 10) :]
            best.last_h = max(best.last_h, t)
            assign[i] = {
                "cluster_id": best.local_id,
                "assigned_similarity": round(best_sim, 6),
                "is_new": False,
            }

    clusters = {
        cl.local_id: {
            "stock_code": cl.stock_code,
            "kind": cl.kind,
            "member_idxs": cl.member_idx,
            "centroid": cl.centroid,
            "first_h": cl.first_h,
            "last_h": cl.last_h,
        }
        for cl in live
    }
    return assign, clusters, cid


def cluster_all_variant(
    rows: list[dict], vecs: np.ndarray, stocks: list[str], cfg: VariantConfig
) -> tuple[dict[int, dict], dict[int, dict]]:
    kinds = [MR.classify_kind(r.get("title", ""), r.get("description", "")) for r in rows]

    by_stock: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        by_stock.setdefault(r["stock_code"], []).append(i)

    all_assign: dict[int, dict] = {}
    all_clusters: dict[int, dict] = {}
    next_id = 1
    for code in stocks:
        idxs = by_stock.get(code, [])
        if not idxs:
            continue
        assign, clusters, next_id = cluster_stock_variant(
            rows, vecs, idxs, code, next_id, cfg, kinds
        )
        all_assign.update(assign)
        all_clusters.update(clusters)
    return all_assign, all_clusters
