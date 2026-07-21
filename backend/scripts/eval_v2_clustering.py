"""뉴스 v2 클러스터링 성능 평가 (읽기 전용, 발표용).

사람이 검수한 216 pair(gold_event_id) 중 v2 가 실제 동일사건 클러스터링한
company_event pair 만 대상으로, 운영 DB 의 v2 배정 결과 vs gold 의 B-cubed 를 계산한다.
DB 는 SELECT 만 한다(쓰기 없음).

사용:
    cd backend
    python -m scripts.eval_v2_clustering
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from collections import defaultdict

from app.core.config import settings
from app.repositories.news_v2 import V2_VERSION


def pad(code: str) -> str:
    return code.strip().zfill(6)


def psql_json(sql: str) -> list[dict]:
    wrapped = f"select coalesce(json_agg(t), '[]') from ({sql.rstrip().rstrip(';')}) t;"
    proc = subprocess.run(
        ["psql", settings.database_url, "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", wrapped],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"psql 실패: {proc.stderr.strip()}")
    return json.loads(proc.stdout.strip() or "[]")


def bcubed(pred: dict, gold: dict, items: list) -> dict:
    P, G = defaultdict(set), defaultdict(set)
    for it in items:
        P[pred[it]].add(it)
        G[gold[it]].add(it)
    prec = rec = 0.0
    for it in items:
        pc, gc = P[pred[it]], G[gold[it]]
        inter = len(pc & gc)
        prec += inter / len(pc)
        rec += inter / len(gc)
    n = len(items)
    prec, rec = prec / n, rec / n
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"precision": prec, "recall": rec, "f1": f1}


def diagnose(pred: dict, gold: dict, items: list) -> dict:
    sys2gold, gold2sys = defaultdict(set), defaultdict(set)
    for it in items:
        sys2gold[pred[it]].add(gold[it])
        gold2sys[gold[it]].add(pred[it])
    overmerge = {c: gs for c, gs in sys2gold.items() if len(gs) > 1}
    undermerge = {g: ss for g, ss in gold2sys.items() if len(ss) > 1}
    worst = sorted(overmerge.items(), key=lambda x: -len(x[1]))[:5]
    return {
        "overmerge_clusters": len(overmerge),
        "undermerge_events": len(undermerge),
        "worst_overmerge": [(c, len(gs), sorted(gs)) for c, gs in worst],
        "n_pred_clusters": len(sys2gold),
        "n_gold_events": len(gold2sys),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="v2 클러스터링 성능 평가(발표용)")
    ap.add_argument("--gold", default="docs/clustering_eval_classified_draft.csv")
    args = ap.parse_args()

    gold_rows = list(csv.DictReader(open(args.gold, encoding="utf-8")))
    gold = {(int(r["article_id"]), pad(r["stock_code"])): r["gold_event_id"].strip()
            for r in gold_rows}
    aids = sorted({k[0] for k in gold})

    # 운영 DB 에서 216 pair 의 v2 배정(사건 클러스터) 조회.
    sql = f"""
    select a.article_id, a.stock_code, a.cluster_id, a.status
    from news_cluster_assignments a
    join news_clusters c on c.id = a.cluster_id
    where c.clustering_version = '{V2_VERSION}'
      and a.status in ('assigned_new', 'assigned_existing')
      and a.article_id in ({",".join(map(str, aids))})
    """
    rows = psql_json(sql)
    pred = {}
    for r in rows:
        key = (int(r["article_id"]), pad(r["stock_code"]))
        if key in gold:
            pred[key] = f"v2c{r['cluster_id']}"

    items = sorted(pred)  # v2 가 실제 클러스터링한 pair 만 평가
    metrics = bcubed(pred, gold, items)
    diag = diagnose(pred, gold, items)

    print("=== 뉴스 v2 동일사건 클러스터링 성능 (216 gold pair 중 v2 클러스터링 대상) ===")
    print(f"평가 대상 pair(v2 company_event 배정): {len(items)}")
    print(f"이 pair 들이 속한 gold 사건 수: {diag['n_gold_events']}")
    print(f"v2 클러스터 수: {diag['n_pred_clusters']}")
    print()
    print(f"B-cubed Precision : {metrics['precision']:.4f}")
    print(f"B-cubed Recall    : {metrics['recall']:.4f}")
    print(f"B-cubed F1        : {metrics['f1']:.4f}")
    print()
    print(f"과병합 클러스터 수 : {diag['overmerge_clusters']}")
    print(f"미병합 사건 수     : {diag['undermerge_events']}")
    print()
    print("가장 심한 과병합 5개 (cluster, 섞인 gold 사건 수, 목록):")
    for cid, n, events in diag["worst_overmerge"]:
        print(f"  - {cid}: {n}개 → {events}")


if __name__ == "__main__":
    main()
