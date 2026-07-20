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
    supabase_url: str = ""
    supabase_service_key: str = ""

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

    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    def validate_news_collection(self) -> None:
        """Fail fast when credentials required by the backfill are missing."""

        missing = [
            name
            for name, value in (
                ("NAVER_CLIENT_ID", self.naver_client_id),
                ("NAVER_CLIENT_SECRET", self.naver_client_secret),
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


settings = Settings()
