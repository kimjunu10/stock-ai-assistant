"""Phase 8 final holdout preflight (no Agent execution).

Canonical news Gold is resolved from ``news_clusters.id`` to the current
read-only RAG document/chunks, and the exact resolution is saved for audit.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.time_context import current_seoul_datetime  # noqa: E402
from app.db.client import get_supabase_client  # noqa: E402
from app.eval.grader import preflight_check_relative_gold_validity  # noqa: E402
from app.eval.news_gold import canonical_news_cluster_id  # noqa: E402
from app.eval.schema import EvalSuite  # noqa: E402
from scripts import phase8_validate_dataset as validator  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_8" / "eval"
DEFAULT_OUTPUT = EVAL_DIR / "stable_news_gold_preflight.json"


def _approval_format_errors(cases: list, path: Path) -> list[str]:
    data = json.loads(path.read_text("utf-8"))
    by_id = {case.id: case for case in cases}
    errors: list[str] = []
    seen: set[str] = set()
    approved_pairs: set[tuple[str, str]] = set()
    for item in data.get("approvals", []):
        case_id = item.get("case_id")
        ids = item.get("approved_equivalent_cluster_ids")
        if case_id in seen:
            errors.append(f"{case_id}:duplicate")
        seen.add(case_id)
        if case_id not in by_id:
            errors.append(f"{case_id}:unknown_case")
        else:
            canonical_clusters = {
                cluster_id
                for gold in by_id[case_id].gold_sources
                if (cluster_id := canonical_news_cluster_id(gold)) is not None
            }
            if str(item.get("strict_gold_cluster_id") or "") not in canonical_clusters:
                errors.append(f"{case_id}:strict_gold_mismatch")
        if not isinstance(ids, list) or not ids or any(not str(value).isdigit() for value in ids):
            errors.append(f"{case_id}:invalid_equivalent_ids")
        if not str(item.get("strict_gold_cluster_id") or "").isdigit():
            errors.append(f"{case_id}:invalid_strict_gold")
        if not str(item.get("basis") or "").strip():
            errors.append(f"{case_id}:missing_basis")
        for value in ids or []:
            approved_pairs.add((str(case_id), str(value)))
    for item in data.get("explicitly_not_approved", []):
        case_id = str(item.get("case_id"))
        ids = item.get("candidate_cluster_ids")
        if case_id not in by_id:
            errors.append(f"{case_id}:unknown_rejected_case")
        if not isinstance(ids, list) or not ids:
            errors.append(f"{case_id}:invalid_rejected_ids")
        if not str(item.get("reason") or "").strip():
            errors.append(f"{case_id}:missing_rejection_reason")
        for value in ids or []:
            if (case_id, str(value)) in approved_pairs:
                errors.append(f"{case_id}:{value}:approved_and_rejected")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evaluation-run-at",
        help="KST ISO timestamp; omit to freeze the actual preflight start time",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    evaluation_run_at = (
        datetime.fromisoformat(args.evaluation_run_at)
        if args.evaluation_run_at
        else current_seoul_datetime()
    )
    suite = EvalSuite.model_validate(
        json.loads((EVAL_DIR / "holdout.json").read_text(encoding="utf-8"))
    )
    cases = suite.cases

    validator._RESULTS.clear()
    validator.check(
        "홀드아웃 40문항·split",
        len(cases) == 40 and all(case.split == "holdout" for case in cases),
        f"{len(cases)}문항",
    )
    validator.check_required_fields(cases)
    validator.check_formats(cases)
    validator.check_review_status(cases)

    client = get_supabase_client()
    validator.check_gold_sources(cases, client)
    news_resolution = validator.check_chunk_sources(cases, client)

    relative = preflight_check_relative_gold_validity(cases, planned_run_at=evaluation_run_at)
    validator.check(
        "상대 기간 Gold 유효성",
        not relative["should_abort"],
        json.dumps(relative, ensure_ascii=False),
    )

    all_cases = []
    for name in ("devset.json", "holdout.json"):
        loaded = EvalSuite.model_validate(json.loads((EVAL_DIR / name).read_text(encoding="utf-8")))
        all_cases.extend(loaded.cases)
    approval_errors = _approval_format_errors(
        all_cases, EVAL_DIR / "event_equivalent_approvals.json"
    )
    validator.check(
        "event-equivalent 승인 데이터 형식",
        not approval_errors,
        f"오류 {approval_errors[:5]}",
    )

    checks = [
        {"name": name, "passed": passed, "detail": detail}
        for name, passed, detail in validator._RESULTS
    ]
    failed = [item["name"] for item in checks if not item["passed"]]
    result = {
        "status": "pass" if not failed else "fail",
        "evaluation_run_at": evaluation_run_at.isoformat(),
        "agent_execution_started": False,
        "n_holdout_cases": len(cases),
        "checks": checks,
        "relative_gold": relative,
        "news_gold_resolution": news_resolution,
        "event_equivalent_additional_approvals": 0,
        "failed_checks": failed,
    }
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"PREFLIGHT_FINAL {'PASS' if not failed else 'FAIL'} "
        f"(resolved news {news_resolution['n_resolved']}/"
        f"{news_resolution['n_canonical_gold']})"
    )
    print(f"저장: {args.output}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
