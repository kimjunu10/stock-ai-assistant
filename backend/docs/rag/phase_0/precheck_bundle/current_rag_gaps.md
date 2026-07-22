# Current RAG gaps (facts only, observed 2026-07-22)

## Implemented today

- FastAPI application, Supabase service-role client, Naver news collection/crawling, relevance processing, BGE-M3 news-event clustering, Solar-based same-event decisions/factual summaries, DART list/document/financial/structured collection code, and several read APIs.
- Actual database data exists for articles, news clusters, disclosures, structured disclosures, financials, company profiles, and corporate events.
- News clustering uses 1024-element BGE-M3 vectors in application memory and stores cluster centroids as `double precision[]`.
- A dry-run-default local report import utility and a proposed report schema SQL file exist.

## Not implemented or not present

- No pgvector extension.
- No pgvector columns, vector search functions, or vector indexes.
- No actual `chunks`, `terms`, `reports`, `research_reports`, `research_report_pages`, `qa_logs`, or `prices` table.
- No implemented source-specific RAG chunker, persistent RAG indexer, query embedder, dense retrieval, hybrid/BM25 retrieval, reranker, top-k experiment integration, term exact-match service, SQL/RAG question router, prompt assembly, citations, SSE QA endpoint, multi-turn query composition/rewrite, or QA logging.
- `qa.py`, `reports.py`, `rag/*.py`, `ml/embeddings.py`, `ml/generation.py`, `jobs/reports.py`, and `sources/naver_research.py` are placeholders.
- No report metadata records are available in the actual database.
- No Supabase Storage bucket exists; the proposed `research-reports` bucket has not been created.

## SPEC versus actual code/database

| SPEC item | Actual observation |
|---|---|
| `create extension vector` | `vector` is absent. |
| `articles.embedding vector(1024)` | `articles` has no embedding column. |
| `clusters.centroid vector(1024)` | There is no `clusters` table. `news_clusters.centroid` is `double precision[]`; stored arrays are 1024 elements. |
| `chunks.embedding vector(4096)` | `chunks` does not exist. |
| Upstage `embedding-passage`/`embedding-query`, 4096 dimensions | These legacy aliases remain temporarily available but are deprecated for 2026-08-31. Current official Embed 2 names are `solar-embedding-2-passage`/`solar-embedding-2-query`, 1024 dimensions. No application RAG embedding implementation exists. |
| `terms` from the Bank of Korea glossary | `terms` does not exist; no ingestion/indexing code is present. |
| `reports` plus a six-hour collection batch | `reports` does not exist; report source/job/API files are placeholders; the scheduler registers no report job. |
| `POST /api/qa` using SSE | QA router has no endpoint. |
| Dense retrieval, then hybrid experiments | Retrieval module is a placeholder; no search function or index exists. |
| Numeric routing through `financials`, `structured_disclosures`, `corporate_events`, `prices` | The first three tables exist and contain data; `prices` does not exist. No QA router performs this routing. |
| All jobs listed in SPEC schedule | Current scheduler registers only the 30-minute news job. DART functionality is callable/manual but not registered there. |
| `qa_logs` persistence | `qa_logs` does not exist. |
| Private report PDF Storage | `storage.buckets` is empty. |
| Proposed `research_reports`/`research_report_pages` page model | SQL and importer exist in `backend/scripts`, but the actual tables are absent. |
| RLS policies | RLS is enabled on actual public tables, but no `public` or `storage` policies exist. |

This file records observed presence, absence, and differences only; it does not rank or recommend changes.
