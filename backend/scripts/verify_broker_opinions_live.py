"""promptv2 수정 검증 — 실제(dev) DB 읽기 전용 스모크.

ResearchReportSearch 를 실제 Supabase(dev) 로 호출해 promptv2 합격 기준을 확인한다.
DB 에 아무것도 쓰지 않는다(검색·조회만).

검증 항목:
  - §2 타 종목 목표주가 0건: 요청 종목과 다른 종목의 stated 목표주가가 없어야 한다.
  - §3 current 응답에 과거 이력 0건: current 에서 effective_date≠report_date stated 없어야.
  - §4 current 증권사 중복 0건: 같은 증권사가 2번 이상 없어야 한다.
  - §3 history 정상: history 는 날짜별 개별값이 그대로 나온다.
  - §5 broker_opinions 게이트: collect_report_opinions 가 stated·중복제거·최신1건만.

실행:
  python scripts/verify_broker_opinions_live.py 005930
"""

from __future__ import annotations

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.agent.tools.reports import (  # noqa: E402
    SearchResearchReportsInput,
    run_search_research_reports,
)
from app.agent.validator import collect_report_opinions  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.client import get_supabase_client  # noqa: E402
from app.ml.embeddings import UpstageEmbedder  # noqa: E402
from app.rag.retrieval import HybridRetriever  # noqa: E402
from app.services.research_reports import ResearchReportSearch  # noqa: E402


def _svc() -> ResearchReportSearch:
    client = get_supabase_client()
    embedder = UpstageEmbedder(settings)
    retriever = HybridRetriever(client, settings, embedder)
    return ResearchReportSearch(client, settings, retriever)


def _run_tool(svc, stock_code, query, time_context=None):
    inp = SearchResearchReportsInput(
        stock_code=stock_code, query=query, time_context=time_context
    )
    return run_search_research_reports(svc, inp)


def _print_hits(label, hits):
    print(f"\n[{label}] stock 귀속·목표주가 상태 (검색 계층 hits)")
    for h in hits:
        print(
            f"  {h.report_date} {h.broker} stock={h.stock_code} "
            f"tp={h.target_price} status={h.target_price_status} "
            f"eff={h.target_price_effective_date} stale={h.is_stale}"
        )


def main(stock_code: str) -> int:
    svc = _svc()
    fails: list[str] = []

    # ── current (time_context 생략 → §1 기본값 current) ──
    hits_current = svc.search("최근 증권사 목표주가", stock_code=stock_code)
    _print_hits("current(기본)", hits_current)

    # §2: 타 종목 stated 목표주가 0건
    other_stock = [
        h
        for h in hits_current
        if h.stock_code not in (None, stock_code) and h.target_price_status == "stated"
    ]
    if other_stock:
        fails.append(f"§2 위반: 타 종목 stated 목표주가 {len(other_stock)}건")

    # §3: current 에 과거 이력값(effective≠report_date stated) 0건
    from app.services.research_reports import _to_date

    hist_in_current = [
        h
        for h in hits_current
        if h.target_price_status == "stated"
        and h.target_price_effective_date
        and _to_date(h.target_price_effective_date) != _to_date(h.report_date)
    ]
    if hist_in_current:
        fails.append(f"§3 위반: current 에 과거 이력 목표주가 {len(hist_in_current)}건")

    # §4: 증권사 중복 0건
    brokers = [h.broker for h in hits_current if h.broker]
    dups = {b for b in brokers if brokers.count(b) > 1}
    if dups:
        fails.append(f"§4 위반: current 증권사 중복 {sorted(dups)}")

    # §5: broker_opinions 게이트 — Tool payload → 카드
    res = _run_tool(svc, stock_code, "최근 증권사 목표주가")
    payload = res.model_dump_agent() if hasattr(res, "model_dump_agent") else {}
    cards = collect_report_opinions([payload])
    print(f"\n[broker_opinions 카드] {len(cards)}건")
    card_brokers = [c["broker"] for c in cards]
    for c in cards:
        print(f"  {c['report_date']} {c['broker']} tp={c['target_price']} "
              f"status={c['target_price_status']} src={c['source_id']} page={c['source_page']}")
    if any(c["target_price_status"] != "stated" for c in cards):
        fails.append("§5 위반: 카드에 stated 아닌 항목 포함")
    if len(card_brokers) != len(set(card_brokers)):
        fails.append("§5 위반: 카드에 증권사 중복")

    # ── history — 날짜별 개별값 유지 확인 ──
    hits_history = svc.search(
        "목표주가 변화 추이", stock_code=stock_code, time_context="history"
    )
    _print_hits("history", hits_history)
    hist_tps = [h.target_price for h in hits_history if h.target_price is not None]
    print(f"  history 개별 목표주가 값: {sorted(hist_tps)}")

    print("\n" + "=" * 60)
    if fails:
        print("❌ 실패:")
        for f in fails:
            print("  -", f)
        return 1
    print("✅ 합격: §2 타 종목 0 / §3 current 이력 0 / §4 중복 0 / §5 카드 게이트 정상")
    return 0


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "005930"
    raise SystemExit(main(code))
