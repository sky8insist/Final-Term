from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.models.memory import LearnerProfileUpdate, MemoryWrite
from app.models.user import CurrentUser
from app.services import hermes_memory_service

router = APIRouter()


class SnapshotRequest(BaseModel):
    session_id: str = Field(validation_alias="sessionId")
    subject_id: str | None = Field(default=None, validation_alias="subjectId")


class SessionSearchRequest(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=50)


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    instructions: str | None = Field(default=None, min_length=1, max_length=4000)
    status: str | None = None


@router.get("/memories")
def list_memories(target: str | None = None, subject_id: str | None = None,
                  current_user: CurrentUser = Depends(get_current_user)):
    return hermes_memory_service.list_memories(user_id=current_user.id, target=target, subject_id=subject_id)


@router.post("/memories")
def write_memory(payload: MemoryWrite, current_user: CurrentUser = Depends(get_current_user)):
    return hermes_memory_service.request_write(
        user_id=current_user.id, action=payload.action, target=payload.target,
        subject_id=payload.subject_id, old_text=payload.old_text, content=payload.content,
        confidence=payload.confidence, importance=payload.importance, reason=payload.reason,
        require_approval=payload.require_approval,
    )


@router.get("/memories/usage")
def memory_usage(current_user: CurrentUser = Depends(get_current_user)):
    return hermes_memory_service.memory_usage(user_id=current_user.id)


@router.delete("/memories")
def clear_memories(target: str | None = None,
                   current_user: CurrentUser = Depends(get_current_user)):
    if target not in {None, "assistant_memory", "user_profile"}:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Invalid memory target")
    return hermes_memory_service.clear_memories(user_id=current_user.id, target=target)


@router.patch("/memories/{memory_id}")
def replace_memory(memory_id: str, payload: MemoryWrite,
                   current_user: CurrentUser = Depends(get_current_user)):
    entries = hermes_memory_service.list_memories(user_id=current_user.id)
    entry = next((item for item in entries if item["id"] == memory_id), None)
    if not entry:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Memory not found")
    return hermes_memory_service.request_write(
        user_id=current_user.id, action="replace", target=entry["target"],
        subject_id=payload.subject_id, old_text=entry["content"], content=payload.content,
        confidence=payload.confidence, importance=payload.importance, reason=payload.reason,
        require_approval=payload.require_approval,
    )


@router.delete("/memories/{memory_id}")
def remove_memory(memory_id: str, current_user: CurrentUser = Depends(get_current_user)):
    entries = hermes_memory_service.list_memories(user_id=current_user.id)
    entry = next((item for item in entries if item["id"] == memory_id), None)
    if not entry:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Memory not found")
    return hermes_memory_service.request_write(
        user_id=current_user.id, action="remove", target=entry["target"],
        subject_id=entry.get("subject_id"), old_text=entry["content"], content=None,
        confidence=1, importance=entry.get("importance", 50), reason="User requested removal",
        require_approval=False,
    )


@router.get("/memory-writes/pending")
def pending_writes(current_user: CurrentUser = Depends(get_current_user)):
    return hermes_memory_service.list_pending_writes(user_id=current_user.id)


@router.post("/memory-writes/{request_id}/approve")
def approve_write(request_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return hermes_memory_service.resolve_write(user_id=current_user.id, request_id=request_id, approve=True)


@router.post("/memory-writes/{request_id}/reject")
def reject_write(request_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return hermes_memory_service.resolve_write(user_id=current_user.id, request_id=request_id, approve=False)


@router.post("/memory-snapshots")
def create_snapshot(payload: SnapshotRequest, current_user: CurrentUser = Depends(get_current_user)):
    return hermes_memory_service.create_snapshot(
        user_id=current_user.id, session_id=payload.session_id, subject_id=payload.subject_id,
    )


@router.get("/learner-profile")
def get_profile(current_user: CurrentUser = Depends(get_current_user)):
    return hermes_memory_service.get_profile(user_id=current_user.id)


@router.patch("/learner-profile")
def update_profile(payload: LearnerProfileUpdate, current_user: CurrentUser = Depends(get_current_user)):
    changes = payload.model_dump(exclude_unset=True)
    profile = hermes_memory_service.update_profile(
        user_id=current_user.id, changes=payload.model_dump(exclude_unset=True),
    )
    if changes.get("daily_minutes") is not None:
        from app.services.study_plan_service import rebalance_active_plans
        rebalance_active_plans(user_id=current_user.id, daily_minutes=changes["daily_minutes"])
    return profile


@router.post("/sessions/search")
def search_sessions(payload: SessionSearchRequest, current_user: CurrentUser = Depends(get_current_user)):
    return hermes_memory_service.search_sessions(user_id=current_user.id, query=payload.query, limit=payload.limit)


@router.get("/skills")
def list_skills(subject_id: str | None = None,
                current_user: CurrentUser = Depends(get_current_user)):
    return hermes_memory_service.list_skills(
        user_id=current_user.id, subject_id=subject_id,
    )


@router.patch("/skills/{skill_id}")
def update_skill(skill_id: str, payload: SkillUpdate,
                 current_user: CurrentUser = Depends(get_current_user)):
    return hermes_memory_service.update_skill(
        user_id=current_user.id, skill_id=skill_id,
        changes=payload.model_dump(exclude_unset=True),
    )


@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return hermes_memory_service.delete_skill(
        user_id=current_user.id, skill_id=skill_id,
    )
