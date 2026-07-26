"""저장된 final-dev 결과를 LLM judge 로 재채점해 기존 키워드 채점과 비교한다.

Agent 를 다시 실행하지 않는다 — 이미 저장된 baseline_dev_records_final.json 의
질문·답변·출처만 읽어 Solar judge 에 넣는다. Retriever·Tool·Gold·devset 은
건드리지 않는다.

목적: grader.py 의 자연어 키워드 판정(_handled_as_unanswerable,
_claim_asserted 등)이 표현 차이만으로 오탐/누락을 내는지 확인하고, 두 방식의
점수 차이를 사람이 눈으로 검토할 수 있게 케이스별로 남긴다.

실행:
    cd backend
    .venv/bin/python scripts/eval_llm_judge_recheck.py
    .venv/bin/python scripts/eval_llm_judge_recheck.py --limit 10   # 일부만
산출:
    docs/rag/phase_8/eval/llm_judge_cache.json      (판정 캐시, 재호출 방지)
    docs/rag/phase_8/eval/llm_judge_comparison.json (키워드 vs judge 비교)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings  # noqa: E402
from app.eval.grader import (  # noqa: E402
    _claim_asserted,
    _handled_as_unanswerable,
    grade_case,
)
from app.eval.llm_judge import JudgeCache, judge_answer  # noqa: E402
from app.eval.runner import RunRecord  # noqa: E402
from app.eval.schema import EvalSuite  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_8" / "eval"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0이면 전체")
    ap.add_argument(
        "--records",
        default="baseline_dev_records_final.json",
        help="재채점할 저장 결과 파일명(EVAL_DIR 기준)",
    )
    args = ap.parse_args()

    cfg = Settings()
    # judge 는 Solar(Upstage)를 쓴다 — 채점 대상 Agent 모델(gpt-4.1-mini)과 다른
    # 모델로 채점해, 같은 모델이 자기 답변을 채점하는 편향을 피한다.
    api_key = cfg.upstage_api_key
    if not api_key:
        print("UPSTAGE_API_KEY 없음 — judge 호출 불가")
        return 2

    suite = EvalSuite.model_validate(json.loads((EVAL_DIR / "devset.json").read_text("utf-8")))
    by_id = {c.id: c for c in suite.cases}
    raw = json.loads((EVAL_DIR / args.records).read_text("utf-8"))
    records = [RunRecord(**r) for r in raw["records"]]
    if args.limit:
        records = records[: args.limit]

    cache = JudgeCache(EVAL_DIR / "llm_judge_cache.json").load()
    print(f"캐시 {len(cache)}건 로드, 대상 {len(records)}문항")

    rows = []
    for rec in records:
        case = by_id[rec.case_id]

        # --- 기존 키워드 채점(비교 기준) ---
        kw_unanswerable = None if case.is_answerable else _handled_as_unanswerable(rec)
        kw_exclusion = [c for c in case.forbidden_claims if _claim_asserted(rec.answer, c)]

        # --- LLM judge 재채점 ---
        v = judge_answer(
            question=rec.question,
            answer=rec.answer,
            sources=rec.sources,
            is_answerable=case.is_answerable,
            forbidden_claims=case.forbidden_claims,
            api_key=api_key,
            cache=cache,
        )
        judge_exclusion_ok = v.exclusion_respected

        row = {
            "case_id": case.id,
            "type": case.type,
            "question": rec.question,
            "answer": rec.answer,
            "is_answerable": case.is_answerable,
            "forbidden_claims": case.forbidden_claims,
            "keyword": {
                "unanswerable_handled": kw_unanswerable,
                "exclusion_violations": kw_exclusion,
            },
            "judge": v.as_dict(),
            # 두 방식이 갈린 항목만 사람이 보면 되도록 표시.
            "disagreement": _disagreement(
                kw_unanswerable, kw_exclusion, v.handled_correctly, judge_exclusion_ok, v.ok
            ),
        }
        rows.append(row)
        if not v.ok:
            print(f"[{case.id}] judge 실패: {v.error}")
        elif row["disagreement"]:
            print(f"[{case.id}] 불일치: {row['disagreement']} | judge: {v.reason[:80]}")

    cache.save()

    # 집계 지표(answer 섹션)까지 두 방식으로 각각 계산해 차이를 보고한다.
    from app.eval.grader import aggregate
    from app.eval.llm_judge import make_grader_judge

    cases_all = [by_id[r.case_id] for r in records]
    grades_kw = [grade_case(c, r, None) for c, r in zip(cases_all, records, strict=True)]
    judge_fn = make_grader_judge(api_key=api_key, cache=cache)
    grades_judge = [
        grade_case(c, r, None, judge=judge_fn) for c, r in zip(cases_all, records, strict=True)
    ]
    agg_kw = aggregate(cases_all, records, grades_kw)
    agg_judge = aggregate(cases_all, records, grades_judge)
    cache.save()

    summary = _summarize(rows)
    summary["aggregate_answer_keyword"] = agg_kw["answer"]
    summary["aggregate_answer_judge"] = agg_judge["answer"]

    out = {
        "note": (
            "저장된 final-dev 결과 재채점(Agent 미실행). 기존 키워드 채점 vs Solar LLM judge "
            "비교. Retriever·Tool·Gold·devset 미변경. Tool·문서ID·숫자·기간 지표는 두 방식이 "
            "동일하다(코드 채점 유지) — 차이가 나는 것은 자연어 판정 항목뿐이다."
        ),
        "records_file": args.records,
        "n": len(rows),
        "summary": summary,
        "rows": rows,
    }
    (EVAL_DIR / "llm_judge_comparison.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n=== 요약 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n캐시 {len(cache)}건 저장 → {EVAL_DIR / 'llm_judge_cache.json'}")
    return 0


def _disagreement(
    kw_unanswerable: bool | None,
    kw_exclusion: list[str],
    judge_handled: bool | None,
    judge_exclusion_ok: bool | None,
    judge_ok: bool,
) -> list[str]:
    """키워드 채점과 judge 판정이 갈린 항목만 뽑는다."""
    if not judge_ok:
        return []
    out = []
    if kw_unanswerable is not None and judge_handled is not None:
        if kw_unanswerable != judge_handled:
            out.append(f"unanswerable: keyword={kw_unanswerable} judge={judge_handled}")
    if kw_exclusion or judge_exclusion_ok is False:
        kw_violated = bool(kw_exclusion)
        judge_violated = judge_exclusion_ok is False
        if kw_violated != judge_violated:
            out.append(f"exclusion: keyword_violated={kw_violated} judge_violated={judge_violated}")
    return out


def _summarize(rows: list[dict]) -> dict:
    judged = [r for r in rows if r["judge"]["ok"]]
    unans = [r for r in judged if r["is_answerable"] is False]
    excl = [r for r in judged if r["forbidden_claims"]]
    return {
        "judge_ok": len(judged),
        "judge_failed": len(rows) - len(judged),
        "disagreement_cases": [r["case_id"] for r in rows if r["disagreement"]],
        "unanswerable": {
            "n": len(unans),
            "keyword_pass": sum(1 for r in unans if r["keyword"]["unanswerable_handled"]),
            "judge_pass": sum(1 for r in unans if r["judge"]["handled_correctly"]),
        },
        "exclusion": {
            "n": len(excl),
            "keyword_violations": sum(1 for r in excl if r["keyword"]["exclusion_violations"]),
            "judge_violations": sum(1 for r in excl if r["judge"]["exclusion_respected"] is False),
        },
        "grounded_false": [r["case_id"] for r in judged if r["judge"]["grounded"] is False],
    }


if __name__ == "__main__":
    raise SystemExit(main())
