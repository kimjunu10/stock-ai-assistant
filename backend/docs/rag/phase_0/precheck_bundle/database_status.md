# Database status (actual, observed 2026-07-22)

All checks were read-only against the configured Supabase PostgreSQL database.

## Extensions

| Extension | Version |
|---|---:|
| pg_stat_statements | 1.11 |
| pgcrypto | 1.3 |
| plpgsql | 1.0 |
| supabase_vault | 0.3.1 |
| uuid-ossp | 1.1 |

`vector`/pgvector is not installed, so there is no pgvector version to report.

## Related table row counts

| Table | Exists | Rows |
|---|---:|---:|
| stocks | yes | 5 |
| articles | yes | 10470 |
| article_stocks | yes | 14570 |
| news_clusters | yes | 6828 |
| news_cluster_assignments | yes | 12923 |
| disclosures | yes | 4722 |
| structured_disclosures | yes | 1524 |
| financials | yes | 510 |
| company_profiles | yes | 5 |
| corporate_events | yes | 142 |
| dart_collection_runs | yes | 1 |
| dart_collection_api_results | yes | 340 |
| chunks | no | n/a |
| reports | no | n/a |
| research_reports | no | n/a |
| research_report_pages | no | n/a |
| terms | no | n/a |

## Vector and embedding columns

- No `public` column has PostgreSQL type `vector(...)`.
- `articles.embedding`, `clusters.centroid`, and `chunks.embedding` from the SPEC do not exist as pgvector columns.
- Actual `public.news_clusters.centroid` is `double precision[]`, not pgvector. Across all 6828 rows, the minimum and maximum stored array lengths are both 1024; null count is 0.

## Search functions and indexes

- Public functions: `claim_news_backfill_pair(text,bigint,text)`, `repair_news_backfill_dirty_clusters(text)`, and trigger function `set_updated_at()`.
- Functions whose name contains `search`, `match`, or `retriev`: none.
- HNSW, IVFFlat, or other vector indexes: none.
- Existing ordinary indexes are captured in `actual_supabase_schema.sql`; they cover article queues/timestamps, disclosure lookups, financial periods, news clustering/backfill state, and structured-disclosure lookups.

## RLS and Storage

- RLS is enabled (not forced) on all 18 actual `public` tables.
- `pg_policies` returned no policies for `public` or `storage`.
- `storage.buckets` returned zero bucket names.
