"""실험 A 오케스트레이터 [4~7]: 임베딩 × 클러스터링 스윕 → 평가 → 산출물.

dev/val/test 프로토콜:
- development: 코드/파이프라인 검증 (스윕 축소 실행 가능)
- validation: 모델·입력·알고리즘·threshold 선택 (주 스윕)
- test: 최종 확정 설정 1회만 평가

주지표는 B-cubed F1, over-merge가 낮은 설정을 우선. Pairwise F1 단독 선택 금지.
로컬(MPS/CPU)·Colab(CUDA) 공용. 무거운 임베딩은 EmbeddingCache로 재사용.

실행:
    python run_experiment.py --split validation --device mps
    python run_experiment.py --split development --fast --models BAAI/bge-m3
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clustering_lib as C  # noqa: E402

BASE = Path(__file__).resolve().parent
SPLITS = BASE / "splits"
RESULTS = BASE / "results"
PLOTS = BASE / "plots"
REPORTS = BASE / "reports"
CACHE = BASE / "emb_cache"

# 비교 모델 (name, revision, kind). revision은 재현성을 위해 commit hash 고정(#5).
MODELS = [
    ("upstage/embedding-passage", "api", "upstage"),
    ("BAAI/bge-m3", "5617a9f61b028005a4858fdac845db406aefb181", "st"),
    ("intfloat/multilingual-e5-large-instruct", "274baa43b0e13e37fafa6428dbc7938e62e5c439", "st"),
]

# 클러스터링 스윕 그리드 (validation용 전체)
CENTROID_THRESHOLDS = [round(x, 2) for x in np.arange(0.70, 0.951, 0.01)]
WINDOWS_H = [24, 72, 168]
LEIDEN_K = [5, 10, 20, 30]
LEIDEN_EDGE = [round(x, 2) for x in np.arange(0.70, 0.951, 0.05)]
LEIDEN_RES = [0.5, 0.8, 1.0, 1.2, 1.5]


def load_split(name: str) -> list[dict]:
    with (SPLITS / f"{name}.csv").open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def eligible_rows(rows: list[dict]) -> list[dict]:
    """평가는 evaluation_eligible=true 행만 (프롬프트 [1])."""

    return [r for r in rows if r.get("evaluation_eligible") == "true"]


def embed_rows(
    rows: list[dict],
    model: str,
    revision: str,
    kind: str,
    input_type: str,
    cache: C.EmbeddingCache,
    device: str,
    api_key: str | None,
    max_seq_length: int | None = None,
) -> tuple[np.ndarray | None, dict]:
    """행들을 임베딩. 캐시 우선. 반환 (vecs, meta). Upstage 키 없으면 (None, skipped).

    캐시 키는 전처리(format_for_model) 완료 텍스트의 SHA + preprocess_version +
    max_seq_length로 계산한다. meta는 100% cache hit에서도 항상 생성된다.
    """

    raw = [C.build_input_text(r, input_type) for r in rows]
    prepared = [C.format_for_model(t, model) for t in raw]
    msl = max_seq_length if max_seq_length else "default"
    keys = [
        cache.key(model, revision, input_type, C.text_sha256(t), max_seq_length=msl)
        for t in prepared
    ]

    cache.load(model)
    missing_idx = [i for i, k in enumerate(keys) if cache.get(k) is None]
    meta = {
        "api_calls": 0,
        "cache_hits": len(keys) - len(missing_idx),
        "cache_misses": len(missing_idx),
    }

    if missing_idx:
        miss_prepared = [prepared[i] for i in missing_idx]
        if kind == "upstage":
            if not api_key:
                return None, {"status": "skipped", "reason": "no UPSTAGE_API_KEY"}
            t0 = time.time()
            vecs = C.embed_upstage(miss_prepared, api_key)
            meta["api_calls"] = (len(miss_prepared) + 99) // 100
            meta["embed_seconds"] = time.time() - t0
        else:
            t0 = time.time()
            vecs, emb_meta = C.embed_sentence_transformer(
                miss_prepared, model, revision, device, max_seq_length=max_seq_length
            )
            meta["embed_seconds"] = time.time() - t0
            meta.update(emb_meta)
        for j, i in enumerate(missing_idx):
            cache.put(keys[i], vecs[j])
        cache.save(model)
    elif kind != "upstage":
        meta.update(C.embedding_meta_only(prepared, model, revision, max_seq_length))

    mat = np.vstack([cache.get(k) for k in keys]).astype(np.float32)
    mat = C.l2_normalize(mat)
    meta["status"] = "ok"
    return mat, meta


def cluster_per_stock(rows, vecs_by_id, method, params) -> dict[str, int]:
    """같은 stock_code 안에서만 클러스터링(프롬프트 [5]). 종목별 라벨을 전역 유일화."""

    by_stock: dict[str, list[int]] = {}
    for idx, r in enumerate(rows):
        by_stock.setdefault(r["stock_code"], []).append(idx)

    global_labels: dict[str, int] = {}
    offset = 0
    for _, idxs in by_stock.items():
        ids = [rows[i]["article_stock_id"] for i in idxs]
        vecs = np.vstack([vecs_by_id[i] for i in ids])
        times = [C.parse_hours(rows[i]["published_at"]) for i in idxs]
        if method == "centroid":
            lab = C.cluster_online_centroid(
                ids, vecs, times, params["threshold"], params["window_h"]
            )
        elif method == "agglomerative":
            lab = C.cluster_agglomerative(ids, vecs, params["threshold"])
        elif method == "leiden":
            lab = C.cluster_leiden(ids, vecs, params["k"], params["edge"], params["resolution"])
        else:
            raise ValueError(method)
        local_max = -1
        for i, la_ in lab.items():
            global_labels[i] = la_ + offset
            local_max = max(local_max, la_)
        offset += local_max + 1
    return global_labels


def run_sweep(rows, vecs_by_id, methods, fast: bool) -> list[dict]:
    """클러스터링 스윕 실행 → run별 지표 리스트."""

    runs = []
    grids = []
    if "centroid" in methods or "agglomerative" in methods:
        thr = CENTROID_THRESHOLDS[:: (5 if fast else 1)]
        wins = WINDOWS_H if not fast else [72]
        for t in thr:
            for w in wins:
                grids.append(("centroid", {"threshold": t, "window_h": w}))
            grids.append(("agglomerative", {"threshold": t}))
    if "leiden" in methods:
        ks = LEIDEN_K if not fast else [10]
        edges = LEIDEN_EDGE if not fast else [0.8]
        res = LEIDEN_RES if not fast else [1.0]
        for k, e, rr in itertools.product(ks, edges, res):
            grids.append(("leiden", {"k": k, "edge": e, "resolution": rr}))

    seen = set()
    uniq = []
    for m, p in grids:
        key = (m, json.dumps(p, sort_keys=True))
        if key not in seen:
            seen.add(key)
            uniq.append((m, p))

    for method, params in uniq:
        t0 = time.time()
        try:
            pred = cluster_per_stock(rows, vecs_by_id, method, params)
            res = C.evaluate_per_stock(pred, rows, eligible_only=True, strict=True)
        except Exception as e:  # noqa: BLE001
            runs.append({"method": method, **params, "error": str(e)})
            continue
        macro = res["macro"]
        runs.append(
            {
                "method": method,
                **{f"param_{k}": v for k, v in params.items()},
                **{f"macro_{k}": round(v, 4) for k, v in macro.items()},
                "n_pred_clusters": len(set(pred.values())),
                "runtime_sec": round(time.time() - t0, 2),
            }
        )
    return runs


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--split", default="validation", choices=["development", "validation", "test"])
    p.add_argument("--device", default="cpu", help="cpu|cuda|mps")
    p.add_argument("--input-types", nargs="+", default=list(C.INPUT_TYPES))
    p.add_argument("--models", nargs="+", default=[m[0] for m in MODELS])
    p.add_argument("--methods", nargs="+", default=["centroid", "agglomerative", "leiden"])
    p.add_argument("--fast", action="store_true", help="축소 스윕(dev 검증용)")
    p.add_argument("--upstage-key", default=None)
    args = p.parse_args()

    import os

    api_key = args.upstage_key or os.environ.get("UPSTAGE_API_KEY")
    for d in (RESULTS, PLOTS, REPORTS, CACHE):
        d.mkdir(parents=True, exist_ok=True)

    rows_all = load_split(args.split)
    rows = eligible_rows(rows_all)
    print(f"[{args.split}] 전체 {len(rows_all)}행, eligible {len(rows)}행")

    cache = C.EmbeddingCache(cache_dir=CACHE)
    all_runs = []
    for model, revision, kind in MODELS:
        if model not in args.models:
            continue
        for input_type in args.input_types:
            vecs, meta = embed_rows(
                rows, model, revision, kind, input_type, cache, args.device, api_key
            )
            if meta.get("status") == "skipped":
                print(f"  SKIP {model} / {input_type}: {meta['reason']}")
                all_runs.append(
                    {
                        "model": model,
                        "input_type": input_type,
                        "status": "skipped",
                        "reason": meta["reason"],
                    }
                )
                continue
            vecs_by_id = {rows[i]["article_stock_id"]: vecs[i] for i in range(len(rows))}
            print(f"  RUN {model} / {input_type} (cache_hits={meta.get('cache_hits')})")
            runs = run_sweep(rows, vecs_by_id, args.methods, args.fast)
            for r in runs:
                r["model"] = model
                r["input_type"] = input_type
                r["split"] = args.split
            all_runs.extend(runs)

    out = RESULTS / "all_runs.csv"
    if all_runs:
        cols = sorted({k for r in all_runs for k in r})
        with out.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(all_runs)
    print(f"저장: {out} ({len(all_runs)} runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
