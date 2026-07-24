"""Phase 5: search_research_reports 검색 품질 검증 (read-only, 실제 임베딩 API 호출).

질문 유형: 정확명칭 / 자연어 / 전망 / 목표주가 / 실적 원인.
평가셋은 특정 질문 하드코딩 없이 DB 의 실제 리포트 메타(제목·증권사·발행일)에서 생성한다.
정답 = 해당 종목의 리포트가 상위 K 안에 들어오는지(Recall@K) + 출처 페이지 유효성.

실행:  uv run --with pymupdf python scripts/phase5_eval_report_search.py
       (fitz 불필요하지만 embedder/네트워크만 사용)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.db.client import get_supabase_client  # noqa: E402
from app.ml.embeddings import UpstageEmbedder  # noqa: E402
from app.rag.retrieval import HybridRetriever  # noqa: E402
from app.services.research_reports import ResearchReportSearch  # noqa: E402

TOP_K = 8


def main() -> int:
    client = get_supabase_client()
    embedder = UpstageEmbedder(settings)
    retriever = HybridRetriever(client, settings, embedder)
    svc = ResearchReportSearch(client, settings, retriever)

    # 종목 코드→이름
    names = {
        r["code"]: r["name"] for r in client.table("stocks").select("code,name").execute().data
    }

    # 5개 유형 질문(종목명은 DB 에서, 문형은 유형별 템플릿 — 특정 리포트 문장 하드코딩 아님)
    cases = []
    for code, name in names.items():
        cases += [
            ("정확명칭", code, name, f"{name} 목표주가"),
            ("자연어", code, name, f"{name} 요즘 실적 어때"),
            ("전망", code, name, f"{name} 향후 실적 전망"),
            ("목표주가", code, name, f"{name} 목표주가 상향 근거"),
            ("실적원인", code, name, f"{name} 영업이익 변화 원인"),
        ]

    by_type: dict[str, dict] = {}
    problems: list[str] = []
    for qtype, code, name, q in cases:
        hits = svc.search(q, stock_code=code, top_k=TOP_K)
        t = by_type.setdefault(qtype, {"n": 0, "hit": 0, "page_ok": 0, "hits_total": 0})
        t["n"] += 1
        # Recall: 상위 K 에 해당 종목 리포트가 있는가
        same_stock = [h for h in hits if h.stock_code == code]
        if same_stock:
            t["hit"] += 1
        t["hits_total"] += len(hits)
        # 출처 페이지 유효성: page_number 존재 + (source_page or pdf_page) 존재
        for h in same_stock:
            if h.page_number and (h.source_page is not None or h.pdf_page is not None):
                t["page_ok"] += 1
        # 문제 사례: 다른 종목이 섞였거나(필터 실패), 결과 0
        wrong = [h for h in hits if h.stock_code != code]
        if wrong:
            problems.append(f"[{qtype}] '{q}' → 타종목 혼입 {len(wrong)}건")
        if not hits:
            problems.append(f"[{qtype}] '{q}' → 결과 0")

    print(f"=== 유형별 Recall@{TOP_K} ===")
    for qtype, t in by_type.items():
        recall = t["hit"] / max(1, t["n"])
        avg_hits = t["hits_total"] / max(1, t["n"])
        print(
            f"  {qtype}: Recall {t['hit']}/{t['n']} ({recall:.0%}) "
            f"평균결과 {avg_hits:.1f} 출처페이지유효 {t['page_ok']}"
        )

    # 대표 결과 3개 상세(전망값 표기 확인)
    print("\n=== 대표 결과(전망/실적 value_kind 노출 확인) ===")
    sample_code = next(iter(names))
    for h in svc.search(f"{names[sample_code]} 향후 실적 전망", stock_code=sample_code, top_k=3):
        print(
            f"  [{h.broker}|{h.report_date}] {(h.title or '')[:30]} "
            f"p{h.page_number}(src={h.source_page},pdf={h.pdf_page}) "
            f"표vk={h.table_value_kinds} sim={h.similarity:.3f}"
        )

    print("\n=== 문제 사례 ===")
    if not problems:
        print("  없음")
    for p in problems[:20]:
        print("  " + p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
