"""과병합 완화 오프라인 재클러스터링 테스트 (읽기 전용, 운영 DB 쓰기 금지).

사람이 검수한 216개 평가 pair(gold_event_id)에만, company 기사를 대상으로
동일사건 배정 로직을 시간순으로 다시 적용해 B-cubed 지표를 baseline과 비교한다.
통합 요약은 생성하지 않고, 임베딩은 1회 계산 후 캐시하며, LLM 호출 수를 기록한다.

- 운영 DB: 조회도 하지 않는다(입력은 CSV 두 개). 쓰기 절대 없음.
- 동일사건 판정: 실제 Solar Pro3 호출(assign_llm.LLMAssigner 재사용). temperature=0.
- --prompt current : 운영과 동일한 same_event_v1 프롬프트로 216 pair 재적용(재현 확인)
- --prompt conservative : 과병합을 더 보수적으로 막는 개선 프롬프트

입력:
  - blind CSV  : article_id, stock_code, title, description, published_at ...
  - gold CSV   : article_id, stock_code, gold_event_id (사람 정답)
  - answer key : article_id, stock_code, system_cluster_id (baseline 파티션)

사용:
    cd backend
    python -m scripts.eval_offline_reclustering \\
      --gold docs/clustering_eval_classified_draft.csv \\
      --prompt conservative
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict

from app.core.config import settings
from app.services.news_clustering import BgeM3Embedder
from experiments.exp_b_factual_summaries import assign_llm, market_rules
from experiments.exp_b_factual_summaries import config as CFG

# baseline (prompt.md 기준선): 현재 운영 system_cluster_id vs gold_event_id 의 B-cubed.
BASELINE = {"precision": 0.7810629443, "recall": 0.8110895562, "f1": 0.7957931123}

# 변경 전 current(216 pair, same_event_v1, 오피니언 미제외) 오프라인 측정값 — 비교 기준선.
CURRENT_RESULT = {
    "precision": 0.7915380658,
    "recall": 0.7500862198,
    "f1": 0.7702548554,
    "overmerge": 11,
    "undermerge": 18,
}

# --- 개선(보수적) 동일사건 프롬프트 -------------------------------------------
# 과병합 실사례(레버리지 ETF 관련 칼럼·사설·논평 다수가 서로 다른 사건인데 한 클러스터로
# 뭉침)를 겨냥한다. 같은 소재라도 '하나의 구체적 사건'을 보도한 게 아니면 new 로 민다.
CONSERVATIVE_SYSTEM_PROMPT = (
    "너는 한국어 금융 뉴스의 '동일 사건' 판정기다. 새 기사가 후보 클러스터들 중 "
    "'완전히 같은 하나의 구체적 사건'을 보도한 것과 같은지 판단한다.\n"
    "판단 기준(네 요소가 모두 실질적으로 일치해야 같은 사건):\n"
    "  - 주체(누가), 행동(무엇을 했나), 대상·프로젝트(무엇에 대해), 발생·발표 시점.\n"
    "규칙:\n"
    "1. 네 요소가 실질적으로 일치할 때만 existing 이다.\n"
    "2. 같은 종목·같은 소재·같은 이슈라는 이유만으로 합치지 않는다. 같은 종목의 다른 "
    "발표, 같은 업종의 다른 회사, 같은 주제의 다른 후속 조치는 서로 다른 사건이다.\n"
    "3. 칼럼·사설·논평·기고·해설·분석·전망·기자수첩처럼 하나의 구체적 사건을 전하는 "
    "것이 아니라 의견·해석·시황을 논하는 기사는, 같은 소재를 다루더라도 서로 다른 "
    "기사이면 합치지 말고 new 로 판정한다.\n"
    "4. 조금이라도 애매하면 합치지 말고 new 로 판정한다(과병합보다 미병합이 낫다).\n"
    "5. 후보 중 같은 사건이 하나도 없으면 new.\n"
    '출력은 반드시 {"decision":"existing"|"new","matched_cluster_id":<cluster_id 또는 null>} '
    "형태의 JSON 하나만. 설명을 덧붙이지 않는다."
)


def pad(code: str) -> str:
    return code.strip().zfill(6)


def load_rows(blind_path: str, gold_path: str, answer_path: str) -> list[dict]:
    """blind(본문/시각) + gold(정답) + answer(baseline)를 pair 키로 합친다."""
    blind = {(r["article_id"].strip(), pad(r["stock_code"])): r for r in _read(blind_path)}
    gold = {(r["article_id"].strip(), pad(r["stock_code"])): r for r in _read(gold_path)}
    answer = {(r["article_id"].strip(), pad(r["stock_code"])): r for r in _read(answer_path)}
    rows = []
    for key, b in blind.items():
        g, a = gold.get(key), answer.get(key)
        if not g or not a:
            continue
        rows.append({
            "article_id": key[0],
            "stock_code": key[1],
            "title": b.get("title") or "",
            "description": b.get("description") or "",
            "published_at": b.get("published_at") or "",
            "gold_event_id": g["gold_event_id"].strip(),
            "system_cluster_id": a["system_cluster_id"].strip(),
        })
    return rows


def _read(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def bcubed(pred: dict, gold: dict, items: list) -> dict:
    """B-cubed precision/recall/f1 (item-level, 배정 성공 pair만 평가)."""
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
    """과병합/미병합 진단 + 가장 심한 과병합 5개."""
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


def run(rows: list[dict], prompt: str, *, exclude_opinion: bool = False) -> dict:
    """216 pair를 stock_code별 published_at 시간순으로 LLMAssigner에 흘려 재배정.

    같은 stock_code 안에서 시간 순서를 지키되, 서로 다른 종목은 하나의 assigner
    상태를 공유해도 _find_candidates 가 stock_code로 격리하므로 안전하다.
    exclude_opinion=True 면 명확한 오피니언 기사를 클러스터링 입력에서 제외한다.
    """
    if prompt == "conservative":
        assign_llm.SYSTEM_PROMPT = CONSERVATIVE_SYSTEM_PROMPT  # 개선 프롬프트로 교체

    # --- 임베딩 1회 배치 계산 후 캐시(article_id 기준) ---
    embedder = BgeM3Embedder(settings.news_embedding_device)
    uniq: dict[str, dict] = {}
    for r in rows:
        uniq.setdefault(r["article_id"], r)
    articles = list(uniq.values())
    vectors = embedder.encode_many(articles)
    vec_cache = {a["article_id"]: v for a, v in zip(articles, vectors, strict=True)}

    assigner = assign_llm.LLMAssigner(
        api_key=settings.upstage_api_key,
        use_llm=True,
        window_hours=CFG.ACTIVE_WINDOW_HOURS,
        max_candidates=CFG.LLM_ASSIGN_MAX_CANDIDATES,
        candidate_min_sim=CFG.LLM_ASSIGN_CANDIDATE_MIN_SIM,
    )

    ordered = sorted(rows, key=lambda r: (r["stock_code"], r["published_at"], r["article_id"]))
    pred: dict = {}
    pending = 0
    opinions: list[dict] = []
    for r in ordered:
        key = (r["article_id"], r["stock_code"])
        # opinion gate: 명확한 오피니언 기사는 company 동일사건 클러스터링 입력에서 제외.
        if exclude_opinion and market_rules.is_opinion(r["title"], r["description"]):
            m = market_rules._OPINION_RE.search(r["title"])
            opinions.append({
                "article_id": r["article_id"],
                "stock_code": r["stock_code"],
                "title": r["title"],
                "rule": m.group() if m else "",
                "gold_event_id": r["gold_event_id"],
            })
            continue
        art = {
            "article_id": r["article_id"],
            "stock_code": r["stock_code"],
            "title": r["title"],
            "description": r["description"],
        }
        t_h = _hours(r["published_at"])
        # assigner 의 idempotent seen 은 article_id 만 보므로, 다종목 pair 구분 위해 종목 접두.
        art["article_id"] = f"{r['stock_code']}:{r['article_id']}"
        res = assigner.assign(art, vec_cache[r["article_id"]], t_h)
        if res.status == "pending_retry":
            pending += 1
            continue  # 배정 실패 pair 는 평가 파티션에서 제외(baseline 과 동일 취급)
        pred[key] = f"NEW{res.cluster_id}"
    return {
        "pred": pred,
        "llm_calls": assigner.calls,
        "pending": pending,
        "opinions": opinions,
    }


def _hours(value: str) -> float:
    from datetime import datetime

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.timestamp() / 3600.0


def main() -> None:
    ap = argparse.ArgumentParser(description="과병합 완화 오프라인 재클러스터링 테스트")
    ap.add_argument("--blind", default="docs/clustering_eval_blind.csv")
    ap.add_argument(
        "--gold",
        default="docs/clustering_eval_classified_draft.csv",
        help="gold_event_id가 채워진 CSV",
    )
    ap.add_argument("--answer", default="docs/clustering_eval_answer_key.csv")
    ap.add_argument("--prompt", choices=["current", "conservative"], default="current")
    ap.add_argument(
        "--exclude-opinion",
        action="store_true",
        help="명확한 오피니언 기사를 company 동일사건 클러스터링 입력에서 제외",
    )
    args = ap.parse_args()

    rows = load_rows(args.blind, args.gold, args.answer)
    gold = {(r["article_id"], r["stock_code"]): r["gold_event_id"] for r in rows}

    out = run(rows, args.prompt, exclude_opinion=args.exclude_opinion)
    pred = out["pred"]
    items = [k for k in pred if k in gold]

    metrics = bcubed(pred, gold, items)
    diag = diagnose(pred, gold, items)

    tag = "opinion-gate" if args.exclude_opinion else args.prompt
    print(f"=== 오프라인 재클러스터링 결과 (prompt={args.prompt}, {tag}) ===")
    print(f"평가 pair 수: {len(items)} (배정 실패 제외 {out['pending']}, opinion 제외 {len(out['opinions'])})")
    print()

    if out["opinions"]:
        print(f"opinion 으로 판정된 기사 ({len(out['opinions'])}건) — 각 기사에 적용된 규칙:")
        for o in out["opinions"]:
            print(f"  - [{o['rule']}] {o['article_id']}/{o['stock_code']} (gold={o['gold_event_id']}): "
                  f"{o['title'][:50]}")
        print()

    print(f"B-cubed Precision : {metrics['precision']:.10f}")
    print(f"B-cubed Recall    : {metrics['recall']:.10f}")
    print(f"B-cubed F1        : {metrics['f1']:.10f}")
    print()
    print(f"과병합 클러스터 수 : {diag['overmerge_clusters']}")
    print(f"미병합 사건 수     : {diag['undermerge_events']}")
    print(f"LLM 호출 수        : {out['llm_calls']}")
    print()
    print("가장 심한 과병합 사례 5개 (cluster_id, 섞인 gold event 수, event 목록):")
    for cid, n, events in diag["worst_overmerge"]:
        print(f"  - {cid}: {n}개 사건 뭉침 → {events}")
    print()

    # 변경 전 current(오피니언 미제외, same_event_v1) 결과와 비교.
    print("변경 전 current 결과와 비교:")
    print(f"  {'지표':<10}{'current':>16}{'이번':>16}{'Δ':>14}")
    for name, key in (("Precision", "precision"), ("Recall", "recall"), ("F1", "f1")):
        c = CURRENT_RESULT[key]
        v = metrics[key]
        print(f"  {name:<10}{c:>16.10f}{v:>16.10f}{v - c:>+14.6f}")
    print(f"  {'과병합':<10}{CURRENT_RESULT['overmerge']:>16}{diag['overmerge_clusters']:>16}"
          f"{diag['overmerge_clusters'] - CURRENT_RESULT['overmerge']:>+14}")
    print(f"  {'미병합':<10}{CURRENT_RESULT['undermerge']:>16}{diag['undermerge_events']:>16}"
          f"{diag['undermerge_events'] - CURRENT_RESULT['undermerge']:>+14}")
    print()
    print("(전체 백필과 운영 반영은 실행하지 않음)")


if __name__ == "__main__":
    main()
