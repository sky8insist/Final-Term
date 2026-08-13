import hashlib
import re
import unicodedata
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status

from app.config.settings import settings
from app.db.supabase_client import get_supabase_client

MEMORY_SELECT = "id,subject_id,target,content,confidence,importance,source_event_id,last_used_at,created_at,updated_at"
WRITE_SELECT = "id,subject_id,action,target,memory_entry_id,old_text,content,confidence,importance,source_event_id,reason,status,created_at,resolved_at"
SUSPICIOUS_PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in (
        r"ignore (all|any|the) previous instructions", r"system prompt", r"developer message",
        r"api[_ -]?key\s*[:=]", r"password\s*[:=]", r"ssh-rsa", r"BEGIN (RSA|OPENSSH) PRIVATE KEY",
    )
]
SENSITIVE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in (
        r"\b1[3-9]\d{9}\b", r"\b\d{17}[\dXx]\b",
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        r"(身份证|护照|住址|家庭地址|病史|诊断|宗教|政治面貌|性取向)",
    )
]


def _hash(content: str) -> str:
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()


def _similarity(left: str, right: str) -> float:
    def grams(value: str) -> set[str]:
        compact = re.sub(r"\s+", "", value.casefold())
        return {compact[index:index + 2] for index in range(max(len(compact) - 1, 1))}
    a, b = grams(left), grams(right)
    return len(a & b) / max(len(a | b), 1)


def _polarity(value: str) -> int:
    negative = bool(re.search(r"(不|没|无|避免|禁止|讨厌|不能|不要|never|not|avoid)", value, re.IGNORECASE))
    return -1 if negative else 1


def _semantic_candidate(*, client, user_id: str, target: str,
                        cleaned: str, entries: list[dict]) -> tuple[dict | None, list[float] | None]:
    try:
        from app.services.embedding_service import embed_texts
        vector = embed_texts([cleaned])[0]
        literal = "[" + ",".join(str(float(value)) for value in vector) + "]"
        rows = client.rpc("find_similar_memory", {
            "query_embedding": literal, "target_user_id": user_id,
            "target_memory_target": target, "result_limit": 3,
        }).execute().data or []
        if rows and float(rows[0].get("similarity", 0)) >= 0.88:
            match = next((entry for entry in entries if entry["id"] == str(rows[0]["id"])), None)
            return match, vector
        return None, vector
    except Exception:
        return None, None


def _scan(content: str) -> str:
    cleaned = content.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="Memory content is required")
    if any(unicodedata.category(char) == "Cf" for char in cleaned):
        raise HTTPException(status_code=422, detail="Memory contains unsafe invisible characters")
    if any(pattern.search(cleaned) for pattern in SUSPICIOUS_PATTERNS):
        raise HTTPException(status_code=422, detail="Memory content failed security scanning")
    return cleaned


def list_memories(*, user_id: str, target: str | None = None, subject_id: str | None = None) -> list[dict]:
    query = get_supabase_client().table("memory_entries").select(MEMORY_SELECT).eq("user_id", user_id)
    if target:
        query = query.eq("target", target)
    if subject_id:
        query = query.eq("subject_id", subject_id)
    return query.order("importance", desc=True).order("updated_at", desc=True).execute().data


def _capacity(target: str) -> int:
    return settings.assistant_memory_char_limit if target == "assistant_memory" else settings.user_profile_char_limit


def _used_chars(entries: list[dict]) -> int:
    return sum(len(entry.get("content", "")) for entry in entries) + max(len(entries) - 1, 0)


def _find_unique_entry(entries: list[dict], old_text: str) -> dict:
    matches = [entry for entry in entries if old_text in entry["content"]]
    if not matches:
        raise HTTPException(status_code=404, detail="No memory matched oldText")
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="oldText matched multiple memories; use a more specific substring")
    return matches[0]


def _apply_write(*, user_id: str, action: str, target: str, subject_id: str | None,
                 old_text: str | None, content: str | None, confidence: float,
                 importance: int = 50, source_event_id: str | None = None) -> dict:
    client = get_supabase_client()
    entries = list_memories(user_id=user_id, target=target)
    if action == "remove":
        entry = _find_unique_entry(entries, (old_text or "").strip())
        client.table("memory_entries").delete().eq("id", entry["id"]).eq("user_id", user_id).execute()
        return {"action": action, "removedId": entry["id"], "target": target}
    cleaned = _scan(content or "")
    duplicate = next((entry for entry in entries if _hash(entry["content"]) == _hash(cleaned)), None)
    if duplicate:
        return {"action": action, "entry": duplicate, "duplicate": True}
    replaced = None
    semantic, embedding = _semantic_candidate(
        client=client, user_id=user_id, target=target, cleaned=cleaned, entries=entries,
    )
    if action == "add":
        similar = semantic or max(entries, key=lambda entry: _similarity(entry["content"], cleaned), default=None)
        if similar and _similarity(similar["content"], cleaned) >= 0.72:
            # Consolidate overlapping facts into one information-dense entry.
            replaced = similar
            action = "replace"
            if similar["content"] not in cleaned and cleaned not in similar["content"]:
                cleaned = f"{similar['content']}；{cleaned}"
    used = _used_chars(entries)
    if action == "replace":
        replaced = replaced or _find_unique_entry(entries, (old_text or "").strip())
        used -= len(replaced["content"])
    projected = used + len(cleaned)
    if projected > int(_capacity(target) * 0.8):
        # Hermes-style core memory stays curated. Prefer removing lower-value
        # entries over allowing an unbounded prompt prefix.
        candidates = sorted(
            (entry for entry in entries if not replaced or entry["id"] != replaced["id"]),
            key=lambda entry: (int(entry.get("importance", 50)), float(entry.get("confidence", 0.5))),
        )
        for entry in candidates:
            if projected <= int(_capacity(target) * 0.8):
                break
            if int(entry.get("importance", 50)) >= importance:
                continue
            client.table("memory_entries").delete().eq("id", entry["id"]).eq("user_id", user_id).execute()
            projected -= len(entry["content"]) + 1
        used = projected - len(cleaned)
    if used + len(cleaned) > _capacity(target):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Memory capacity exceeded; consolidate or remove entries first", "used": used,
                    "limit": _capacity(target), "currentEntries": entries},
        )
    payload = {"user_id": user_id, "subject_id": subject_id, "target": target,
               "content": cleaned, "content_hash": _hash(cleaned), "confidence": confidence,
               "importance": importance, "source_event_id": source_event_id}
    if embedding:
        payload.update({
            "embedding": "[" + ",".join(str(float(value)) for value in embedding) + "]",
            "embedding_model": settings.embedding_model,
            "embedding_dimensions": len(embedding),
        })
    if replaced:
        response = client.table("memory_entries").update(payload).eq("id", replaced["id"]).eq("user_id", user_id).select(MEMORY_SELECT).execute()
    else:
        response = client.table("memory_entries").insert(payload).select(MEMORY_SELECT).execute()
    return {"action": action, "entry": response.data[0], "duplicate": False}


def request_write(*, user_id: str, action: str, target: str, subject_id: str | None,
                  old_text: str | None, content: str | None, confidence: float,
                  importance: int, reason: str | None, require_approval: bool | None,
                  source_event_id: str | None = None) -> dict:
    profile = get_profile(user_id=user_id)
    if not profile.get("memoryEnabled", True) and action != "remove":
        return {"status": "disabled", "reason": "Long-term memory is disabled"}
    must_approve = profile.get("writeApproval", False) if require_approval is None else require_approval
    if confidence < 0.7 or target == "user_profile" and confidence < 0.9:
        must_approve = True
    if content and any(pattern.search(content) for pattern in SENSITIVE_PATTERNS):
        must_approve = True
    if action == "add" and content and not must_approve:
        existing = list_memories(user_id=user_id, target=target)
        similar = max(existing, key=lambda item: _similarity(item["content"], content), default=None)
        if similar and _similarity(similar["content"], content) >= 0.55 and _polarity(similar["content"]) != _polarity(content):
            must_approve = True
    if content:
        _scan(content)
    if not must_approve:
        return {"status": "applied", **_apply_write(
            user_id=user_id, action=action, target=target, subject_id=subject_id,
            old_text=old_text, content=content, confidence=confidence, importance=importance,
            source_event_id=source_event_id,
        )}
    response = get_supabase_client().table("memory_write_requests").insert({
        "user_id": user_id, "subject_id": subject_id, "action": action, "target": target,
        "old_text": old_text, "content": content, "confidence": confidence, "reason": reason,
        "importance": importance, "source_event_id": source_event_id,
    }).select(WRITE_SELECT).execute()
    return {"status": "pending", "request": response.data[0]}


def list_pending_writes(*, user_id: str) -> list[dict]:
    return get_supabase_client().table("memory_write_requests").select(WRITE_SELECT).eq("user_id", user_id).eq("status", "pending").order("created_at").execute().data


def resolve_write(*, user_id: str, request_id: str, approve: bool) -> dict:
    client = get_supabase_client()
    response = client.table("memory_write_requests").select(WRITE_SELECT).eq("id", request_id).eq("user_id", user_id).eq("status", "pending").limit(1).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Pending memory write not found")
    item = response.data[0]
    result = None
    if approve:
        result = _apply_write(
            user_id=user_id, action=item["action"], target=item["target"], subject_id=item.get("subject_id"),
            old_text=item.get("old_text"), content=item.get("content"), confidence=item.get("confidence", 1),
            importance=item.get("importance", 50), source_event_id=item.get("source_event_id"),
        )
    state = "approved" if approve else "rejected"
    client.table("memory_write_requests").update({"status": state, "resolved_at": datetime.now(UTC).isoformat()}).eq("id", request_id).eq("user_id", user_id).execute()
    return {"status": state, "result": result}


def create_snapshot(*, user_id: str, session_id: str, subject_id: str | None = None) -> dict:
    UUID(session_id)
    client = get_supabase_client()
    existing = client.table("memory_snapshots").select("*").eq("user_id", user_id).eq("session_id", session_id).limit(1).execute()
    if existing.data:
        if subject_id and existing.data[0].get("subject_id") not in {None, subject_id}:
            raise HTTPException(status_code=409, detail="Session is already bound to a different subject")
        return existing.data[0]
    profile = get_profile(user_id=user_id)
    entries = list_memories(user_id=user_id) if profile.get("memoryEnabled", True) else []
    if subject_id:
        entries = [entry for entry in entries if entry.get("subject_id") in {None, subject_id}]
    assistant = "\n§\n".join(entry["content"] for entry in entries if entry["target"] == "assistant_memory")
    user = "\n§\n".join(entry["content"] for entry in entries if entry["target"] == "user_profile")
    payload = {"user_id": user_id, "subject_id": subject_id, "session_id": session_id,
               "assistant_memory": assistant, "user_profile": user,
               "assistant_chars": len(assistant), "user_chars": len(user)}
    response = client.table("memory_snapshots").insert(payload).select("*").execute()
    return response.data[0]


def get_profile(*, user_id: str) -> dict:
    client = get_supabase_client()
    response = client.table("learner_profiles").select("*").eq("user_id", user_id).limit(1).execute()
    if not response.data:
        response = client.table("learner_profiles").insert({"user_id": user_id}).select("*").execute()
    row = response.data[0]
    return {"userId": row["user_id"], "displayName": row.get("display_name"), "timezone": row.get("timezone"),
            "level": row.get("level"), "preferredRole": row.get("preferred_role"),
            "responseStyle": row.get("response_style"), "dailyMinutes": row.get("daily_minutes"),
            "examDate": row.get("exam_date"), "memoryEnabled": row.get("memory_enabled", True),
            "writeApproval": row.get("write_approval", False), "metadata": row.get("metadata", {})}


def update_profile(*, user_id: str, changes: dict) -> dict:
    mapping = {"display_name": "display_name", "timezone": "timezone", "level": "level",
               "preferred_role": "preferred_role", "response_style": "response_style",
               "daily_minutes": "daily_minutes", "exam_date": "exam_date",
               "memory_enabled": "memory_enabled", "write_approval": "write_approval"}
    payload = {column: value for field, column in mapping.items() if (value := changes.get(field)) is not None}
    payload["user_id"] = user_id
    get_supabase_client().table("learner_profiles").upsert(payload, on_conflict="user_id").execute()
    return get_profile(user_id=user_id)


def search_sessions(*, user_id: str, query: str, limit: int = 10) -> list[dict]:
    cleaned = query.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="Search query is required")
    parameters = {
        "query_text": cleaned, "target_user_id": user_id,
        "result_limit": min(max(limit, 1), 50), "query_embedding": None,
    }
    try:
        from app.services.embedding_service import embed_texts
        vector = embed_texts([cleaned])[0]
        parameters["query_embedding"] = "[" + ",".join(str(float(value)) for value in vector) + "]"
    except Exception:
        # Keyword/trigram history search remains available during embedding outages.
        pass
    return get_supabase_client().rpc("search_learning_sessions", parameters).execute().data


def list_active_skills(*, user_id: str, subject_id: str | None = None, limit: int = 3) -> list[dict]:
    query = (
        get_supabase_client().table("procedural_skills").select("*")
        .eq("user_id", user_id).eq("status", "active")
    )
    rows = query.order("confidence", desc=True).limit(min(max(limit, 1), 10)).execute().data
    return [row for row in rows if row.get("subject_id") in {None, subject_id}]


def memory_usage(*, user_id: str) -> dict:
    entries = list_memories(user_id=user_id)
    result = {}
    for target in ("assistant_memory", "user_profile"):
        selected = [entry for entry in entries if entry["target"] == target]
        used = _used_chars(selected)
        limit = _capacity(target)
        result[target] = {
            "used": used, "limit": limit,
            "ratio": used / limit if limit else 0, "entryCount": len(selected),
        }
    return result


def clear_memories(*, user_id: str, target: str | None = None) -> dict:
    client = get_supabase_client()
    query = client.table("memory_entries").delete().eq("user_id", user_id)
    if target:
        query = query.eq("target", target)
    query.execute()
    pending = client.table("memory_write_requests").delete().eq("user_id", user_id).eq("status", "pending")
    if target:
        pending = pending.eq("target", target)
    pending.execute()
    client.table("memory_snapshots").delete().eq("user_id", user_id).execute()
    return {"cleared": True, "target": target}


def list_skills(*, user_id: str, subject_id: str | None = None) -> list[dict]:
    query = get_supabase_client().table("procedural_skills").select("*").eq("user_id", user_id)
    if subject_id:
        query = query.eq("subject_id", subject_id)
    return query.order("updated_at", desc=True).execute().data


def update_skill(*, user_id: str, skill_id: str, changes: dict) -> dict:
    client = get_supabase_client()
    rows = client.table("procedural_skills").select("*").eq("id", skill_id).eq("user_id", user_id).limit(1).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="Skill not found")
    current = rows[0]
    client.table("procedural_skill_versions").upsert({
        "user_id": user_id, "skill_id": skill_id, "version": current["version"],
        "name": current["name"], "description": current["description"],
        "instructions": current["instructions"], "confidence": current["confidence"],
        "status": current["status"],
    }, on_conflict="skill_id,version").execute()
    allowed = {"name", "description", "instructions", "status"}
    payload = {key: value for key, value in changes.items() if key in allowed and value is not None}
    if payload.get("status") not in {None, "candidate", "active", "archived"}:
        raise HTTPException(status_code=422, detail="Invalid skill status")
    payload["version"] = int(current["version"]) + 1
    return client.table("procedural_skills").update(payload).eq("id", skill_id).eq("user_id", user_id).select("*").execute().data[0]


def delete_skill(*, user_id: str, skill_id: str) -> dict:
    response = get_supabase_client().table("procedural_skills").delete().eq("id", skill_id).eq("user_id", user_id).select("id").execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"deleted": True, "id": skill_id}
