from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.course import TopicCreate, TopicUpdate, UnitCreate
from app.models.exam_goal import ExamEventSave, SyllabusCreate
from app.models.user import CurrentUser
from app.services import course_service

router = APIRouter()


@router.get("/{subject_id}/exam-goals")
def exam_goals(subject_id: UUID, user: CurrentUser = Depends(get_current_user)):
    from app.services.exam_goal_service import list_goals
    return list_goals(user_id=user.id, subject_id=str(subject_id))


@router.post("/{subject_id}/exam-events")
def create_exam_event(subject_id: UUID, payload: ExamEventSave, user: CurrentUser = Depends(get_current_user)):
    from app.services.exam_goal_service import save_event
    return save_event(user_id=user.id, subject_id=str(subject_id), values=payload.model_dump(mode="json"))


@router.put("/{subject_id}/exam-events/{event_id}")
def update_exam_event(subject_id: UUID, event_id: UUID, payload: ExamEventSave,
                      user: CurrentUser = Depends(get_current_user)):
    from app.services.exam_goal_service import save_event
    return save_event(user_id=user.id, subject_id=str(subject_id), event_id=str(event_id),
                      values=payload.model_dump(mode="json"))


@router.post("/{subject_id}/syllabi")
def create_syllabus(subject_id: UUID, payload: SyllabusCreate, user: CurrentUser = Depends(get_current_user)):
    from app.services.exam_goal_service import create_syllabus
    return create_syllabus(user_id=user.id, subject_id=str(subject_id), values=payload.model_dump(mode="json"))


@router.get("/{subject_id}/learner-state")
def learner_state(subject_id: UUID, user: CurrentUser = Depends(get_current_user)):
    from app.services.learner_state_service import list_states
    return list_states(user_id=user.id, subject_id=str(subject_id))


@router.post("/{subject_id}/topics/{topic_id}/covered")
def cover_topic(subject_id: UUID, topic_id: UUID, user: CurrentUser = Depends(get_current_user)):
    from app.services.learner_state_service import mark_covered
    return mark_covered(user_id=user.id, subject_id=str(subject_id), topic_id=str(topic_id))


@router.get("/{subject_id}/structure")
def structure(subject_id: UUID, user: CurrentUser = Depends(get_current_user)):
    return course_service.get_structure(user_id=user.id, subject_id=str(subject_id))


@router.post("/{subject_id}/units")
def create_unit(subject_id: UUID, payload: UnitCreate, user: CurrentUser = Depends(get_current_user)):
    return course_service.create_unit(user_id=user.id, subject_id=str(subject_id), values=payload.model_dump())


@router.patch("/{subject_id}/units/{unit_id}")
def update_unit(subject_id: UUID, unit_id: UUID, payload: UnitCreate,
                user: CurrentUser = Depends(get_current_user)):
    return course_service.update_unit(user_id=user.id, subject_id=str(subject_id), unit_id=str(unit_id),
                                      values=payload.model_dump())


@router.post("/{subject_id}/topics")
def create_topic(subject_id: UUID, payload: TopicCreate, user: CurrentUser = Depends(get_current_user)):
    return course_service.create_topic(user_id=user.id, subject_id=str(subject_id),
                                       values=payload.model_dump(mode="json"))


@router.patch("/{subject_id}/topics/{topic_id}")
def update_topic(subject_id: UUID, topic_id: UUID, payload: TopicUpdate,
                 user: CurrentUser = Depends(get_current_user)):
    return course_service.update_topic(user_id=user.id, subject_id=str(subject_id), topic_id=str(topic_id),
                                       values=payload.model_dump(mode="json", exclude_unset=True))
