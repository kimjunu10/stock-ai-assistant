"""Phase 8 뉴스 최종 최소 교정 — targeted regression (실제 LLM·DB 호출, read-only).

news-11 Tool 선택 오류(뉴스 사건 질문에 search_news 미호출)를 프롬프트 정책만
수정해 고쳤는지, 그리고 그 수정이 "숫자만 묻는 질문"에서 불필요한 search_news
호출을 늘리지 않는지 확인한다. 특정 문항 문자열을 하드코딩해 분기하지 않는다
(app/agent/prompts.py 의 공통 정책 수정만 검증).

devset.json 자체는 건드리지 않는다 — 이 스크립트가 만드는 EvalCase 는 파일에
저장하지 않고 메모리에서만 실행·채점한다(회귀 확인 전용, 공식 devset 지표에
포함되지 않음).

대상 질문(모두 news-11 과 같은 유형의 "일반적 변형" — 문항 자체 하드코딩이
아니라 정책이 다뤄야 하는 4가지 질문 패턴을 확인):
  A. news-11 원본: 사건 질문 + 재무 수치 언급 → search_news 필요, get_financial_facts 불필요
  B. news-11 유사 변형(다른 종목·다른 수치): 위와 동일 패턴 재확인
  C. 순수 숫자 질문(사건·배경 언급 없음): get_financial_facts 만 필요, search_news 는 불필요
  D. 수치의 공식 사실 확인까지 요구: search_news + get_financial_facts 둘 다 필요

실행:
    cd backend
    AGENT_ENABLED=true .venv/bin/python scripts/phase8_news_final_correction.py
산출: docs/rag/phase_8/eval/news_final_correction_regression.json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("AGENT_ENABLED", "true")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings  # noqa: E402
from app.eval.recorder import ToolCallRecorder  # noqa: E402
from app.eval.runner import EvalRunner  # noqa: E402
from app.eval.schema import EvalCase  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_8" / "eval"

# prompt.md §1 이 명시한 확인 기준: search_news 는 사건·배경 질문에서 반드시 호출돼야
# 하고(핵심 회귀 대상), 공식 수치 확인 요구가 없으면 get_financial_facts 를 곁들여
# 부르지 않아야 한다(devset news-11 라벨의 forbidden_tools 와 동일 기준).
CASES = [
    EvalCase(
        id="regress-news11-original",
        type="뉴스 사건·영향",
        question="SK하이닉스 2분기 영업이익 64조원 관련해서 무슨 일 있었어?",
        stock_code="000660",
        required_tools=["search_news"],
        forbidden_tools=["get_financial_facts"],
    ),
    EvalCase(
        id="regress-news11-variant-stock",
        type="뉴스 사건·영향",
        question="삼성전자 3분기 영업이익 12조원 관련해서 무슨 일 있었어?",
        stock_code="005930",
        required_tools=["search_news"],
        forbidden_tools=["get_financial_facts"],
    ),
    EvalCase(
        id="regress-news11-variant-phrasing",
        type="뉴스 사건·영향",
        question="한화오션 영업이익 5000억원 관련 뉴스랑 배경 알려줘",
        stock_code="042660",
        required_tools=["search_news"],
        forbidden_tools=["get_financial_facts"],
    ),
    EvalCase(
        id="regress-pure-number-question",
        type="정확한 재무 숫자",
        question="SK하이닉스 2026년 2분기 영업이익 얼마야?",
        stock_code="000660",
        required_tools=["get_financial_facts"],
        forbidden_tools=["search_news"],
    ),
    EvalCase(
        id="regress-official-confirmation",
        type="복수 기능 혼합",
        question=(
            "SK하이닉스 2분기 영업이익 64조원이라는데 실제로 맞는 수치야? "
            "무슨 일이 있었는지도 알려줘"
        ),
        stock_code="000660",
        required_tools=["search_news", "get_financial_facts"],
    ),
]


def main() -> int:
    from scripts.phase8_dryrun import build_agent

    cfg = Settings(agent_enabled=True, agent_timeout_seconds=45.0)
    recorder = ToolCallRecorder()
    agent, _facts = build_agent(cfg, recorder)
    runner = EvalRunner(agent, recorder)

    results = []
    for case in CASES:
        rec = runner.run(case)
        used = set(rec.tool_sequence)
        required_ok = set(case.required_tools).issubset(used)
        forbidden_hit = sorted(set(case.forbidden_tools) & used)
        row = {
            "id": case.id,
            "question": case.question,
            "required_tools": case.required_tools,
            "forbidden_tools": case.forbidden_tools,
            "tool_sequence": rec.tool_sequence,
            "required_tools_ok": required_ok,
            "forbidden_tools_violated": forbidden_hit,
            "also_called_get_financial_facts": "get_financial_facts" in used,
            "pass": required_ok and not forbidden_hit,
            "stop_reason": rec.stop_reason,
            "total_latency_ms": rec.total_latency_ms,
        }
        results.append(row)
        status = "PASS" if row["pass"] else "FAIL"
        print(f"[{status}] {case.id}: tools={rec.tool_sequence}")

    n_pass = sum(1 for r in results if r["pass"])
    out = {
        "note": (
            "phase/8-news-final-correction targeted regression. devset.json 미변경, "
            "여기 문항은 공식 지표에 포함되지 않는다."
        ),
        "n": len(results),
        "n_pass": n_pass,
        "all_pass": n_pass == len(results),
        "results": results,
    }
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL_DIR / "news_final_correction_regression.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n{n_pass}/{len(results)} PASS")
    return 0 if out["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
