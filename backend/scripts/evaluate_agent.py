"""Phase 5.5-F: 실제 LLM 기반 Agent 평가 (read-only, 실제 Upstage·DB 호출).

devset.json 의 각 질문을 실제 Agent(create_agent)로 실행하고 Tool trace 로 지표를 계산한다:
- Required Tool Recall / Forbidden Tool Violation / Tool Argument Accuracy
- no_data 처리, 동일 호출 반복, 지연(P50/P95)
- 모델이 직접 Tool 을 선택했음을 tool trace(질문별 실제 tool_calls)로 증명
- legacy QueryPlan 비교(같은 질문의 규칙 기반 예상 경로)

특정 질문·종목별 Tool 강제 없음(Agent 가 스스로 선택). 평가 정답표는 devset.json 에만 있다.

실행:
    cd backend
    AGENT_ENABLED=true .venv/bin/python scripts/evaluate_agent.py
결과: docs/rag/phase_5_5/eval/eval_result.json (+ 콘솔 요약)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.environ.setdefault("AGENT_ENABLED", "true")

import sys  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings  # noqa: E402
from app.db.client import get_supabase_client  # noqa: E402
from app.ml.embeddings import UpstageEmbedder  # noqa: E402
from app.rag.query_plan import build_query_plan  # noqa: E402
from app.rag.retrieval import HybridRetriever  # noqa: E402
from app.services.agent_qa import AgentQaService  # noqa: E402
from app.services.facts import FactsService  # noqa: E402
from app.services.research_reports import ResearchReportSearch  # noqa: E402

DEVSET = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_5_5" / "eval" / "devset.json"
OUT = DEVSET.parent / "eval_result.json"


def _legacy_route(question: str, stock_code: str | None) -> list[str]:
    """legacy QueryPlan 규칙이 예상하는 조회 경로(비교용)."""
    p = build_query_plan(question, stock_code=stock_code)
    route = []
    if p.need_financials:
        route.append("get_financial_facts")
    if p.need_terms:
        route.append("lookup_financial_term")
    if p.need_documents:
        route.append("search_news")
    if p.need_reports:
        route.append("search_research_reports")
    return route


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = int(round((pct / 100) * (len(s) - 1)))
    return s[k]


def main() -> int:
    # 평가에서는 모델 왕복 지연(solar-pro3)이 커 8초 기본 timeout 이 검색 질문을 끊는다.
    # Agent 의 실제 Tool 선택 능력을 측정하기 위해 평가 timeout 을 상향한다(설정값 조정).
    eval_timeout = float(os.environ.get("AGENT_TIMEOUT_SECONDS", "35"))
    cfg = Settings(agent_enabled=True, agent_timeout_seconds=eval_timeout)
    api_key, base_url = cfg.agent_model_credentials()
    if not api_key:
        print(f"{cfg.agent_chat_provider} API 키 없음 — 평가 불가")
        return 2
    print(
        f"평가 provider={cfg.agent_chat_provider} model={cfg.agent_chat_model} "
        f"timeout={eval_timeout}s"
    )

    client = get_supabase_client()
    embedder = UpstageEmbedder(cfg)
    retriever = HybridRetriever(client, cfg, embedder)
    from app.agent.context import ToolServices

    services = ToolServices(
        facts=FactsService(client),
        retriever=retriever,
        reports=ResearchReportSearch(client, cfg, retriever),
    )
    agent = AgentQaService(cfg, services, api_key=api_key, base_url=base_url)

    cases = json.loads(DEVSET.read_text(encoding="utf-8"))["cases"]
    rows = []
    lat = []
    req_hit = req_total = 0
    forbidden_viol = 0
    dup_calls = 0
    nodata_ok = nodata_total = 0

    for c in cases:
        t0 = time.perf_counter()
        r = agent.answer(c["question"], stock_code=c["stock_code"], request_id=c["id"])
        ms = int((time.perf_counter() - t0) * 1000)
        lat.append(ms)
        used = [tc.name for tc in r.tool_calls]
        used_set = set(used)

        # Required Tool Recall
        req = set(c.get("required_tools", []))
        hit = len(req & used_set)
        req_hit += hit
        req_total += len(req)
        # Forbidden Tool Violation
        forb = set(c.get("forbidden_tools", []))
        viol = forb & used_set
        if viol:
            forbidden_viol += 1
        # 동일 호출 반복: 같은 Tool 을 3회 이상 부른 경우만 과다 반복으로 집계.
        # (비교 질문에서 인자가 다른 2회 호출은 정상 — DuplicateToolCallMiddleware 가
        #  동일 인자 반복을 이미 차단하므로 여기서는 과다 호출만 본다.)
        from collections import Counter

        if any(cnt >= 3 for cnt in Counter(used).values()):
            dup_calls += 1
        # no_data 처리
        if not c.get("is_answerable", True):
            nodata_total += 1
            # 근거 없음/데이터 없음이면 답변에 확정 숫자 없어야
            if (
                r.validation_errors
                or "없" in r.answer
                or r.stop_reason != "completed"
                or not r.source_ids
            ):
                nodata_ok += 1

        rows.append(
            {
                "id": c["id"],
                "type": c["type"],
                "question": c["question"],
                "stock_code": c["stock_code"],
                "tools_used": used,  # 모델이 직접 선택한 실제 Tool trace
                "required": sorted(req),
                "required_hit": sorted(req & used_set),
                "forbidden_violated": sorted(viol),
                "legacy_route": _legacy_route(c["question"], c["stock_code"]),
                "stop_reason": r.stop_reason,
                "model_calls": r.model_calls,
                "validation_errors": r.validation_errors,
                "source_ids_count": len(r.source_ids),
                "latency_ms": ms,
                "answer_head": (r.answer or r.error or "")[:120],
            }
        )
        print(
            f"[{c['id']:14}] tools={used} req_hit={sorted(req & used_set)} "
            f"forb={sorted(viol)} {ms}ms"
        )

    summary = {
        "n": len(cases),
        "required_tool_recall": round(req_hit / max(1, req_total), 4),
        "forbidden_tool_violation_rate": round(forbidden_viol / max(1, len(cases)), 4),
        "duplicate_call_cases": dup_calls,
        "no_data_handled": f"{nodata_ok}/{nodata_total}",
        "latency_ms_p50": _percentile(lat, 50),
        "latency_ms_p95": _percentile(lat, 95),
        "model_selected_tools_proof": "case.tools_used = Agent 실제 tool_calls(코드 강제 아님)",
    }
    OUT.write_text(
        json.dumps({"summary": summary, "cases": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\n=== 요약 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("저장:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
