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

EVAL_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_5_5" / "eval"

# gpt-4.1-mini 공개 단가(USD/1M tok). 비용 채점용(모델 변경 시 갱신).
PRICE_IN_PER_M = 0.40
PRICE_OUT_PER_M = 1.60


def _gold_financial(facts, spec: dict) -> dict | None:
    """재무 정답값을 DB(FactsService)에서 조회한다(하드코딩 아님).

    Tool 과 동일한 report_period→reprt_code 매핑을 써서 '정답' 행을 가져온다.
    """
    from app.agent.tools.financials import FinancialFactsInput, run_get_financial_facts

    inp = FinancialFactsInput(
        stock_code=spec["stock_code"],
        account_name=spec["account_name"],
        business_year=spec.get("business_year"),
        report_period=spec.get("report_period"),
        amount_type=spec.get("amount_type"),
        fs_div=spec.get("fs_div", "CFS"),
    )
    res = run_get_financial_facts(facts, inp)
    if res.status != "ok" or not res.data.get("facts"):
        return None
    return res.data["facts"][0]  # value_won·unit·period·value_kind


def _grade_financial(answer: str, gold: dict) -> dict:
    """답변에 정답 숫자·기간·단위·성격이 반영됐는지 채점(Exact Match)."""
    import re

    ans_digits = re.sub(r"[,\s]", "", answer)
    gold_val = str(gold["value_won"])
    exact = gold_val in ans_digits
    if not exact:
        # value_display(조/억 표기)와 일치하면 정답으로 인정(예: '43.60조원' 앞 정수부).
        from app.rag.prompting import format_won

        disp = format_won(gold["value_won"])  # 예: '43.60조원'
        head = re.match(r"[\d.]+", disp)
        if head and head.group(0) and head.group(0) in answer:
            exact = True
    if not exact:
        # 조 단위 근사(예: 43조 ↔ 43,601,051,000,000)
        jo = gold["value_won"] // 1_000_000_000_000
        if jo >= 1 and str(jo) in ans_digits:
            exact = True
    period_ok = bool(gold.get("period")) and any(
        tok in answer for tok in _period_tokens(gold["period"])
    )
    kind_ok = gold.get("value_kind") == "actual_value"  # financials 는 실제값
    return {"exact": exact, "period_ok": period_ok, "actual_ok": kind_ok}


def _period_tokens(period: str) -> list[str]:
    """'2025년 3분기보고서 누적' → 채점용 핵심 토큰."""
    toks = []
    for t in ("연간", "사업보고서", "1분기", "반기", "3분기", "누적", "당기"):
        if t in period:
            toks.append(t)
    m = period.split("년")[0]
    if m.isdigit():
        toks.append(m)
    return toks or [period]


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


def _evaluate_set(name: str, cases: list, agent, facts) -> dict:
    """한 평가셋을 실행·채점한다."""
    from collections import Counter

    rows = []
    lat = []
    req_hit = req_total = 0
    forbidden_viol = 0
    dup_calls = 0
    nodata_ok = nodata_total = 0
    fin_total = fin_exact = fin_period = fin_actual = 0
    bad_citation = 0
    cost_total = 0.0

    for c in cases:
        t0 = time.perf_counter()
        r = agent.answer(c["question"], stock_code=c["stock_code"], request_id=c["id"])
        ms = int((time.perf_counter() - t0) * 1000)
        lat.append(ms)
        used = [tc.name for tc in r.tool_calls]
        used_set = set(used)

        req = set(c.get("required_tools", []))
        req_hit += len(req & used_set)
        req_total += len(req)
        forb = set(c.get("forbidden_tools", []))
        viol = forb & used_set
        if viol:
            forbidden_viol += 1
        if any(cnt >= 3 for cnt in Counter(used).values()):
            dup_calls += 1

        # 존재하지 않는 인용(검증기): validation_errors 에 '인용' 포함 시 위반
        if any("인용" in e for e in r.validation_errors):
            bad_citation += 1

        # 비용(질문당): 토큰 × 단가
        cost = (
            r.input_tokens / 1_000_000 * PRICE_IN_PER_M
            + r.output_tokens / 1_000_000 * PRICE_OUT_PER_M
        )
        cost_total += cost

        # no_data
        if not c.get("is_answerable", True):
            nodata_total += 1
            if (
                r.validation_errors
                or "없" in r.answer
                or r.stop_reason != "completed"
                or not r.source_ids
            ):
                nodata_ok += 1

        # 재무 Exact Match·기간·단위·actual (expected_financial 있는 케이스만)
        fin_grade = None
        spec = c.get("expected_financial")
        if spec:
            fin_total += 1
            gold = _gold_financial(facts, spec)
            if gold:
                fin_grade = _grade_financial(r.answer, gold)
                fin_exact += int(fin_grade["exact"])
                fin_period += int(fin_grade["period_ok"])
                fin_actual += int(fin_grade["actual_ok"])

        rows.append(
            {
                "id": c["id"],
                "type": c["type"],
                "tools_used": used,
                "required_hit": sorted(req & used_set),
                "forbidden_violated": sorted(viol),
                "legacy_route": _legacy_route(c["question"], c["stock_code"]),
                "stop_reason": r.stop_reason,
                "financial_grade": fin_grade,
                "validation_errors": r.validation_errors,
                "tokens": {"in": r.input_tokens, "out": r.output_tokens},
                "cost_usd": round(cost, 6),
                "latency_ms": ms,
                "answer_head": (r.answer or r.error or "")[:120],
            }
        )
        print(f"[{name}:{c['id']:12}] tools={used} fin={fin_grade} {ms}ms")

    return {
        "set": name,
        "n": len(cases),
        "required_tool_recall": round(req_hit / max(1, req_total), 4),
        "forbidden_tool_violation_rate": round(forbidden_viol / max(1, len(cases)), 4),
        "duplicate_call_cases": dup_calls,
        "no_data_handled": f"{nodata_ok}/{nodata_total}",
        "financial_exact_match": f"{fin_exact}/{fin_total}",
        "financial_period_ok": f"{fin_period}/{fin_total}",
        "financial_actual_ok": f"{fin_actual}/{fin_total}",
        "nonexistent_citation": bad_citation,
        "latency_ms_p50": _percentile(lat, 50),
        "latency_ms_p95": _percentile(lat, 95),
        "cost_usd_total": round(cost_total, 6),
        "cost_usd_per_query": round(cost_total / max(1, len(cases)), 6),
        "_rows": rows,
    }


def main() -> int:
    eval_timeout = float(os.environ.get("AGENT_TIMEOUT_SECONDS", "30"))
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

    facts = FactsService(client)
    services = ToolServices(
        facts=facts, retriever=retriever, reports=ResearchReportSearch(client, cfg, retriever)
    )
    agent = AgentQaService(cfg, services, api_key=api_key, base_url=base_url)

    results = {}
    for name, fname in [("dev", "devset.json"), ("holdout", "holdout.json")]:
        cases = json.loads((EVAL_DIR / fname).read_text(encoding="utf-8"))["cases"]
        results[name] = _evaluate_set(name, cases, agent, facts)

    # 저장: 요약은 추적, rows(원문 조각)는 별도(gitignore)
    summaries = {k: {kk: vv for kk, vv in v.items() if kk != "_rows"} for k, v in results.items()}
    (EVAL_DIR / "eval_result.json").write_text(
        json.dumps(
            {"summaries": summaries, "cases": {k: v["_rows"] for k, v in results.items()}},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\n=== 요약 ===")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
