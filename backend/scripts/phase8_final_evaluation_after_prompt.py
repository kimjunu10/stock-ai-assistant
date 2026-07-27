"""Phase 8 최종 개발셋 평가 (프롬프트 리팩터링·LLM judge 도입 이후).

기존 실행기·채점기를 그대로 재사용한다(새 평가기를 만들지 않는다):
- scripts/phase8_dryrun.py 의 build_agent (운영 build_agent + 평가용 recorder)
- app/eval/runner.EvalRunner
- app/eval/grader.grade_case / aggregate  ← judge 주입해서 자연어 판정 교체
- app/eval/llm_judge (Solar, temperature=0, 결과 캐시)

이전 라운드와 다른 점:
- grade_case 에 Solar judge 를 주입해 채점한다(제외조건·답변불가 자연어 판정).
- judge 호출 성공/폴백 건수를 분리 집계한다.
- grounded 는 참고 지표로만 보고하고 통과 조건에 넣지 않는다.
- 산출 파일명을 분리해 이전 final-dev 결과를 덮어쓰지 않는다.

홀드아웃은 절대 열지 않는다(파일을 읽지도 않는다).

실행:
    cd backend
    AGENT_ENABLED=true .venv/bin/python scripts/phase8_final_evaluation_after_prompt.py
    ... --limit 5      # 부분 실행(점검용)
    ... --resume       # 중단 지점부터 이어서
    ... --grade-only   # 실행 없이 저장된 기록만 재채점
산출: docs/rag/phase_8/eval/final_after_prompt_{records,metrics}.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("AGENT_ENABLED", "true")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings  # noqa: E402
from app.eval.grader import aggregate, grade_case  # noqa: E402
from app.eval.llm_judge import JudgeCache, make_grader_judge  # noqa: E402
from app.eval.recorder import ToolCallRecorder  # noqa: E402
from app.eval.runner import EvalRunner, RunRecord  # noqa: E402
from app.eval.schema import EvalSuite  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_8" / "eval"
RECORDS_PATH = EVAL_DIR / "final_after_prompt_records.json"
METRICS_PATH = EVAL_DIR / "final_after_prompt_metrics.json"
APPROVALS_PATH = EVAL_DIR / "event_equivalent_approvals.json"

_spec = importlib.util.spec_from_file_location(
    "phase8_dryrun", Path(__file__).resolve().parent / "phase8_dryrun.py"
)
_dryrun = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dryrun)

# 외부 환경 문제로 볼 종료 상태(제품 정확성 실패와 분리해 집계한다).
_ENV_STOP_REASONS = {"timeout", "error", "runner_error"}
# 모델 API 장애가 답변 본문으로 새어 나온 경우의 식별 조각. LangChain 미들웨어가
# 재시도를 소진하면 stop_reason 은 completed 인 채 answer 에 오류 문자열이 담긴다
# — 이걸 제품 실패로 세면 답변 품질 지표가 왜곡된다.
_ENV_ANSWER_MARKERS = (
    "RateLimitError",
    "Model call failed after",
    "Error code: 429",
    "APIConnectionError",
    "InternalServerError",
)


def is_environment_failure(rec: RunRecord) -> tuple[bool, str]:
    """일시적 외부 문제인지 판정한다(제품 정확성 실패와 섞이면 지표가 왜곡된다)."""
    if rec.stop_reason in _ENV_STOP_REASONS:
        return True, f"stop_reason={rec.stop_reason}" + (f" ({rec.error})" if rec.error else "")
    answer = rec.answer or ""
    hit = next((m for m in _ENV_ANSWER_MARKERS if m in answer), None)
    if hit:
        return True, f"모델 API 오류가 답변에 노출됨({hit})"
    bad = [c["name"] for c in rec.tool_calls if c.get("status") == "error"]
    if bad and not rec.answer.strip():
        return True, f"모든 Tool 실패({bad})로 답변 없음"
    return False, ""


def case_passed(case, grade) -> tuple[bool, list[str]]:
    """문항 1건의 '전체 조건 통과' 판정과 실패 사유.

    prompt.md: grounded 는 통과 조건에 넣지 않는다(참고 지표).
    """
    fails: list[str] = []
    if not grade.passed_required_tools:
        fails.append("required_tool_missing")
    if grade.forbidden_violated:
        fails.append("forbidden_tool_called")
    if grade.arg_results and not all(grade.arg_results.values()):
        fails.append("tool_arg_mismatch")
    if grade.exclusion_violations:
        fails.append("exclusion_violated")
    if grade.other_stock_sources:
        fails.append("other_stock_source")
    if grade.overclaim:
        fails.append("overclaim")
    if grade.unanswerable_handled is False:
        fails.append("false_answer_on_unanswerable")
    if grade.financial_grade and not grade.financial_grade.get("exact"):
        fails.append("financial_value_mismatch")
    if any(not n.get("matched") for n in grade.number_results):
        fails.append("number_mismatch")
    if grade.period_ok is False:
        fails.append("period_mismatch")
    if grade.trading_day_ok is False:
        fails.append("trading_day_mismatch")
    return (not fails), fails


def per_type_metrics(cases, records, grades) -> dict:
    by_type: dict[str, list[int]] = {}
    for i, c in enumerate(cases):
        by_type.setdefault(c.type, []).append(i)
    out = {}
    for t, idxs in by_type.items():
        out[t] = aggregate(
            [cases[i] for i in idxs], [records[i] for i in idxs], [grades[i] for i in idxs]
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 이면 전체 120문항")
    ap.add_argument("--resume", action="store_true", help="기존 기록 뒤부터 이어서 실행")
    ap.add_argument("--grade-only", action="store_true", help="실행 없이 저장된 기록만 재채점")
    args = ap.parse_args()

    # 개발셋만 읽는다. 홀드아웃 파일은 열지 않는다.
    suite = EvalSuite.model_validate(json.loads((EVAL_DIR / "devset.json").read_text("utf-8")))
    cases = suite.cases
    if len(cases) != 120:
        print(f"개발셋이 120문항이 아님({len(cases)}) — 중단")
        return 2
    if any(c.split != "dev" for c in cases):
        print("개발셋에 홀드아웃 문항이 섞여 있음 — 중단")
        return 2

    done: dict[str, dict] = {}
    if (args.resume or args.grade_only) and RECORDS_PATH.exists():
        prev = json.loads(RECORDS_PATH.read_text("utf-8"))
        done = {r["case_id"]: r for r in prev.get("records", [])}
        print(f"기존 기록 {len(done)}건 로드")

    cfg = Settings(agent_enabled=True, agent_timeout_seconds=45.0)
    elapsed = 0.0
    facts = None

    if not args.grade_only:
        todo = [c for c in cases if c.id not in done]
        if args.limit:
            todo = todo[: args.limit]
        print(f"개발셋 {len(cases)}문항 중 {len(todo)}건 실행 (홀드아웃 미사용)")

        recorder = ToolCallRecorder()
        agent, facts = _dryrun.build_agent(cfg, recorder)
        runner = EvalRunner(agent, recorder)

        started = time.time()
        for n, case in enumerate(todo, 1):
            rec = runner.run(case)
            done[case.id] = rec.as_dict()
            env, why = is_environment_failure(rec)
            tools = "→".join(rec.tool_sequence) or "(없음)"
            flag = " [ENV]" if env else ""
            print(
                f"[{n:3}/{len(todo)}] {case.id:14} {case.type:12} {tools[:44]:44} "
                f"{rec.total_latency_ms:6}ms{flag} {why[:36]}"
            )
            if n % 10 == 0 or n == len(todo):
                RECORDS_PATH.write_text(
                    json.dumps(
                        {
                            "note": "Phase 8 최종 개발셋 평가(프롬프트 리팩터링 이후) 원시 결과",
                            "records": list(done.values()),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
        elapsed = time.time() - started
    else:
        # 재채점만 할 때도 재무 정답 대조는 DB 조회가 필요하다.
        _, facts = _dryrun.build_agent(cfg, ToolCallRecorder())

    # --- 채점: Solar judge 주입(자연어 판정만 교체) ---
    ran_cases = [c for c in cases if c.id in done]
    records = [RunRecord(**done[c.id]) for c in ran_cases]

    judge_cache = JudgeCache(EVAL_DIR / "llm_judge_cache.json").load()
    judge_fn = make_grader_judge(api_key=cfg.upstage_api_key, cache=judge_cache)
    grades = [
        grade_case(c, r, facts, judge=judge_fn) for c, r in zip(ran_cases, records, strict=True)
    ]
    judge_cache.save()

    # --- 외부 환경 실패(제품 실패와 분리) ---
    env_rows = []
    env_ids: set[str] = set()
    for c, r in zip(ran_cases, records, strict=True):
        env, why = is_environment_failure(r)
        if env:
            env_rows.append({"id": c.id, "type": c.type, "reason": why})
            env_ids.add(c.id)

    # --- 전체 조건 통과율 ---
    # 모델 API 장애(429 등)로 답변 자체가 생성되지 못한 문항은 제품 실패로 세지
    # 않는다. 그 문항을 분모에 남겨두면 외부 장애가 제품 품질처럼 보인다.
    pass_rows = []
    env_failed_rows = []
    for c, g in zip(ran_cases, grades, strict=True):
        ok, fails = case_passed(c, g)
        if ok:
            continue
        row = {"id": c.id, "type": c.type, "fails": fails}
        if c.id in env_ids:
            env_failed_rows.append(row)
        else:
            pass_rows.append(row)
    n_eligible = len(ran_cases) - len(env_ids)
    n_pass = n_eligible - len(pass_rows)

    # --- Solar judge 성공/폴백 분리 ---
    judge_used = sum(1 for g in grades if g.judge_used)
    judge_fallback = [{"id": g.case_id, "error": g.judge_error} for g in grades if not g.judge_used]
    grounded_false = [g.case_id for g in grades if g.judge_grounded is False]

    overall = aggregate(ran_cases, records, grades, event_equivalent_approvals_path=APPROVALS_PATH)
    by_type = per_type_metrics(ran_cases, records, grades)

    cost_total = round(sum(r.cost_usd for r in records), 6)
    out = {
        "note": (
            "Phase 8 최종 개발셋 평가(프롬프트 리팩터링·LLM judge 도입 이후). "
            "홀드아웃 미실행. 측정 대상이 없는 지표는 null(미측정)이며 0 이 아니다. "
            "grounded 는 참고 지표이며 전체 통과 조건에 포함하지 않는다."
        ),
        "n_ran": len(ran_cases),
        "elapsed_sec": round(elapsed, 1),
        "overall_pass": {
            "n_pass": n_pass,
            "n_eligible": n_eligible,
            "n_total_ran": len(ran_cases),
            "n_excluded_environment": len(env_ids),
            "pass_rate": round(n_pass / n_eligible, 4) if n_eligible else None,
            "pass_rate_including_environment": (
                round(n_pass / len(ran_cases), 4) if ran_cases else None
            ),
            "failed_cases": pass_rows,
            "environment_failed_cases": env_failed_rows,
        },
        "judge": {
            "solar_success": judge_used,
            "fallback_to_keyword": len(judge_fallback),
            "fallback_cases": judge_fallback,
            "grounded_false_reference_only": grounded_false,
        },
        "environment_failures": env_rows,
        "cost_usd_total": cost_total,
        "overall": overall,
        "by_type": by_type,
        "grades": [g.as_dict() for g in grades],
    }
    METRICS_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== 실행 {len(ran_cases)}건 / {elapsed:.0f}초 / 외부환경 실패 {len(env_rows)}건 ===")
    print(
        f"전체 조건 통과: {n_pass}/{n_eligible} ({out['overall_pass']['pass_rate']}) "
        f"— 외부장애 {len(env_ids)}건 제외"
    )
    print(f"Solar judge 성공 {judge_used} / 폴백 {len(judge_fallback)}")
    print(f"비용 합계: ${cost_total}")
    print(json.dumps(overall, ensure_ascii=False, indent=2))
    print(f"\n저장: {RECORDS_PATH.name}, {METRICS_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
