begin;

create table public.stock_news_issue_briefs (
    stock_code text primary key references public.stocks(code) on delete cascade,
    positive_items jsonb not null default '[]'::jsonb,
    negative_items jsonb not null default '[]'::jsonb,
    source_cluster_ids jsonb not null default '[]'::jsonb,
    source_hash text not null,
    model text not null,
    prompt_version text not null,
    generated_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (jsonb_typeof(positive_items) = 'array'),
    check (jsonb_typeof(negative_items) = 'array'),
    check (jsonb_typeof(source_cluster_ids) = 'array')
);

create index stock_news_issue_briefs_generated_at_idx
    on public.stock_news_issue_briefs (generated_at desc);

alter table public.stock_news_issue_briefs enable row level security;

commit;
