from functools import lru_cache

from supabase import Client, create_client

from app.config.settings import settings


@lru_cache
def get_supabase_client() -> Client:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("Supabase URL and service role key must be configured")

    return create_client(settings.supabase_url, settings.supabase_service_role_key)
