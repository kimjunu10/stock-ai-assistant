begin;

drop index if exists public.news_clusters_sentiment_backfill_idx;

alter table public.news_clusters
    drop column if exists sentiment_analyzed_at,
    drop column if exists sentiment_input_hash,
    drop column if exists sentiment_input_version,
    drop column if exists sentiment_model_revision,
    drop column if exists sentiment_model,
    drop column if exists sentiment_negative_score,
    drop column if exists sentiment_neutral_score,
    drop column if exists sentiment_positive_score,
    drop column if exists sentiment_score,
    drop column if exists sentiment_label;

commit;
