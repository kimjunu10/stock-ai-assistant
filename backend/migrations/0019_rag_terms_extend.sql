-- ============================================================================
-- RAG Phase 4: rag_terms 확장 — 경제금융용어 800선 적재용 컬럼 추가
--
-- 기존 rag_terms(시험 시드 6건)를 보존하며 컬럼만 추가한다(데이터 변경/삭제 없음).
-- - related_terms: 연관검색어(동의어 아님, GPT §3)
-- - 출처 메타: source_name/title/edition, pdf_page (source_page 는 이미 있음)
-- - content_hash: 재실행 시 중복 임베딩 skip 판정
-- - embedding: solar-embedding-2-passage(1024)
-- 재실행 안전(if not exists). 롤백: rollback/0019_rag_terms_extend_down.sql
-- ============================================================================
begin;

alter table public.rag_terms
    add column if not exists related_terms text[] not null default '{}',
    add column if not exists source_name text,
    add column if not exists source_title text,
    add column if not exists source_edition text,
    add column if not exists pdf_page integer,
    add column if not exists content_hash text,
    add column if not exists embedding extensions.vector(1024);

commit;

-- 벡터/키워드 인덱스(트랜잭션 밖).
create index if not exists rag_terms_embedding_hnsw
    on public.rag_terms
    using hnsw (embedding extensions.vector_cosine_ops);

-- content_hash 는 재실행 skip 판정용 조회 인덱스(unique 아님: 서로 다른 용어가
-- 우연히 같은 해시일 가능성 배제). canonical 키는 term unique 이다.
create index if not exists rag_terms_content_hash_idx
    on public.rag_terms (content_hash);
