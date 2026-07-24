"""EXP-5 오케스트레이터: 클러스터링 재사용/생성 → Solar 사실 통합 본문 → 산출물 6개.

이번 단계는 **오프라인 산출물 단계**다. Supabase에 아무것도 쓰지 않고, 감성 모델을
실행하지 않으며, gold_label 을 만들지 않는다. 산출물 생성 후 멈춘다.

실행:
    python -m experiments.exp_b_factual_summaries.run --device mps
    python -m experiments.exp_b_factual_summaries.run --device mps --limit-clusters 5   # 스모크
    python -m experiments.exp_b_factual_summaries.run --skip-solar                       # 요약 전 단계까지만

산출물(artifacts/):
    clustered_articles.jsonl, cluster_sources.jsonl, factual_summaries.jsonl,
    sentiment_reference_template.csv, summary_run_env.json, README.md
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import UTC
from pathlib import Path

from . import config as CFG
from . import pipeline as P
from . import summarize as S

BASE = Path(__file__).resolve().parent
ART = BASE / "artifacts"
CACHE = BASE / "emb_cache"
DEFAULT_ENV = Path(__file__).resolve().parents[2] / ".env"

STOCK_NAMES = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "034020": "두산에너빌리티",
    "042660": "한화오션",
    "005380": "현대차",
}


def _git_commit() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=str(BASE), stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:  # noqa: BLE001
        return "unknown"


def _iso_from_hours(h: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(h * 3600.0, tz=UTC).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--device", default="mps", help="cpu|cuda|mps")
    ap.add_argument("--env", default=str(DEFAULT_ENV))
    ap.add_argument(
        "--limit-clusters", type=int, default=0, help=">0이면 요약할 클러스터 수 제한(스모크)"
    )
    ap.add_argument("--skip-solar", action="store_true", help="Solar 요약 생략(클러스터링까지만)")
    ap.add_argument("--concurrency", type=int, default=8, help="Solar 동시 호출 수")
    ap.add_argument("--now", default=None, help="실행 시각 ISO(재현용). 없으면 시스템 시각")
    args = ap.parse_args()

    ART.mkdir(parents=True, exist_ok=True)
    env = P._load_env(Path(args.env))

    # 1) 로드
    print("[1] Supabase relevant 기사 로드...")
    rows = P.load_relevant_articles(env, CFG.STOCKS)
    print(f"    총 {len(rows)}개 (기사,종목) 연결")

    # 2) 임베딩
    print(f"[2] BGE-M3 임베딩 (device={args.device})...")
    vecs = P.embed_articles(rows, args.device, CACHE)
    assert vecs.shape[1] == CFG.EMBEDDING_DIM, f"임베딩 차원 {vecs.shape[1]} != {CFG.EMBEDDING_DIM}"
    print(f"    임베딩 shape={vecs.shape}")

    # 3) 종목별 시간순 online centroid
    print("[3] 종목별 online centroid 클러스터링...")
    assign, clusters = P.cluster_all(rows, vecs)
    print(f"    클러스터 {len(clusters)}개")

    # 산출물 1: clustered_articles.jsonl
    _write_clustered_articles(rows, assign)
    # 산출물 2: cluster_sources.jsonl
    reps = _write_cluster_sources(rows, vecs, clusters)

    # 4) Solar 사실 통합 본문
    summaries: dict[int, dict] = {}
    solar_stats = {
        "attempted": 0,
        "ok": 0,
        "parse_fail": 0,
        "http_fail": 0,
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "latencies_ms": [],
    }
    if not args.skip_solar:
        print("[4] Solar Pro 사실 통합 본문 생성...")
        from concurrent.futures import ThreadPoolExecutor, as_completed

        api_key = env["UPSTAGE_API_KEY"]
        cids = sorted(clusters.keys())
        if args.limit_clusters:
            cids = cids[: args.limit_clusters]

        def _one(cid: int) -> tuple[int, dict, dict]:
            cl = clusters[cid]
            members = sorted(
                cl["member_idxs"], key=lambda i: P.C.parse_hours(rows[i]["published_at"])
            )
            members = members[: CFG.MAX_ARTICLES_PER_SUMMARY]
            arts = [rows[i] for i in members]
            stock_name = STOCK_NAMES.get(cl["stock_code"], cl["stock_code"])
            prompt = S.build_user_prompt(arts, stock_name)
            parsed, meta = S.call_solar(api_key, prompt)
            return cid, parsed, meta

        done = 0
        with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            futs = {ex.submit(_one, cid): cid for cid in cids}
            for fut in as_completed(futs):
                cid, parsed, meta = fut.result()
                cl = clusters[cid]
                solar_stats["attempted"] += 1
                if meta.get("ok") and meta.get("parse_success"):
                    solar_stats["ok"] += 1
                    u = meta.get("usage", {})
                    solar_stats["total_prompt_tokens"] += u.get("prompt_tokens", 0)
                    solar_stats["total_completion_tokens"] += u.get("completion_tokens", 0)
                    solar_stats["latencies_ms"].append(meta.get("latency_ms", 0))
                elif meta.get("ok"):
                    solar_stats["parse_fail"] += 1
                else:
                    solar_stats["http_fail"] += 1
                summaries[cid] = {
                    "parsed": parsed,
                    "meta": meta,
                    "truncated_articles": len(cl["member_idxs"]) > CFG.MAX_ARTICLES_PER_SUMMARY,
                }
                done += 1
                if done % 50 == 0 or done == len(cids):
                    print(
                        f"    {done}/{len(cids)} (ok={solar_stats['ok']} parse_fail={solar_stats['parse_fail']} http_fail={solar_stats['http_fail']})"
                    )

    # 산출물 3: factual_summaries.jsonl
    _write_factual_summaries(rows, clusters, reps, summaries, args.now)
    # 산출물 4: sentiment_reference_template.csv
    _write_reference_template(rows, clusters, reps, summaries)
    # 산출물 5: summary_run_env.json
    _write_run_env(rows, clusters, summaries, solar_stats, args)
    # 산출물 6: README.md
    _write_readme(rows, clusters, solar_stats, args)

    print(f"\n완료. 산출물: {ART}")
    return 0


def _write_clustered_articles(rows, assign) -> None:
    p = ART / "clustered_articles.jsonl"
    with p.open("w", encoding="utf-8") as f:
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
                        "embedding_model": CFG.EMBEDDING_MODEL,
                        "embedding_revision": CFG.EMBEDDING_REVISION,
                        "preprocessing_version": CFG.PREPROCESS_VERSION,
                        "clustering_version": CFG.CLUSTERING_VERSION,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"    → {p.name}")


def _write_cluster_sources(rows, vecs, clusters) -> dict[int, int]:
    """cluster_sources.jsonl 작성 + 클러스터별 대표 기사 idx 반환."""

    reps: dict[int, int] = {}
    p = ART / "cluster_sources.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for cid in sorted(clusters):
            cl = clusters[cid]
            rep_i = P.pick_representative(rows, vecs, cl)
            reps[cid] = rep_i
            members = sorted(
                cl["member_idxs"], key=lambda i: P.C.parse_hours(rows[i]["published_at"])
            )
            f.write(
                json.dumps(
                    {
                        "cluster_id": cid,
                        "stock_code": cl["stock_code"],
                        "article_count": len(members),
                        "source_count": len(
                            {rows[i]["press"] for i in members if rows[i]["press"]}
                        ),
                        "first_published_at": _iso_from_hours(cl["first_h"]),
                        "last_active_at": _iso_from_hours(cl["last_h"]),
                        "representative_article_id": rows[rep_i]["article_id"],
                        "representative_title": rows[rep_i]["title"],
                        "article_ids": [rows[i]["article_id"] for i in members],
                        "publishers": [rows[i]["press"] for i in members],
                        "source_urls": [rows[i]["canonical_url"] for i in members],
                        "clustering_version": CFG.CLUSTERING_VERSION,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"    → {p.name}")
    return reps


def _write_factual_summaries(rows, clusters, reps, summaries, now) -> None:
    from datetime import datetime

    created = now or datetime.now(UTC).isoformat()
    p = ART / "factual_summaries.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for cid in sorted(clusters):
            cl = clusters[cid]
            members = sorted(
                cl["member_idxs"], key=lambda i: P.C.parse_hours(rows[i]["published_at"])
            )
            s = summaries.get(cid, {})
            parsed = s.get("parsed", {})
            meta = s.get("meta", {})
            f.write(
                json.dumps(
                    {
                        "cluster_id": cid,
                        "stock_code": cl["stock_code"],
                        "stock_name": STOCK_NAMES.get(cl["stock_code"], cl["stock_code"]),
                        "article_ids": [rows[i]["article_id"] for i in members],
                        "publishers": sorted(
                            {rows[i]["press"] for i in members if rows[i]["press"]}
                        ),
                        "source_urls": [rows[i]["canonical_url"] for i in members],
                        "factual_title": parsed.get("title", ""),
                        "factual_summary": parsed.get("factual_body", ""),
                        "summary_prompt_version": CFG.SUMMARY_PROMPT_VERSION,
                        "summary_model": CFG.SOLAR_MODEL,
                        "parse_success": meta.get("parse_success", False),
                        "input_truncated": s.get("truncated_articles", False),
                        "created_at": created,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"    → {p.name}")


def _write_reference_template(rows, clusters, reps, summaries) -> None:
    p = ART / "sentiment_reference_template.csv"
    cols = [
        "cluster_id",
        "stock_code",
        "stock_name",
        "factual_title",
        "factual_summary",
        "representative_article",
        "source_count",
        "article_ids",
        "source_urls",
        "gold_label",
        "label_reason",
    ]
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for cid in sorted(clusters):
            cl = clusters[cid]
            members = sorted(
                cl["member_idxs"], key=lambda i: P.C.parse_hours(rows[i]["published_at"])
            )
            rep_i = reps[cid]
            parsed = summaries.get(cid, {}).get("parsed", {})
            w.writerow(
                {
                    "cluster_id": cid,
                    "stock_code": cl["stock_code"],
                    "stock_name": STOCK_NAMES.get(cl["stock_code"], cl["stock_code"]),
                    "factual_title": parsed.get("title", ""),
                    "factual_summary": parsed.get("factual_body", ""),
                    "representative_article": rows[rep_i]["title"],
                    "source_count": len({rows[i]["press"] for i in members if rows[i]["press"]}),
                    "article_ids": "|".join(str(rows[i]["article_id"]) for i in members),
                    "source_urls": "|".join(rows[i]["canonical_url"] for i in members),
                    "gold_label": "",  # 사람이 작성 (positive/negative/neutral). 지금은 비움.
                    "label_reason": "",  # 사람이 작성. 지금은 비움.
                }
            )
    print(f"    → {p.name}")


def _write_run_env(rows, clusters, summaries, stats, args) -> None:
    from datetime import datetime

    lat = stats["latencies_ms"]
    singleton = sum(1 for c in clusters.values() if len(c["member_idxs"]) == 1)
    p = ART / "summary_run_env.json"
    p.write_text(
        json.dumps(
            {
                "step": "EXP-5 offline factual summaries",
                "git_commit": _git_commit(),
                "run_at": args.now or datetime.now(UTC).isoformat(),
                "device": args.device,
                "embedding": {
                    "model": CFG.EMBEDDING_MODEL,
                    "revision": CFG.EMBEDDING_REVISION,
                    "dim": CFG.EMBEDDING_DIM,
                    "input_type": CFG.INPUT_TYPE,
                    "preprocess_version": CFG.PREPROCESS_VERSION,
                },
                "clustering": {
                    "method": CFG.CLUSTERING_METHOD,
                    "threshold": CFG.COSINE_THRESHOLD,
                    "active_window_hours": CFG.ACTIVE_WINDOW_HOURS,
                    "version": CFG.CLUSTERING_VERSION,
                    "reused_existing": False,
                    "reason": "DB에 기존 클러스터 없음 → 확정 설정으로 신규 생성",
                },
                "solar": {
                    "model": CFG.SOLAR_MODEL,
                    "base_url": CFG.SOLAR_BASE_URL,
                    "prompt_version": CFG.SUMMARY_PROMPT_VERSION,
                    "temperature": CFG.SOLAR_TEMPERATURE,
                    "max_articles_per_summary": CFG.MAX_ARTICLES_PER_SUMMARY,
                    "system_prompt": S.SYSTEM_PROMPT,
                },
                "input_stats": {
                    "article_stock_links": len(rows),
                    "stocks": sorted({r["stock_code"] for r in rows}),
                },
                "output_stats": {
                    "clusters": len(clusters),
                    "singleton_clusters": singleton,
                    "multi_article_clusters": len(clusters) - singleton,
                    "solar_attempted": stats["attempted"],
                    "solar_ok": stats["ok"],
                    "solar_parse_fail": stats["parse_fail"],
                    "solar_http_fail": stats["http_fail"],
                    "total_prompt_tokens": stats["total_prompt_tokens"],
                    "total_completion_tokens": stats["total_completion_tokens"],
                    "avg_latency_ms": round(sum(lat) / len(lat), 1) if lat else None,
                },
                "did_not_do": [
                    "Supabase write",
                    "sentiment prediction",
                    "gold_label 자동 생성",
                    "API / UI 구현",
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"    → {p.name}")


def _write_readme(rows, clusters, stats, args) -> None:
    singleton = sum(1 for c in clusters.values() if len(c["member_idxs"]) == 1)
    txt = f"""# EXP-5 산출물 — 사건 클러스터별 사실 통합 본문

이 폴더는 확정된 뉴스 클러스터링 설정을 재사용/재현하여 각 사건 클러스터의
**라벨 비의존 사실 통합 본문**과 원문 출처 목록을 생성한 오프라인 산출물이다.
감성 분류, gold label, Supabase 반영, API/UI는 이 단계에서 하지 않았다.

## 이 산출물을 만들 당시의 실험 설정

> 이 절은 오프라인 실험을 재현하기 위한 기록이며 현재 운영 클러스터링 설정을
> 뜻하지 않는다.

- 임베딩: `{CFG.EMBEDDING_MODEL}` (revision `{CFG.EMBEDDING_REVISION[:12]}…`), 1024차원
- 입력: title + description
- 클러스터링: online centroid, cosine ≥ {CFG.COSINE_THRESHOLD}, 활성창 {CFG.ACTIVE_WINDOW_HOURS}h, 같은 stock_code끼리만
- 요약: Solar Pro `{CFG.SOLAR_MODEL}`, prompt version `{CFG.SUMMARY_PROMPT_VERSION}`

기존 확정 클러스터링 결과가 DB에 없어(clusters 테이블 미존재) prompt.md 2번 경로에 따라
위 확정 설정으로 신규 생성했다.

## 실행
```bash
# .env 의 DATABASE_URL, UPSTAGE_API_KEY 사용
python -m experiments.exp_b_factual_summaries.run --device mps
```

## 데이터/결과 요약
- 입력 relevant (기사,종목) 연결: {len(rows)}
- 생성 클러스터: {len(clusters)} (단독 {singleton}, 복수기사 {len(clusters) - singleton})
- Solar 요약: 시도 {stats["attempted"]} / 성공 {stats["ok"]} / 파싱실패 {stats["parse_fail"]} / HTTP실패 {stats["http_fail"]}

## 산출물
1. `clustered_articles.jsonl` — 기사별 cluster_id, assigned_similarity, is_new_cluster
2. `cluster_sources.jsonl` — 클러스터별 article_ids, 언론사, 원문 URL, 대표 기사, 활성 구간
3. `factual_summaries.jsonl` — factual_title, factual_summary, source mapping, prompt/version
4. `sentiment_reference_template.csv` — 빈 `gold_label`, `label_reason` (사람이 작성)
5. `summary_run_env.json` — git commit, 모델·프롬프트 버전, 입력/출력 통계
6. `README.md` — 이 문서

## 다음 단계에서 사람이 결정/작성할 것
- `sentiment_reference_template.csv` 의 `gold_label` (positive/negative/neutral) 과 `label_reason` 을 사람이 작성하고 reference version 을 동결한다.
- 이 실험 산출물만으로 감성 예측을 생성·노출하지 않는다.

## 한계
- 원문 body 크롤 실패 기사는 title+description 만으로 임베딩·요약된다.
- 이번 클러스터링은 시간순 holdout 이 아니라 현재 축적분 전체에 대한 배치 재현이다.
"""
    (ART / "README.md").write_text(txt, encoding="utf-8")
    print("    → README.md")


if __name__ == "__main__":
    raise SystemExit(main())
