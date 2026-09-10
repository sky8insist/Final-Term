from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, TypeVar

from pydantic import BaseModel

from app.config.settings import settings
from app.runtime.model_factory import get_dayend_model, get_dayend_model_name
from app.schemas.common import AgentEnvelope, AgentMeta, AgentRunFailed, AgentTrace


T = TypeVar("T", bound=BaseModel)


def _token_usage(raw: Any) -> dict[str, Any] | None:
    """Normalize provider usage without treating unavailable usage as zero."""
    if raw is None:
        return None
    usage = getattr(raw, "usage_metadata", None)
    if usage is None:
        metadata = getattr(raw, "response_metadata", None) or {}
        usage = metadata.get("token_usage") or metadata.get("usage")
    if usage is None and isinstance(raw, dict):
        usage = raw.get("usage_metadata") or (raw.get("response_metadata") or {}).get("token_usage")
    if not usage:
        return None
    return dict(usage) if hasattr(usage, "items") else None


async def invoke_structured_agent(
    *, agent_name: str, schema: type[T], system_prompt: str, user_prompt: str,
    run_id: str, input_refs: list[str], tools: list[Any] | None = None,
) -> tuple[AgentEnvelope[T], AgentTrace]:
    """Invoke one specialist independently and validate its native structured output."""
    started_at = datetime.now(timezone.utc)
    started = perf_counter()
    tool_calls = [tool.name for tool in (tools or [])]
    model_name = get_dayend_model_name(agent_name)
    last_error: Exception | None = None
    for attempt in range(1, settings.dayend_max_retries + 2):
        try:
            model = get_dayend_model(agent_name)
            # Tools are bound to the agent runtime (and surfaced in the trace).
            # Structured output remains schema-native instead of regex/JSON repair.
            if tools:
                model = model.bind_tools(tools)
            # include_raw retains provider metadata such as token usage while the
            # parsed Pydantic result remains the only value exposed to agents.
            result = await asyncio.wait_for(
                model.with_structured_output(schema, include_raw=True).ainvoke([
                    ("system", system_prompt), ("user", user_prompt),
                ]),
                timeout=settings.dayend_agent_timeout_seconds,
            )
            raw = result.get("raw") if isinstance(result, dict) else None
            if isinstance(result, dict) and result.get("parsing_error"):
                raise result["parsing_error"]
            result = result.get("parsed") if isinstance(result, dict) else result
            if not isinstance(result, schema):
                result = schema.model_validate(result)
            envelope = AgentEnvelope[T](
                meta=AgentMeta(agent_name=agent_name, run_id=run_id, model=model_name, attempt=attempt),
                data=result, confidence=getattr(result, "confidence", 1.0),
            )
            return envelope, AgentTrace(
                agent=agent_name, started_at=started_at, ended_at=datetime.now(timezone.utc),
                duration_ms=round((perf_counter() - started) * 1000), attempt=attempt,
                input_refs=input_refs, output_schema=schema.__name__, tool_calls=tool_calls,
                status="success", token_usage=_token_usage(raw),
            )
        except Exception as exc:  # provider/schema errors must be visible, never rule-fallback.
            last_error = exc
    failure_type = type(last_error).__name__ if last_error else "UnknownError"
    trace = AgentTrace(
        agent=agent_name, started_at=started_at, ended_at=datetime.now(timezone.utc),
        duration_ms=round((perf_counter() - started) * 1000), attempt=settings.dayend_max_retries + 1,
        input_refs=input_refs, output_schema=schema.__name__, tool_calls=tool_calls, status="failed",
        failure_type=failure_type,
    )
    reason = "timeout" if isinstance(last_error, TimeoutError) else "provider_or_schema_error"
    raise AgentRunFailed(f"{agent_name} failed after retries ({reason})", trace=trace, failure_type=failure_type) from last_error
