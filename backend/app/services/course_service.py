from fastapi import HTTPException

from app.db.supabase_client import get_supabase_client
from app.services.subject_service import get_subject


def resolve_topic(*, client, user_id: str, subject_id: str, title: str, details: dict | None = None) -> dict:
    """The DB resolves aliases atomically and never overwrites a display name."""
    params = {
        "p_user_id": user_id, "p_subject_id": subject_id, "p_title": title,
    }
    if details is not None:
        params["p_details"] = details
    result = client.rpc("resolve_course_topic", params).execute().data
    return result[0] if isinstance(result, list) else result


def _owned(*, table: str, row_id: str, user_id: str, subject_id: str) -> dict:
    rows = (get_supabase_client().table(table).select("*").eq("id", row_id)
            .eq("user_id", user_id).eq("subject_id", subject_id).limit(1).execute().data)
    if not rows:
        raise HTTPException(404, "课程对象不存在")
    return rows[0]


def get_structure(*, user_id: str, subject_id: str) -> dict:
    get_subject(user_id=user_id, subject_id=subject_id)
    client = get_supabase_client()
    return {
        "units": client.table("knowledge_units").select("*").eq("user_id", user_id)
            .eq("subject_id", subject_id).order("sequence_index").order("created_at").execute().data,
        "topics": client.table("knowledge_points").select("*").eq("user_id", user_id)
            .eq("subject_id", subject_id).order("sequence_index").order("created_at").execute().data,
    }


def create_unit(*, user_id: str, subject_id: str, values: dict) -> dict:
    get_subject(user_id=user_id, subject_id=subject_id)
    return get_supabase_client().table("knowledge_units").insert({
        **values, "user_id": user_id, "subject_id": subject_id,
    }).select("*").execute().data[0]


def update_unit(*, user_id: str, subject_id: str, unit_id: str, values: dict) -> dict:
    _owned(table="knowledge_units", row_id=unit_id, user_id=user_id, subject_id=subject_id)
    return (get_supabase_client().table("knowledge_units").update(values).eq("id", unit_id)
            .eq("user_id", user_id).eq("subject_id", subject_id).select("*").execute().data[0])


def create_topic(*, user_id: str, subject_id: str, values: dict) -> dict:
    get_subject(user_id=user_id, subject_id=subject_id)
    if values.get("unit_id"):
        _owned(table="knowledge_units", row_id=values["unit_id"], user_id=user_id, subject_id=subject_id)
    client = get_supabase_client()
    topic = resolve_topic(client=client, user_id=user_id, subject_id=subject_id, title=values["title"], details=values)
    # Idempotent creation must not reset existing user metadata or unarchive it.
    return topic


def update_topic(*, user_id: str, subject_id: str, topic_id: str, values: dict) -> dict:
    current = _owned(table="knowledge_points", row_id=topic_id, user_id=user_id, subject_id=subject_id)
    if values.get("unit_id"):
        _owned(table="knowledge_units", row_id=values["unit_id"], user_id=user_id, subject_id=subject_id)
    if not values:
        return current
    client = get_supabase_client()
    if "title" in values and values["title"] != current["title"]:
        # Renames retain old aliases, preventing future generations from duplicating the topic.
        normalized = " ".join(values["title"].strip().lower().split())
        rows = (client.table("topic_aliases").select("knowledge_point_id").eq("user_id", user_id)
                .eq("subject_id", subject_id).eq("alias", normalized).execute().data)
        if rows and rows[0]["knowledge_point_id"] != topic_id:
            raise HTTPException(409, "该名称已属于另一个知识点")
        if not rows:
            try:
                client.table("topic_aliases").insert({"user_id": user_id, "subject_id": subject_id,
                    "alias": normalized, "knowledge_point_id": topic_id}).execute()
            except Exception as exc:
                if getattr(exc, "code", None) == "23505":
                    raise HTTPException(409, "知识点名称已被使用，请刷新后重试") from exc
                raise
    return (client.table("knowledge_points").update(values).eq("id", topic_id)
            .eq("user_id", user_id).eq("subject_id", subject_id).select("*").execute().data[0])
