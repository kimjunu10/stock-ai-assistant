"""Phase 8 1차 교정: targeted regression (실제 LLM 호출, read-only).

baseline 실패 파일에서 이번 수정과 관련된 유형의 문항만 자동 추출해 재실행하고,
같은 문항 기준으로 수정 전후를 비교한다. 전체 120문항은 재실행하지 않는다.
홀드아웃은 열지도 않는다.

실행:
    cd backend
    AGENT_ENABLED=true .venv/bin/python scripts/phase8_targeted_regression.py
    ... --dry-run      # 대상 문항만 출력(모델 호출 없음)
    ... --limit 10     # 일부만
산출: docs/rag/phase_8/eval/regression_round1.json
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
from app.eval.grader import grade_case  # noqa: E402
from app.eval.recorder import ToolCallRecorder  # noqa: E402
from app.eval.runner import EvalRunner, RunRecord  # noqa: E402
from app.eval.schema import EvalSuite  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_8" / "eval"
OUT_PATH = EVAL_DIR / "regression_round1.json"

# 이번 수정과 관련된 실패 유형(§6).
TARGET_KINDS = [
    "answer_dropped_by_validator",
    "unsupported_number",
    "tool_enum_value_unknown",
    "number_or_period_error",
    "tool_argument_error",
    "label_gold_id_too_strict",
]

_spec = importlib.util.spec_from_file_location(
    "phase8_dryrun", Path(__file__).resolve().parent / "phase8_dryrun.py"
)
_dryrun = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dryrun)


def select_case_ids() -> list[str]:
    """대상 문항을 자동 추출한다(중복 문항은 한 번만)."""
    failures = json.loads((EVAL_DIR / "baseline_dev_failures.json").read_text("utf-8"))
    ids: list[str] = []
    seen: set[str] = set()
    for kind in TARGET_KINDS:
        for row in failures["details"].get(kind, []):
            if row["id"] not in seen:
                seen.add(row["id"])
                ids.append(row["id"])
    return ids


def summarize(record: RunRecord, grade) -> dict:
    """수정 전후 비교에 쓸 핵심 신호만 뽑는다."""
    return {
        "tools": record.tool_sequence,
        "stop_reason": record.stop_reason,
        "validation_errors": record.validation_errors,
        "answer_dropped": any("제거함" in e for e in record.validation_errors),
        "unsupported_number": any("재무성 숫자" in e for e in record.validation_errors),
        "unknown_broker": any("없는 증권사" in e for e in record.validation_errors),
        "no_data_tools": [c["name"] for c in record.tool_calls if c.get("status") == "no_data"],
        "financial_exact": (grade.financial_grade or {}).get("exact"),
        "period_ok": grade.period_ok,
        "arg_errors": [k for k, v in grade.arg_results.items() if v is False],
        "answer_head": (record.answer or record.error or "")[:120],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    suite = EvalSuite.model_validate(json.loads((EVAL_DIR / "devset.json").read_text("utf-8")))
    by_id = {c.id: c for c in suite.cases}
    ids = [i for i in select_case_ids() if i in by_id]
    if args.limit:
        ids = ids[: args.limit]

    print(f"targeted 대상 {len(ids)}문항 (개발셋만, 홀드아웃 미사용)")
    if args.dry_run:
        for i in ids:
            print(" ", i, by_id[i].type, by_id[i].question[:48])
        return 0

    before_raw = json.loads((EVAL_DIR / "baseline_dev_records.json").read_text("utf-8"))
    before = {r["case_id"]: RunRecord(**r) for r in before_raw["records"]}

    cfg = Settings(agent_enabled=True, agent_timeout_seconds=45.0)
    recorder = ToolCallRecorder()
    agent, facts = _dryrun.build_agent(cfg, recorder)
    runner = EvalRunner(agent, recorder)

    rows = []
    started = time.time()
    for n, cid in enumerate(ids, 1):
        case = by_id[cid]
        after_rec = runner.run(case)
        after_grade = grade_case(case, after_rec, facts)
        before_grade = grade_case(case, before[cid], facts) if cid in before else None
        rows.append(
            {
                "id": cid,
                "type": case.type,
                "question": case.question,
                "before": summarize(before[cid], before_grade) if before_grade else None,
                "after": summarize(after_rec, after_grade),
            }
        )
        b = rows[-1]["before"] or {}
        a = rows[-1]["after"]
        mark = []
        if b.get("answer_dropped") and not a["answer_dropped"]:
            mark.append("답변복구")
        if b.get("unsupported_number") and not a["unsupported_number"]:
            mark.append("숫자오탐해소")
        if b.get("no_data_tools") and not a["no_data_tools"]:
            mark.append("no_data해소")
        print(f"[{n:3}/{len(ids)}] {cid:14} {case.type:12} {' '.join(mark) or '-'}")
        if n % 10 == 0 or n == len(ids):
            OUT_PATH.write_text(
                json.dumps({"rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    # 집계
    def count(key: str, side: str) -> int:
        return sum(1 for r in rows if (r[side] or {}).get(key))

    summary = {
        "n": len(rows),
        "elapsed_sec": round(time.time() - started, 1),
        "answer_dropped": {
            "before": count("answer_dropped", "before"),
            "after": count("answer_dropped", "after"),
        },
        "unsupported_number": {
            "before": count("unsupported_number", "before"),
            "after": count("unsupported_number", "after"),
        },
        "unknown_broker": {
            "before": count("unknown_broker", "before"),
            "after": count("unknown_broker", "after"),
        },
        "cases_with_no_data": {
            "before": sum(1 for r in rows if (r["before"] or {}).get("no_data_tools")),
            "after": sum(1 for r in rows if r["after"]["no_data_tools"]),
        },
        "financial_exact": {
            "before": sum(1 for r in rows if (r["before"] or {}).get("financial_exact")),
            "after": sum(1 for r in rows if r["after"]["financial_exact"]),
        },
        "period_ok": {
            "before": sum(1 for r in rows if (r["before"] or {}).get("period_ok")),
            "after": sum(1 for r in rows if r["after"]["period_ok"]),
        },
    }
    OUT_PATH.write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\n=== 수정 전 → 후 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
