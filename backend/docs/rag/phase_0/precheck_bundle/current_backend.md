# Current backend (observed 2026-07-22)

Basis: `main` commit `3c014e0e70b6072298fcc2de0e19c3da6957523f` after `git pull --ff-only`.

## FastAPI entry point

- Entry point: `backend/app/main.py`, object `app` (`app.main:app`).
- The application creates `FastAPI(title=settings.app_name, lifespan=lifespan)` and mounts `api_router` under `/api`.
- The lifespan constructs one in-process `AsyncIOScheduler`. It starts only when `NEWS_SCHEDULER_ENABLED` is true and shuts down without waiting when the API process exits.
- Registered route modules: `stocks`, `clusters`, `disclosures`, `financials`, `reports`, and `qa`.
- `backend/app/api/routes/reports.py` and `backend/app/api/routes/qa.py` define routers only; they expose no endpoints.

## Database connection

- `backend/app/db/client.py` uses `supabase.create_client(settings.supabase_url, settings.supabase_service_key)`.
- The normal backend client is a cached, backend-only service-role Supabase client. Worker threads can request independent clients.
- Settings are loaded by `pydantic-settings` from `backend/.env`; values were not copied into this bundle.
- `DATABASE_URL` exists as a separate direct PostgreSQL connection setting for DDL/verification tooling. Runtime repositories use the Supabase Python client/PostgREST boundary.

## Batch structure

- The only job registered by `backend/app/jobs/scheduler.py` is `news-collection`, an interval job (default 30 minutes, Asia/Seoul, one instance, coalescing enabled).
- A news cycle performs: Naver search collection → eligible article crawl → relevance classification → role classification → v2 cluster assignment → Solar factual summary → verification.
- News collection/crawling functions are in `app/jobs/news.py`; orchestration is in `app/jobs/scheduler.py`; clustering service logic is in `app/services/news_clustering.py` and the v2 repository/experiment modules.
- DART functions exist as callable jobs (`disclosures`, `financials`, `dart_major_events`, `dart_regular_facts`, `dart_company_profiles`, `dart_corporate_events`, `dart_corrections`) but are not registered in the current APScheduler builder.
- `backend/scripts/backfill_dart.py` is a manual initial backfill orchestrator. Additional manual completion/verification scripts are under `backend/scripts/`.
- `app/jobs/reports.py` is a one-line placeholder. `app/jobs/prices.py` is also a placeholder; current stock market HTTP routes call the Toss adapter directly.

## News, DART, and report files

### News

- Sources: `app/sources/naver_news.py`, `crawler.py`, `publishers.py`, `news_utils.py`.
- Jobs/services: `app/jobs/news.py`, `app/jobs/scheduler.py`, `app/services/relevance.py`, `news_clustering.py`, `news_backfill.py`.
- Persistence: `app/repositories/news.py`, `news_clusters.py`, `news_v2.py`.
- Current production clustering uses local `BAAI/bge-m3`, pinned revision `5617a9f61b028005a4858fdac845db406aefb181`, 1024 dimensions, normalized `title + description` input. Solar model `solar-pro3-260323` is used for same-event decisions and factual summaries.

### DART

- API/document sources: `app/sources/dart.py`, `dart_documents.py`, `dart_parsing.py`, `dart_financials.py`, `dart_major_events.py`, `dart_regular_facts.py`, `dart_company.py`, `dart_events.py`.
- Jobs: `app/jobs/disclosures.py`, `financials.py`, `dart_major_events.py`, `dart_regular_facts.py`, `dart_structured.py`, `dart_company_profiles.py`, `dart_corporate_events.py`, `dart_corrections.py`.
- Persistence: `app/repositories/dart.py`.

### Research reports

- `app/sources/naver_research.py`, `app/jobs/reports.py`, and `app/api/routes/reports.py` are placeholders.
- `scripts/import_research_reports.py` contains a local PDF inventory/import utility with a dry-run default.
- `scripts/research_reports_schema.sql` contains a proposed private Storage bucket plus `research_reports`/`research_report_pages` schema, but those objects do not exist in the actual database.

## QA, retrieval, chunking, and embedding state

- `app/api/routes/qa.py`: router only, no `POST /api/qa` implementation.
- `app/rag/chunking.py`, `indexing.py`, `retrieval.py`, and `prompting.py`: docstring-only placeholders.
- `app/ml/embeddings.py` and `app/ml/generation.py`: docstring-only Upstage boundary placeholders.
- There is no implemented RAG chunk persistence, query embedding, pgvector retrieval, hybrid retrieval, source citation assembly, SSE answer generation, multi-turn rewrite, term lookup, or QA logging.
- The implemented BGE-M3 embedding path is for news-event clustering, not RAG. It stores 1024-element centroids as PostgreSQL `double precision[]` in `news_clusters`.
- Experimental code contains an Upstage embedding helper using legacy `embedding-passage`, but it is not wired to application RAG routes or database indexing.

## Direct packages and observed versions

Versions below are installed in `backend/.venv` and satisfy `backend/pyproject.toml`; `backend/uv.lock` is present.

| Package | Version |
|---|---:|
| apscheduler | 3.11.3 |
| beautifulsoup4 | 4.15.0 |
| fastapi | 0.139.2 |
| numpy | 2.5.1 |
| pydantic-settings | 2.14.2 |
| requests | 2.34.2 |
| sentence-transformers | 5.6.0 |
| supabase | 2.31.0 |
| torch | 2.13.0 |
| trafilatura | 2.1.0 |
| uvicorn | 0.51.0 |
| httpx (dev) | 0.28.1 |
| pytest (dev) | 8.4.2 |
| ruff (dev) | 0.15.22 |
