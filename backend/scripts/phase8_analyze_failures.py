"""Phase 8: baseline 실패를 원인별로 분류한다 (모델 호출 없음).

실패 질문을 나열하지 않고 근본 원인으로 묶는다. 각 실패에 치명도와
'수정이 필요한 계층'을 붙인다. 실제 수정은 하지 않는다.

실행:
    cd backend
    .venv/bin/python scripts/phase8_analyze_failures.py
산출: docs/rag/phase_8/eval/baseline_dev_failures.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.eval.runner import RunRecord  # noqa: E402
from app.eval.schema import EvalSuite  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_8" / "eval"

# (분류 키, 치명도, 수정이 필요한 계층)
CATALOG: dict[str, tuple[str, str]] = {
    "required_tool_missing": ("중요", "시스템 프롬프트 / Tool description"),
    "forbidden_tool_called": ("치명적", "시스템 프롬프트"),
    "unnecessary_tool_called": ("일반", "시스템 프롬프트"),
    "tool_argument_error": ("중요", "Tool description / 시스템 프롬프트"),
    "gold_evidence_not_retrieved": ("중요", "검색"),
    "evidence_retrieved_but_unused": ("중요", "시스템 프롬프트"),
    "label_gold_id_too_strict": ("라벨", "평가 데이터"),
    "tool_enum_value_unknown": ("치명적", "Tool description"),
    "stale_duplicate_index": ("중요", "외부 환경 / 데이터 정합성"),
    "answer_dropped_by_validator": ("치명적", "검증기"),
    "number_or_period_error": ("치명적", "Tool 구현 / 시스템 프롬프트"),
    "value_kind_confusion": ("치명적", "시스템 프롬프트"),
    "citation_error": ("치명적", "검증기 / 시스템 프롬프트"),
    "exclusion_violation": ("치명적", "시스템 프롬프트"),
    "other_stock_contamination": ("치명적", "검색"),
    "unsupported_number": ("치명적", "검증기 / 시스템 프롬프트"),
    "false_answer_on_unanswerable": ("치명적", "시스템 프롬프트"),
    "overclaim": ("일반", "시스템 프롬프트"),
    "multistep_incomplete": ("중요", "시스템 프롬프트"),
    "environment_failure": ("환경", "외부 환경"),
}


def _looks_korean(text: str) -> bool:
    return any("가" <= ch <= "힣" for ch in text)


def _label_is_over_specific(case, rec: RunRecord) -> bool:
    """정답 식별자가 과도하게 좁아서 실패로 잡힌 것인지 판정한다.

    질문이 특정 자료를 지정하지 않았는데(예: "배당 얼마나 줬어?") 라벨이 접수번호
    1건만 정답으로 못박은 경우, Agent 가 같은 종류의 다른 자료를 정상적으로
    가져와도 Recall 이 0 이 된다. 이건 제품 결함이 아니라 평가 데이터 문제다.

    판정: 기대한 출처 '종류'는 맞게 가져왔고, 종목도 맞고, 답변도 냈다면
    라벨이 좁은 것으로 본다.
    """
    if not rec.sources or not rec.answer.strip():
        return False
    want_types = {gs.source_type for gs in case.gold_sources}
    got_types = {str(s.get("source_type")) for s in rec.sources}
    if not (want_types & got_types):
        return False
    # 다른 종목이 섞였으면 라벨 문제가 아니라 검색 문제다.
    want_stock = case.context.stock_code or case.stock_code
    if want_stock and any(
        s.get("stock_code") and str(s["stock_code"]) != want_stock for s in rec.sources
    ):
        return False
    # 질문이 특정 자료를 지정했는지: 날짜·증권사명 같은 한정어가 있으면 좁은 라벨이 정당하다.
    pinned = any(
        token in case.question
        for token in ("증권", "리포트", "20", "년 ", "월 ")  # 증권사명·발행일 한정
    )
    return not pinned


def classify(case, rec: RunRecord, grade: dict, env: bool) -> list[str]:
    """한 문항에서 발생한 실패 유형들을 모은다(복수 가능)."""
    hits: list[str] = []
    if env:
        return ["environment_failure"]

    if not grade["passed_required_tools"]:
        hits.append("required_tool_missing")
    if grade["forbidden_violated"]:
        hits.append("forbidden_tool_called")
    if grade["unnecessary_tools"]:
        hits.append("unnecessary_tool_called")
    if any(v is False for v in grade["arg_results"].values()):
        hits.append("tool_argument_error")

    # 검색 실패는 원인이 셋으로 갈린다. 뭉뚱그리면 엉뚱한 계층을 고치게 된다.
    #  (a) 라벨이 특정 1건만 정답으로 못박아, 질문이 지정하지 않은 다른 자료를
    #      정상적으로 가져와도 실패로 잡히는 경우 → 평가 데이터 문제
    #  (b) 같은 자료를 실제로 가져왔는데 답변에 쓰지 않은 경우 → 프롬프트 문제
    #  (c) 정말로 못 찾은 경우 → 검색 문제
    if grade["gold_source_misses"]:
        got = set(rec.retrieved_ids) | {
            str(s.get("source_id")) for s in rec.sources if s.get("source_id")
        }
        if any(m in got for m in grade["gold_source_misses"]):
            hits.append("evidence_retrieved_but_unused")
        elif _label_is_over_specific(case, rec):
            hits.append("label_gold_id_too_strict")
        else:
            hits.append("gold_evidence_not_retrieved")

    # 검증기가 근거 있는 문장까지 지워 답을 못 낸 경우(리포트 목표주가에서 관찰).
    if any("제거함" in e for e in rec.validation_errors):
        hits.append("answer_dropped_by_validator")

    # 열거형 인자에 사전에 없는 값을 넣어 no_data 가 된 경우.
    # 예: event_types=['배당'] — DB 실제 값은 'dividend_matter' 인데 Tool 설명에
    # 유효값 목록이 없어 모델이 한국어로 추측한다. 데이터는 있는데 못 찾는다.
    for call in rec.tool_calls:
        if call.get("status") != "no_data":
            continue
        args = call.get("args") or {}
        enum_args = [v for k, v in args.items() if k.endswith("types") and isinstance(v, list)]
        for values in enum_args:
            if any(_looks_korean(str(v)) for v in values):
                hits.append("tool_enum_value_unknown")
                break
    if grade["other_stock_sources"]:
        hits.append("other_stock_contamination")

    fg = grade.get("financial_grade")
    if fg:
        if not fg["exact"] or not fg["period_ok"]:
            hits.append("number_or_period_error")
        if fg["value_kind_confused"]:
            hits.append("value_kind_confusion")
    if any(not n["matched"] for n in grade["number_results"]):
        hits.append("number_or_period_error")
    if grade["period_ok"] is False or grade["trading_day_ok"] is False:
        hits.append("number_or_period_error")

    errs = rec.validation_errors
    if any("존재하지 않는 인용" in e for e in errs):
        hits.append("citation_error")
    if any("재무성 숫자" in e for e in errs):
        hits.append("unsupported_number")
    if grade["exclusion_violations"]:
        hits.append("exclusion_violation")
    if grade["overclaim"]:
        hits.append("overclaim")
    if grade["unanswerable_handled"] is False:
        hits.append("false_answer_on_unanswerable")
    if (
        len(case.required_tools) + len(case.required_tools_any) >= 2
        and not grade["passed_required_tools"]
    ):
        hits.append("multistep_incomplete")

    return sorted(set(hits))


def main() -> int:
    suite = EvalSuite.model_validate(json.loads((EVAL_DIR / "devset.json").read_text("utf-8")))
    cases = {c.id: c for c in suite.cases}
    recs_raw = json.loads((EVAL_DIR / "baseline_dev_records.json").read_text("utf-8"))["records"]
    metrics = json.loads((EVAL_DIR / "baseline_dev_metrics.json").read_text("utf-8"))
    grades = {g["case_id"]: g for g in metrics["grades"]}
    env_ids = {e["id"]: e["reason"] for e in metrics["environment_failures"]}

    groups: dict[str, list[dict]] = defaultdict(list)
    clean = 0
    for raw in recs_raw:
        rec = RunRecord(**raw)
        case = cases.get(rec.case_id)
        grade = grades.get(rec.case_id)
        if not case or not grade:
            continue
        kinds = classify(case, rec, grade, rec.case_id in env_ids)
        if not kinds:
            clean += 1
            continue
        for k in kinds:
            groups[k].append(
                {
                    "id": case.id,
                    "type": case.type,
                    "question": case.question,
                    "tool_trace": [
                        {"name": c["name"], "args": c.get("args"), "status": c.get("status")}
                        for c in rec.tool_calls
                    ],
                    "expected": {
                        "required_tools": case.required_tools,
                        "required_tools_any": case.required_tools_any,
                        "forbidden_tools": case.forbidden_tools,
                        "expected_args": case.expected_args,
                    },
                    "actual_answer_head": (rec.answer or rec.error or "")[:160],
                    "validation_errors": rec.validation_errors,
                    "env_reason": env_ids.get(case.id, ""),
                }
            )

    summary = []
    for kind, rows in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        sev, layer = CATALOG.get(kind, ("일반", "미분류"))
        summary.append(
            {
                "kind": kind,
                "severity": sev,
                "fix_layer": layer,
                "count": len(rows),
                "by_type": dict(Counter(r["type"] for r in rows)),
                "example_ids": [r["id"] for r in rows[:5]],
            }
        )

    sev_count = Counter(s["severity"] for s in summary for _ in range(s["count"]))
    # 중복 계수와 고유 문항 수를 구분한다 — 한 문항이 여러 오류를 가질 수 있어
    # 합계만 보면 실제보다 심각해 보인다.
    sev_unique: dict[str, set[str]] = defaultdict(set)
    for kind, rows in groups.items():
        sev = CATALOG.get(kind, ("일반", ""))[0]
        for r in rows:
            sev_unique[sev].add(r["id"])
    out = {
        "note": "baseline 실패 원인별 분류. 실제 수정은 하지 않았다.",
        "n_ran": len(recs_raw),
        "clean_cases": clean,
        "failed_cases": len(recs_raw) - clean,
        "severity_totals": dict(sev_count),
        "severity_unique_cases": {k: len(v) for k, v in sev_unique.items()},
        "summary": summary,
        "details": groups,
    }
    (EVAL_DIR / "baseline_dev_failures.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"실행 {len(recs_raw)} / 무결점 {clean} / 실패 유형 발생 {len(recs_raw) - clean}")
    print(f"치명도 합계(중복 계수): {dict(sev_count)}")
    print(f"치명도별 고유 문항 수:   {dict(sorted((k, len(v)) for k, v in sev_unique.items()))}\n")
    for s in summary:
        print(f"{s['count']:3}건  [{s['severity']:3}] {s['kind']:32} → {s['fix_layer']}")
        print(f"       유형: {s['by_type']}  예: {s['example_ids'][:3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
