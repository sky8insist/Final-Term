from fastapi import HTTPException, status

from app.db.supabase_client import get_supabase_client
from app.models.chat import ChatMessage, Citation
from app.models.review import ReviewProgress
from app.services.subject_service import get_subject


def _to_citation(item: dict) -> dict:
    material_id = item.get("materialId") or item.get("material_id") or ""
    source_name = item.get("sourceName") or item.get("source_name") or item.get("filename") or "Unknown source"
    text = item.get("text") or item.get("chunkText") or item.get("chunk_text") or ""
    citation_id = item.get("id") or f"{material_id}:{item.get('chunkIndex', item.get('chunk_index', 0))}"
    return Citation(
        id=str(citation_id),
        material_id=str(material_id),
        source_name=str(source_name),
        text=str(text),
        score=item.get("score"),
    ).model_dump(by_alias=True)


def normalize_retrieval_citations(citations: list[dict]) -> list[dict]:
    normalized = []
    for item in citations:
        chunk_index = item.get("chunkIndex", item.get("chunk_index", 0))
        source_name = item.get("filename") or item.get("sourceName") or "Unknown source"
        if chunk_index is not None:
            source_name = f"{source_name} #{chunk_index}"
        normalized.append(
            _to_citation(
                {
                    **item,
                    "sourceName": source_name,
                    "text": item.get("chunkText", item.get("text", "")),
                }
            )
        )
    return normalized


def _to_chat_message(row: dict) -> dict:
    citations = [_to_citation(item) for item in row.get("citations", [])]
    return ChatMessage(
        id=row["id"],
        subject_id=row["subject_id"],
        role=row["role"],
        content=row["content"],
        citations=citations,
        created_at=row.get("created_at"),
    ).model_dump(by_alias=True)


def _to_review_progress(row: dict | None, subject_id: str) -> dict:
    if row is None:
        return ReviewProgress(subject_id=subject_id).model_dump(by_alias=True)
    return ReviewProgress(
        subject_id=row["subject_id"],
        mastered_count=row.get("mastered_count", 0),
        total_count=row.get("total_count", 0),
        updated_at=row.get("updated_at"),
    ).model_dump(by_alias=True)


def insert_chat_message(
    *,
    user_id: str,
    subject_id: str,
    role: str,
    content: str,
    citations: list[dict] | None = None,
) -> dict:
    payload = {
        "user_id": user_id,
        "subject_id": subject_id,
        "role": role,
        "content": content.strip(),
        "citations": citations or [],
    }
    response = (
        get_supabase_client()
        .table("chat_messages")
        .insert(payload)
        .select("id,subject_id,role,content,citations,created_at")
        .execute()
    )
    return _to_chat_message(response.data[0])


def record_qa_history(
    *,
    user_id: str,
    subject_id: str,
    question: str,
    answer: str,
    citations: list[dict],
) -> dict:
    insert_chat_message(
        user_id=user_id,
        subject_id=subject_id,
        role="user",
        content=question,
    )
    return insert_chat_message(
        user_id=user_id,
        subject_id=subject_id,
        role="assistant",
        content=answer,
        citations=citations,
    )


def list_chat_history(*, user_id: str, subject_id: str) -> list[dict]:
    get_subject(user_id=user_id, subject_id=subject_id)
    response = (
        get_supabase_client()
        .table("chat_messages")
        .select("id,subject_id,role,content,citations,created_at")
        .eq("user_id", user_id)
        .eq("subject_id", subject_id)
        .order("created_at", desc=False)
        .execute()
    )
    return [_to_chat_message(row) for row in response.data]


def get_review_progress(*, user_id: str, subject_id: str) -> dict:
    get_subject(user_id=user_id, subject_id=subject_id)
    response = (
        get_supabase_client()
        .table("review_progress")
        .select("subject_id,mastered_count,total_count,updated_at")
        .eq("user_id", user_id)
        .eq("subject_id", subject_id)
        .limit(1)
        .execute()
    )
    row = response.data[0] if response.data else None
    return _to_review_progress(row, subject_id)


def update_review_progress(
    *,
    user_id: str,
    subject_id: str,
    mastered_count: int | None = None,
    total_count: int | None = None,
) -> dict:
    current = get_review_progress(user_id=user_id, subject_id=subject_id)
    next_mastered = current["masteredCount"] if mastered_count is None else mastered_count
    next_total = current["totalCount"] if total_count is None else total_count

    if next_mastered < 0 or next_total < 0 or next_mastered > next_total:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Review progress counts must be non-negative and masteredCount cannot exceed totalCount",
        )

    payload = {
        "user_id": user_id,
        "subject_id": subject_id,
        "mastered_count": next_mastered,
        "total_count": next_total,
    }
    response = (
        get_supabase_client()
        .table("review_progress")
        .upsert(payload, on_conflict="user_id,subject_id")
        .select("subject_id,mastered_count,total_count,updated_at")
        .execute()
    )
    return _to_review_progress(response.data[0], subject_id)


def increment_review_total(*, user_id: str, subject_id: str) -> dict:
    current = get_review_progress(user_id=user_id, subject_id=subject_id)
    return update_review_progress(
        user_id=user_id,
        subject_id=subject_id,
        mastered_count=current["masteredCount"],
        total_count=current["totalCount"] + 1,
    )
