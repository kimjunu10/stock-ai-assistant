-- 롤백: 0019_rag_terms_extend.sql
-- 추가한 컬럼/인덱스만 제거. 기존 rag_terms 행(시드 6건)은 보존.
begin;
drop index if exists public.rag_terms_embedding_hnsw;
drop index if exists public.rag_terms_content_hash_idx;
alter table public.rag_terms
    drop column if exists related_terms,
    drop column if exists source_name,
    drop column if exists source_title,
    drop column if exists source_edition,
    drop column if exists pdf_page,
    drop column if exists content_hash,
    drop column if exists embedding;
commit;
