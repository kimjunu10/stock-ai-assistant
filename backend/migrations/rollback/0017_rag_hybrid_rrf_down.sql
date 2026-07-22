-- 롤백: 0017_rag_hybrid_rrf.sql
begin;
drop function if exists public.rag_search_hybrid(
    extensions.vector, text, integer, integer, integer, integer,
    double precision, double precision, text, text, timestamptz, timestamptz, text
);
commit;
