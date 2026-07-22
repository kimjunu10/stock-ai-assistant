# Phase 1. DB · Storage · 기본 Repository (기준 문서)

이 문서는 Phase 1에서 실제로 만든 DB 스키마·인덱스·Storage·Repository의 기준을 정의한다.
SPEC(`RAG_IMPLEMENTATION_SPEC.md` §6~7)을 따르되, 실제 DB/코드에 맞게 확정한 값이 우선한다.

## 1. 마이그레이션 파일

| 파일 | 내용 |
|---|---|
| `migrations/0012_rag_core.sql` | 확장(vector, pg_trgm) + `rag_documents` / `rag_sections` / `rag_chunks` + `rag_ingestion_runs` / `rag_query_logs` |
| `migrations/0013_research_reports.sql` | `research_reports` / `research_report_pages` / `research_report_tables` |
| `migrations/0014_rag_hybrid_search.sql` | `rag_terms` + 벡터(HNSW)/키워드(trgm)/필터 인덱스 |
| `migrations/0015_rag_rls_storage.sql` | 신규 테이블 RLS enable 재확인(멱등) |

롤백: `migrations/rollback/00NN_*_down.sql` (역순).
적용/롤백 러너: `scripts/apply_rag_migrations.py [--check|--rollback]`.

## 2. 테이블 (실제 적용됨)

- `rag_documents` — 검색 원본의 버전/출처. `(source_type, source_pk, content_hash)` unique,
  `(source_type, source_pk)` 당 `is_current=true` 하나만(부분 unique 인덱스). 원본 테이블에 FK 없음.
- `rag_sections` — 큰 문맥 단위. `document_id` FK(on delete cascade).
- `rag_chunks` — 검색 단위. `embedding vector(1024)`. denormalize 필터 컬럼
  `stock_code / source_type / published_at / value_kind / is_active` 포함.
- `research_reports` — 리포트 메타. `file_hash` unique(중복 업로드 방지), 원본은 Storage 경로만.
- `research_report_pages` — 페이지별 텍스트/마크다운/요소. `unique(report_id, page_number)`.
- `research_report_tables` — 정상 추출 표만. `value_kind ∈ {actual, forecast, mixed, unknown}`.
- `rag_terms` — 금융 용어. `term` unique, `aliases`/`search_text` 검색.
- `rag_ingestion_runs` — 인덱싱 실행 로그(건수/비용).
- `rag_query_logs` — 질의 로그(개인정보 없는 데모 전제).

## 3. 인덱스 (rag_chunks)

- `rag_chunks_embedding_hnsw` — HNSW, `vector_cosine_ops` (의미 검색)
- `rag_chunks_search_text_trgm` — GIN, `gin_trgm_ops` (키워드 검색)
- `rag_chunks_filter_idx` — `(stock_code, source_type, is_active)`
- `rag_chunks_published_idx` — `(published_at desc) where is_active`
- `rag_chunks_document_idx` — `(document_id, chunk_order)`
- `rag_terms`: `term` unique + `aliases` GIN + `search_text` trgm

## 4. Storage

- 버킷 `research-reports-private`, **public=false** (생성/검증 완료).
- 생성 스크립트: `scripts/create_rag_storage.py [--apply]` (멱등).
- 백엔드는 service_role 로만 접근. 공개 UI에 원본 URL 직접 노출 금지(SPEC §7).

## 5. Repository (`app/repositories/rag.py`)

`RagRepository(client, cfg)` — 기존 프로젝트 패턴(Supabase 클라이언트) 사용.

- 문서: `upsert_document`(내용 동일 시 재사용, 변경 시 이전 버전 자동 비활성화),
  `find_current_document`, `deactivate_previous_versions`
- 섹션/청크: `replace_sections`, `replace_chunks`(벡터+denorm 포함), `existing_chunk_hashes`
- 용어: `upsert_terms`
- 리포트: `find_report_by_hash`, `upsert_report`, `replace_report_pages`, `replace_report_tables`
- 실행 로그: `start_ingestion_run`, `finish_ingestion_run`

임베딩 생성 자체는 Phase 2(`app/ml/embeddings.py`)에서 담당한다. Repository는 벡터 저장/조회만 한다.

## 6. 고정 원칙 준수

- 임베딩 1024차원 단일 세대(solar-embedding-2). 다른 차원/세대 혼용 금지.
- 기존 뉴스/DART/재무 테이블 무변경(신규 테이블만 추가).
- 원본 PDF 비공개 Storage. DB엔 경로만.
- 마이그레이션 재실행 안전 + 롤백 스크립트 존재.
