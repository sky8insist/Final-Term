def generate_answer(question: str, contexts: list[dict]) -> str:
    return ""


def generate_outline(subject_id: str, contexts: list[dict]) -> dict:
    return {"subject_id": subject_id, "sections": []}


def generate_quiz(subject_id: str, contexts: list[dict], question_count: int) -> dict:
    return {
        "subject_id": subject_id,
        "question_count": question_count,
        "questions": [],
    }
