-- OpenDART가 status=013/014로 원본 파일 부재를 확정한 공시를 재시도 대상과 구분한다.
-- 데이터 삭제 없이 CHECK 제약만 확장한다.
begin;

alter table public.disclosures
    drop constraint if exists disclosures_parse_status_check;

alter table public.disclosures
    add constraint disclosures_parse_status_check
    check (parse_status in ('pending', 'success', 'failed', 'not_selected', 'unavailable'));

commit;
