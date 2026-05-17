from app.services.retrieval_service import search_subject_context


def retrieve_context(user_id: str, subject_id: str, query: str, top_k: int = 5) -> list[dict]:
    result = search_subject_context(
        user_id=user_id,
        subject_id=subject_id,
        question=query,
        top_k=top_k,
    )
    return result["citations"]
