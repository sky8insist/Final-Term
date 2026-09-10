from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.db.supabase_client import get_supabase_client
from app.models.user import CurrentUser
from app.config.settings import settings

router = APIRouter()


@router.get("/metrics")
def metrics(days: int = Query(7, ge=1, le=90),
            acceptance_run_id: str | None = Query(None, alias="acceptanceRunId"),
            current_user: CurrentUser = Depends(get_current_user)):
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    client = get_supabase_client()
    operation_query = (client.table("operation_metrics").select("*")
                       .eq("user_id", current_user.id).gte("created_at", since))
    model_query = (client.table("model_call_logs").select("*")
                   .eq("user_id", current_user.id).gte("created_at", since))
    if acceptance_run_id:
        operation_query = operation_query.eq("acceptance_run_id", acceptance_run_id)
        model_query = model_query.eq("acceptance_run_id", acceptance_run_id)
    operations = operation_query.execute().data or []
    model_calls = model_query.execute().data or []
    succeeded = sum(row.get("status") == "succeeded" for row in operations)
    stages: dict[str, dict] = {}
    for row in operations:
        key = f"{row.get('operation')}:{row.get('stage') or 'overall'}"
        bucket = stages.setdefault(key, {"count": 0, "durationMs": 0, "failed": 0})
        bucket["count"] += 1
        bucket["durationMs"] += int(row.get("duration_ms") or 0)
        bucket["failed"] += row.get("status") == "failed"
    for bucket in stages.values():
        bucket["averageDurationMs"] = round(bucket["durationMs"] / bucket["count"])
    return {
        "windowDays": days,
        "acceptanceRunId": acceptance_run_id,
        "operations": {
            "total": len(operations), "succeeded": succeeded,
            "successRate": succeeded / len(operations) if operations else None,
            "averageDurationMs": (
                round(sum(int(row.get("duration_ms") or 0) for row in operations) / len(operations))
                if operations else None
            ),
            "stages": stages,
        },
        "models": {
            "calls": len(model_calls),
            "estimatedCost": round(sum(float(row.get("estimated_cost") or 0) for row in model_calls), 6),
            "currency": settings.model_price_currency,
            "estimatedCostUsd": (
                round(sum(float(row.get("estimated_cost") or 0) for row in model_calls), 6)
                if settings.model_price_currency == "USD" else None
            ),
            "inputTokens": sum(int(row.get("input_tokens") or 0) for row in model_calls),
            "outputTokens": sum(int(row.get("output_tokens") or 0) for row in model_calls),
        },
    }
