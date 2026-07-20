begin;

alter table public.articles
    add column if not exists image_url text;

commit;
