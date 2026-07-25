-- 롤백: 0022_research_report_target_price_status.sql
-- 신규 목표주가 상태 컬럼만 제거한다. 기존 target_price/target_price_currency 는 보존.
begin;

alter table public.research_reports
    drop column if exists target_price_status,
    drop column if exists target_price_effective_date,
    drop column if exists target_price_source_page,
    drop column if exists target_price_source_chunk_id,
    drop column if exists target_price_evidence_text,
    drop column if exists target_price_extracted_at,
    drop column if exists target_price_extractor_version;

commit;
