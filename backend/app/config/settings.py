from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    mock_external_apis: bool = False
    mock_embedding_dimensions: int = 1024
    frontend_origin: str = "http://localhost:5173"

    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None
    supabase_jwt_secret: str | None = None
    database_url: str | None = None

    openai_api_key: str | None = Field(default=None, validation_alias="EXAMAI_OPENAI_API_KEY")
    model_provider: str = Field(default="openai_compatible", validation_alias="EXAMAI_MODEL_PROVIDER")
    model_provider_trust_env: bool = Field(
        default=False,
        validation_alias="EXAMAI_MODEL_PROVIDER_TRUST_ENV",
    )
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
    vision_model: str = Field(default="Qwen/Qwen2.5-VL-72B-Instruct", validation_alias="EXAMAI_VISION_MODEL")
    transcription_model: str = Field(default="FunAudioLLM/SenseVoiceSmall", validation_alias="EXAMAI_TRANSCRIPTION_MODEL")
    max_audio_minutes: int = 180
    audio_segment_seconds: int = 600
    audio_silence_threshold_db: float = -35.0
    audio_min_silence_seconds: float = 0.7

    lightrag_working_dir: str = "backend/data/lightrag"
    # Knowledge-graph extraction is an optional enhancement. Bound it so a
    # slow model provider cannot keep an otherwise searchable material stuck.
    lightrag_index_timeout_seconds: float = Field(default=180.0, gt=0)
    default_answer_language: str = "zh-CN"
    max_upload_mb: int = 200

    # MinerU is the primary parser for documents and images. Local parsers are
    # retained as a guarded fallback so a provider outage does not strand an
    # uploaded material.
    enable_mineru: bool = True
    mineru_api_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MINERU_API_TOKEN", "MINERU_AB_TOKEN"),
    )
    mineru_base_url: str = "https://mineru.net"
    mineru_model_version: str = "pipeline"
    mineru_language: str = "ch"
    mineru_enable_table: bool = True
    mineru_enable_formula: bool = True
    mineru_poll_interval_seconds: float = 3.0
    mineru_timeout_seconds: int = 900
    mineru_transport_retries: int = 3
    mineru_max_result_mb: int = 300
    mineru_max_unpacked_mb: int = 800
    mineru_native_coverage_threshold: float = 0.95
    mineru_page_coverage_threshold: float = 0.90
    mineru_enable_local_fallback: bool = True

    # Feature flags keep unfinished capabilities explicit and make test/dev
    # environments deterministic while the application is expanded.
    enable_hermes_memory: bool = True
    enable_external_knowledge: bool = False
    enable_wikipedia_fallback: bool = True
    wikipedia_language: str = "zh"

    request_id_header: str = "X-Request-ID"
    trace_id_header: str = "X-Trace-ID"
    acceptance_run_id_header: str = "X-Acceptance-Run-ID"
    redis_url: str = "redis://localhost:6379/0"
    celery_task_always_eager: bool = False
    material_storage_bucket: str = "study-materials"
    task_max_retries: int = 3
    assistant_memory_char_limit: int = 1400
    user_profile_char_limit: int = 900
    web_search_url: str | None = Field(default=None, validation_alias="EXAMAI_WEB_SEARCH_URL")
    web_search_api_key: str | None = Field(default=None, validation_alias="EXAMAI_WEB_SEARCH_API_KEY")
    web_search_max_results: int = 5
    wikipedia_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    web_search_timeout_seconds: float = Field(default=6.0, gt=0, le=60)
    exam_batch_size: int = Field(default=4, ge=1, le=8)
    exam_retrieval_timeout_seconds: float = Field(default=30.0, gt=5, le=120)
    exam_batch_timeout_seconds: float = Field(default=60.0, gt=5, le=180)
    exam_batch_retries: int = Field(default=1, ge=0, le=2)
    max_active_tasks_per_user: int = 3
    max_daily_upload_mb: int = 1000
    original_file_retention_days: int = 90
    model_call_budget: float = Field(
        default=35.0,
        validation_alias=AliasChoices("MODEL_CALL_BUDGET", "MODEL_CALL_BUDGET_USD"),
    )
    model_input_cost_per_million: float = 1.0
    model_output_cost_per_million: float = 2.0
    embedding_cost_per_million: float = 0.7
    model_price_currency: str = "CNY"
    vision_cost_per_call: float = 0.0
    transcription_cost_per_minute: float = 0.0
    prompt_version: str = "1.0.0"

    # Dayend V3 is deliberately isolated from the existing exam-assistant
    # routing. `demo` may simulate outputs; `multi_agent` never falls back to
    # rules when an LLM invocation fails.
    dayend_mode: str = Field(default="demo", validation_alias="DAYEND_MODE")
    dayend_checkpoint_path: str = Field(
        default="backend/data/dayend/checkpoints.sqlite",
        validation_alias="DAYEND_CHECKPOINT_PATH",
    )
    dayend_store_path: str = Field(
        default="backend/data/dayend/business.sqlite",
        validation_alias="DAYEND_STORE_PATH",
    )
    dayend_persistence_backend: str = Field(
        default="sqlite", validation_alias="DAYEND_PERSISTENCE_BACKEND",
    )
    dayend_model: str | None = Field(default=None, validation_alias="DAYEND_LLM_MODEL")
    # All Dayend agents use the existing SiliconFlow OpenAI-compatible API.
    # These overrides permit quality/cost routing without introducing another provider.
    dayend_orchestrator_model: str | None = Field(default=None, validation_alias="DAYEND_ORCHESTRATOR_MODEL")
    dayend_specialist_model: str | None = Field(default=None, validation_alias="DAYEND_SPECIALIST_MODEL")
    dayend_critic_model: str | None = Field(default=None, validation_alias="DAYEND_CRITIC_MODEL")
    dayend_safety_model: str | None = Field(default=None, validation_alias="DAYEND_SAFETY_MODEL")
    dayend_max_retries: int = Field(default=2, ge=0, le=5, validation_alias="DAYEND_MAX_RETRIES")
    dayend_agent_timeout_seconds: float = Field(
        default=120.0, gt=0, le=300, validation_alias="DAYEND_AGENT_TIMEOUT_SECONDS",
    )

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
