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
    news_backfill_batch_size: int = 25
    news_backfill_max_assignment_calls: int = 25
    news_backfill_max_summary_calls: int = 25
    news_backfill_max_cost_usd: float = 1.0
    news_backfill_daily_cost_usd: float = 5.0
    news_backfill_solar_min_interval_seconds: float = 0.25
    toss_request_timeout_seconds: float = 15.0
    toss_market_data_cache_seconds: int = 15

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
