-- ============================================================================
-- RAG Phase 1: 증권사 리포트 원문/페이지/표 (SPEC §6.5~6.7)
--
-- 정책:
--   - 원본 PDF 는 비공개 Storage(research-reports-private, 0015)에 저장하고
--     DB 에는 경로만 기록한다. public UI 에 원본 URL 을 직접 노출하지 않는다.
--   - 실제값(A)과 전망값(E/F)을 표 단위로 구분(value_kind)한다.
--   - 정상 추출된 표만 research_report_tables 에 저장한다.
--   - file_hash unique 로 동일 PDF 중복 업로드를 방지한다.
-- 재실행 안전: 전부 if not exists. 롤백: rollback/0013_research_reports_down.sql
-- ============================================================================
begin;

-- 6.5 research_reports ------------------------------------------------------
create table if not exists public.research_reports (
    id uuid primary key default gen_random_uuid(),
    stock_code text not null
        check (stock_code ~ '^[0-9]{6}$'),
    broker text not null,
    title text not null,
    report_date date,
    investment_opinion text,
    target_price numeric,
    target_price_currency text default 'KRW',
    current_price numeric,
    page_count integer,
    storage_bucket text not null,
    storage_path text not null,
    file_hash text not null unique,
    parse_status text not null default 'pending'
        check (parse_status in ('pending', 'parsing', 'success', 'failed', 'partial')),
    parser_name text,
    parser_version text,
    parse_cost numeric,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists research_reports_stock_date_idx
    on public.research_reports (stock_code, report_date desc);

drop trigger if exists research_reports_set_updated_at on public.research_reports;
create trigger research_reports_set_updated_at
before update on public.research_reports
for each row execute function public.set_updated_at();

alter table public.research_reports enable row level security;

-- 6.6 research_report_pages -------------------------------------------------
create table if not exists public.research_report_pages (
    id uuid primary key default gen_random_uuid(),
    report_id uuid not null references public.research_reports(id) on delete cascade,
    page_number integer not null,
    plain_text text,
    markdown_text text,
    elements jsonb not null default '{}'::jsonb,
    page_hash text,
    created_at timestamptz not null default now(),
    unique (report_id, page_number)
);

alter table public.research_report_pages enable row level security;

-- 6.7 research_report_tables ------------------------------------------------
create table if not exists public.research_report_tables (
    id uuid primary key default gen_random_uuid(),
    report_id uuid not null references public.research_reports(id) on delete cascade,
    page_number integer not null,
    table_order integer not null default 0,
    title text,
    unit text,
    headers jsonb not null default '[]'::jsonb,
    rows jsonb not null default '[]'::jsonb,
    value_kind text not null default 'unknown'
        check (value_kind in ('actual', 'forecast', 'mixed', 'unknown')),
    source_bbox jsonb,
    parse_confidence numeric,
    created_at timestamptz not null default now()
);

create index if not exists research_report_tables_report_idx
    on public.research_report_tables (report_id, page_number, table_order);

alter table public.research_report_tables enable row level security;

commit;
