"""Supabase client construction boundary."""

from functools import lru_cache

from supabase import Client, create_client

from app.core.config import settings


def create_supabase_client() -> Client:
    """Create an independent service-role client for a dedicated worker thread."""

    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY are required")
    return create_client(settings.supabase_url, settings.supabase_service_key)


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Return the backend-only service-role Supabase client."""

    return create_supabase_client()
