"""Phase 3: 의미검색 단독(Phase 2) vs 하이브리드(Phase 3) 비교 평가.

방법:
- 인덱싱된 뉴스 사건에서 평가 질문을 만든다.
  A) 자연어 질문 = 사건 제목 전체 (쉬운 표현 유지 확인)
  B) 정확명칭 질문 = 제목에서 뽑은 영문 약어/제품명/종목코드 등 키워드
- 각 질문에 대해 "그 사건(source_pk)"이 상위에 몇 위로 회수되는지(self-rank)를 두 방식으로 측정.
- 지표: recall@k(상위 top_k 안에 자기 사건 포함 비율), MRR(평균 역순위), 검색 시간.

결과를 backend/docs/rag/phase_3/eval_result.json 에 저장.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.db.client import get_supabase_client  # noqa: E402
from app.ml.embeddings import UpstageEmbedder  # noqa: E402
from app.rag.retrieval import HybridRetriever, SemanticRetriever  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_3"

# 영문 약어/제품명/숫자 토큰(정확명칭 질문 후보) 추출용
_EXACT_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]{2,}|[0-9]{4,}")

# 코퍼스 대비 document-frequency 가 이 비율을 넘는 토큰은 "변별력 없음"으로 제외.
# (특정 토큰 하드코딩이 아니라 데이터에서 계산되는 일반 임계값)
_MAX_DF_RATIO = 0.05


def _distinctive_tokens(
    title: str, stock_names: set[str], df_counter, total_docs: int
) -> list[str]:
    """제목에서 정확명칭 질문에 쓸 '변별력 있는' 토큰만 고른다.

    일반 규칙(특정 값 하드코딩 없음):
    - 정규식으로 영문(3자+)·긴 숫자 토큰 추출
    - 종목명에 포함된 조각(예: 회사명 일부)은 정확명칭이 아니므로 제외
    - 코퍼스 document-frequency 가 너무 높은(흔한) 토큰 제외
    """
    out = []
    for tok in _EXACT_TOKEN.findall(title):
        low = tok.lower()
        if any(low in name for name in stock_names):
            continue
        if df_counter.get(low, 0) / max(total_docs, 1) > _MAX_DF_RATIO:
            continue
        out.append(tok)
    return out


def _build_df_counter(db, titles: list[str]) -> tuple[dict, int]:
    """샘플 제목 토큰의 코퍼스 document-frequency 를 DB 로 계산한다."""
    from collections import Counter

    total = (
        db.table("rag_documents")
        .select("id", count="exact")
        .eq("source_type", "news_event")
        .eq("is_current", True)
        .execute()
    ).count or 1
    df: Counter = Counter()
    seen: set[str] = set()
    for title in titles:
        for tok in _EXACT_TOKEN.findall(title):
            low = tok.lower()
            if low in seen:
                continue
            seen.add(low)
            df[low] = (
                db.table("rag_chunks")
                .select("id", count="exact")
                .eq("is_active", True)
                .ilike("search_text", f"%{low}%")
                .execute()
            ).count or 0
    return df, total


def _sample_events(db, n: int, offset: int = 0) -> list[dict]:
    # offset>0 이면 최신 n개가 아닌 다른 구간을 뽑아 홀드아웃 검증에 쓴다.
    rows = (
        db.table("rag_documents")
        .select("source_pk,stock_code,title")
        .eq("source_type", "news_event")
        .eq("is_current", True)
        .order("published_at", desc=True)
        .range(offset, offset + n - 1)
        .execute()
    ).data or []
    return rows


def _self_rank(hits, source_pk: str) -> int | None:
    pks = [h.source_pk for h in hits]
    return pks.index(source_pk) + 1 if source_pk in pks else None


def _run(retriever, question: str, stock_code: str, source_pk: str, top_k: int):
    t = time.perf_counter()
    hits = retriever.search(question, stock_code=stock_code, source_type="news_event", top_k=top_k)
    ms = (time.perf_counter() - t) * 1000
    return _self_rank(hits, source_pk), ms


def _aggregate(ranks: list[int | None], top_k: int) -> dict:
    found = [r for r in ranks if r is not None]
    recall = len(found) / max(len(ranks), 1)
    mrr = sum(1.0 / r for r in found) / max(len(ranks), 1)
    return {"n": len(ranks), f"recall@{top_k}": round(recall, 3), "mrr": round(mrr, 3)}


def main() -> int:
    # usage: rag_phase3_eval.py [n] [offset] [out_name]
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    offset = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    out_name = sys.argv[3] if len(sys.argv) > 3 else "eval_result.json"
    top_k = 8
    db = get_supabase_client()
    emb = UpstageEmbedder(settings)
    sem = SemanticRetriever(db, settings, emb)
    hyb = HybridRetriever(db, settings, emb)

    events = _sample_events(db, n, offset)

    # 종목명(하드코딩 아님, stocks 테이블에서 로드) — 회사명 조각을 정확명칭에서 제외하는 데 사용
    stock_names = {
        (r.get("name") or "").lower()
        for r in (db.table("stocks").select("name").execute().data or [])
        if r.get("name")
    }
    titles = [e.get("title") or "" for e in events]
    df_counter, total_docs = _build_df_counter(db, titles)

    cases = []  # (kind, question, stock_code, source_pk)
    for e in events:
        title = e.get("title") or ""
        spk = e["source_pk"]
        code = e.get("stock_code")
        cases.append(("nl_title", title, code, spk))
        tokens = _distinctive_tokens(title, stock_names, df_counter, total_docs)
        if tokens:
            # 정확명칭 질문: 변별력 있는 대표 토큰 1~2개 (영문약어/제품명/숫자)
            cases.append(("exact_token", " ".join(tokens[:2]), code, spk))

    report: dict = {"top_k": top_k, "num_events": len(events), "num_cases": len(cases)}
    detail = []
    sem_ranks_by_kind: dict[str, list] = {}
    hyb_ranks_by_kind: dict[str, list] = {}
    sem_ms, hyb_ms = [], []

    for kind, q, code, spk in cases:
        sr, sms = _run(sem, q, code, spk, top_k)
        hr, hms = _run(hyb, q, code, spk, top_k)
        sem_ms.append(sms)
        hyb_ms.append(hms)
        sem_ranks_by_kind.setdefault(kind, []).append(sr)
        hyb_ranks_by_kind.setdefault(kind, []).append(hr)
        detail.append({"kind": kind, "q": q[:60], "stock": code, "sem_rank": sr, "hyb_rank": hr})

    report["semantic"] = {kind: _aggregate(rs, top_k) for kind, rs in sem_ranks_by_kind.items()}
    report["hybrid"] = {kind: _aggregate(rs, top_k) for kind, rs in hyb_ranks_by_kind.items()}
    report["latency_ms"] = {
        "semantic_avg": round(sum(sem_ms) / max(len(sem_ms), 1)),
        "hybrid_avg": round(sum(hyb_ms) / max(len(hyb_ms), 1)),
    }
    # 개선/악화 사례
    improved = [d for d in detail if _better(d["hyb_rank"], d["sem_rank"])]
    worsened = [d for d in detail if _better(d["sem_rank"], d["hyb_rank"])]
    report["improved_count"] = len(improved)
    report["worsened_count"] = len(worsened)
    report["improved_examples"] = improved[:8]
    report["worsened_examples"] = worsened[:8]

    report["offset"] = offset
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / out_name).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("semantic", "hybrid", "latency_ms", "improved_count", "worsened_count")
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _better(a: int | None, b: int | None) -> bool:
    """a 가 b 보다 나은 순위인가(작을수록 좋음, None 은 최악)."""
    if a is None:
        return False
    if b is None:
        return True
    return a < b


if __name__ == "__main__":
    raise SystemExit(main())
