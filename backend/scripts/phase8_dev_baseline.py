"""Phase 8: 개발셋 120문항 baseline 실행 (실제 LLM·DB 호출, read-only).

새 평가기를 만들지 않는다 — 기존 실행기·채점기를 그대로 재사용한다:
- scripts/phase8_dryrun.py 의 build_agent (운영 build_agent + 평가용 recorder)
- app/eval/runner.EvalRunner
- app/eval/grader.grade_case / aggregate

홀드아웃은 절대 실행하지 않는다(파일을 읽지도 않는다).

실행 중 외부 API 오류는 제품 정확성 실패와 분리해 기록한다.
재시도는 운영 Agent 의 middleware 범위 안에서만 일어난다(여기서 추가 재시도 없음).

실행:
    cd backend
    AGENT_ENABLED=true .venv/bin/python scripts/phase8_dev_baseline.py
    ... --limit 5      # 부분 실행(점검용)
    ... --resume       # 중단 지점부터 이어서
산출: docs/rag/phase_8/eval/baseline_dev_{records,metrics}.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("AGENT_ENABLED", "true")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import importlib.util  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.eval.grader import aggregate, grade_case  # noqa: E402
from app.eval.recorder import ToolCallRecorder  # noqa: E402
from app.eval.runner import EvalRunner, RunRecord  # noqa: E402
from app.eval.schema import EvalSuite  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_8" / "eval"
RECORDS_PATH = EVAL_DIR / "baseline_dev_records.json"
METRICS_PATH = EVAL_DIR / "baseline_dev_metrics.json"

# dry-run 스크립트의 Agent 조립을 재사용한다(운영 build_agent + recorder).
_spec = importlib.util.spec_from_file_location(
    "phase8_dryrun", Path(__file__).resolve().parent / "phase8_dryrun.py"
)
_dryrun = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dryrun)

# 외부 환경 문제로 볼 종료 상태(제품 정확성 실패와 분리해 집계한다).
_ENV_STOP_REASONS = {"timeout", "error", "runner_error"}
# Tool 결과가 error 인 것도 외부 API 실패일 수 있어 따로 센다.
_ENV_TOOL_STATUS = "error"


def is_environment_failure(rec: RunRecord) -> tuple[bool, str]:
    """일시적 외부 문제인지 판정한다.

    제품 정확성 실패(Tool 선택 오류·숫자 오류 등)와 섞이면 baseline 이 왜곡된다.
    """
    if rec.stop_reason in _ENV_STOP_REASONS:
        return True, f"stop_reason={rec.stop_reason}" + (f" ({rec.error})" if rec.error else "")
    bad = [c["name"] for c in rec.tool_calls if c.get("status") == _ENV_TOOL_STATUS]
    if bad and not rec.answer.strip():
        return True, f"모든 Tool 실패({bad})로 답변 없음"
    return False, ""


def per_type_metrics(cases, records, grades) -> dict:
    """유형별 지표. aggregate 를 유형별 부분집합에 그대로 적용한다."""
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
    if args.resume and RECORDS_PATH.exists():
        prev = json.loads(RECORDS_PATH.read_text("utf-8"))
        done = {r["case_id"]: r for r in prev.get("records", [])}
        print(f"이어서 실행: 기존 {len(done)}건 재사용")

    todo = [c for c in cases if c.id not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"개발셋 {len(cases)}문항 중 {len(todo)}건 실행 (홀드아웃 미사용)")

    cfg = Settings(agent_enabled=True, agent_timeout_seconds=45.0)
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
            f"[{n:3}/{len(todo)}] {case.id:14} {case.type:12} {tools[:48]:48} "
            f"{rec.total_latency_ms:6}ms{flag} {why[:40]}"
        )
        # 중간 저장: 긴 실행이 끊겨도 결과를 잃지 않는다.
        if n % 10 == 0 or n == len(todo):
            RECORDS_PATH.write_text(
                json.dumps(
                    {"note": "개발셋 baseline 원시 실행 결과", "records": list(done.values())},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    elapsed = time.time() - started
    # 채점: 기록이 있는 문항만(부분 실행 지원)
    ran_cases = [c for c in cases if c.id in done]
    records = [RunRecord(**done[c.id]) for c in ran_cases]
    grades = [grade_case(c, r, facts) for c, r in zip(ran_cases, records, strict=True)]

    env_rows = []
    for c, r in zip(ran_cases, records, strict=True):
        env, why = is_environment_failure(r)
        if env:
            env_rows.append({"id": c.id, "type": c.type, "reason": why})

    overall = aggregate(ran_cases, records, grades)
    by_type = per_type_metrics(ran_cases, records, grades)

    METRICS_PATH.write_text(
        json.dumps(
            {
                "note": (
                    "개발셋 baseline 자동 평가 결과. 홀드아웃 미실행. "
                    "측정 대상이 없는 지표는 null(미측정)이며 0 이 아니다."
                ),
                "n_ran": len(ran_cases),
                "elapsed_sec": round(elapsed, 1),
                "environment_failures": env_rows,
                "overall": overall,
                "by_type": by_type,
                "grades": [g.as_dict() for g in grades],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n실행 {len(ran_cases)}건 / {elapsed:.0f}초 / 외부환경 실패 {len(env_rows)}건")
    print(json.dumps(overall, ensure_ascii=False, indent=2))
    print("\n유형별 필수 Tool 호출률:")
    for t, m in by_type.items():
        print(f"  {t:14} {m['agent']['required_tool_recall']}  (n={m['n']})")
    print(f"\n저장: {RECORDS_PATH.name}, {METRICS_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
