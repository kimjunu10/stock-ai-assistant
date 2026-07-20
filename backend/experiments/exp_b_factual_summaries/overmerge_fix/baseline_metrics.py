"""baseline 지표 계산 — 기존 clustered_articles.jsonl 만 읽는다(임베딩/DB 불필요).

prompt.md 5절: 코드 수정 전에 기존 결과에서 지표를 계산해 기존 분석의 원인이
실제 산출물과 일치하는지 확인한다. 큰 JSONL 은 스트리밍으로 처리하고, 대표 제목만
제한적으로 남긴다.

출력: overmerge_baseline_metrics.json
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import market_rules as MR

BASE = Path(__file__).resolve().parent
ARTIFACTS = BASE.parent / "artifacts"
CLUSTERED = ARTIFACTS / "clustered_articles.jsonl"
OUT = BASE / "overmerge_baseline_metrics.json"

# prompt.md 4절 회귀 검증 세트(초기 baseline 스냅샷 기준 cluster_id).
# 데이터 증가로 cluster_id 는 매 실행 달라지므로, 이후 실험/검증은 대표 제목으로
# 재식별한다(run_experiments.py CASE_NEEDLES 참조). 아래 ID 는 최초 baseline 참고용.
# (om_522 는 om_600 과 같은 클러스터로 병합돼 제외 — 중복)
OVERMERGE_CASES = [623, 1024, 385, 26, 378]  # om_600, om_997, om_371, om_26, om_364
NORMAL_CASES = [1018, 905, 1034, 686]  # nm_992, nm_881, nm_1008/1221, nm_663


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def main() -> None:
    # cluster_id -> list of article dicts (필요 필드만)
    clusters: dict[int, list[dict]] = defaultdict(list)
    total_articles = 0
    market_wide_total = 0

    with CLUSTERED.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            total_articles += 1
            mw = MR.is_market_wide(r.get("title", ""), r.get("description", ""))
            if mw:
                market_wide_total += 1
            clusters[r["cluster_id"]].append(
                {
                    "title": r.get("title", ""),
                    "published_at": r.get("published_at", ""),
                    "stock_code": r.get("stock_code", ""),
                    "sim": r.get("assigned_similarity", 0.0),
                    "market_wide": mw,
                }
            )

    sizes = {cid: len(a) for cid, a in clusters.items()}
    n_clusters = len(clusters)
    singletons = sum(1 for s in sizes.values() if s == 1)
    max_size = max(sizes.values()) if sizes else 0
    ge50 = sum(1 for s in sizes.values() if s >= 50)

    def case_detail(cid: int) -> dict:
        arts = clusters.get(cid)
        if not arts:
            return {"cluster_id": cid, "found": False}
        arts_sorted = sorted(arts, key=lambda a: a["published_at"])
        days = sorted({a["published_at"][:10] for a in arts_sorted})
        mw_ratio = sum(1 for a in arts if a["market_wide"]) / len(arts)
        # 날짜별 대표 제목(가장 이른 기사)
        by_day: dict[str, str] = {}
        for a in arts_sorted:
            d = a["published_at"][:10]
            if d not in by_day:
                by_day[d] = a["title"]
        first, last = arts_sorted[0], arts_sorted[-1]
        return {
            "cluster_id": cid,
            "found": True,
            "stock_code": arts[0]["stock_code"],
            "n_articles": len(arts),
            "n_days": len(days),
            "date_span": [days[0], days[-1]],
            "market_wide_ratio": round(mw_ratio, 3),
            "first_title": first["title"],
            "last_title": last["title"],
            "titles_by_day": by_day,
        }

    result = {
        "source": str(CLUSTERED.relative_to(BASE.parent)),
        "total_articles": total_articles,
        "n_clusters": n_clusters,
        "singleton_count": singletons,
        "singleton_ratio": round(singletons / n_clusters, 4) if n_clusters else 0,
        "max_cluster_size": max_size,
        "clusters_ge_50": ge50,
        "market_wide_articles": market_wide_total,
        "market_wide_ratio": round(market_wide_total / total_articles, 4) if total_articles else 0,
        "overmerge_cases": [case_detail(c) for c in OVERMERGE_CASES],
        "normal_cases": [case_detail(c) for c in NORMAL_CASES],
    }

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # 대화용 짧은 요약만 출력 (원문 나열 금지)
    print(
        f"기사={total_articles} 클러스터={n_clusters} singleton={singletons}({result['singleton_ratio']})"
    )
    print(f"최대크기={max_size} 50건이상={ge50} 시황비율={result['market_wide_ratio']}")
    print("--- over-merge 검증 사례 ---")
    for c in result["overmerge_cases"]:
        if c["found"]:
            print(
                f"cid {c['cluster_id']}: {c['n_articles']}건 {c['n_days']}일 "
                f"{c['date_span'][0]}~{c['date_span'][1]} 시황비율={c['market_wide_ratio']}"
            )
        else:
            print(f"cid {c['cluster_id']}: 없음")
    print("--- 정상 검증 사례 ---")
    for c in result["normal_cases"]:
        if c["found"]:
            print(
                f"cid {c['cluster_id']}: {c['n_articles']}건 {c['n_days']}일 "
                f"시황비율={c['market_wide_ratio']}"
            )
        else:
            print(f"cid {c['cluster_id']}: 없음")


if __name__ == "__main__":
    main()
