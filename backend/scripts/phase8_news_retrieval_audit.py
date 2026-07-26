"""Phase 8 뉴스 검색 실패 감사: search_news Retriever 단독 재현(읽기 전용, LLM 미호출).

8개 실패 문항(search_news 를 실제로 호출한 케이스)에 대해 저장된 final-dev
실행과 동일한 검색어·필터로 rag_search_hybrid RPC 를 직접 호출해, gold
뉴스 클러스터가 semantic/lexical/RRF 각 단계에서 어느 순위에 있는지 관찰한다.

임베딩 API(Upstage)는 호출한다(검색어를 벡터로 바꿔야 재현 가능) — 대화형
LLM 은 호출하지 않는다. 운영 데이터는 SELECT 만 하고 수정하지 않는다.
운영 top_k/RRF 가중치는 그대로 쓰되, 관찰 목적으로 semantic/lexical 후보
풀만 넉넉히 키워 gold 가 후보에 있는지 자체를 보는 것이 목적이다(제품
설정을 바꾸는 것이 아니라 진단용 별도 호출).

실행:
    cd backend
    .venv/bin/python scripts/phase8_news_retrieval_audit.py
산출: docs/rag/phase_8/eval/news_retrieval_audit.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings  # noqa: E402
from app.db.client import get_supabase_client  # noqa: E402
from app.ml.embeddings import UpstageEmbedder  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_8" / "eval"

# 저장된 final-dev 실행에서 실제로 search_news 를 호출한 8문항의 검색어·필터.
# (news-11 은 search_news 자체를 호출하지 않아 Retriever 재현 대상이 아니다.)
TARGETS = [
    {
        "id": "news-04",
        "gold_cluster_id": "6888",
        "stock_code": "034020",
        "query": "미국 원전 수주",
        "relative_period": "recent",
    },
    {
        "id": "news-09",
        "gold_cluster_id": "6858",
        "stock_code": "034020",
        "query": "중부발전",
        "relative_period": "recent",
    },
    {
        # 최종 호출(두 번째)만 재현: 첫 호출은 실패 후 모델이 쿼리를 좁혀 재시도했다.
        "id": "news-10",
        "gold_cluster_id": "6974",
        "stock_code": "042660",
        "query": "레이도스 깁스 앤 건",
        "relative_period": "recent",
    },
    {
        "id": "news-13",
        "gold_cluster_id": "7182",
        "stock_code": "005930",
        "query": "구글 AI 협업",
        "relative_period": "recent",
    },
    {
        # query 없이 relative_period 만 있음 → list_recent_news 경로(임베딩 미사용).
        "id": "news-14",
        "gold_cluster_id": "6972",
        "stock_code": "042660",
        "query": "",
        "relative_period": "recent",
    },
    {
        "id": "news-15",
        "gold_cluster_id": "7159",
        "stock_code": "000660",
        "query": "SK",
        "relative_period": None,
    },
    {
        "id": "news-18",
        "gold_cluster_id": "6944",
        "stock_code": "042660",
        "query": "한미 조선협력센터 워싱턴",
        "relative_period": "recent",
    },
    {
        "id": "news-19",
        "gold_cluster_id": "7117",
        "stock_code": "000660",
        "query": "최태원",
        "relative_period": None,
    },
]

# 진단용 후보 풀(운영 top_k 는 변경하지 않는다 — 이건 별도 관찰 호출의 파라미터).
DIAG_SEMANTIC_CANDIDATES = 200
DIAG_LEXICAL_CANDIDATES = 200
DIAG_MATCH_COUNT = 200


def _date_range_for_recent(cfg: Settings) -> tuple[str | None, str | None]:
    """relative_period='recent' 가 실제로 어떤 날짜 범위로 풀리는지 그대로 재사용.

    참조일은 baseline_dev_records_final.json 파일의 최종 수정 시각(2026-07-27
    00:49, 120문항 실행 완료 시점)을 기준으로 한다 — 실행 시작 시각은 저장돼
    있지 않지만, 같은 날짜(07-27) 안에서는 recent 범위 계산 결과가 동일하다.
    """
    from datetime import date

    from app.agent.time_context import resolve_relative_date_range
    from app.rag.retrieval import _inclusive_end

    start, end = resolve_relative_date_range("recent", reference_date=date(2026, 7, 27))
    return start, _inclusive_end(end)


def audit_one(db, embedder, cfg: Settings, target: dict) -> dict:
    cluster_id = target["gold_cluster_id"]
    query = target["query"]
    date_from = date_to = None
    if target["relative_period"] == "recent":
        date_from, date_to = _date_range_for_recent(cfg)

    result: dict = {
        "id": target["id"],
        "gold_cluster_id": cluster_id,
        "query": query,
        "stock_code": target["stock_code"],
        "date_from": date_from,
        "date_to": date_to,
    }

    if not query.strip():
        result["note"] = "query 없음 — list_recent_news 경로(임베딩 미사용), RPC 감사 대상 아님"
        return result

    query_vec = embedder.embed_query(query)
    resp = db.rpc(
        "rag_search_hybrid",
        {
            "query_embedding": query_vec,
            "query_text": query.lower(),
            "match_count": DIAG_MATCH_COUNT,
            "semantic_candidates": DIAG_SEMANTIC_CANDIDATES,
            "lexical_candidates": DIAG_LEXICAL_CANDIDATES,
            "rrf_k": cfg.rag_rrf_k,
            "filter_stock_code": target["stock_code"],
            "filter_source_type": "news_event",
            "filter_from": date_from,
            "filter_to": date_to,
            "filter_value_kind": None,
        },
    ).execute()
    rows = resp.data or []

    # 운영 실제 top_k 로 잘랐을 때의 결과(비교용, 코드 그대로 재현).
    prod_top_k = cfg.rag_retrieval_top_k
    prod_rows = sorted(rows, key=lambda r: -(r.get("rrf_score") or 0))[:prod_top_k]
    prod_cluster_ids = [r["doc_source_pk"] for r in prod_rows]

    # gold 클러스터가 RRF 결합 후보 전체(진단 풀) 안 어디에 있는지.
    rrf_ranked = sorted(rows, key=lambda r: -(r.get("rrf_score") or 0))
    rrf_rank = next(
        (i + 1 for i, r in enumerate(rrf_ranked) if r["doc_source_pk"] == cluster_id), None
    )

    # semantic 단독 순위(유사도 내림차순), lexical 단독 순위(word_similarity 내림차순).
    sem_ranked = sorted(
        [r for r in rows if r.get("similarity") is not None], key=lambda r: -r["similarity"]
    )
    sem_rank = next(
        (i + 1 for i, r in enumerate(sem_ranked) if r["doc_source_pk"] == cluster_id), None
    )
    lex_ranked = sorted(
        [r for r in rows if r.get("lexical_similarity") is not None],
        key=lambda r: -r["lexical_similarity"],
    )
    lex_rank = next(
        (i + 1 for i, r in enumerate(lex_ranked) if r["doc_source_pk"] == cluster_id), None
    )

    gold_row = next((r for r in rows if r["doc_source_pk"] == cluster_id), None)

    result.update(
        {
            "candidates_returned": len(rows),
            "gold_in_semantic_candidates": sem_rank is not None,
            "gold_semantic_rank": sem_rank,
            "gold_in_lexical_candidates": lex_rank is not None,
            "gold_lexical_rank": lex_rank,
            "gold_in_rrf_fused": rrf_rank is not None,
            "gold_rrf_rank": rrf_rank,
            "gold_similarity": gold_row.get("similarity") if gold_row else None,
            "gold_lexical_similarity": gold_row.get("lexical_similarity") if gold_row else None,
            "gold_rrf_score": gold_row.get("rrf_score") if gold_row else None,
            "gold_in_final_prod_topk": cluster_id in prod_cluster_ids,
            "prod_top_k": prod_top_k,
            "final_prod_cluster_ids_in_order": prod_cluster_ids,
            "top10_rrf_cluster_ids": [r["doc_source_pk"] for r in rrf_ranked[:10]],
        }
    )
    return result


def main() -> int:
    cfg = Settings()
    db = get_supabase_client()
    embedder = UpstageEmbedder(cfg)

    results = []
    for target in TARGETS:
        r = audit_one(db, embedder, cfg, target)
        results.append(r)
        print(f"=== {r['id']} (gold cluster {r['gold_cluster_id']}) ===")
        if "note" in r:
            print(" ", r["note"])
        else:
            print(f"  semantic_rank={r['gold_semantic_rank']} (sim={r['gold_similarity']})")
            lex_sim = r["gold_lexical_similarity"]
            print(f"  lexical_rank={r['gold_lexical_rank']} (lex_sim={lex_sim})")
            print(f"  rrf_rank={r['gold_rrf_rank']} (rrf={r['gold_rrf_score']})")
            print(f"  in_final_top{r['prod_top_k']}={r['gold_in_final_prod_topk']}")
        print()

    (EVAL_DIR / "news_retrieval_audit.json").write_text(
        json.dumps({"targets": results}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
