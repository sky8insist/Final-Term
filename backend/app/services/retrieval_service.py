from fastapi import HTTPException, status

from app.db.supabase_client import get_supabase_client
from app.services.lightrag_service import extract_chunk_markers, search_context
from app.services.subject_service import get_subject


def _clean_question(question: str) -> str:
    cleaned = question.strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Question is required",
        )
    if len(cleaned) > 4000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Question must be 4000 characters or fewer",
        )
    return cleaned


def _normalize_top_k(top_k: int | None) -> int:
    if top_k is None:
        return 5
    return min(max(top_k, 1), 20)


def _get_subject_embedding_dimension(user_id: str, subject_id: str) -> int:
    client = get_supabase_client()
    response = (
        client.table("material_chunks")
        .select("embedding_dimensions")
        .eq("user_id", user_id)
        .eq("subject_id", subject_id)
        .not_.is_("embedding", "null")
        .limit(1)
        .execute()
    )
    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No indexed material found for this subject",
        )
    dimension = response.data[0].get("embedding_dimensions")
    if not dimension:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No indexed material found for this subject",
        )
    return int(dimension)


def search_subject_context(
    *,
    user_id: str,
    subject_id: str,
    question: str,
    top_k: int | None = None,
) -> dict:
    get_subject(user_id=user_id, subject_id=subject_id)
    cleaned_question = _clean_question(question)
    normalized_top_k = _normalize_top_k(top_k)
    embedding_dimension = _get_subject_embedding_dimension(user_id=user_id, subject_id=subject_id)
    workspace, raw_context = search_context(
        user_id=user_id,
        subject_id=subject_id,
        question=cleaned_question,
        top_k=normalized_top_k,
        embedding_dimension=embedding_dimension,
    )
    citations = extract_chunk_markers(raw_context)
    return {
        "subjectId": subject_id,
        "question": cleaned_question,
        "workspace": workspace,
        "rawContext": raw_context,
        "citations": citations,
    }
