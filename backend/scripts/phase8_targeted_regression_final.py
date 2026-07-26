"""Phase 8 최종 교정: targeted regression (실제 LLM 호출, read-only).

round3 에서 실패로 분류된 문항 중 이번 라운드가 손댄 영역만 재실행해 수정
전후를 비교한다. 전체 120문항은 재실행하지 않고, 홀드아웃은 열지도 않는다.

대상(중복 문항은 한 번만):
  뉴스 Retriever 7건 / 리포트 Retriever 4건(06·08 은 의미 검색 한계로 이미 확정,
  09·15 는 이번에 코드 수정) / Validator 오탐 확인 2건(mix-09·mix-15) /
  부정 표현 평가 4건(disc-13·report-10·excl-05·na-05)

실행:
    cd backend
    AGENT_ENABLED=true .venv/bin/python scripts/phase8_targeted_regression_final.py
    ... --dry-run
산출: docs/rag/phase_8/eval/regression_final.json
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
OUT_PATH = EVAL_DIR / "regression_final.json"

TARGET_IDS = [
    # 뉴스 Retriever 실패 7건
    "news-03",
    "news-04",
    "news-09",
    "news-13",
    "news-14",
    "news-15",
    "news-19",
    # 리포트 Retriever 실패 4건(06·08 은 의미 검색 한계 재확인용, 09·15 는 수정 확인)
    "report-06",
    "report-08",
    "report-09",
    "report-15",
    # Validator 오탐 재확인 2건
    "mix-09",
    "mix-15",
    # 부정 표현 평가 오탐 4건
    "disc-13",
    "report-10",
    "excl-05",
    "na-05",
    # 공시 비결정성
    "disc-11",
]

_spec = importlib.util.spec_from_file_location(
    "phase8_dryrun", Path(__file__).resolve().parent / "phase8_dryrun.py"
)
_dryrun = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dryrun)


def summarize(case, record: RunRecord, grade) -> dict:
    got = set(record.retrieved_ids) | {
        str(s.get("source_id")) for s in record.sources if s.get("source_id")
    }
    gold_ids = {g.source_id for g in case.gold_sources if g.source_id}
    import re

    want: set[tuple[str, str]] = set()
    for g in case.gold_sources:
        note = g.note or ""
        m = re.search(r"news_clusters\.id=(\d+)", note)
        if m:
            want.add(("news", m.group(1)))
        m = re.search(r"research_reports\.id=([0-9a-f-]{36})", note)
        if m:
            want.add(("report", m.group(1)))
    doc_hit = None
    if want:
        doc_hit = False
        for s in record.sources:
            loc = s.get("locator") or {}
            if loc.get("report_id") and ("report", str(loc["report_id"])) in want:
                doc_hit = True
            if loc.get("source_pk") and ("news", str(loc["source_pk"])) in want:
                doc_hit = True

    return {
        "tools": record.tool_sequence,
        "stop_reason": record.stop_reason,
        "required_tools_ok": grade.passed_required_tools,
        "forbidden_violated": grade.forbidden_violated,
        "exclusion_violations": list(grade.exclusion_violations),
        "gold_chunk_hit": bool(gold_ids & got) if gold_ids else None,
        "gold_document_hit": doc_hit,
        "other_stock_sources": list(grade.other_stock_sources),
        "validation_errors": record.validation_errors,
        "answer_dropped": any("제거함" in e for e in record.validation_errors),
        "n_sources": len(record.sources),
        "answer_head": (record.answer or record.error or "")[:200],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--repeat-disc11", type=int, default=10)
    args = ap.parse_args()

    suite = EvalSuite.model_validate(json.loads((EVAL_DIR / "devset.json").read_text("utf-8")))
    by_id = {c.id: c for c in suite.cases}
    ids = [i for i in TARGET_IDS if i in by_id]

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
        b = None
        if cid in before:
            b = summarize(case, before[cid], grade_case(case, before[cid], facts))
        a = summarize(case, after_rec, after_grade)
        rows.append(
            {"id": cid, "type": case.type, "question": case.question, "before": b, "after": a}
        )
        marks = []
        if (b or {}).get("gold_document_hit") is False and a["gold_document_hit"]:
            marks.append("정답문서적중")
        if (b or {}).get("exclusion_violations") and not a["exclusion_violations"]:
            marks.append("제외조건오탐해소")
        if (b or {}).get("answer_dropped") and not a["answer_dropped"]:
            marks.append("답변삭제해소")
        print(f"[{n:3}/{len(ids)}] {cid:12} {case.type:14} {' '.join(marks) or '-'}")

    # 공시 비결정성: disc-11 을 N 회 반복 실행해 결과 식별자·순서가 동일한지 확인.
    disc11_runs: list[list[str]] = []
    if "disc-11" in by_id:
        case = by_id["disc-11"]
        for _ in range(args.repeat_disc11):
            rec = runner.run(case)
            ids_seq = list(rec.retrieved_ids) or [
                str(s.get("source_id")) for s in rec.sources if s.get("source_id")
            ]
            disc11_runs.append(ids_seq)
    disc11_stable = len({tuple(r) for r in disc11_runs}) <= 1 if disc11_runs else None

    out = {
        "n": len(rows),
        "elapsed_sec": round(time.time() - started, 1),
        "disc11_repeat_runs": disc11_runs,
        "disc11_stable": disc11_stable,
        "rows": rows,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\ndisc-11 반복 실행 결과 동일 여부:", disc11_stable)
    print(f"저장: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
