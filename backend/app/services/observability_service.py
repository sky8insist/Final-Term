import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from time import perf_counter

from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.utils.errors import AppError

logger = logging.getLogger("examai.operations")
request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
trace_id_context: ContextVar[str | None] = ContextVar("trace_id", default=None)
acceptance_run_id_context: ContextVar[str | None] = ContextVar("acceptance_run_id", default=None)
user_id_context: ContextVar[str | None] = ContextVar("user_id", default=None)


def current_trace_metadata() -> dict[str, str]:
    values = {
        "requestId": request_id_context.get(),
        "traceId": trace_id_context.get(),
        "acceptanceRunId": acceptance_run_id_context.get(),
    }
    return {key: value for key, value in values.items() if value}


def restore_trace_metadata(metadata: dict | None, *, user_id: str | None = None) -> None:
    metadata = metadata or {}
    request_id_context.set(metadata.get("requestId"))
    trace_id_context.set(metadata.get("traceId") or metadata.get("requestId"))
    acceptance_run_id_context.set(metadata.get("acceptanceRunId"))
    user_id_context.set(user_id)


@contextmanager
def bind_trace_metadata(metadata: dict | None, *, user_id: str | None = None):
    metadata = metadata or {}
    tokens = [
        (request_id_context, request_id_context.set(metadata.get("requestId"))),
        (trace_id_context, trace_id_context.set(metadata.get("traceId") or metadata.get("requestId"))),
        (acceptance_run_id_context, acceptance_run_id_context.set(metadata.get("acceptanceRunId"))),
        (user_id_context, user_id_context.set(user_id)),
    ]
    try:
        yield
    finally:
        for context, token in reversed(tokens):
            context.reset(token)


def ensure_model_budget() -> None:
    """Reject paid model work after the authenticated user's daily cap."""
    user_id = user_id_context.get()
    if not user_id or settings.model_call_budget <= 0:
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
    if spent >= settings.model_call_budget:
        raise AppError(
            f"今日模型预算已用完（上限 {settings.model_call_budget:.2f} {settings.model_price_currency}），请明日重试或调整预算",
            status_code=402,
            code="model_budget_exceeded",
            details={"dailyBudget": settings.model_call_budget, "spent": spent,
                     "currency": settings.model_price_currency},
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
    trace_metadata = current_trace_metadata()
    payload = {
        "request_id": request_id_context.get(), "trace_id": trace_id_context.get(),
        "acceptance_run_id": acceptance_run_id_context.get(),
        "user_id": user_id_context.get(), "capability": capability,
        "provider": "openai-compatible", "model_name": model_name, "status": status,
        "latency_ms": latency_ms, "input_tokens": input_tokens or None,
        "output_tokens": output_tokens or None,
        "estimated_cost": token_estimated_cost if estimated_cost_usd is None else estimated_cost_usd,
        "error_code": error_code,
        "metadata": {
            "promptVersion": settings.prompt_version,
            "priceCurrency": settings.model_price_currency,
            **trace_metadata,
            **(metadata or {}),
        },
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
        "request_id": request_id_context.get(), "trace_id": trace_id_context.get(),
        "acceptance_run_id": acceptance_run_id_context.get(),
        "user_id": user_id_context.get(), "task_id": task_id, "material_id": material_id,
        "operation": operation, "stage": stage, "status": status,
        "duration_ms": round((perf_counter() - started_at) * 1000),
        "pages": pages, "metadata": {**current_trace_metadata(), **(metadata or {})},
    }
    logger.info("operation", extra=payload)
    try:
        get_supabase_client().table("operation_metrics").insert(payload).execute()
    except Exception:
        logger.debug("Operation metric persistence unavailable", exc_info=True)


class StageTimer:
    """Persist non-overlapping stage durations for one logical operation."""

    def __init__(self, operation: str, *, task_id: str | None = None,
                 material_id: str | None = None):
        self.operation = operation
        self.task_id = task_id
        self.material_id = material_id
        self.stage: str | None = None
        self.started_at = perf_counter()

    def transition(self, stage: str, *, metadata: dict | None = None) -> None:
        if self.stage is not None and self.stage != stage:
            record_operation(
                operation=self.operation, stage=self.stage, status="succeeded",
                started_at=self.started_at, task_id=self.task_id,
                material_id=self.material_id, metadata=metadata,
            )
        if self.stage != stage:
            self.stage = stage
            self.started_at = perf_counter()

    def finish(self, status: str = "succeeded", *, metadata: dict | None = None) -> None:
        if self.stage is None:
            return
        record_operation(
            operation=self.operation, stage=self.stage, status=status,
            started_at=self.started_at, task_id=self.task_id,
            material_id=self.material_id, metadata=metadata,
        )
        self.stage = None
