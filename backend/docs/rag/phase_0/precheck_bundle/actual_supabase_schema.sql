-- ACTUAL SUPABASE SCHEMA SNAPSHOT
-- Observed read-only on 2026-07-22; no migration or write was executed.
-- Scope: public schema tables, columns, constraints, indexes, triggers, functions, and RLS state.
-- Database-wide extensions: pg_stat_statements 1.11, pgcrypto 1.3, plpgsql 1.0,
--   supabase_vault 0.3.1, uuid-ossp 1.1. The vector/pgvector extension is NOT installed.
-- RLS policies in public or storage: none.
-- Supabase Storage bucket names: none (storage.buckets returned zero rows).
-- This is a schema-only dump. It contains no API keys, connection strings, or data rows.

--
-- PostgreSQL database dump
--


-- Dumped from database version 17.6
-- Dumped by pg_dump version 17.6

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA public;


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS 'standard public schema';


--
-- Name: claim_news_backfill_pair(text, bigint, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.claim_news_backfill_pair(p_run_key text, p_article_id bigint, p_stock_code text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
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


--
-- Name: repair_news_backfill_dirty_clusters(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.repair_news_backfill_dirty_clusters(p_run_key text) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
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


--
-- Name: set_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO ''
    AS $$
begin
    new.updated_at = now();
    return new;
end;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: article_stocks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.article_stocks (
    article_id bigint NOT NULL,
    stock_code text NOT NULL,
    matched_query text,
    relevance text DEFAULT 'pending'::text NOT NULL,
    mention_count integer DEFAULT 0 NOT NULL,
    relevance_reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    article_role text,
    event_eligible boolean,
    role_reason text,
    role_source text,
    role_version text,
    event_signature jsonb,
    role_classified_at timestamp with time zone,
    CONSTRAINT article_stocks_article_role_check CHECK ((article_role = ANY (ARRAY['company_event'::text, 'opinion'::text, 'market_summary'::text, 'price_reaction'::text, 'background'::text, 'incidental'::text, 'unrelated'::text]))),
    CONSTRAINT article_stocks_mention_count_check CHECK ((mention_count >= 0)),
    CONSTRAINT article_stocks_relevance_check CHECK ((relevance = ANY (ARRAY['pending'::text, 'relevant'::text, 'irrelevant'::text]))),
    CONSTRAINT article_stocks_role_source_check CHECK ((role_source = ANY (ARRAY['rule'::text, 'llm'::text])))
);


--
-- Name: articles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.articles (
    id bigint NOT NULL,
    canonical_url text NOT NULL,
    original_url text NOT NULL,
    naver_url text,
    final_url text,
    title text NOT NULL,
    description text,
    body text,
    press text,
    published_at timestamp with time zone NOT NULL,
    crawl_status text DEFAULT 'pending'::text NOT NULL,
    crawl_attempts integer DEFAULT 0 NOT NULL,
    last_attempt_at timestamp with time zone,
    next_retry_at timestamp with time zone,
    fail_reason text,
    http_status integer,
    crawled_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    image_url text,
    CONSTRAINT articles_crawl_attempts_check CHECK ((crawl_attempts >= 0)),
    CONSTRAINT articles_crawl_status_check CHECK ((crawl_status = ANY (ARRAY['pending'::text, 'processing'::text, 'success'::text, 'failed'::text, 'skipped'::text]))),
    CONSTRAINT articles_http_status_check CHECK (((http_status >= 100) AND (http_status <= 599)))
);


--
-- Name: articles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.articles ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.articles_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: company_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.company_profiles (
    stock_code text NOT NULL,
    corp_name text,
    corp_name_eng text,
    stock_name text,
    ceo_nm text,
    corp_cls text,
    jurir_no text,
    bizr_no text,
    adres text,
    hm_url text,
    ir_url text,
    phn_no text,
    fax_no text,
    induty_code text,
    est_dt date,
    acc_mt text,
    raw_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: corporate_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.corporate_events (
    id bigint NOT NULL,
    stock_code text NOT NULL,
    event_type text NOT NULL,
    title text NOT NULL,
    announced_at timestamp with time zone,
    event_date date,
    event_end_date date,
    start_time time without time zone,
    end_time time without time zone,
    location text,
    amount bigint,
    status text DEFAULT 'scheduled'::text NOT NULL,
    rcept_no text NOT NULL,
    supersedes_rcept_no text,
    source_url text,
    normalized_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    raw_text text,
    parse_status text DEFAULT 'success'::text NOT NULL,
    parse_error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: corporate_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.corporate_events ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.corporate_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: dart_collection_api_results; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dart_collection_api_results (
    id bigint NOT NULL,
    run_id bigint NOT NULL,
    stock_code text NOT NULL,
    data_group text NOT NULL,
    source_api text NOT NULL,
    request_key text NOT NULL,
    result_status text NOT NULL,
    dart_status text,
    row_count integer DEFAULT 0 NOT NULL,
    error text,
    requested_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: dart_collection_api_results_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.dart_collection_api_results ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.dart_collection_api_results_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: dart_collection_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dart_collection_runs (
    id bigint NOT NULL,
    run_key text NOT NULL,
    mode text NOT NULL,
    status text DEFAULT 'running'::text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    stats jsonb DEFAULT '{}'::jsonb NOT NULL,
    error text
);


--
-- Name: dart_collection_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.dart_collection_runs ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.dart_collection_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: disclosures; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.disclosures (
    id bigint NOT NULL,
    stock_code text NOT NULL,
    rcept_no text NOT NULL,
    title text NOT NULL,
    disclosed_at timestamp with time zone,
    disclosure_type text,
    is_correction boolean DEFAULT false NOT NULL,
    viewer_url text,
    raw_text text,
    raw_text_truncated boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    raw_document_path text,
    raw_text_length bigint,
    content_hash text,
    parse_status text DEFAULT 'pending'::text NOT NULL,
    parse_error text,
    original_rcept_no text,
    supersedes_rcept_no text,
    is_latest boolean DEFAULT true NOT NULL,
    correction_status text DEFAULT 'original'::text NOT NULL,
    CONSTRAINT disclosures_correction_status_check CHECK ((correction_status = ANY (ARRAY['original'::text, 'correction'::text, 'cancelled'::text, 'withdrawn'::text]))),
    CONSTRAINT disclosures_parse_status_check CHECK ((parse_status = ANY (ARRAY['pending'::text, 'success'::text, 'failed'::text, 'not_selected'::text, 'unavailable'::text])))
);


--
-- Name: disclosures_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.disclosures ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.disclosures_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: financials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.financials (
    id bigint NOT NULL,
    stock_code text NOT NULL,
    bsns_year text NOT NULL,
    reprt_code text NOT NULL,
    fs_div text NOT NULL,
    account_nm text NOT NULL,
    thstrm_amount bigint,
    frmtrm_amount bigint,
    amount_type text DEFAULT 'quarter'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT financials_amount_type_check CHECK ((amount_type = ANY (ARRAY['quarter'::text, 'cumulative'::text, 'point_in_time'::text])))
);


--
-- Name: financials_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.financials ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.financials_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: news_article_processing; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.news_article_processing (
    article_id bigint NOT NULL,
    kind text,
    status text NOT NULL,
    retry_count integer DEFAULT 0 NOT NULL,
    next_retry_at timestamp with time zone,
    last_error text,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT news_article_processing_kind_check CHECK ((kind = ANY (ARRAY['company'::text, 'market'::text, 'info'::text]))),
    CONSTRAINT news_article_processing_retry_count_check CHECK ((retry_count >= 0)),
    CONSTRAINT news_article_processing_status_check CHECK ((status = ANY (ARRAY['processing'::text, 'completed'::text, 'pending_retry'::text])))
);


--
-- Name: news_backfill_dirty_clusters; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.news_backfill_dirty_clusters (
    run_key text NOT NULL,
    cluster_id bigint NOT NULL,
    status text DEFAULT 'dirty'::text NOT NULL,
    retry_count integer DEFAULT 0 NOT NULL,
    claimed_at timestamp with time zone,
    next_retry_at timestamp with time zone,
    last_error text,
    summarized_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT news_backfill_dirty_clusters_retry_count_check CHECK ((retry_count >= 0)),
    CONSTRAINT news_backfill_dirty_clusters_status_check CHECK ((status = ANY (ARRAY['dirty'::text, 'processing'::text, 'success'::text, 'pending_retry'::text])))
);


--
-- Name: news_backfill_pair_claims; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.news_backfill_pair_claims (
    article_id bigint NOT NULL,
    stock_code text NOT NULL,
    run_key text NOT NULL,
    status text DEFAULT 'processing'::text NOT NULL,
    claimed_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    last_error text,
    CONSTRAINT news_backfill_pair_claims_status_check CHECK ((status = ANY (ARRAY['processing'::text, 'completed'::text, 'pending_retry'::text])))
);


--
-- Name: news_backfill_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.news_backfill_runs (
    run_key text NOT NULL,
    status text NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    last_success_article_id bigint,
    last_success_stock_code text,
    last_success_published_at timestamp with time zone,
    processed_articles integer DEFAULT 0 NOT NULL,
    processed_pairs integer DEFAULT 0 NOT NULL,
    completed_articles integer DEFAULT 0 NOT NULL,
    pending_retry_articles integer DEFAULT 0 NOT NULL,
    assignment_calls integer DEFAULT 0 NOT NULL,
    summary_calls integer DEFAULT 0 NOT NULL,
    prompt_tokens bigint DEFAULT 0 NOT NULL,
    completion_tokens bigint DEFAULT 0 NOT NULL,
    estimated_cost_usd numeric(12,6) DEFAULT 0 NOT NULL,
    limits jsonb DEFAULT '{}'::jsonb NOT NULL,
    totals jsonb DEFAULT '{}'::jsonb NOT NULL,
    last_error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT news_backfill_runs_assignment_calls_check CHECK ((assignment_calls >= 0)),
    CONSTRAINT news_backfill_runs_completed_articles_check CHECK ((completed_articles >= 0)),
    CONSTRAINT news_backfill_runs_completion_tokens_check CHECK ((completion_tokens >= 0)),
    CONSTRAINT news_backfill_runs_estimated_cost_usd_check CHECK ((estimated_cost_usd >= (0)::numeric)),
    CONSTRAINT news_backfill_runs_pending_retry_articles_check CHECK ((pending_retry_articles >= 0)),
    CONSTRAINT news_backfill_runs_processed_articles_check CHECK ((processed_articles >= 0)),
    CONSTRAINT news_backfill_runs_processed_pairs_check CHECK ((processed_pairs >= 0)),
    CONSTRAINT news_backfill_runs_prompt_tokens_check CHECK ((prompt_tokens >= 0)),
    CONSTRAINT news_backfill_runs_status_check CHECK ((status = ANY (ARRAY['planned'::text, 'running'::text, 'stopped_budget'::text, 'stopped'::text, 'completed'::text, 'failed'::text]))),
    CONSTRAINT news_backfill_runs_summary_calls_check CHECK ((summary_calls >= 0))
);


--
-- Name: news_cluster_assignments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.news_cluster_assignments (
    article_id bigint NOT NULL,
    stock_code text NOT NULL,
    cluster_id bigint,
    kind text NOT NULL,
    status text NOT NULL,
    llm_called boolean DEFAULT false NOT NULL,
    candidate_count integer DEFAULT 0 NOT NULL,
    assignment_reason text,
    error_code text,
    prompt_version text,
    retry_count integer DEFAULT 0 NOT NULL,
    next_retry_at timestamp with time zone,
    assigned_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT news_cluster_assignments_candidate_count_check CHECK ((candidate_count >= 0)),
    CONSTRAINT news_cluster_assignments_check CHECK ((((status = 'pending_retry'::text) AND (cluster_id IS NULL) AND (next_retry_at IS NOT NULL)) OR ((status <> 'pending_retry'::text) AND (cluster_id IS NOT NULL) AND (next_retry_at IS NULL)))),
    CONSTRAINT news_cluster_assignments_kind_check CHECK ((kind = ANY (ARRAY['company'::text, 'market'::text, 'info'::text]))),
    CONSTRAINT news_cluster_assignments_retry_count_check CHECK ((retry_count >= 0)),
    CONSTRAINT news_cluster_assignments_status_check CHECK ((status = ANY (ARRAY['assigned_new'::text, 'assigned_existing'::text, 'pending_retry'::text])))
);


--
-- Name: news_clusters; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.news_clusters (
    id bigint NOT NULL,
    stock_code text NOT NULL,
    kind text NOT NULL,
    anchor_article_id bigint NOT NULL,
    representative_article_id bigint NOT NULL,
    centroid double precision[] NOT NULL,
    article_count integer DEFAULT 1 NOT NULL,
    first_published_at timestamp with time zone NOT NULL,
    last_active_at timestamp with time zone NOT NULL,
    clustering_version text NOT NULL,
    summary_title text,
    factual_body text,
    summary_status text DEFAULT 'pending'::text NOT NULL,
    summary_prompt_version text,
    summary_error text,
    summary_retry_count integer DEFAULT 0 NOT NULL,
    summary_next_retry_at timestamp with time zone,
    summarized_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    easy_explanation text,
    event_signature jsonb,
    CONSTRAINT news_clusters_article_count_check CHECK ((article_count > 0)),
    CONSTRAINT news_clusters_kind_check CHECK ((kind = ANY (ARRAY['company'::text, 'market'::text, 'info'::text]))),
    CONSTRAINT news_clusters_summary_retry_count_check CHECK ((summary_retry_count >= 0)),
    CONSTRAINT news_clusters_summary_status_check CHECK ((summary_status = ANY (ARRAY['pending'::text, 'success'::text, 'pending_retry'::text])))
);


--
-- Name: COLUMN news_clusters.easy_explanation; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.news_clusters.easy_explanation IS 'Beginner-friendly explanation shown between the cluster title and factual event write-up.';


--
-- Name: news_clusters_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.news_clusters ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.news_clusters_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: news_pipeline_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.news_pipeline_state (
    id integer DEFAULT 1 NOT NULL,
    active_version text DEFAULT 'bge_m3_title_desc_centroid_bridge_info_v3'::text NOT NULL,
    active_run_key text,
    activated_at timestamp with time zone,
    previous_version text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT news_pipeline_state_id_check CHECK ((id = 1))
);


--
-- Name: news_role_claims; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.news_role_claims (
    article_id bigint NOT NULL,
    stock_code text NOT NULL,
    run_key text NOT NULL,
    status text DEFAULT 'processing'::text NOT NULL,
    retry_count integer DEFAULT 0 NOT NULL,
    claimed_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    last_error text,
    CONSTRAINT news_role_claims_retry_count_check CHECK ((retry_count >= 0)),
    CONSTRAINT news_role_claims_status_check CHECK ((status = ANY (ARRAY['processing'::text, 'completed'::text, 'pending_retry'::text])))
);


--
-- Name: stocks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stocks (
    code text NOT NULL,
    name text NOT NULL,
    aliases text[] DEFAULT '{}'::text[] NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    dart_corp_code text,
    CONSTRAINT stocks_code_check CHECK ((code ~ '^[0-9]{6}$'::text))
);


--
-- Name: structured_disclosures; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.structured_disclosures (
    id bigint NOT NULL,
    stock_code text NOT NULL,
    rcept_no text,
    data_group text NOT NULL,
    source_api text NOT NULL,
    event_type text NOT NULL,
    announced_at timestamp with time zone,
    bsns_year text,
    reprt_code text,
    record_key text NOT NULL,
    normalized_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    raw_data jsonb NOT NULL,
    summary_text text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT structured_disclosures_data_group_check CHECK ((data_group = ANY (ARRAY['major_event'::text, 'regular_report'::text])))
);


--
-- Name: structured_disclosures_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.structured_disclosures ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.structured_disclosures_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: article_stocks article_stocks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_stocks
    ADD CONSTRAINT article_stocks_pkey PRIMARY KEY (article_id, stock_code);


--
-- Name: articles articles_canonical_url_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.articles
    ADD CONSTRAINT articles_canonical_url_key UNIQUE (canonical_url);


--
-- Name: articles articles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.articles
    ADD CONSTRAINT articles_pkey PRIMARY KEY (id);


--
-- Name: company_profiles company_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_profiles
    ADD CONSTRAINT company_profiles_pkey PRIMARY KEY (stock_code);


--
-- Name: corporate_events corporate_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.corporate_events
    ADD CONSTRAINT corporate_events_pkey PRIMARY KEY (id);


--
-- Name: corporate_events corporate_events_stock_code_event_type_rcept_no_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.corporate_events
    ADD CONSTRAINT corporate_events_stock_code_event_type_rcept_no_key UNIQUE (stock_code, event_type, rcept_no);


--
-- Name: dart_collection_api_results dart_collection_api_results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dart_collection_api_results
    ADD CONSTRAINT dart_collection_api_results_pkey PRIMARY KEY (id);


--
-- Name: dart_collection_api_results dart_collection_api_results_run_id_stock_code_data_group_so_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dart_collection_api_results
    ADD CONSTRAINT dart_collection_api_results_run_id_stock_code_data_group_so_key UNIQUE (run_id, stock_code, data_group, source_api, request_key);


--
-- Name: dart_collection_runs dart_collection_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dart_collection_runs
    ADD CONSTRAINT dart_collection_runs_pkey PRIMARY KEY (id);


--
-- Name: dart_collection_runs dart_collection_runs_run_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dart_collection_runs
    ADD CONSTRAINT dart_collection_runs_run_key_key UNIQUE (run_key);


--
-- Name: disclosures disclosures_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disclosures
    ADD CONSTRAINT disclosures_pkey PRIMARY KEY (id);


--
-- Name: disclosures disclosures_rcept_no_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disclosures
    ADD CONSTRAINT disclosures_rcept_no_key UNIQUE (rcept_no);


--
-- Name: financials financials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.financials
    ADD CONSTRAINT financials_pkey PRIMARY KEY (id);


--
-- Name: financials financials_stock_code_bsns_year_reprt_code_fs_div_account_n_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.financials
    ADD CONSTRAINT financials_stock_code_bsns_year_reprt_code_fs_div_account_n_key UNIQUE (stock_code, bsns_year, reprt_code, fs_div, account_nm, amount_type);


--
-- Name: news_article_processing news_article_processing_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_article_processing
    ADD CONSTRAINT news_article_processing_pkey PRIMARY KEY (article_id);


--
-- Name: news_backfill_dirty_clusters news_backfill_dirty_clusters_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_backfill_dirty_clusters
    ADD CONSTRAINT news_backfill_dirty_clusters_pkey PRIMARY KEY (run_key, cluster_id);


--
-- Name: news_backfill_pair_claims news_backfill_pair_claims_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_backfill_pair_claims
    ADD CONSTRAINT news_backfill_pair_claims_pkey PRIMARY KEY (article_id, stock_code);


--
-- Name: news_backfill_runs news_backfill_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_backfill_runs
    ADD CONSTRAINT news_backfill_runs_pkey PRIMARY KEY (run_key);


--
-- Name: news_cluster_assignments news_cluster_assignments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_cluster_assignments
    ADD CONSTRAINT news_cluster_assignments_pkey PRIMARY KEY (article_id, stock_code);


--
-- Name: news_clusters news_clusters_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_clusters
    ADD CONSTRAINT news_clusters_pkey PRIMARY KEY (id);


--
-- Name: news_pipeline_state news_pipeline_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_pipeline_state
    ADD CONSTRAINT news_pipeline_state_pkey PRIMARY KEY (id);


--
-- Name: news_role_claims news_role_claims_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_role_claims
    ADD CONSTRAINT news_role_claims_pkey PRIMARY KEY (article_id, stock_code);


--
-- Name: stocks stocks_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stocks
    ADD CONSTRAINT stocks_name_key UNIQUE (name);


--
-- Name: stocks stocks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stocks
    ADD CONSTRAINT stocks_pkey PRIMARY KEY (code);


--
-- Name: structured_disclosures structured_disclosures_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structured_disclosures
    ADD CONSTRAINT structured_disclosures_pkey PRIMARY KEY (id);


--
-- Name: structured_disclosures structured_disclosures_stock_code_source_api_record_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structured_disclosures
    ADD CONSTRAINT structured_disclosures_stock_code_source_api_record_key_key UNIQUE (stock_code, source_api, record_key);


--
-- Name: article_stocks_event_eligible_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX article_stocks_event_eligible_idx ON public.article_stocks USING btree (stock_code, event_eligible, article_role) WHERE (event_eligible IS TRUE);


--
-- Name: article_stocks_role_pending_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX article_stocks_role_pending_idx ON public.article_stocks USING btree (relevance, article_role) WHERE (relevance = 'relevant'::text);


--
-- Name: article_stocks_stock_relevance_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX article_stocks_stock_relevance_idx ON public.article_stocks USING btree (stock_code, relevance, article_id);


--
-- Name: articles_crawl_queue_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX articles_crawl_queue_idx ON public.articles USING btree (crawl_status, next_retry_at, created_at) WHERE (crawl_status = ANY (ARRAY['pending'::text, 'failed'::text]));


--
-- Name: articles_published_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX articles_published_at_idx ON public.articles USING btree (published_at DESC);


--
-- Name: corporate_events_stock_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX corporate_events_stock_date_idx ON public.corporate_events USING btree (stock_code, event_date DESC);


--
-- Name: dart_collection_api_results_lookup_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dart_collection_api_results_lookup_idx ON public.dart_collection_api_results USING btree (stock_code, data_group, source_api, requested_at DESC);


--
-- Name: disclosures_latest_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX disclosures_latest_idx ON public.disclosures USING btree (stock_code, is_latest, disclosed_at DESC);


--
-- Name: disclosures_original_rcept_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX disclosures_original_rcept_idx ON public.disclosures USING btree (original_rcept_no, disclosed_at);


--
-- Name: disclosures_parse_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX disclosures_parse_status_idx ON public.disclosures USING btree (parse_status, raw_text_truncated);


--
-- Name: disclosures_stock_disclosed_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX disclosures_stock_disclosed_idx ON public.disclosures USING btree (stock_code, disclosed_at DESC);


--
-- Name: financials_stock_year_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX financials_stock_year_idx ON public.financials USING btree (stock_code, bsns_year, reprt_code);


--
-- Name: news_article_processing_retry_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX news_article_processing_retry_idx ON public.news_article_processing USING btree (status, next_retry_at) WHERE (status = 'pending_retry'::text);


--
-- Name: news_backfill_dirty_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX news_backfill_dirty_status_idx ON public.news_backfill_dirty_clusters USING btree (run_key, status, cluster_id);


--
-- Name: news_backfill_runs_started_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX news_backfill_runs_started_idx ON public.news_backfill_runs USING btree (started_at DESC);


--
-- Name: news_cluster_assignments_cluster_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX news_cluster_assignments_cluster_idx ON public.news_cluster_assignments USING btree (cluster_id, assigned_at) WHERE (cluster_id IS NOT NULL);


--
-- Name: news_cluster_assignments_retry_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX news_cluster_assignments_retry_idx ON public.news_cluster_assignments USING btree (status, next_retry_at) WHERE (status = 'pending_retry'::text);


--
-- Name: news_clusters_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX news_clusters_active_idx ON public.news_clusters USING btree (stock_code, kind, last_active_at DESC);


--
-- Name: news_clusters_summary_retry_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX news_clusters_summary_retry_idx ON public.news_clusters USING btree (summary_status, summary_next_retry_at) WHERE (summary_status = ANY (ARRAY['pending'::text, 'pending_retry'::text]));


--
-- Name: news_role_claims_run_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX news_role_claims_run_status_idx ON public.news_role_claims USING btree (run_key, status);


--
-- Name: structured_disclosures_group_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX structured_disclosures_group_idx ON public.structured_disclosures USING btree (stock_code, data_group, source_api);


--
-- Name: article_stocks article_stocks_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER article_stocks_set_updated_at BEFORE UPDATE ON public.article_stocks FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: articles articles_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER articles_set_updated_at BEFORE UPDATE ON public.articles FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: company_profiles company_profiles_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER company_profiles_set_updated_at BEFORE UPDATE ON public.company_profiles FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: corporate_events corporate_events_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER corporate_events_set_updated_at BEFORE UPDATE ON public.corporate_events FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: disclosures disclosures_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER disclosures_set_updated_at BEFORE UPDATE ON public.disclosures FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: financials financials_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER financials_set_updated_at BEFORE UPDATE ON public.financials FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: news_article_processing news_article_processing_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER news_article_processing_set_updated_at BEFORE UPDATE ON public.news_article_processing FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: news_backfill_dirty_clusters news_backfill_dirty_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER news_backfill_dirty_set_updated_at BEFORE UPDATE ON public.news_backfill_dirty_clusters FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: news_backfill_runs news_backfill_runs_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER news_backfill_runs_set_updated_at BEFORE UPDATE ON public.news_backfill_runs FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: news_cluster_assignments news_cluster_assignments_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER news_cluster_assignments_set_updated_at BEFORE UPDATE ON public.news_cluster_assignments FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: news_clusters news_clusters_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER news_clusters_set_updated_at BEFORE UPDATE ON public.news_clusters FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: news_pipeline_state news_pipeline_state_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER news_pipeline_state_set_updated_at BEFORE UPDATE ON public.news_pipeline_state FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: stocks stocks_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER stocks_set_updated_at BEFORE UPDATE ON public.stocks FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: structured_disclosures structured_disclosures_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER structured_disclosures_set_updated_at BEFORE UPDATE ON public.structured_disclosures FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: article_stocks article_stocks_article_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_stocks
    ADD CONSTRAINT article_stocks_article_id_fkey FOREIGN KEY (article_id) REFERENCES public.articles(id) ON DELETE CASCADE;


--
-- Name: article_stocks article_stocks_stock_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.article_stocks
    ADD CONSTRAINT article_stocks_stock_code_fkey FOREIGN KEY (stock_code) REFERENCES public.stocks(code) ON DELETE CASCADE;


--
-- Name: company_profiles company_profiles_stock_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_profiles
    ADD CONSTRAINT company_profiles_stock_code_fkey FOREIGN KEY (stock_code) REFERENCES public.stocks(code) ON DELETE CASCADE;


--
-- Name: corporate_events corporate_events_rcept_no_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.corporate_events
    ADD CONSTRAINT corporate_events_rcept_no_fkey FOREIGN KEY (rcept_no) REFERENCES public.disclosures(rcept_no) ON DELETE CASCADE;


--
-- Name: corporate_events corporate_events_stock_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.corporate_events
    ADD CONSTRAINT corporate_events_stock_code_fkey FOREIGN KEY (stock_code) REFERENCES public.stocks(code) ON DELETE CASCADE;


--
-- Name: dart_collection_api_results dart_collection_api_results_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dart_collection_api_results
    ADD CONSTRAINT dart_collection_api_results_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.dart_collection_runs(id) ON DELETE CASCADE;


--
-- Name: dart_collection_api_results dart_collection_api_results_stock_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dart_collection_api_results
    ADD CONSTRAINT dart_collection_api_results_stock_code_fkey FOREIGN KEY (stock_code) REFERENCES public.stocks(code) ON DELETE CASCADE;


--
-- Name: disclosures disclosures_original_rcept_no_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disclosures
    ADD CONSTRAINT disclosures_original_rcept_no_fkey FOREIGN KEY (original_rcept_no) REFERENCES public.disclosures(rcept_no) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;


--
-- Name: disclosures disclosures_stock_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disclosures
    ADD CONSTRAINT disclosures_stock_code_fkey FOREIGN KEY (stock_code) REFERENCES public.stocks(code) ON DELETE CASCADE;


--
-- Name: disclosures disclosures_supersedes_rcept_no_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disclosures
    ADD CONSTRAINT disclosures_supersedes_rcept_no_fkey FOREIGN KEY (supersedes_rcept_no) REFERENCES public.disclosures(rcept_no) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;


--
-- Name: financials financials_stock_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.financials
    ADD CONSTRAINT financials_stock_code_fkey FOREIGN KEY (stock_code) REFERENCES public.stocks(code) ON DELETE CASCADE;


--
-- Name: news_article_processing news_article_processing_article_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_article_processing
    ADD CONSTRAINT news_article_processing_article_id_fkey FOREIGN KEY (article_id) REFERENCES public.articles(id) ON DELETE CASCADE;


--
-- Name: news_backfill_dirty_clusters news_backfill_dirty_clusters_cluster_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_backfill_dirty_clusters
    ADD CONSTRAINT news_backfill_dirty_clusters_cluster_id_fkey FOREIGN KEY (cluster_id) REFERENCES public.news_clusters(id) ON DELETE CASCADE;


--
-- Name: news_backfill_dirty_clusters news_backfill_dirty_clusters_run_key_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_backfill_dirty_clusters
    ADD CONSTRAINT news_backfill_dirty_clusters_run_key_fkey FOREIGN KEY (run_key) REFERENCES public.news_backfill_runs(run_key) ON DELETE CASCADE;


--
-- Name: news_backfill_pair_claims news_backfill_pair_claims_article_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_backfill_pair_claims
    ADD CONSTRAINT news_backfill_pair_claims_article_id_fkey FOREIGN KEY (article_id) REFERENCES public.articles(id) ON DELETE CASCADE;


--
-- Name: news_backfill_pair_claims news_backfill_pair_claims_run_key_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_backfill_pair_claims
    ADD CONSTRAINT news_backfill_pair_claims_run_key_fkey FOREIGN KEY (run_key) REFERENCES public.news_backfill_runs(run_key) ON DELETE CASCADE;


--
-- Name: news_backfill_pair_claims news_backfill_pair_claims_stock_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_backfill_pair_claims
    ADD CONSTRAINT news_backfill_pair_claims_stock_code_fkey FOREIGN KEY (stock_code) REFERENCES public.stocks(code) ON DELETE CASCADE;


--
-- Name: news_backfill_runs news_backfill_runs_last_success_article_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_backfill_runs
    ADD CONSTRAINT news_backfill_runs_last_success_article_id_fkey FOREIGN KEY (last_success_article_id) REFERENCES public.articles(id) ON DELETE SET NULL;


--
-- Name: news_backfill_runs news_backfill_runs_last_success_stock_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_backfill_runs
    ADD CONSTRAINT news_backfill_runs_last_success_stock_code_fkey FOREIGN KEY (last_success_stock_code) REFERENCES public.stocks(code) ON DELETE SET NULL;


--
-- Name: news_cluster_assignments news_cluster_assignments_article_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_cluster_assignments
    ADD CONSTRAINT news_cluster_assignments_article_id_fkey FOREIGN KEY (article_id) REFERENCES public.articles(id) ON DELETE CASCADE;


--
-- Name: news_cluster_assignments news_cluster_assignments_cluster_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_cluster_assignments
    ADD CONSTRAINT news_cluster_assignments_cluster_id_fkey FOREIGN KEY (cluster_id) REFERENCES public.news_clusters(id) ON DELETE CASCADE;


--
-- Name: news_cluster_assignments news_cluster_assignments_stock_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_cluster_assignments
    ADD CONSTRAINT news_cluster_assignments_stock_code_fkey FOREIGN KEY (stock_code) REFERENCES public.stocks(code) ON DELETE CASCADE;


--
-- Name: news_clusters news_clusters_anchor_article_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_clusters
    ADD CONSTRAINT news_clusters_anchor_article_id_fkey FOREIGN KEY (anchor_article_id) REFERENCES public.articles(id) ON DELETE RESTRICT;


--
-- Name: news_clusters news_clusters_representative_article_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_clusters
    ADD CONSTRAINT news_clusters_representative_article_id_fkey FOREIGN KEY (representative_article_id) REFERENCES public.articles(id) ON DELETE RESTRICT;


--
-- Name: news_clusters news_clusters_stock_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_clusters
    ADD CONSTRAINT news_clusters_stock_code_fkey FOREIGN KEY (stock_code) REFERENCES public.stocks(code) ON DELETE CASCADE;


--
-- Name: news_role_claims news_role_claims_article_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_role_claims
    ADD CONSTRAINT news_role_claims_article_id_fkey FOREIGN KEY (article_id) REFERENCES public.articles(id) ON DELETE CASCADE;


--
-- Name: news_role_claims news_role_claims_stock_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.news_role_claims
    ADD CONSTRAINT news_role_claims_stock_code_fkey FOREIGN KEY (stock_code) REFERENCES public.stocks(code) ON DELETE CASCADE;


--
-- Name: structured_disclosures structured_disclosures_stock_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structured_disclosures
    ADD CONSTRAINT structured_disclosures_stock_code_fkey FOREIGN KEY (stock_code) REFERENCES public.stocks(code) ON DELETE CASCADE;


--
-- Name: article_stocks; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.article_stocks ENABLE ROW LEVEL SECURITY;

--
-- Name: articles; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.articles ENABLE ROW LEVEL SECURITY;

--
-- Name: company_profiles; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.company_profiles ENABLE ROW LEVEL SECURITY;

--
-- Name: corporate_events; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.corporate_events ENABLE ROW LEVEL SECURITY;

--
-- Name: dart_collection_api_results; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.dart_collection_api_results ENABLE ROW LEVEL SECURITY;

--
-- Name: dart_collection_runs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.dart_collection_runs ENABLE ROW LEVEL SECURITY;

--
-- Name: disclosures; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.disclosures ENABLE ROW LEVEL SECURITY;

--
-- Name: financials; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.financials ENABLE ROW LEVEL SECURITY;

--
-- Name: news_article_processing; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.news_article_processing ENABLE ROW LEVEL SECURITY;

--
-- Name: news_backfill_dirty_clusters; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.news_backfill_dirty_clusters ENABLE ROW LEVEL SECURITY;

--
-- Name: news_backfill_pair_claims; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.news_backfill_pair_claims ENABLE ROW LEVEL SECURITY;

--
-- Name: news_backfill_runs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.news_backfill_runs ENABLE ROW LEVEL SECURITY;

--
-- Name: news_cluster_assignments; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.news_cluster_assignments ENABLE ROW LEVEL SECURITY;

--
-- Name: news_clusters; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.news_clusters ENABLE ROW LEVEL SECURITY;

--
-- Name: news_pipeline_state; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.news_pipeline_state ENABLE ROW LEVEL SECURITY;

--
-- Name: news_role_claims; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.news_role_claims ENABLE ROW LEVEL SECURITY;

--
-- Name: stocks; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.stocks ENABLE ROW LEVEL SECURITY;

--
-- Name: structured_disclosures; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.structured_disclosures ENABLE ROW LEVEL SECURITY;

--
-- PostgreSQL database dump complete
--
