-- 롤백: 0012_rag_core.sql
-- 주의: RAG 신규 테이블만 제거한다. 기존 뉴스/DART/재무 테이블·확장은 건드리지 않는다.
--       vector/pg_trgm 확장은 다른 곳에서 쓸 수 있으므로 drop 하지 않는다.
begin;
drop table if exists public.rag_query_logs;
drop table if exists public.rag_ingestion_runs;
drop table if exists public.rag_chunks;      -- 0014 인덱스도 함께 제거됨
drop table if exists public.rag_sections;
drop table if exists public.rag_documents;
commit;
