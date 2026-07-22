# Phase 2. 뉴스 기반 최소 RAG (기준 문서)

뉴스 사건 데이터만으로 질문→검색→답변→출처 흐름을 구현한 기준을 정의한다.

## 1. 데이터 흐름

```
활성 뉴스 사건(news_clusters)
  → 정규화(normalization) → 청킹(chunking) → passage 임베딩(Upstage Embed 2)
  → rag_documents / rag_chunks 저장
질문 → query 임베딩 → 의미 검색(rag_search_semantic, pgvector cosine)
  → 현재 문맥 우선 → 프롬프트 → Solar 답변(+스트리밍) → 출처 + 인용 검증
```

## 2. 인덱싱 대상 / 조건 (SPEC §8.2)

- `news_clusters.clustering_version == active_version`(현재 `v2_event_role_20260721`)
- `summary_status = 'success'` + `factual_body` 존재 + `stock_code` 존재
- 활성 사건 총 2,940건 (2026-07-22 기준)
- 청크 = `summary_title + easy_explanation + factual_body` 결합
  - 1,200자 이하 = 1청크, 초과 시 500~900자로 분할(overlap ≤100자), 사건당 최대 3청크
- **대표 기사 원문은 기본 검색에서 제외** (사건 통합 본문만 인덱싱)

## 3. 임베딩 (SPEC §5)

- 문서: `solar-embedding-2-passage`, 질문: `solar-embedding-2-query`, **1024차원**
- 배치 최대 100, 429/5xx 지수 백오프
- **해시 기반 중복 방지**: 문서 `content_hash`가 기존 current와 같으면 재임베딩/재저장 skip

## 4. 검색 (Phase 2 = 의미 검색만)

- RPC `rag_search_semantic(query_embedding, match_count, filter_stock_code, filter_source_type)`
  - `is_active=true` + `is_current=true` 청크만, cosine 유사도 상위
- 후보 24개 → 현재 문맥(`context_source_id`) 우선 정렬 → 최종 top-8
- 하이브리드(키워드+RRF)는 Phase 3 범위

## 5. 답변 (계획서 Phase 2 형식)

- 형식: `## 한 줄 결론 / ## 쉽게 설명하면 / ## 자세히 보면 / ## 핵심 숫자 / ## 주의할 점`
- 쉬운/자세한 설명을 한 번의 Solar 호출에서 생성, temperature 0.0
- 문맥 청크에 [1]…[n], 답변은 그 번호만 인용 → 범위 밖 번호는 `invalid_citations`로 검출
- 인과 단정 금지("때문에" 금지, "발표 이후" 허용), 매수/매도 직접 추천 금지

## 6. API

- `POST /api/qa` — 비스트리밍, `QaResponse{answer, sources, invalid_citations, latency_ms}`
- `POST /api/qa/stream` — SSE: `sources`(1회) → `token`(다수) → `done{invalid_citations}`
- 요청: `QaRequest{question, stock_code?, context_source_id?, context_source_type?, stream}`

## 7. 코드 위치

| 역할 | 파일 |
|---|---|
| 정규화 | `app/rag/normalization.py` |
| 청킹 | `app/rag/chunking.py` |
| 임베딩 | `app/ml/embeddings.py` |
| 인덱싱 | `app/rag/indexing.py` |
| 검색 | `app/rag/retrieval.py` + `migrations/0016_rag_search_semantic.sql` |
| 프롬프트 | `app/rag/prompting.py` |
| 생성 | `app/ml/generation.py` |
| QA 서비스 | `app/services/rag_qa.py` |
| API | `app/api/routes/qa.py`, `app/schemas/qa.py` |
| 시험 스크립트 | `scripts/rag_phase2_trial.py` |
