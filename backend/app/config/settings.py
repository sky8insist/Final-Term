from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    frontend_origin: str = "http://localhost:5173"

    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None
    supabase_jwt_secret: str | None = None
    database_url: str | None = None

    openai_api_key: str | None = Field(default=None, validation_alias="EXAMAI_OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.siliconflow.cn/v1",
        validation_alias="EXAMAI_OPENAI_BASE_URL",
    )
    llm_model: str = Field(
        default="deepseek-ai/DeepSeek-V4-Flash",
        validation_alias="EXAMAI_LLM_MODEL",
    )
    embedding_model: str = Field(
        default="Qwen/Qwen3-VL-Embedding-8B",
        validation_alias="EXAMAI_EMBEDDING_MODEL",
    )

    lightrag_working_dir: str = "backend/data/lightrag"
    default_answer_language: str = "zh-CN"
    max_upload_mb: int = 200

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
