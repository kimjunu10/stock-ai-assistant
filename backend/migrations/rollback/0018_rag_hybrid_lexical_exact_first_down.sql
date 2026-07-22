-- 롤백: 0018_rag_hybrid_lexical_exact_first.sql
-- rag_search_hybrid 를 0017 버전(lexical = word_similarity 단일 순위)으로 되돌린다.
-- 함수를 drop 하지 않고 CREATE OR REPLACE 로 이전 로직을 복원한다.
begin;

create or replace function public.rag_search_hybrid(
    query_embedding extensions.vector(1024),
    query_text text,
    match_count integer default 24,
    semantic_candidates integer default 24,
    lexical_candidates integer default 24,
    rrf_k integer default 50,
    semantic_weight double precision default 1.0,
    lexical_weight double precision default 1.0,
    filter_stock_code text default null,
    filter_source_type text default null,
    filter_from timestamptz default null,
    filter_to timestamptz default null,
    filter_value_kind text default null
)
returns table (
    chunk_id uuid,
    document_id uuid,
    content text,
    value_kind text,
    stock_code text,
    source_type text,
    published_at timestamptz,
    section_id uuid,
    chunk_order integer,
    content_hash text,
    source_locator jsonb,
    doc_title text,
    doc_publisher text,
    doc_source_url text,
    doc_source_pk text,
    similarity double precision,
    lexical_similarity double precision,
    rrf_score double precision
)
language sql
stable
as $$
    with base as (
        select c.*, d.title as d_title, d.publisher as d_publisher,
               d.source_url as d_source_url, d.source_pk as d_source_pk
        from public.rag_chunks c
        join public.rag_documents d on d.id = c.document_id
        where c.is_active = true
          and d.is_current = true
          and (filter_stock_code is null or c.stock_code = filter_stock_code)
          and (filter_source_type is null or c.source_type = filter_source_type)
          and (filter_value_kind is null or c.value_kind = filter_value_kind)
          and (filter_from is null or c.published_at >= filter_from)
          and (filter_to is null or c.published_at <= filter_to)
    ),
    semantic as (
        select id as chunk_id,
               1 - (embedding <=> query_embedding) as sem_sim,
               row_number() over (order by embedding <=> query_embedding) as rank_sem
        from base
        where embedding is not null
        order by embedding <=> query_embedding
        limit semantic_candidates
    ),
    lexical as (
        select id as chunk_id,
               extensions.word_similarity(query_text, search_text) as lex_sim,
               row_number() over (
                   order by extensions.word_similarity(query_text, search_text) desc
               ) as rank_lex
        from base
        where query_text <> ''
          and (search_text ilike '%' || query_text || '%'
               or query_text <% search_text)
        order by extensions.word_similarity(query_text, search_text) desc
        limit lexical_candidates
    ),
    fused as (
        select
            coalesce(s.chunk_id, l.chunk_id) as chunk_id,
            s.sem_sim,
            l.lex_sim,
            coalesce(semantic_weight / (rrf_k + s.rank_sem), 0)
              + coalesce(lexical_weight / (rrf_k + l.rank_lex), 0) as rrf_score
        from semantic s
        full outer join lexical l on s.chunk_id = l.chunk_id
    )
    select
        b.id, b.document_id, b.content, b.value_kind, b.stock_code, b.source_type,
        b.published_at, b.section_id, b.chunk_order, b.content_hash, b.source_locator,
        b.d_title, b.d_publisher, b.d_source_url, b.d_source_pk,
        f.sem_sim, f.lex_sim, f.rrf_score
    from fused f
    join base b on b.id = f.chunk_id
    order by f.rrf_score desc
    limit match_count;
$$;

commit;
