-- ============================================================================
-- 증권사 리포트 목표주가 신뢰 상태 확장 (prompt.md §2)
--
-- 배경: research_reports.target_price 가 전량 NULL 이다. 원인은 "목표주가 미제시"가
--   아니라 파서/로더에 목표주가 추출 로직이 없어서다(감사 결과). NULL 하나로는
--   미제시·추출실패·현재값확정불가를 구분할 수 없으므로 상태 필드를 추가한다.
--
-- 정책:
--   - 기존 컬럼(target_price, target_price_currency, investment_opinion)은 그대로 둔다.
--   - 신규 컬럼은 전부 nullable + 기본값으로 추가한다(비파괴, 재실행 안전).
--   - target_price_status 로 stated/not_stated/parse_failed/ambiguous/unknown 을 표현한다.
--       unknown = 아직 추출/판정을 돌리지 않은 초기 상태(기존 행 전부 여기서 시작).
--   - 목표주가 숫자는 답변 계층에서 status='stated' 인 경우에만 사용한다(Tool/검증기 강제).
--
-- ⚠️ 공유(운영) Supabase 에는 적용하지 않는다. 로컬/임시 DB 에서만 검증한다.
--    실제 적용은 별도 승인 후: psql "$DATABASE_URL" -f migrations/0022_research_report_target_price_status.sql
-- 롤백: migrations/rollback/0022_research_report_target_price_status_down.sql
-- ============================================================================
begin;

alter table public.research_reports
    add column if not exists target_price_status text not null default 'unknown'
        check (target_price_status in (
            'unknown', 'stated', 'not_stated', 'parse_failed', 'ambiguous'
        )),
    add column if not exists target_price_effective_date date,
    add column if not exists target_price_source_page integer,
    add column if not exists target_price_source_chunk_id text,
    add column if not exists target_price_evidence_text text,
    add column if not exists target_price_extracted_at timestamptz,
    add column if not exists target_price_extractor_version text;

comment on column public.research_reports.target_price_status is
    'stated=현재 목표주가 신뢰 추출, not_stated=원문에 목표주가 없음, '
    'parse_failed=원문엔 있으나 추출 실패, ambiguous=현재값 확정 불가, unknown=미판정';
comment on column public.research_reports.target_price_effective_date is
    '해당 목표주가의 제시일(변동추이표의 현재 행 날짜). report_date 와 다를 수 있음.';
comment on column public.research_reports.target_price_source_page is
    '목표주가 근거 페이지(pdf page_number). 검증기가 답변 인용과 대조.';
comment on column public.research_reports.target_price_source_chunk_id is
    '목표주가 근거 rag_chunks.chunk_id(있으면). 답변 source_id 연결용.';
comment on column public.research_reports.target_price_evidence_text is
    '추출 근거 원문 스니펫(감사·검증용, 짧게).';

commit;
