"""요약 실패(빈 factual_summary) 클러스터만 표적 재시도.

전체 재실행은 기사 유입으로 클러스터 구성이 바뀌므로, 이미 저장된 산출물
(cluster_sources.jsonl + clustered_articles.jsonl)의 클러스터 구성을 그대로 재사용해
factual_summary 가 빈 클러스터만 Solar 로 다시 호출해 채운다.

실행:
    python -m experiments.exp_b_factual_summaries.retry_failed --env <.env> --concurrency 3
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from . import config as CFG
from . import summarize as S

BASE = Path(__file__).resolve().parent
ART = BASE / "artifacts"
DEFAULT_ENV = Path(__file__).resolve().parents[2] / ".env"

STOCK_NAMES = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "034020": "두산에너빌리티",
    "042660": "한화오션",
    "005380": "현대차",
}


def _load_env(p: Path) -> dict[str, str]:
    env = {}
    for line in p.open(encoding="utf-8"):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k] = v.strip().strip('"').strip("'")
    return env


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--env", default=str(DEFAULT_ENV))
    ap.add_argument("--concurrency", type=int, default=3)
    args = ap.parse_args()
    env = _load_env(Path(args.env))
    api_key = env["UPSTAGE_API_KEY"]

    # 클러스터별 소속 기사 (clustered_articles.jsonl 에서, 발행 시간순)
    members: dict[int, list[dict]] = {}
    for line in (ART / "clustered_articles.jsonl").open(encoding="utf-8"):
        a = json.loads(line)
        members.setdefault(a["cluster_id"], []).append(a)
    for cid in members:
        members[cid].sort(key=lambda x: x["published_at"])

    # 빈 factual_summary 클러스터 찾기
    summaries = [
        json.loads(line) for line in (ART / "factual_summaries.jsonl").open(encoding="utf-8")
    ]
    failed = [s for s in summaries if not s["factual_summary"]]
    print(f"재시도 대상: {len(failed)}개 클러스터")
    if not failed:
        print("실패 없음. 종료.")
        return 0

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _one(s: dict) -> tuple[int, dict, dict]:
        cid = s["cluster_id"]
        arts = [
            {
                "press": a["publisher"],
                "title": a["title"],
                "description": a["description"],
                "body": "",
                "published_at": a["published_at"],
            }
            for a in members.get(cid, [])[: CFG.MAX_ARTICLES_PER_SUMMARY]
        ]
        stock_name = STOCK_NAMES.get(s["stock_code"], s["stock_code"])
        prompt = S.build_user_prompt(arts, stock_name)
        parsed, meta = S.call_solar(api_key, prompt, max_retries=6)
        return cid, parsed, meta

    fixed: dict[int, dict] = {}
    ok = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = [ex.submit(_one, s) for s in failed]
        for fut in as_completed(futs):
            cid, parsed, meta = fut.result()
            if meta.get("ok") and meta.get("parse_success"):
                fixed[cid] = parsed
                ok += 1
    print(f"재시도 성공: {ok}/{len(failed)}")

    # factual_summaries.jsonl 갱신
    for s in summaries:
        if s["cluster_id"] in fixed:
            p = fixed[s["cluster_id"]]
            s["factual_title"] = p["title"]
            s["factual_summary"] = p["factual_body"]
            s["parse_success"] = True
    with (ART / "factual_summaries.jsonl").open("w", encoding="utf-8") as f:
        for s in summaries:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    # sentiment_reference_template.csv 갱신 (factual_title/summary 채움)
    rows = list(csv.DictReader((ART / "sentiment_reference_template.csv").open(encoding="utf-8")))
    for r in rows:
        cid = int(r["cluster_id"])
        if cid in fixed:
            r["factual_title"] = fixed[cid]["title"]
            r["factual_summary"] = fixed[cid]["factual_body"]
    with (ART / "sentiment_reference_template.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)

    still = len(failed) - ok
    print(f"남은 실패: {still}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
