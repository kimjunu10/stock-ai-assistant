-- 롤백: 0016_rag_search_semantic.sql
begin;
drop function if exists public.rag_search_semantic(extensions.vector, integer, text, text);
commit;
