-- 롤백: 0014_rag_hybrid_search.sql
-- 인덱스와 rag_terms 만 제거한다. rag_chunks 데이터는 유지(인덱스만 drop).
begin;
drop index if exists public.rag_chunks_embedding_hnsw;
drop index if exists public.rag_chunks_search_text_trgm;
drop index if exists public.rag_chunks_filter_idx;
drop index if exists public.rag_chunks_published_idx;
drop index if exists public.rag_chunks_document_idx;
drop index if exists public.rag_terms_aliases_gin;
drop index if exists public.rag_terms_search_text_trgm;
drop table if exists public.rag_terms;
commit;
