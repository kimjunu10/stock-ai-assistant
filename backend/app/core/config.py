"""Environment-backed application settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
