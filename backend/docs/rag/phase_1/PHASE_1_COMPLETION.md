# Phase 1 완료 보고

- 완료일: 2026-07-22
- 브랜치: `rag/phase0` (Phase 0 이어서 진행)
- 기준 문서: `backend/docs/rag/phase_1/PHASE_1_DB_STORAGE.md` (본 Phase에서 신규 작성)

## 완료한 작업
- 마이그레이션 0012~0015 작성 및 **실제 DB 적용**
- 테이블 9개 생성: rag_documents / rag_sections / rag_chunks / research_reports /
  research_report_pages / research_report_tables / rag_terms / rag_ingestion_runs / rag_query_logs
- rag_chunks denormalize 컬럼(stock_code / source_type / published_at / value_kind / is_active) 저장
- 벡터 인덱스(HNSW cosine) / 키워드 인덱스(trgm GIN) / 필터 인덱스 생성
- 비공개 Storage 버킷 `research-reports-private` 생성(public=false 확인)
- Repository(`app/repositories/rag.py`) 구현
- 문서 버전 비활성화 로직 구현 및 실DB 검증
- 마이그레이션 재실행 안전성 확인(멱등)
- 롤백 스크립트 4개 작성(`migrations/rollback/`)
- 기존 DB 기능 회귀 확인(pytest 58 passed)

## 수정/추가한 파일
- `migrations/0012_rag_core.sql` (신규)
- `migrations/0013_research_reports.sql` (신규)
- `migrations/0014_rag_hybrid_search.sql` (신규)
- `migrations/0015_rag_rls_storage.sql` (신규)
- `migrations/rollback/0012~0015_*_down.sql` (신규 4개)
- `scripts/apply_rag_migrations.py` (신규, 적용/롤백/체크 러너)
- `scripts/create_rag_storage.py` (신규, 버킷 멱등 생성)
- `app/repositories/rag.py` (신규, RagRepository)
- `backend/docs/rag/phase_1/PHASE_1_DB_STORAGE.md` (신규 기준 문서)
- `backend/docs/rag/phase_1/PHASE_1_COMPLETION.md` (본 보고서)

## DB 변경
- 신규 테이블 9개 + 확장(vector, pg_trgm) + 인덱스 8개 + Storage 버킷 1개.
- **기존 테이블/데이터는 변경하지 않음.** (검증 시 기존 행수 그대로; articles 증가분은
  news 스케줄러의 정상 신규 수집분으로 본 마이그레이션과 무관.)
- 모든 신규 테이블 RLS enable(정책 없음 = 익명 차단, 백엔드 service_role 우회). 기존 관례 동일.

## 테스트 결과
- `pytest`: **58 passed** (회귀 없음)
- 마이그레이션 적용: 성공, 재실행 시 전부 skip(멱등)
- 스키마 검증: 테이블 9/9, `rag_chunks.embedding = vector(1024)`, denorm 5컬럼, 인덱스 6개, RLS 전부 on
- Repository 스모크: 문서 재사용/버전전환(is_current 정확히 1개)/청크(벡터) 저장 성공, 테스트 데이터 정리 완료
- Storage: 버킷 public=false 확인
- ruff: All checks passed

## 실제 응답 시간과 비용
- 마이그레이션/버킷 생성/스모크 모두 로컬 psql·API 소량 호출. 비용 무시 수준.
- 대량 인덱싱은 Phase 2에서 수행.

## 기획서와 달라진 점
1. **uuid 기본값**: SPEC 예시의 `extensions.uuid_generate_v4()` 대신 `gen_random_uuid()`(pg_catalog) 사용.
   - 이유: 스키마 접두어 없이 안정적, 이식성 좋음(둘 다 사용 가능 확인).
   - 영향: 기능 동일. 사용자 확인 불필요.
2. **rag_chunks denormalize 확장**: 계획서 체크리스트대로 stock_code/source_type/published_at/value_kind
   를 rag_chunks 에 중복 저장(SPEC은 "성능 보고 결정" 여지). 인덱싱 단계에서 rag_documents 와 일치 보장 필요.
   - 영향: 필터 쿼리 단순화/고속화. 인덱싱 로직(Phase 2)에서 정합성 유지 책임.
3. **Storage 버킷은 SQL 아닌 API로 생성**: 0015는 RLS 재확인만, 버킷은 `create_rag_storage.py`.
   - 이유: Supabase Storage 버킷은 SQL DDL 대상이 아님.
4. **RLS 정책 미부여(enable만)**: 기존 18개 테이블과 동일하게 정책 0개 유지.
   - 이유: 백엔드가 service_role(우회)로만 접근하는 기존 아키텍처. anon/authenticated는 정책 없어 기본 거부.
   - 영향: 원본 비공개 요건 충족. 공개 API 노출 시 재검토 필요(향후).
5. **기준 문서 신규 작성**: 지시된 `PHASE_1_DB_STORAGE.md`가 저장소에 없어 실제 구현 기준으로 새로 작성.

## 아직 남은 문제
- research_report_* 테이블은 스키마만 존재(데이터 없음) → Phase 5에서 채움.
- rag_terms 비어 있음 → Phase 4에서 적재.
- 임베딩 생성/실제 인덱싱은 미구현 → Phase 2.
- denorm 컬럼 정합성은 인덱싱 로직 책임(현재는 컬럼만 준비).

## 사용자 확인이 필요한 것
- 없음 (데이터 손상·비용 초과·보안 위험·기존 기능 회귀 없음)

## 다음 Phase 진행 가능 여부
- **가능** — Phase 2(뉴스 기반 최소 RAG) 진행 가능.

---

## Phase 종료 기록 (계획서 반영용)
```text
상태: 완료
완료일: 2026-07-22
생성한 마이그레이션: 0012_rag_core, 0013_research_reports, 0014_rag_hybrid_search, 0015_rag_rls_storage
실제 적용된 테이블: rag_documents, rag_sections, rag_chunks, research_reports,
  research_report_pages, research_report_tables, rag_terms, rag_ingestion_runs, rag_query_logs (9개)
기획서와 달라진 스키마: uuid=gen_random_uuid, rag_chunks denorm 컬럼 확장, RLS enable만(정책 없음),
  Storage 버킷은 API로 생성
롤백 방법: scripts/apply_rag_migrations.py --rollback (migrations/rollback/*_down.sql 역순)
남은 위험: denorm 정합성은 Phase2 인덱싱 책임, RLS 정책은 공개 API 시 재검토
```
