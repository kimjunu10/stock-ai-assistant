-- 롤백: 0015_rag_rls_storage.sql
-- 0015 는 RLS enable(멱등)만 수행했고 정책을 추가하지 않았으므로 실질적 down 은 없다.
-- RLS 를 끄면 오히려 익명 접근이 열릴 수 있어 의도적으로 no-op 로 둔다.
select 1;
