from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.db.supabase_client import get_supabase_client
from app.models.user import CurrentUser

router = APIRouter()


@router.get("/metrics")
def metrics(days: int = Query(7, ge=1, le=90), current_user: CurrentUser = Depends(get_current_user)):
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    client = get_supabase_client()
    operations = (client.table("operation_metrics").select("*")
                  .eq("user_id", current_user.id).gte("created_at", since).execute()).data or []
    model_calls = (client.table("model_call_logs").select("*")
                   .eq("user_id", current_user.id).gte("created_at", since).execute()).data or []
    succeeded = sum(row.get("status") == "succeeded" for row in operations)
    return {
        "windowDays": days,
        "operations": {
            "total": len(operations), "succeeded": succeeded,
            "successRate": succeeded / len(operations) if operations else None,
            "averageDurationMs": (
                round(sum(int(row.get("duration_ms") or 0) for row in operations) / len(operations))
                if operations else None
            ),
        },
        "models": {
            "calls": len(model_calls),
            "estimatedCostUsd": round(sum(float(row.get("estimated_cost") or 0) for row in model_calls), 6),
            "inputTokens": sum(int(row.get("input_tokens") or 0) for row in model_calls),
            "outputTokens": sum(int(row.get("output_tokens") or 0) for row in model_calls),
        },
    }
