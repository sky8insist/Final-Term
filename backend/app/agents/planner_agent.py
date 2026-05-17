def plan_review_tasks(subject_id: str, goal: str) -> list[dict]:
    return [
        {
            "subject_id": subject_id,
            "task": goal,
            "status": "pending",
        }
    ]
