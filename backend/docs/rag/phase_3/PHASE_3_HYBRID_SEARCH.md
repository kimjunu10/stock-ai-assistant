# Phase 3. 하이브리드 검색 (기준 문서)

의미 검색 + 정확 키워드 검색을 RRF로 결합한 하이브리드 검색 기준을 정의한다 (SPEC §10).

## 1. 구성

```
질문 → query 임베딩(의미) + query text(키워드)
  → rag_search_hybrid RPC
       ├ semantic: pgvector cosine 순위 (후보 24)
       └ lexical : pg_trgm 순위 (후보 24)  — word_similarity + ILIKE 부분일치
  → RRF 순위 결합 (rrf_k=50, 가중치 1:1)
  → 현재 문서 우선(있으면) → 중복 제거 → 부모 문맥 확장 → 최종 top-8
```

## 2. 키워드 검색 (SPEC §10.2)

- 한국어 형태소기 미설치. pg_trgm 사용.
- 전체 `similarity(%)`는 긴 문서·짧은 쿼리에서 threshold 미달이라 **`word_similarity(<%)` + `ILIKE` 부분일치**로 후보를 잡는다.
- lexical 순위(0018): **정확 부분일치(ILIKE) 우선 → word_similarity** 2단계. 쿼리 문자열을 그대로 포함하는 청크를 먼저 둔다.
- 영문 약어(HBM, CEO), 종목코드(005930), 숫자, 제품명 부분일치를 잡는다.
- `search_text`는 인덱싱 시 소문자화되어 있어 쿼리도 소문자로 던진다.

## 3. RRF (SPEC §10.3)

- `rrf_score = w_sem/(rrf_k+rank_sem) + w_lex/(rrf_k+rank_lex)`
- 기본 `rrf_k=50`, `semantic_weight=lexical_weight=1.0`.
- cosine 점수와 trigram 점수를 직접 더하지 않는다(순위 기반).
- SQL RPC(`rag_search_hybrid`)에서 결합. 파이썬 참조 구현은 `app/rag/fusion.py`.

## 4. 현재 문서 우선 (SPEC §10.4)

- `context_source_id`가 있으면: 현재 문서 내부 후보(최대 4) + 전체 후보(최대 12)를 합쳐 중복 제거 후, 현재 문서 청크를 앞으로 정렬.

## 5. 중복 제거 (SPEC §10.5)

- 동일 `content_hash` 제거
- 문서당 최대 2청크, 뉴스 사건당 최대 2청크
- (Phase 3 뉴스는 대부분 사건=1청크라 실제 중복은 드묾)

## 6. 부모 문맥 확장 (SPEC §10.7)

- 뉴스 사건은 section이 없어 같은 문서의 앞뒤 청크(chunk_order ±1)를 배경으로 덧붙인다.
- 전체 문맥은 `RAG_CONTEXT_CHAR_BUDGET`(기본 12000자) 이하.
- 인용 번호는 검색된 핵심 청크 기준(배경은 인용 대상 아님).

## 7. 설정 (config)

| 키 | 기본 | 의미 |
|---|---|---|
| `rag_semantic_candidates` | 24 | 의미 후보 수 |
| `rag_lexical_candidates` | 24 | 키워드 후보 수 |
| `rag_rrf_k` | 50 | RRF 상수 |
| `rag_max_chunks_per_document` | 2 | 문서/사건당 최대 청크 |
| `rag_current_doc_candidates` | 4 | 현재 문서 내부 후보 |
| `rag_global_candidates` | 12 | 전체 후보 |
| `rag_context_char_budget` | 12000 | 문맥 길이 상한 |
| `rag_retrieval_top_k` | 8 | 최종 문맥 수 |

## 8. 코드/마이그레이션

| 역할 | 위치 |
|---|---|
| 하이브리드 RRF RPC (최초) | `migrations/0017_rag_hybrid_rrf.sql` |
| lexical 정확일치 우선 개선 | `migrations/0018_rag_hybrid_lexical_exact_first.sql` (CREATE OR REPLACE) |
| 검색기 | `app/rag/retrieval.py` (`HybridRetriever`, `SemanticRetriever` 유지) |
| RRF 참조 구현 | `app/rag/fusion.py` |
| QA 라우트 연결 | `app/api/routes/qa.py` (HybridRetriever 사용) |
| 비교 평가 | `scripts/rag_phase3_eval.py` |
