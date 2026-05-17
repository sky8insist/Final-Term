def evaluate_generation(output: str, contexts: list[dict]) -> dict:
    return {
        "passed": True,
        "score": 0,
        "context_count": len(contexts),
    }
