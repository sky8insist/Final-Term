from fastapi import HTTPException, status

from app.db.supabase_client import get_supabase_client


def _to_subject(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row.get("description"),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _clean_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Subject name is required",
        )
    if len(cleaned) > 120:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Subject name must be 120 characters or fewer",
        )
    return cleaned


def _clean_description(description: str | None) -> str | None:
    if description is None:
        return None

    cleaned = description.strip()
    if not cleaned:
        return None
    if len(cleaned) > 1000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Subject description must be 1000 characters or fewer",
        )
    return cleaned


def list_subjects(user_id: str) -> list[dict]:
    client = get_supabase_client()
    response = (
        client.table("subjects")
        .select("id,name,description,created_at,updated_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return [_to_subject(row) for row in response.data]


def get_subject(user_id: str, subject_id: str) -> dict:
    client = get_supabase_client()
    response = (
        client.table("subjects")
        .select("id,name,description,created_at,updated_at")
        .eq("id", subject_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subject not found",
        )

    return _to_subject(response.data[0])


def create_subject(user_id: str, name: str, description: str | None = None) -> dict:
    client = get_supabase_client()
    payload = {
        "user_id": user_id,
        "name": _clean_name(name),
        "description": _clean_description(description),
    }
    response = (
        client.table("subjects")
        .insert(payload)
        .select("id,name,description,created_at,updated_at")
        .execute()
    )
    return _to_subject(response.data[0])


def update_subject(
    user_id: str,
    subject_id: str,
    name: str | None = None,
    description: str | None = None,
) -> dict:
    get_subject(user_id=user_id, subject_id=subject_id)

    payload: dict = {}
    if name is not None:
        payload["name"] = _clean_name(name)
    if description is not None:
        payload["description"] = _clean_description(description)

    if not payload:
        return get_subject(user_id=user_id, subject_id=subject_id)

    client = get_supabase_client()
    response = (
        client.table("subjects")
        .update(payload)
        .eq("id", subject_id)
        .eq("user_id", user_id)
        .select("id,name,description,created_at,updated_at")
        .execute()
    )

    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subject not found",
        )

    return _to_subject(response.data[0])


def delete_subject(user_id: str, subject_id: str) -> None:
    get_subject(user_id=user_id, subject_id=subject_id)
    client = get_supabase_client()
    client.table("subjects").delete().eq("id", subject_id).eq("user_id", user_id).execute()
