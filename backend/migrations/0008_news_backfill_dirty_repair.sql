begin;

create or replace function public.repair_news_backfill_dirty_clusters(p_run_key text)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
    affected integer := 0;
begin
    insert into public.news_backfill_dirty_clusters (run_key, cluster_id, status)
    select distinct p_run_key, assignment.cluster_id, 'dirty'
    from public.news_backfill_pair_claims claim
    join public.news_cluster_assignments assignment
      on assignment.article_id = claim.article_id
     and assignment.stock_code = claim.stock_code
    where claim.run_key = p_run_key
      and assignment.status in ('assigned_new', 'assigned_existing')
      and assignment.cluster_id is not null
    on conflict (run_key, cluster_id) do nothing;
    get diagnostics affected = row_count;
    return affected;
end;
$$;

revoke all on function public.repair_news_backfill_dirty_clusters(text) from public;
grant execute on function public.repair_news_backfill_dirty_clusters(text) to service_role;

commit;
