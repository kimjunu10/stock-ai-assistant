begin;

create table if not exists public.news_backfill_runs (
    run_key text primary key,
    status text not null
        check (status in ('planned', 'running', 'stopped_budget', 'stopped', 'completed', 'failed')),
    started_at timestamptz,
    finished_at timestamptz,
    last_success_article_id bigint references public.articles(id) on delete set null,
    last_success_stock_code text references public.stocks(code) on delete set null,
    last_success_published_at timestamptz,
    processed_articles integer not null default 0 check (processed_articles >= 0),
    processed_pairs integer not null default 0 check (processed_pairs >= 0),
    completed_articles integer not null default 0 check (completed_articles >= 0),
    pending_retry_articles integer not null default 0 check (pending_retry_articles >= 0),
    assignment_calls integer not null default 0 check (assignment_calls >= 0),
    summary_calls integer not null default 0 check (summary_calls >= 0),
    prompt_tokens bigint not null default 0 check (prompt_tokens >= 0),
    completion_tokens bigint not null default 0 check (completion_tokens >= 0),
    estimated_cost_usd numeric(12, 6) not null default 0 check (estimated_cost_usd >= 0),
    limits jsonb not null default '{}'::jsonb,
    totals jsonb not null default '{}'::jsonb,
    last_error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists news_backfill_runs_started_idx
    on public.news_backfill_runs (started_at desc);

drop trigger if exists news_backfill_runs_set_updated_at on public.news_backfill_runs;
create trigger news_backfill_runs_set_updated_at
before update on public.news_backfill_runs
for each row execute function public.set_updated_at();

alter table public.news_backfill_runs enable row level security;

commit;
