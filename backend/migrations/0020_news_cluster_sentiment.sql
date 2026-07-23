begin;

alter table public.news_clusters
    add column sentiment_label text
        check (sentiment_label in ('negative', 'neutral', 'positive', 'unknown')),
    add column sentiment_score double precision
        check (sentiment_score between 0 and 1),
    add column sentiment_positive_score double precision
        check (sentiment_positive_score between 0 and 1),
    add column sentiment_neutral_score double precision
        check (sentiment_neutral_score between 0 and 1),
    add column sentiment_negative_score double precision
        check (sentiment_negative_score between 0 and 1),
    add column sentiment_model text,
    add column sentiment_model_revision text,
    add column sentiment_input_version text,
    add column sentiment_input_hash text,
    add column sentiment_analyzed_at timestamptz;

create index news_clusters_sentiment_backfill_idx
    on public.news_clusters (id)
    where sentiment_label is null or sentiment_label = 'unknown';

commit;
