"""Phase 4 소량 검증: 필수 시험 질문으로 숫자·용어·혼합·정정·설명 흐름 확인.

특정 종목/항목 하드코딩 없이, 조사에서 확인된 실제 데이터로 질문을 만든다.
결과를 backend/docs/rag/phase_4/trial_result.json 에 저장한다.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.db.client import get_supabase_client  # noqa: E402
from app.ml.embeddings import UpstageEmbedder  # noqa: E402
from app.ml.generation import SolarGenerator  # noqa: E402
from app.rag.retrieval import HybridRetriever  # noqa: E402
from app.services.facts import FactsService  # noqa: E402
from app.services.rag_qa_facts import FactsQaService  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_4"

# 필수 시험 질문(SPEC/계획서). 종목코드는 조사에서 확인된 대상 종목을 파라미터로 전달.
CASES = [
    {"q": "영업이익이 얼마야?", "stock": "005930"},
    {"q": "영업이익이 얼마고 왜 늘었어?", "stock": "005930"},
    {"q": "ADR이 뭐야?", "stock": None},
    {"q": "정정 전과 정정 후 뭐가 바뀌었어?", "stock": "000660"},
    {"q": "이 공시가 왜 중요해?", "stock": "000660"},
    {"q": "없는 회사 재무 알려줘", "stock": None},  # 근거 부족 응답 테스트
]


def main() -> int:
    db = get_supabase_client()
    emb = UpstageEmbedder(settings)
    svc = FactsQaService(
        HybridRetriever(db, settings, emb),
        FactsService(db),
        SolarGenerator(settings),
        settings,
    )

    results = []
    for c in CASES:
        t = time.perf_counter()
        r = svc.answer(c["q"], stock_code=c["stock"])
        ms = round((time.perf_counter() - t) * 1000)
        results.append(
            {
                "question": c["q"],
                "stock": c["stock"],
                "plan": r.plan,
                "num_numeric_sources": len(r.numeric_sources),
                "numeric_preview": r.numeric_sources[:2],
                "term": r.term["term"] if r.term else None,
                "num_doc_sources": len(r.sources),
                "invalid_citations": r.invalid_citations,
                "latency_ms": r.latency_ms,
                "answer_preview": r.answer[:300],
                "total_ms": ms,
            }
        )
        print(
            f"Q: {c['q']}\n"
            f"  plan={r.plan}\n"
            f"  numeric={len(r.numeric_sources)} term={r.term['term'] if r.term else None} "
            f"docs={len(r.sources)} invalid={r.invalid_citations}\n"
            f"  A: {r.answer[:120].replace(chr(10), ' ')}\n"
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "trial_result.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
