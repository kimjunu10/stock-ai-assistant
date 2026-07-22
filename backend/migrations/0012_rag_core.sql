-- ============================================================================
-- RAG Phase 1: 핵심 문서/섹션/청크 + 운영 로그 테이블 (SPEC §6.1~6.4, §6.9~6.10)
--
-- 정책:
--   - 기존 뉴스·DART·재무 테이블을 변경/삭제하지 않는다. 신규 테이블만 추가.
--   - pgvector/pg_trgm 확장은 extensions 스키마에 설치(Phase 0에서 권한 확인 완료).
--   - 임베딩 차원은 1024(solar-embedding-2). 다른 세대/차원 벡터를 섞지 않는다.
--   - rag_chunks 에 stock_code/source_type/published_at/value_kind 를 denormalize 저장
--     (필터 인덱스 성능용). 인덱싱 단계에서 rag_documents 와 일치하도록 보장한다.
--   - 모든 신규 테이블은 RLS enable (정책은 0015 에서 다룸; 백엔드는 service_role 사용).
-- 재실행 안전: 전부 if not exists. 롤백: migrations/rollback/0012_rag_core_down.sql
-- ============================================================================
begin;

-- 6.1 확장 기능 -------------------------------------------------------------
create extension if not exists vector with schema extensions;
create extension if not exists pg_trgm with schema extensions;

-- 6.2 rag_documents ---------------------------------------------------------
create table if not exists public.rag_documents (
    id uuid primary key default gen_random_uuid(),
    source_type text not null
        check (source_type in ('news_event', 'dart_document', 'research_report', 'financial_term')),
    source_pk text not null,
    stock_code text
        check (stock_code is null or stock_code ~ '^[0-9]{6}$'),
    title text,
    publisher text,
    published_at timestamptz,
    source_url text,
    storage_bucket text,
    storage_path text,
    content_hash text not null,
    parser_name text,
    parser_version text,
    chunking_version text,
    embedding_model text,
    embedding_dimension integer,
    metadata jsonb not null default '{}'::jsonb,
    is_current boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    -- (source_type, source_pk, content_hash) 동일 원본/동일 내용 중복 방지
    constraint rag_documents_source_content_uniq
        unique (source_type, source_pk, content_hash)
);

-- 같은 (source_type, source_pk) 에서 is_current=true 는 하나만 허용
create unique index if not exists rag_documents_current_uniq
    on public.rag_documents (source_type, source_pk)
    where is_current;

create index if not exists rag_documents_stock_idx
    on public.rag_documents (stock_code, source_type, is_current);

drop trigger if exists rag_documents_set_updated_at on public.rag_documents;
create trigger rag_documents_set_updated_at
before update on public.rag_documents
for each row execute function public.set_updated_at();

alter table public.rag_documents enable row level security;

-- 6.3 rag_sections ----------------------------------------------------------
create table if not exists public.rag_sections (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references public.rag_documents(id) on delete cascade,
    section_order integer not null default 0,
    heading_path text[] not null default '{}',
    section_type text
        check (section_type is null or section_type in (
            'summary', 'narrative', 'table', 'correction_delta',
            'figure_caption', 'term_definition'
        )),
    page_start integer,
    page_end integer,
    content text not null,
    content_hash text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists rag_sections_document_idx
    on public.rag_sections (document_id, section_order);

alter table public.rag_sections enable row level security;

-- 6.4 rag_chunks ------------------------------------------------------------
create table if not exists public.rag_chunks (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references public.rag_documents(id) on delete cascade,
    section_id uuid references public.rag_sections(id) on delete set null,
    chunk_order integer not null default 0,
    content text not null,
    search_text text not null default '',
    token_estimate integer,
    page_start integer,
    page_end integer,
    source_locator jsonb not null default '{}'::jsonb,
    value_kind text
        check (value_kind is null or value_kind in (
            'official_fact', 'actual_value', 'forecast_value',
            'news_interpretation', 'broker_opinion', 'term_definition'
        )),
    content_hash text not null,
    embedding extensions.vector(1024),
    -- denormalized filter 컬럼 (계획서 Phase 1 요구): rag_documents 와 인덱싱 단계에서 일치 보장
    stock_code text
        check (stock_code is null or stock_code ~ '^[0-9]{6}$'),
    source_type text,
    published_at timestamptz,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

drop trigger if exists rag_chunks_set_updated_at on public.rag_chunks;
create trigger rag_chunks_set_updated_at
before update on public.rag_chunks
for each row execute function public.set_updated_at();

alter table public.rag_chunks enable row level security;
-- 벡터/키워드/필터 인덱스는 0014_rag_hybrid_search.sql 에서 생성한다.

-- 6.9 rag_ingestion_runs ----------------------------------------------------
create table if not exists public.rag_ingestion_runs (
    id uuid primary key default gen_random_uuid(),
    source_type text not null,
    status text not null default 'running'
        check (status in ('running', 'success', 'failed', 'partial')),
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    processed_count integer not null default 0,
    success_count integer not null default 0,
    failure_count integer not null default 0,
    estimated_cost numeric,
    actual_cost numeric,
    config jsonb not null default '{}'::jsonb,
    error_summary jsonb not null default '{}'::jsonb
);

create index if not exists rag_ingestion_runs_source_idx
    on public.rag_ingestion_runs (source_type, started_at desc);

alter table public.rag_ingestion_runs enable row level security;

-- 6.10 rag_query_logs -------------------------------------------------------
-- 개인정보 없는 데모 전제(SPEC §6.10). 공개 시 저장 범위 재검토.
create table if not exists public.rag_query_logs (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    question text,
    stock_code text,
    context_source_type text,
    context_source_id text,
    query_plan jsonb not null default '{}'::jsonb,
    retrieved_chunk_ids uuid[] not null default '{}',
    answer text,
    citations jsonb not null default '[]'::jsonb,
    latency_ms jsonb not null default '{}'::jsonb,
    model text,
    status text,
    error_code text
);

create index if not exists rag_query_logs_created_idx
    on public.rag_query_logs (created_at desc);

alter table public.rag_query_logs enable row level security;

commit;
