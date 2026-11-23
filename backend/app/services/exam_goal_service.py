from app.db.supabase_client import get_supabase_client
from app.services.course_service import _owned
from app.services.subject_service import get_subject


def list_goals(*, user_id: str, subject_id: str) -> dict:
    get_subject(user_id=user_id, subject_id=subject_id)
    client = get_supabase_client()
    result = {}
    for table in ["exam_events", "exam_topic_map", "syllabi", "syllabus_topics"]:
        query = client.table(table).select("*").eq("user_id", user_id).eq("subject_id", subject_id)
        if table == "exam_events": query = query.order("exam_date")
        result[table] = query.execute().data
    return result


def save_event(*, user_id: str, subject_id: str, values: dict, event_id: str | None = None) -> dict:
    get_subject(user_id=user_id, subject_id=subject_id)
    if event_id:
        _owned(table="exam_events", row_id=event_id, user_id=user_id, subject_id=subject_id)
    if values.get("syllabus_id"):
        _owned(table="syllabi", row_id=values["syllabus_id"], user_id=user_id, subject_id=subject_id)
    for topic in values["topics"]:
        _owned(table="knowledge_points", row_id=topic["knowledge_point_id"], user_id=user_id, subject_id=subject_id)
    result = get_supabase_client().rpc("save_course_exam", {"p_user_id": user_id,
        "p_subject_id": subject_id, "p_event_id": event_id, "p_values": values}).execute().data
    return result[0] if isinstance(result, list) else result


def create_syllabus(*, user_id: str, subject_id: str, values: dict) -> dict:
    get_subject(user_id=user_id, subject_id=subject_id)
    for topic_id in values["topic_ids"]:
        _owned(table="knowledge_points", row_id=topic_id, user_id=user_id, subject_id=subject_id)
    result = get_supabase_client().rpc("create_course_syllabus", {"p_user_id": user_id,
        "p_subject_id": subject_id, "p_values": values}).execute().data
    return result[0] if isinstance(result, list) else result
