def evaluate_answer(question: str, answer: str, context: list[str]) -> dict:
    return {
        "score": 0,
        "question": question,
        "answer": answer,
        "context_count": len(context),
    }
