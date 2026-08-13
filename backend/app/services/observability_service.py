import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from time import perf_counter

from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.utils.errors import AppError

logger = logging.getLogger("examai.operations")
request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_context: ContextVar[str | None] = ContextVar("user_id", default=None)


def ensure_model_budget() -> None:
    """Reject paid model work after the authenticated user's daily cap."""
    user_id = user_id_context.get()
    if not user_id or settings.model_call_budget_usd <= 0:
        return
    try:
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        result = (get_supabase_client().table("model_call_logs")
                  .select("estimated_cost").eq("user_id", user_id)
                  .eq("status", "succeeded").gte("created_at", start).execute())
        spent = sum(float(row.get("estimated_cost") or 0) for row in (result.data or []))
    except Exception:
        logger.warning("Could not evaluate model budget; continuing in degraded mode", exc_info=True)
        return
    if spent >= settings.model_call_budget_usd:
        raise AppError(
            f"今日模型预算已用完（上限 ${settings.model_call_budget_usd:.2f}），请明日重试或调整预算",
            status_code=402,
            code="model_budget_exceeded",
            details={"dailyBudgetUsd": settings.model_call_budget_usd, "spentUsd": spent},
        )


def record_model_call(*, capability: str, model_name: str, status: str,
                      started_at: float, usage: dict | None = None,
                      error_code: str | None = None, metadata: dict | None = None,
                      estimated_cost_usd: float | None = None) -> None:
    latency_ms = round((perf_counter() - started_at) * 1000)
    usage = usage or {}
    input_tokens = usage.get("prompt_tokens") or 0
    output_tokens = usage.get("completion_tokens") or 0
    token_estimated_cost = (
        input_tokens * settings.model_input_cost_per_million
        + output_tokens * settings.model_output_cost_per_million
    ) / 1_000_000
    payload = {
        "request_id": request_id_context.get(), "user_id": user_id_context.get(), "capability": capability,
        "provider": "openai-compatible", "model_name": model_name, "status": status,
        "latency_ms": latency_ms, "input_tokens": input_tokens or None,
        "output_tokens": output_tokens or None,
        "estimated_cost": token_estimated_cost if estimated_cost_usd is None else estimated_cost_usd,
        "error_code": error_code,
        "metadata": {"promptVersion": settings.prompt_version, **(metadata or {})},
    }
    logger.info("model_call", extra=payload)
    try:
        get_supabase_client().table("model_call_logs").insert(payload).execute()
    except Exception:
        logger.debug("Model call log persistence unavailable", exc_info=True)


def record_operation(*, operation: str, status: str, started_at: float,
                     task_id: str | None = None, material_id: str | None = None,
                     stage: str | None = None, pages: int | None = None,
                     metadata: dict | None = None) -> None:
    payload = {
        "user_id": user_id_context.get(), "task_id": task_id, "material_id": material_id,
        "operation": operation, "stage": stage, "status": status,
        "duration_ms": round((perf_counter() - started_at) * 1000),
        "pages": pages, "metadata": metadata or {},
    }
    logger.info("operation", extra=payload)
    try:
        get_supabase_client().table("operation_metrics").insert(payload).execute()
    except Exception:
        logger.debug("Operation metric persistence unavailable", exc_info=True)
