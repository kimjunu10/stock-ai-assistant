-- ============================================================================
-- RAG Phase 1: RLS/Storage 정책 확인 (SPEC §6, §7)
--
-- 현황(Phase 0 조사):
--   - 기존 public 테이블 18개는 RLS enable(not forced), public/storage 정책 0개.
--   - 백엔드는 service_role 키로 접근하며 service_role 은 RLS 를 우회한다.
--   - 따라서 기존 관례와 동일하게 신규 RAG 테이블도 RLS enable + 정책 없음(=익명 차단)
--     을 유지한다. anon/authenticated 롤에는 어떤 정책도 부여하지 않아 기본 거부된다.
--
-- 이 파일은 신규 테이블에 RLS 가 켜져 있음을 재확인(idempotent)만 한다.
-- 실제 Storage 버킷(research-reports-private) 생성은 SQL 이 아니라
--   scripts/create_rag_storage.py (Storage API) 로 수행한다. 아래 §7 참고.
-- 재실행 안전. 롤백: 정책을 추가하지 않았으므로 down 은 no-op(문서만).
-- ============================================================================
begin;

alter table public.rag_documents enable row level security;
alter table public.rag_sections enable row level security;
alter table public.rag_chunks enable row level security;
alter table public.rag_ingestion_runs enable row level security;
alter table public.rag_query_logs enable row level security;
alter table public.research_reports enable row level security;
alter table public.research_report_pages enable row level security;
alter table public.research_report_tables enable row level security;
alter table public.rag_terms enable row level security;

commit;

-- ----------------------------------------------------------------------------
-- §7 원본 PDF Storage (참고 — SQL 아님)
--   버킷명: research-reports-private
--   - public = false
--   - 백엔드만 service_role 로 읽기
--   - 공개 UI 에는 원본 URL 직접 노출 금지, 필요 시 짧은 만료 signed URL
--   생성 명령: uv run python scripts/create_rag_storage.py --apply
-- ----------------------------------------------------------------------------
