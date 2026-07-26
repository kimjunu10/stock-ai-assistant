"""Phase 8 지표 감사: final-dev 저장 결과 재채점(모델·DB 호출 없음).

phase/8-metric-audit 전용. LLM·DB 를 다시 호출하지 않고, 이미 저장된
docs/rag/phase_8/eval/baseline_dev_records_final.json 원시 실행 기록만
새 aggregate()(app/eval/grader.py, 부모 문서 ID 기준)로 재채점한다.

devset·gold label·Agent·Tool·Retriever·프롬프트·Validator 는 전혀 건드리지
않는다. 이 스크립트는 순수 재계산 + 필수 Tool 호출률 독립 검증만 한다.

실행:
    cd backend
    .venv/bin/python scripts/phase8_metric_audit.py
산출: docs/rag/phase_8/eval/metric_audit_final.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.eval.grader import aggregate, document_ranking, grade_case  # noqa: E402
from app.eval.runner import RunRecord  # noqa: E402
from app.eval.schema import EvalSuite  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_8" / "eval"


def independent_required_tool_recall(cases, records) -> dict:
    """공식 aggregate() 와 별개로 required_tool_recall 을 처음부터 다시 계산한다."""
    by_id = {c.id: c for c in cases}
    total = 0
    hit = 0
    missing: list[tuple[str, str]] = []
    for rec in records:
        case = by_id[rec.case_id]
        used = {c["name"] for c in rec.tool_calls}
        for t in case.required_tools:
            total += 1
            if t in used:
                hit += 1
            else:
                missing.append((case.id, t))
        if case.required_tools_any:
            total += 1
            if set(case.required_tools_any) & used:
                hit += 1
            else:
                missing.append((case.id, "ANY:" + ",".join(case.required_tools_any)))
    return {
        "required_total": total,
        "required_hit": hit,
        "recall": round(hit / total, 4) if total else None,
        "missing": missing,
    }


def main() -> int:
    suite = EvalSuite.model_validate(json.loads((EVAL_DIR / "devset.json").read_text("utf-8")))
    by_id = {c.id: c for c in suite.cases}
    raw = json.loads((EVAL_DIR / "baseline_dev_records_final.json").read_text("utf-8"))
    records = [RunRecord(**r) for r in raw["records"]]
    cases = [by_id[r.case_id] for r in records]

    # facts=None: DB 재조회 없이 채점(expected_financial 대조만 건너뜀, 문서 검색·
    # Tool 지표에는 영향 없음 — 이번 라운드는 DB 재조회 금지).
    grades = [grade_case(c, r, None) for c, r in zip(cases, records, strict=True)]
    official = aggregate(cases, records, grades)

    independent_tools = independent_required_tool_recall(cases, records)

    # 뉴스/리포트 각 케이스의 문서 순위를 원문 그대로 남겨 감사 근거로 보존.
    ranking_audit = []
    for c, r in zip(cases, records, strict=True):
        if c.type not in ("뉴스 사건·영향", "증권사 리포트"):
            continue
        ranking_audit.append(
            {
                "id": c.id,
                "type": c.type,
                "question": c.question,
                "document_ranking": document_ranking(r),
            }
        )

    out = {
        "note": (
            "phase/8-metric-audit — final-dev 저장 결과 재채점(LLM·DB 미호출). "
            "devset·gold·Agent·Tool·Retriever·프롬프트·Validator 미변경."
        ),
        "n": len(cases),
        "official_metrics": official,
        "required_tool_recall_independent_check": independent_tools,
        "official_vs_independent_match": (
            official["agent"]["required_tool_recall"] == independent_tools["recall"]
        ),
        "document_ranking_audit": ranking_audit,
    }
    (EVAL_DIR / "metric_audit_final.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=== 문서 검색(뉴스) ===")
    print(json.dumps(official["retrieval"]["news_retrieval"], ensure_ascii=False, indent=2))
    print("=== 문서 검색(리포트) ===")
    print(json.dumps(official["retrieval"]["report_retrieval"], ensure_ascii=False, indent=2))
    print("=== 리포트 페이지 정확도 ===")
    print(json.dumps(official["retrieval"]["report_page_accuracy"], ensure_ascii=False, indent=2))
    print("\n=== 필수 Tool 호출률 독립 검증 ===")
    print(f"공식값: {official['agent']['required_tool_recall']}")
    print(f"독립계산: {independent_tools['recall']}")
    print(f"분자/분모: {independent_tools['required_hit']}/{independent_tools['required_total']}")
    print(f"누락: {independent_tools['missing']}")
    print(f"\n일치 여부: {out['official_vs_independent_match']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
