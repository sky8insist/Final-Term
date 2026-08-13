"""Legacy generator facade kept for callers migrating to specialized services."""


def generate_answer(question: str, contexts: list[dict]) -> str:
    evidence = "\n\n".join(str(item.get("content") or item.get("text") or "") for item in contexts)
    return f"问题：{question}\n\n可用证据：\n{evidence}".strip()


def generate_outline(subject_id: str, contexts: list[dict]) -> dict:
    return {"subject_id": subject_id, "sections": [
        {"title": f"证据 {index + 1}", "content": item.get("content") or item.get("text", "")}
        for index, item in enumerate(contexts)
    ]}


def generate_quiz(subject_id: str, contexts: list[dict], question_count: int) -> dict:
    return {
        "subject_id": subject_id,
        "question_count": question_count,
        "questions": [
            {"stem": f"请解释：{str(item.get('content') or item.get('text', ''))[:120]}", "sourceIndex": index}
            for index, item in enumerate(contexts[:question_count])
        ],
    }
