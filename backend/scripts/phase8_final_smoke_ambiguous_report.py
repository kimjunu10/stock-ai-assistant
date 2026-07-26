"""Phase 8 최종 교정: 모호한 리포트 질문 4종 targeted smoke test (prompt.md §4).

운영 build_agent(phase8_dryrun.build_agent)를 그대로 재사용해 실제 LLM·DB로
A/B/C/D 4개 질문의 실제 동작을 확인한다. 새 평가 로직을 만들지 않는다.

실행:
    cd backend
    AGENT_ENABLED=true .venv/bin/python scripts/phase8_final_smoke_ambiguous_report.py
산출: docs/rag/phase_8/eval/final_ambiguous_report_smoke.json
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("AGENT_ENABLED", "true")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings  # noqa: E402
from app.eval.recorder import ToolCallRecorder  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_8" / "eval"

_spec = importlib.util.spec_from_file_location(
    "phase8_dryrun", Path(__file__).resolve().parent / "phase8_dryrun.py"
)
_dryrun = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dryrun)

CASES = [
    {
        "key": "A",
        "question": "삼성전자 최근 리포트 알려줘",
        "stock_code": "005930",
        "context": {},
    },
    {
        "key": "B",
        "question": "삼성전자 대신증권 리포트 알려줘",
        "stock_code": "005930",
        "context": {},
    },
    {
        "key": "C",
        "question": "삼성전자 리포트 요약해줘",
        "stock_code": "005930",
        "context": {},
    },
    {
        "key": "D",
        "question": "이 리포트 목표주가 근거 알려줘",
        "stock_code": "005930",
        "context": {
            "source_type": "research_report",
            "source_id": "6aeec588-7537-4102-8c0a-f438bc62ba09",
        },
    },
]


def main() -> int:
    cfg = Settings()
    recorder = ToolCallRecorder()
    svc, _facts = _dryrun.build_agent(cfg, recorder)

    results = []
    for c in CASES:
        recorder.reset()
        res = svc.answer(
            c["question"],
            stock_code=c["stock_code"],
            source_type=c["context"].get("source_type"),
            source_id=c["context"].get("source_id"),
        )
        tool_calls = [
            {"name": rc.name, "args": rc.args, "status": rc.status} for rc in recorder.calls
        ]
        results.append(
            {
                "key": c["key"],
                "question": c["question"],
                "context": c["context"],
                "answer": res.answer,
                "tool_calls": tool_calls,
            }
        )
        print(f"=== {c['key']} ===")
        print("질문:", c["question"])
        print("Tool:", [(tc["name"], tc["args"]) for tc in tool_calls])
        print("답변:", (res.answer or "")[:300])
        print()

    (EVAL_DIR / "final_ambiguous_report_smoke.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
