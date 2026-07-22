-- ============================================================================
-- RAG Phase 3: 하이브리드 검색 RRF (의미 + 키워드) — SPEC §10
--
-- 원리(Supabase 공식 하이브리드와 동일): semantic(cosine)과 lexical(pg_trgm)을
-- 각각 순위화한 뒤 Reciprocal Rank Fusion 으로 결합한다.
-- cosine 점수와 trigram 점수를 직접 더하지 않는다(순위 기반).
--   rrf_score = w_sem / (rrf_k + rank_sem) + w_lex / (rrf_k + rank_lex)
--
-- 필터: is_active/is_current 고정 + stock_code/source_type/날짜/value_kind(선택).
-- 재실행 안전(create or replace). 롤백: rollback/0017_*_down.sql
-- ============================================================================
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
        -- 정확 명칭·영문 약어·종목코드·제품명 등 부분일치를 잡는다.
        -- 전체 텍스트 similarity(%)는 긴 문서·짧은 쿼리에서 threshold 미달이라
        -- word_similarity(<%, 쿼리가 텍스트의 일부 단어와 얼마나 유사한가)로 순위화하고
        -- ILIKE 부분일치도 후보에 포함한다.
        -- (주의: 정확 부분일치 우선 순위는 0018 에서 CREATE OR REPLACE 로 개선한다.)
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
