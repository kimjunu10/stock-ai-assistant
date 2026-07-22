-- 롤백: 0013_research_reports.sql
-- 주의: Storage 버킷/원본 PDF 는 삭제하지 않는다(scripts/create_rag_storage.py 로 별도 관리).
begin;
drop table if exists public.research_report_tables;
drop table if exists public.research_report_pages;
drop table if exists public.research_reports;
commit;
