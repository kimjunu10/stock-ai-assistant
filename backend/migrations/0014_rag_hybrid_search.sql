-- ============================================================================
-- RAG Phase 1: 하이브리드 검색 인덱스 + 금융 용어 (SPEC §6.4 인덱스, §6.8)
--
-- 정책:
--   - 의미검색은 HNSW cosine, 키워드검색은 pg_trgm GIN.
--   - 자주 쓰는 필터(stock_code, source_type, is_active, published_at)에 인덱스.
--   - rag_terms 는 정확일치(term/aliases)와 유사검색(trgm)을 모두 지원.
-- 재실행 안전: 전부 if not exists. 롤백: rollback/0014_rag_hybrid_search_down.sql
-- ============================================================================
begin;

-- 6.8 rag_terms -------------------------------------------------------------
create table if not exists public.rag_terms (
    id uuid primary key default gen_random_uuid(),
    term text not null unique,
    aliases text[] not null default '{}',
    english_name text,
    official_definition text not null,
    easy_definition text,
    source_page integer,
    search_text text not null default '',
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

drop trigger if exists rag_terms_set_updated_at on public.rag_terms;
create trigger rag_terms_set_updated_at
before update on public.rag_terms
for each row execute function public.set_updated_at();

alter table public.rag_terms enable row level security;

commit;

-- 인덱스 생성은 트랜잭션 밖에서 실행(대용량 시 concurrently 전환 여지). ---------

-- 의미 검색: HNSW cosine (SPEC §6.4)
create index if not exists rag_chunks_embedding_hnsw
    on public.rag_chunks
    using hnsw (embedding extensions.vector_cosine_ops);

-- 키워드 검색: trigram GIN (SPEC §6.4)
create index if not exists rag_chunks_search_text_trgm
    on public.rag_chunks
    using gin (search_text extensions.gin_trgm_ops);

-- 자주 쓰는 필터 (SPEC §6.4 + 계획서: published_at 추가)
create index if not exists rag_chunks_filter_idx
    on public.rag_chunks (stock_code, source_type, is_active);

create index if not exists rag_chunks_published_idx
    on public.rag_chunks (published_at desc)
    where is_active;

create index if not exists rag_chunks_document_idx
    on public.rag_chunks (document_id, chunk_order);

-- 용어: 정확 일치용 term 은 unique 로 이미 커버. 별칭/유사검색 인덱스.
create index if not exists rag_terms_aliases_gin
    on public.rag_terms using gin (aliases);

create index if not exists rag_terms_search_text_trgm
    on public.rag_terms
    using gin (search_text extensions.gin_trgm_ops);
