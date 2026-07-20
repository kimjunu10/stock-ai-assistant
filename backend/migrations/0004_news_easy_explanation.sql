begin;

alter table public.news_clusters
    add column easy_explanation text;

comment on column public.news_clusters.easy_explanation is
    'Beginner-friendly explanation shown between the cluster title and factual event write-up.';

commit;
