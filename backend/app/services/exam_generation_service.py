from app.services.generation_task_service import create_generation_task as _create_generation_task


def create_generation_task(*, user_id: str, payload) -> dict:
    return _create_generation_task(
        user_id=user_id, payload=payload,
        task_type="exam_generation",
        idempotency_prefix="exam", result_metadata={"examId": None},
    )
