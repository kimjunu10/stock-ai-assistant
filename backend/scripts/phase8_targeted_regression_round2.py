"""Phase 8 2차 교정: targeted regression (실제 LLM 호출, read-only).

round2 에서 실패로 분류된 계층의 문항만 재실행해 수정 전후를 비교한다.
전체 120문항은 재실행하지 않고, 홀드아웃은 열지도 않는다(prompt.md §5·§6).

대상(중복 문항은 한 번만):
  뉴스 Retriever / Agent Tool 선택 / Tool 인자 / 평가기·라벨 / 리포트 Retriever

실행:
    cd backend
    AGENT_ENABLED=true .venv/bin/python scripts/phase8_targeted_regression_round2.py
    ... --dry-run
산출: docs/rag/phase_8/eval/regression_round2.json
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
OUT_PATH = EVAL_DIR / "regression_round2.json"

TARGET_LAYERS = [
    "뉴스 Retriever",
    "Agent Tool 선택",
    "Tool 인자",
    "평가기·라벨",
    "리포트 Retriever",
]

_spec = importlib.util.spec_from_file_location(
    "phase8_dryrun", Path(__file__).resolve().parent / "phase8_dryrun.py"
)
_dryrun = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dryrun)


def select_case_ids() -> list[str]:
    """round2 실패 분류에서 대상 문항을 뽑는다(중복 제거, 입력 순서 유지)."""
    data = json.loads((EVAL_DIR / "round2_failures.json").read_text("utf-8"))
    ids: list[str] = []
    seen: set[str] = set()
    for layer in TARGET_LAYERS:
        for row in data["details"].get(layer, []):
            if row["id"] not in seen:
                seen.add(row["id"])
                ids.append(row["id"])
    return ids


def summarize(case, record: RunRecord, grade) -> dict:
    """이번 라운드의 확인 항목(§5)에 맞춘 신호만 뽑는다."""
    got = set(record.retrieved_ids) | {
        str(s.get("source_id")) for s in record.sources if s.get("source_id")
    }
    gold_ids = {g.source_id for g in case.gold_sources if g.source_id}
    # 문서 단위 적중: 라벨 note 의 원본 식별자와 실제 출처 locator 를 맞춘다.
    # (같은 정답 문서의 다른 청크도 '사건을 찾았다'로 본다 — grader §4 와 같은 기준)
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
        "unnecessary_tools": list(grade.unnecessary_tools),
        "arg_errors": [k for k, v in grade.arg_results.items() if v is False],
        "gold_chunk_hit": bool(gold_ids & got) if gold_ids else None,
        "gold_document_hit": doc_hit,
        "other_stock_sources": list(grade.other_stock_sources),
        "validation_errors": record.validation_errors,
        "answer_dropped": any("제거함" in e for e in record.validation_errors),
        "unsupported_number": any("재무성 숫자" in e for e in record.validation_errors),
        "unknown_broker": any("없는 증권사" in e for e in record.validation_errors),
        "n_sources": len(record.sources),
        "answer_head": (record.answer or record.error or "")[:160],
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
        if (b or {}).get("required_tools_ok") is False and a["required_tools_ok"]:
            marks.append("필수Tool복구")
        if (b or {}).get("arg_errors") and not a["arg_errors"]:
            marks.append("인자수정")
        if (b or {}).get("forbidden_violated") and not a["forbidden_violated"]:
            marks.append("금지Tool해소")
        print(f"[{n:3}/{len(ids)}] {cid:12} {case.type:14} {' '.join(marks) or '-'}")
        if n % 5 == 0 or n == len(ids):
            OUT_PATH.write_text(
                json.dumps({"rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def cnt(side: str, pred) -> int:
        return sum(1 for r in rows if r[side] and pred(r[side]))

    news_rows = [r for r in rows if r["type"] == "뉴스 사건·영향"]

    def news_hit(side: str) -> int:
        return sum(1 for r in news_rows if r[side] and r[side].get("gold_document_hit"))

    summary = {
        "n": len(rows),
        "elapsed_sec": round(time.time() - started, 1),
        "news_gold_document_hit": {
            "total": len(news_rows),
            "before": news_hit("before"),
            "after": news_hit("after"),
        },
        "gold_document_hit": {
            "before": cnt("before", lambda s: s.get("gold_document_hit")),
            "after": cnt("after", lambda s: s.get("gold_document_hit")),
        },
        "required_tools_missing": {
            "before": cnt("before", lambda s: s.get("required_tools_ok") is False),
            "after": cnt("after", lambda s: s.get("required_tools_ok") is False),
        },
        "forbidden_violated": {
            "before": cnt("before", lambda s: s.get("forbidden_violated")),
            "after": cnt("after", lambda s: s.get("forbidden_violated")),
        },
        "unnecessary_tools": {
            "before": cnt("before", lambda s: s.get("unnecessary_tools")),
            "after": cnt("after", lambda s: s.get("unnecessary_tools")),
        },
        "arg_errors": {
            "before": cnt("before", lambda s: s.get("arg_errors")),
            "after": cnt("after", lambda s: s.get("arg_errors")),
        },
        "other_stock_contamination": {
            "before": cnt("before", lambda s: s.get("other_stock_sources")),
            "after": cnt("after", lambda s: s.get("other_stock_sources")),
        },
        "answer_dropped": {
            "before": cnt("before", lambda s: s.get("answer_dropped")),
            "after": cnt("after", lambda s: s.get("answer_dropped")),
        },
        "unsupported_number": {
            "before": cnt("before", lambda s: s.get("unsupported_number")),
            "after": cnt("after", lambda s: s.get("unsupported_number")),
        },
        "unknown_broker": {
            "before": cnt("before", lambda s: s.get("unknown_broker")),
            "after": cnt("after", lambda s: s.get("unknown_broker")),
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
