"""Phase 8 round2: round1 원시 기록을 현재(수정된) 채점기로 재채점 (모델 호출 없음).

round1 baseline_dev_metrics.json 은 옛 채점기/분류기로 계산된 값이라 round2(현재
채점기)와 직접 비교하면 "채점 기준이 바뀐 효과"와 "Agent 동작이 바뀐 효과"가 섞인다.
같은 기준으로 비교하려면 round1 의 원시 실행 결과(Tool trace·답변·출처)는 그대로 두고
채점기만 현재 버전으로 다시 돌려야 한다.

실행:
    cd backend
    .venv/bin/python scripts/phase8_regrade_round1.py
산출: docs/rag/phase_8/eval/baseline_dev_metrics_round1_regraded.json
      docs/rag/phase_8/eval/baseline_dev_failures_round1_regraded.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.client import get_supabase_client  # noqa: E402
from app.eval.grader import aggregate, grade_case  # noqa: E402
from app.eval.runner import RunRecord  # noqa: E402
from app.eval.schema import EvalSuite  # noqa: E402
from app.services.facts import FactsService  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_8" / "eval"


def per_type_metrics(cases, records, grades) -> dict:
    by_type: dict[str, list[int]] = {}
    for i, c in enumerate(cases):
        by_type.setdefault(c.type, []).append(i)
    return {
        t: aggregate(
            [cases[i] for i in idxs], [records[i] for i in idxs], [grades[i] for i in idxs]
        )
        for t, idxs in by_type.items()
    }


def main() -> int:
    suite = EvalSuite.model_validate(json.loads((EVAL_DIR / "devset.json").read_text("utf-8")))
    by_id = {c.id: c for c in suite.cases}

    raw = json.loads((EVAL_DIR / "baseline_dev_records_round1.json").read_text("utf-8"))
    records = [RunRecord(**r) for r in raw["records"]]
    cases = [by_id[r.case_id] for r in records]

    facts = FactsService(get_supabase_client())
    grades = [grade_case(c, r, facts) for c, r in zip(cases, records, strict=True)]

    overall = aggregate(cases, records, grades)
    by_type = per_type_metrics(cases, records, grades)

    (EVAL_DIR / "baseline_dev_metrics_round1_regraded.json").write_text(
        json.dumps(
            {
                "note": (
                    "round1 원시 실행 결과를 현재(round2) 채점기로 다시 채점한 값. "
                    "round1 vs round2 비교의 '같은 채점 기준' 대조군."
                ),
                "n_ran": len(cases),
                "overall": overall,
                "by_type": by_type,
                "grades": [g.as_dict() for g in grades],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("재채점 완료:", len(cases), "건")
    print(json.dumps(overall, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
