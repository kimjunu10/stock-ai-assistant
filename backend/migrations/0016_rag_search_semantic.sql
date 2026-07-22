-- ============================================================================
-- RAG Phase 2: 의미 검색 RPC (pgvector cosine)
--
-- PostgREST 로는 벡터 연산자를 직접 쓰기 어려워 SQL 함수로 노출한다.
-- 서비스 역할이 supabase.rpc('rag_search_semantic', ...) 로 호출한다.
-- 필터: stock_code(선택), source_type(선택), is_active=true 고정.
-- 반환: 청크 + 문서 메타 + cosine distance/similarity.
-- 재실행 안전(create or replace). 롤백: rollback/0016_*_down.sql
-- ============================================================================
begin;

create or replace function public.rag_search_semantic(
    query_embedding extensions.vector(1024),
    match_count integer default 24,
    filter_stock_code text default null,
    filter_source_type text default null
)
returns table (
    chunk_id uuid,
    document_id uuid,
    content text,
    value_kind text,
    stock_code text,
    source_type text,
    published_at timestamptz,
    page_start integer,
    page_end integer,
    source_locator jsonb,
    doc_title text,
    doc_publisher text,
    doc_source_url text,
    doc_source_pk text,
    similarity double precision
)
language sql
stable
as $$
    select
        c.id as chunk_id,
        c.document_id,
        c.content,
        c.value_kind,
        c.stock_code,
        c.source_type,
        c.published_at,
        c.page_start,
        c.page_end,
        c.source_locator,
        d.title as doc_title,
        d.publisher as doc_publisher,
        d.source_url as doc_source_url,
        d.source_pk as doc_source_pk,
        1 - (c.embedding <=> query_embedding) as similarity
    from public.rag_chunks c
    join public.rag_documents d on d.id = c.document_id
    where c.is_active = true
      and d.is_current = true
      and c.embedding is not null
      and (filter_stock_code is null or c.stock_code = filter_stock_code)
      and (filter_source_type is null or c.source_type = filter_source_type)
    order by c.embedding <=> query_embedding
    limit match_count;
$$;

commit;
