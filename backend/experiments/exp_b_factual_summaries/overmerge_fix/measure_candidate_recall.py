"""후보 검색 recall@1/3/5 측정 (LLM 호출 없음).

정답: exp_a validation.csv 의 gold_event_id(사람/AI 검수 동일사건 라벨).
방법: validation 기사를 종목별·시간순으로 스트리밍하며, 각 기사 시점에 '이미 등장한'
기사들로 gold_event_id 별 클러스터를 구성한다. 각 클러스터의 anchor(최초 기사)
임베딩과 새 기사의 cosine 으로 후보를 정렬한다.
 - 새 기사의 gold_event_id 에 '이전 기사'가 있으면(=정답 클러스터 존재) 평가 대상.
 - 정답 클러스터가 cosine 상위 top-k(1/3/5) 후보에 들면 recall@k 히트.
 - cosine < 0.55(LLM_ASSIGN_CANDIDATE_MIN_SIM) 로 정답이 후보에서 제외된 사례를 따로 집계.

anchor 정책(최초 기사 고정)을 그대로 반영해 측정한다. 추가 LLM 호출 없음.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent
EXP_B = BASE.parent
EXP_A = EXP_B.parent / "exp_a_clustering"
for p in (EXP_A, EXP_B, BASE):
    sys.path.insert(0, str(p))

import clustering_lib as C  # noqa: E402
import config as CFG  # noqa: E402

VALIDATION = EXP_A / "splits" / "validation.csv"
CACHE_DIR = BASE / "emb_cache"
MIN_SIM = CFG.LLM_ASSIGN_CANDIDATE_MIN_SIM  # 0.55
WINDOW_H = CFG.ACTIVE_WINDOW_HOURS


def _embed(rows: list[dict]) -> np.ndarray:
    prepared = [
        C.format_for_model(C.build_input_text(r, CFG.INPUT_TYPE), CFG.EMBEDDING_MODEL) for r in rows
    ]
    cache = C.EmbeddingCache(cache_dir=CACHE_DIR)
    cache.load(CFG.EMBEDDING_MODEL)
    keys = [
        cache.key(CFG.EMBEDDING_MODEL, CFG.EMBEDDING_REVISION, CFG.INPUT_TYPE, C.text_sha256(t))
        for t in prepared
    ]
    missing = [i for i, k in enumerate(keys) if cache.get(k) is None]
    if missing:
        vecs, _ = C.embed_sentence_transformer(
            [prepared[i] for i in missing], CFG.EMBEDDING_MODEL, CFG.EMBEDDING_REVISION, "mps"
        )
        for j, i in enumerate(missing):
            cache.put(keys[i], vecs[j])
        cache.save(CFG.EMBEDDING_MODEL)
    mat = np.vstack([cache.get(k) for k in keys]).astype(np.float32)
    return C.l2_normalize(mat)


def main() -> None:
    rows = []
    with VALIDATION.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append(
                {
                    "article_id": r["article_id"],
                    "stock_code": r["stock_code"],
                    "title": r.get("title", ""),
                    "description": r.get("description", ""),
                    "published_at": r["published_at"],
                    "gold": r["gold_event_id"],
                }
            )
    vecs = _embed(rows)

    # 종목별 시간순
    by_stock = defaultdict(list)
    for i, r in enumerate(rows):
        by_stock[r["stock_code"]].append(i)
    for code in by_stock:
        by_stock[code].sort(key=lambda i: C.parse_hours(rows[i]["published_at"]))

    hit1 = hit3 = hit5 = evald = 0
    excluded_by_055 = []  # 정답이 존재하나 cosine<0.55 로 후보에서 빠진 사례

    for code, idxs in by_stock.items():
        # gold_event_id -> {anchor_idx, last_active_h}
        clusters: dict[str, dict] = {}
        for i in idxs:
            t = C.parse_hours(rows[i]["published_at"])
            gold = rows[i]["gold"]
            # 활성 클러스터 후보(같은 종목, 72h 이내) + anchor 유사도
            scored = []
            for g, cl in clusters.items():
                if t - cl["last_h"] > WINDOW_H:
                    continue
                sim = float(np.dot(vecs[i], vecs[cl["anchor"]]))
                scored.append((sim, g))
            scored.sort(key=lambda x: -x[0])

            gold_exists = gold in clusters and (t - clusters[gold]["last_h"] <= WINDOW_H)
            if gold_exists:
                evald += 1
                # 정답의 anchor 유사도
                gold_sim = float(np.dot(vecs[i], vecs[clusters[gold]["anchor"]]))
                # min_sim 필터 적용 후 top-k
                filtered = [(s, g) for s, g in scored if s >= MIN_SIM]
                topk = [g for _s, g in filtered]
                if gold in topk[:1]:
                    hit1 += 1
                if gold in topk[:3]:
                    hit3 += 1
                if gold in topk[:5]:
                    hit5 += 1
                # 정답이 0.55 미만이라 후보에서 빠졌나
                if gold_sim < MIN_SIM:
                    excluded_by_055.append(
                        (code, rows[i]["article_id"], round(gold_sim, 3), rows[i]["title"][:45])
                    )

            # 클러스터 갱신(anchor 는 최초 기사로 고정)
            if gold not in clusters:
                clusters[gold] = {"anchor": i, "last_h": t}
            else:
                clusters[gold]["last_h"] = max(clusters[gold]["last_h"], t)

    print(f"validation 기사={len(rows)}  평가대상(정답 클러스터 존재)={evald}")
    if evald:
        print(f"recall@1 = {hit1 / evald:.3f} ({hit1}/{evald})")
        print(f"recall@3 = {hit3 / evald:.3f} ({hit3}/{evald})")
        print(f"recall@5 = {hit5 / evald:.3f} ({hit5}/{evald})")
    print(f"\ncosine<{MIN_SIM} 로 정답 후보 제외된 건수 = {len(excluded_by_055)}")
    for c in excluded_by_055[:20]:
        print(f"  [{c[0]}] aid={c[1]} gold_sim={c[2]} | {c[3]}")


if __name__ == "__main__":
    main()
