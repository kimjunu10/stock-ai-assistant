"""Phase 8 §10: 평가 실행기 dry-run (실제 LLM·DB 호출, read-only).

목적은 실행기 검증이지 최종 성능 발표가 아니다. 각 주요 유형에서 1문항씩,
최대 10문항만 실행한다. 전체 160문항 운영 평가는 이 단계에서 하지 않는다.

/qa 기준(AgentQaService.answer)으로 실행하고, SSE 계약은 대표 시나리오 1건만 확인한다.

실행:
    cd backend
    AGENT_ENABLED=true .venv/bin/python scripts/phase8_dryrun.py
    .venv/bin/python scripts/phase8_dryrun.py --limit 3   # 더 적게
산출: docs/rag/phase_8/eval/dryrun_result.json, human_review_rater{1,2}.csv
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("AGENT_ENABLED", "true")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings  # noqa: E402
from app.eval.grader import aggregate, grade_case  # noqa: E402
from app.eval.human_form import build_form_csv  # noqa: E402
from app.eval.recorder import ToolCallRecorder  # noqa: E402
from app.eval.runner import EvalRunner  # noqa: E402
from app.eval.schema import EvalSuite  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_8" / "eval"

# dry-run 대상 유형(각 1문항). 답변 불가·화면 문맥은 회귀 위험이 커서 반드시 포함한다.
DRYRUN_TYPES = [
    "금융용어",
    "정확한 재무 숫자",
    "뉴스 사건·영향",
    "공시 설명·구조화 값",
    "증권사 리포트",
    "복수 기능 혼합",
    "부정·제외·대조",
    "현재 화면 문맥",
    "답변 불가능·모호",
]


def build_agent(cfg: Settings, recorder: ToolCallRecorder):
    """운영과 동일한 서비스 조립 + 평가용 recorder 만 추가한다.

    운영 코드는 수정하지 않는다. 반환: (AgentQaService, FactsService).
    FactsService 는 재무 정답을 DB 에서 재조회하는 채점에 쓴다.
    """
    from app.agent.context import ToolServices
    from app.db.client import get_supabase_client
    from app.ml.embeddings import UpstageEmbedder
    from app.rag.retrieval import HybridRetriever
    from app.services.agent_qa import AgentQaService
    from app.services.facts import FactsService
    from app.services.research_reports import ResearchReportSearch

    api_key, base_url = cfg.agent_model_credentials()
    if not api_key:
        raise SystemExit(f"{cfg.agent_chat_provider} API 키 없음 — dry-run 불가")

    client = get_supabase_client()
    embedder = UpstageEmbedder(cfg)
    retriever = HybridRetriever(client, cfg, embedder)
    prices = None
    if cfg.toss_client_id and cfg.toss_client_secret:
        from app.api.routes.stocks import get_toss_client
        from app.services.stock_prices import StockPriceService

        prices = StockPriceService(
            get_toss_client(),
            cache_seconds=cfg.stock_price_cache_seconds,
            rate_limit_retries=cfg.stock_price_rate_limit_retries,
            rate_limit_backoff_seconds=cfg.stock_price_rate_limit_backoff_seconds,
            max_candle_pages=cfg.stock_price_max_candle_pages,
        )
    services = ToolServices(
        facts=FactsService(client),
        retriever=retriever,
        reports=ResearchReportSearch(client, cfg, retriever),
        prices=prices,
    )
    svc = AgentQaService(cfg, services, api_key=api_key, base_url=base_url)
    # 평가용 관찰자를 얹은 Agent 로 교체한다(운영 파일은 그대로 둔다).
    svc._agent = _attach_recorder(cfg, api_key, base_url, recorder)
    # 재무 정답을 DB 에서 재조회할 때 쓴다(정답 숫자를 라벨에 적어두지 않는다).
    return svc, services.facts


def _attach_recorder(cfg: Settings, api_key: str, base_url: str, recorder: ToolCallRecorder):
    """운영 build_agent 를 그대로 쓰되 recorder middleware 만 끼운 Agent 를 만든다.

    미들웨어 구성을 여기에 복제하면 운영이 바뀔 때 조용히 어긋나(모델 재시도·호출 상한
    설정이 달라져) dry-run 이 실제 동작을 반영하지 못한다. 그래서 create_agent 를
    한 번 감싸 middleware 목록에 recorder 만 추가한다.
    """
    from app.agent import runtime as rt

    real_create_agent = rt.create_agent

    def _patched(*a, **kw):
        mw = list(kw.get("middleware") or [])
        # 프롬프트 미들웨어 바로 뒤에 두어 Tool 호출을 모두 관찰한다.
        mw.insert(1, recorder)
        kw["middleware"] = mw
        return real_create_agent(*a, **kw)

    rt.create_agent = _patched
    try:
        return rt.build_agent(cfg, api_key=api_key, base_url=base_url)
    finally:
        rt.create_agent = real_create_agent


def check_sse_contract(question: str, stock_code: str | None) -> dict:
    """대표 시나리오 1건으로 /qa/stream 이벤트 순서를 확인한다(§7)."""
    from fastapi.testclient import TestClient

    from app.main import app

    events: list[str] = []
    body: dict = {"question": question}
    if stock_code:
        body["stock_code"] = stock_code
    with TestClient(app) as client, client.stream("POST", "/api/qa/stream", json=body) as resp:
        if resp.status_code != 200:
            return {"ok": False, "status_code": resp.status_code, "events": []}
        for line in resp.iter_lines():
            if line and line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
    required = {"agent_start", "delta", "done"}
    return {
        "ok": required.issubset(set(events)),
        "events": events,
        "missing": sorted(required - set(events)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10, help="최대 실행 문항 수")
    ap.add_argument("--skip-sse", action="store_true")
    args = ap.parse_args()

    suite = EvalSuite.model_validate(json.loads((EVAL_DIR / "devset.json").read_text("utf-8")))
    # 유형별 1문항씩(개발셋에서만 뽑는다 — 홀드아웃은 최종 평가 전까지 쓰지 않는다).
    picked = []
    for t in DRYRUN_TYPES:
        for c in suite.cases:
            if c.type == t:
                picked.append(c)
                break
    picked = picked[: args.limit]
    print(f"dry-run 대상 {len(picked)}문항 (개발셋에서만 선정, 홀드아웃 미사용)")

    cfg = Settings(agent_enabled=True, agent_timeout_seconds=45.0)
    recorder = ToolCallRecorder()
    agent, facts = build_agent(cfg, recorder)
    runner = EvalRunner(agent, recorder)

    records = []
    grades = []
    for c in picked:
        rec = runner.run(c)
        g = grade_case(c, rec, facts)
        records.append(rec)
        grades.append(g)
        tools = "→".join(rec.tool_sequence) or "(없음)"
        print(
            f"[{c.id:12}] {c.type:14} tools={tools} {rec.total_latency_ms}ms "
            f"stop={rec.stop_reason} 검증오류={len(rec.validation_errors)}"
        )

    agg = aggregate(picked, records, grades)

    sse = {}
    if not args.skip_sse:
        rep = next((c for c in picked if c.type == "복수 기능 혼합"), picked[0])
        sse = check_sse_contract(rep.question, rep.stock_code or rep.context.stock_code)
        sse["case_id"] = rep.id
        print(f"SSE 계약({rep.id}): ok={sse['ok']} events={sse['events'][:8]}")

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL_DIR / "dryrun_result.json").write_text(
        json.dumps(
            {
                "note": "실행기 검증용 dry-run. 최종 성능 수치가 아니다(문항 수 적음).",
                "n": len(picked),
                "metrics": agg,
                "sse_contract": sse,
                "records": [r.as_dict() for r in records],
                "grades": [g.as_dict() for g in grades],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # 사람 평가 양식(평가자 2명 독립 기록)
    rows = [
        {
            "case_id": r.case_id,
            "type": c.type,
            "question": r.question,
            "answer": r.answer,
            "sources": ", ".join(str(s.get("source_id", "")) for s in r.sources),
            "gold_basis": c.label_basis,
        }
        for c, r in zip(picked, records, strict=True)
    ]
    for rater in ("rater1", "rater2"):
        (EVAL_DIR / f"human_review_{rater}.csv").write_text(
            build_form_csv(rows, rater), encoding="utf-8"
        )

    print("\n=== 지표 요약 ===")
    print(json.dumps(agg, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
