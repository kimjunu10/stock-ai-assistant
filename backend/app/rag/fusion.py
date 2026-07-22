"""Reciprocal Rank Fusion (RRF) — SPEC §10.3.

실제 하이브리드 검색의 RRF 결합은 SQL RPC(rag_search_hybrid)에서 수행한다.
이 모듈은 동일한 공식의 파이썬 참조 구현으로, 오프라인 재랭킹·테스트·문서화에 쓴다.

    rrf_score(d) = Σ_r  weight_r / (rrf_k + rank_r(d))

cosine 점수와 trigram 점수를 직접 더하지 않는다(순위 기반 결합).
"""

from __future__ import annotations


def rrf_fuse(
    semantic_ids: list[str],
    lexical_ids: list[str],
    *,
    rrf_k: int = 50,
    semantic_weight: float = 1.0,
    lexical_weight: float = 1.0,
) -> list[tuple[str, float]]:
    """두 순위 리스트(각 검색 결과의 id 순서)를 RRF 로 결합한다.

    입력은 이미 각 방식의 점수 내림차순으로 정렬된 id 리스트(0-based index = rank-1).
    반환: (id, rrf_score) 리스트, rrf_score 내림차순.
    """

    scores: dict[str, float] = {}
    for rank, cid in enumerate(semantic_ids, start=1):
        scores[cid] = scores.get(cid, 0.0) + semantic_weight / (rrf_k + rank)
    for rank, cid in enumerate(lexical_ids, start=1):
        scores[cid] = scores.get(cid, 0.0) + lexical_weight / (rrf_k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
