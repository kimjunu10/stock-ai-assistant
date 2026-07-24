"""Environment-backed application settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuration keys required by the fixed backend stack."""

    app_name: str = "Stock Assistant API"
    app_env: str = "local"
    naver_client_id: str = ""
    naver_client_secret: str = ""
    dart_api_key: str = ""
    upstage_api_key: str = ""
    toss_client_id: str = ""
    toss_client_secret: str = ""
    supabase_url: str = ""
    supabase_service_key: str = ""
    # DDL(마이그레이션) 적용 및 검증 SQL 실행용 Postgres 직접 연결 문자열.
    # 서비스 키(PostgREST)로는 DDL을 실행할 수 없어 별도로 받는다.
    database_url: str = ""

    search_display: int = 100
    request_timeout_seconds: float = 15.0
    crawl_delay_seconds: float = 1.2
    user_agent: str = "StockAssistant/0.1 (+news collection prototype)"
    respect_robots: bool = True
    robots_fail_closed: bool = False
    min_body_length: int = 250
    failed_retry_minutes: int = 60
    max_crawl_retries: int = 3
    crawl_batch_size: int = 50
    supabase_batch_size: int = 100
    news_scheduler_enabled: bool = True
    news_scheduler_interval_minutes: int = 30
    news_scheduler_max_per_stock: int = 100
    news_clustering_batch_size: int = 50
    news_clustering_retry_minutes: int = 30
    news_embedding_device: str = "cpu"
    use_llm_assign: bool = True
    sentiment_enabled: bool = True
    sentiment_model_id: str = "FISA-conclave/klue-roberta-news-sentiment"
    sentiment_model_revision: str = "b1950b9499e5f24e1e36593c62720cc1b2326c6b"
    sentiment_model_cache_dir: str = ""
    sentiment_device: str = "auto"
    # 스케줄러 사이클에서 사건 요약(title+easy_explanation+factual_body, Solar 1회 호출)을
    # 생성할지 여부. 서비스 미운영 중에는 False 로 두어 요약 LLM 비용을 아끼고,
    # 나중에 scripts/summarize_v2.py 로 원하는 날짜부터 일괄 요약한다.
    # (동일사건 판정 assign_llm 은 클러스터링에 필수라 이 플래그와 무관하게 유지된다.)
    news_summary_enabled: bool = False
    # 오늘의 핵심 이슈는 변경된 종목들을 한 요청으로 묶어 최대 스케줄러 주기당
    # Solar 1회만 호출한다. 입력 해시가 같으면 호출하지 않는다.
    news_issue_brief_enabled: bool = True
    # 스케줄러 뉴스 사이클(summary/verify) 후 RAG 증분 인덱싱을 자동 실행할지 여부.
    # 실패해도 뉴스 수집/클러스터링을 중단시키지 않는다(예외 격리).
    rag_index_on_schedule: bool = True
    news_backfill_batch_size: int = 25
    news_backfill_max_assignment_calls: int = 25
    news_backfill_max_summary_calls: int = 25
    news_backfill_max_cost_usd: float = 1.0
    news_backfill_daily_cost_usd: float = 5.0
    news_backfill_solar_min_interval_seconds: float = 0.25
    toss_request_timeout_seconds: float = 15.0
    toss_market_data_cache_seconds: int = 15

    # --- RAG (Phase 2+) ---
    upstage_base_url: str = "https://api.upstage.ai/v1"
    rag_embedding_query_model: str = "solar-embedding-2-query"
    rag_embedding_passage_model: str = "solar-embedding-2-passage"
    rag_embedding_dimension: int = 1024
    rag_chat_model: str = "solar-pro3-260323"
    rag_chat_temperature: float = 0.0
    rag_embedding_batch_size: int = 100  # Upstage 배치 최대 100
    rag_request_timeout_seconds: float = 90.0
    rag_retrieval_top_k: int = 8  # 최종 문맥 개수
    rag_retrieval_candidate_k: int = 24  # 의미 검색 후보 개수
    # --- Phase 3 하이브리드 검색 ---
    rag_semantic_candidates: int = 24
    rag_lexical_candidates: int = 24
    rag_rrf_k: int = 50  # RRF 상수 (SPEC 기본)
    rag_max_chunks_per_document: int = 2
    rag_context_char_budget: int = 12000
    # 현재 문서 우선(SPEC §10.4)
    rag_current_doc_candidates: int = 4
    rag_global_candidates: int = 12

    # --- Phase 5.5 Agentic RAG (SPEC §18) ---
    # Agent 경로는 평가 통과 전까지 기본 비활성(라이브 QA 는 기존 결정론적 경로 유지).
    agent_enabled: bool = False
    # Upstage 는 OpenAI 호환 API → langchain-openai ChatOpenAI(base_url) 사용(5.5-A 확정).
    agent_chat_provider: str = "upstage"
    agent_chat_model: str = "solar-pro3-260323"
    agent_max_model_calls: int = 4
    agent_max_tool_calls: int = 5
    agent_max_same_tool_args: int = 1
    agent_tool_retry: int = 1
    agent_timeout_seconds: float = 8.0

    # --- DART 수집 튜닝 (SPEC §4-5) ---
    dart_request_delay_seconds: float = 0.25  # 호출 사이 기본 sleep
    dart_max_backoff_seconds: float = 8.0  # status=020 지수 백오프 상한
    dart_request_timeout_seconds: float = 30.0
    dart_disclosure_lookback_days: int = 365  # 공시 목록/구조화 최근 1년
    dart_financial_years: int = 2  # 재무/정기보고서 최근 2개 사업연도
    # DART document.xml 원본 ZIP 저장 루트. 절대경로를 환경변수로 덮어쓸 수 있다.
    dart_raw_document_dir: str = "data/dart/raw_documents"

    def validate_dart_collection(self) -> None:
        """DART 백필에 필요한 자격 증명이 없으면 즉시 실패."""

        missing = [
            name
            for name, value in (
                ("DART_API_KEY", self.dart_api_key),
                ("SUPABASE_URL", self.supabase_url),
                ("SUPABASE_SERVICE_KEY", self.supabase_service_key),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    def validate_toss_market_data(self) -> None:
        """토스증권 시세 API 호출에 필요한 OAuth 자격증명을 검증한다."""

        missing = [
            name
            for name, value in (
                ("TOSS_CLIENT_ID", self.toss_client_id),
                ("TOSS_CLIENT_SECRET", self.toss_client_secret),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    def validate_news_collection(self) -> None:
        """Fail fast when credentials required by the backfill are missing."""

        missing = [
            name
            for name, value in (
                ("NAVER_CLIENT_ID", self.naver_client_id),
                ("NAVER_CLIENT_SECRET", self.naver_client_secret),
                ("UPSTAGE_API_KEY", self.upstage_api_key),
                ("SUPABASE_URL", self.supabase_url),
                ("SUPABASE_SERVICE_KEY", self.supabase_service_key),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
        if not 1 <= self.search_display <= 100:
            raise RuntimeError("SEARCH_DISPLAY must be between 1 and 100")
        if self.news_scheduler_interval_minutes < 1:
            raise RuntimeError("NEWS_SCHEDULER_INTERVAL_MINUTES must be at least 1")
        if not 1 <= self.news_scheduler_max_per_stock <= 1000:
            raise RuntimeError("NEWS_SCHEDULER_MAX_PER_STOCK must be between 1 and 1000")
        if self.news_clustering_batch_size < 1 or self.news_backfill_batch_size < 1:
            raise RuntimeError("News clustering batch sizes must be positive")
        if self.news_backfill_max_cost_usd <= 0 or self.news_backfill_daily_cost_usd <= 0:
            raise RuntimeError("News backfill cost caps must be positive")


settings = Settings()
