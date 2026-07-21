begin;

create table if not exists public.news_backfill_dirty_clusters (
    run_key text not null references public.news_backfill_runs(run_key) on delete cascade,
    cluster_id bigint not null references public.news_clusters(id) on delete cascade,
    status text not null default 'dirty'
        check (status in ('dirty', 'processing', 'success', 'pending_retry')),
    retry_count integer not null default 0 check (retry_count >= 0),
    claimed_at timestamptz,
    next_retry_at timestamptz,
    last_error text,
    summarized_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (run_key, cluster_id)
);

create index if not exists news_backfill_dirty_status_idx
    on public.news_backfill_dirty_clusters (run_key, status, cluster_id);

drop trigger if exists news_backfill_dirty_set_updated_at
    on public.news_backfill_dirty_clusters;
create trigger news_backfill_dirty_set_updated_at
before update on public.news_backfill_dirty_clusters
for each row execute function public.set_updated_at();

alter table public.news_backfill_dirty_clusters enable row level security;

create table if not exists public.news_backfill_pair_claims (
    article_id bigint not null references public.articles(id) on delete cascade,
    stock_code text not null references public.stocks(code) on delete cascade,
    run_key text not null references public.news_backfill_runs(run_key) on delete cascade,
    status text not null default 'processing'
        check (status in ('processing', 'completed', 'pending_retry')),
    claimed_at timestamptz not null default now(),
    finished_at timestamptz,
    last_error text,
    primary key (article_id, stock_code)
);

alter table public.news_backfill_pair_claims enable row level security;

create or replace function public.claim_news_backfill_pair(
    p_run_key text,
    p_article_id bigint,
    p_stock_code text
) returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
    claimed boolean := false;
begin
    insert into public.news_backfill_pair_claims (
        article_id, stock_code, run_key, status, claimed_at, finished_at, last_error
    ) values (
        p_article_id, p_stock_code, p_run_key, 'processing', now(), null, null
    )
    on conflict (article_id, stock_code) do update
    set run_key = excluded.run_key,
        status = 'processing',
        claimed_at = now(),
        finished_at = null,
        last_error = null
    where news_backfill_pair_claims.status <> 'completed'
      and (
          news_backfill_pair_claims.status <> 'processing'
          or news_backfill_pair_claims.claimed_at < now() - interval '30 minutes'
      )
    returning true into claimed;
    return coalesce(claimed, false);
end;
$$;

revoke all on function public.claim_news_backfill_pair(text, bigint, text) from public;
grant execute on function public.claim_news_backfill_pair(text, bigint, text) to service_role;

commit;
