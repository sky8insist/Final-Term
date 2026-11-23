from datetime import UTC, datetime
import hashlib
import json

from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.services import hermes_memory_service, task_service
from app.services.material_service import ProcessingCancelled
from app.worker.celery_app import celery_app


from app.services.llm_service import generate_json_async
from app.services.embedding_service import EmbeddingError, embed_texts
from app.services.observability_service import (
    StageTimer,
    restore_trace_metadata,
)
import asyncio
from time import perf_counter
from fastapi import HTTPException


@celery_app.task(name='app.worker.tasks.process_conversion')
def process_conversion(conversion_id: str):
    from app.services.conversion_service import run_conversion
    return run_conversion(conversion_id)


@celery_app.task(name='app.worker.tasks.process_learning_job')
def process_learning_job(job_id: str):
    from app.services.learning_job_service import run
    return run(job_id)


@celery_app.task(name='app.worker.tasks.sweep_learning_jobs')
def sweep_learning_jobs():
    from app.services.learning_job_service import sweep
    return sweep()


@celery_app.task(name='app.worker.tasks.sweep_conversions')
def sweep_conversions():
    from app.services.conversion_service import sweep
    return sweep()


@celery_app.task(name='app.worker.tasks.sweep_upload_notes')
def sweep_upload_notes():
    from app.services.material_notes_service import sweep
    return sweep()


@celery_app.task
def refresh_study_plans():
    from app.services.study_plan_v3_service import refresh_changed_plans
    return refresh_changed_plans()


@celery_app.task(bind=True)
def process_material(self, task_id: str):
    from app.services.material_ingestion_job_service import run
    return run(task_id)


@celery_app.task(name='app.worker.tasks.sweep_material_ingestions')
def sweep_material_ingestions():
    from app.services.material_ingestion_job_service import sweep
    return sweep()


@celery_app.task(name="app.worker.tasks.generate_exam")
def generate_exam(task_id: str):
    operation_started_at = perf_counter()
    client = get_supabase_client()
    rows = client.table("processing_tasks").select("*").eq("id", task_id).limit(1).execute().data
    if not rows or rows[0]["status"] not in {"queued", "running"}:
        return None
    row = rows[0]
    metadata = dict(row.get("metadata") or {})
    restore_trace_metadata(metadata, user_id=row["user_id"])
    stage_timer = StageTimer("exam_generation_stage", task_id=task_id)
    stage_timer.transition("retrieving")
    task_service.update_task(
        user_id=row["user_id"], task_id=task_id, status="running", stage="parsing",
        progress=5, attempts=int(row.get("attempts", 0)) + 1,
        started_at=datetime.now(UTC).isoformat(), error_code=None, error_message=None,
    )

    stage_map = {
        "retrieving": ("parsing", 15),
        "generating": ("embedding", 45),
        "validating": ("indexing", 75),
        "saving": ("indexing", 90),
    }

    def report(stage_name: str, details: dict | None = None):
        stage_timer.transition(stage_name, metadata=details)
        current = task_service.get_task(user_id=row["user_id"], task_id=task_id)
        if current["status"] == "cancelled":
            raise ProcessingCancelled("Exam generation cancelled by user")
        details = details or {}
        db_stage, progress = stage_map[stage_name]
        completed = int(details.get("completedQuestions") or 0)
        total = int(details.get("totalQuestions") or 0)
        if stage_name == "generating" and total:
            progress = min(72, 25 + round(completed / total * 47))
        elif stage_name == "validating" and details.get("batchCount"):
            batch = int(details.get("batch") or 1)
            batch_count = max(int(details["batchCount"]), 1)
            progress = min(72, 25 + round(((batch - 1) + 0.8) / batch_count * 47))
        metadata["currentStage"] = stage_name
        metadata["stageDetails"] = {key: value for key, value in details.items() if key != "checkpoint"}
        if details.get("checkpoint"):
            metadata["generationCheckpoint"] = details["checkpoint"]
        task_service.update_task(
            user_id=row["user_id"], task_id=task_id, status="running",
            stage=db_stage, progress=progress, metadata=metadata,
        )

    try:
        from app.models.exam import ExamGenerateRequest
        from app.services import exam_service
        payload = ExamGenerateRequest(**metadata["request"])
        exam = asyncio.run(exam_service.generate_exam(
            user_id=row["user_id"], payload=payload, on_stage=report,
            checkpoint=metadata.get("generationCheckpoint"),
        ))
        generation = exam.get("generation") or {}
        metadata.pop("generationCheckpoint", None)
        metadata.update({
            "currentStage": "ready", "examId": exam["id"],
            "stageDetails": {"completedQuestions": exam.get("question_count", 0)},
            "retrieval": generation.get("retrieval") or {},
            "evidence": generation.get("evidence") or [],
        })
        task_service.update_task(
            user_id=row["user_id"], task_id=task_id, status="succeeded", stage="ready",
            progress=100, metadata=metadata, finished_at=datetime.now(UTC).isoformat(),
        )
        from app.services.observability_service import record_operation
        record_operation(
            operation="exam_generation", status="succeeded", started_at=operation_started_at,
            task_id=task_id, stage="ready", metadata={"examId": exam["id"]},
        )
        stage_timer.finish()
        return {"status": "succeeded", "taskId": task_id, "examId": exam["id"]}
    except ProcessingCancelled:
        stage_timer.finish("cancelled")
        return {"status": "cancelled", "taskId": task_id}
    except Exception as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        message = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
        friendly_messages = {
            "No relevant indexed course material was found for this topic": "当前主题在课程资料中没有找到足够相关的内容，请更换主题或先上传相关资料。",
            "Practice topic is required": "请输入练习主题后再生成。",
        }
        message = friendly_messages.get(message, message)
        lowered = message.casefold()
        error_code = "model_timeout" if "timeout" in lowered or "超时" in message else "exam_generation_failed"
        metadata["currentStage"] = "failed"
        task_service.update_task(
            user_id=row["user_id"], task_id=task_id, status="failed", stage="failed",
            progress=100, metadata=metadata, error_code=error_code,
            error_message=message[:2000], finished_at=datetime.now(UTC).isoformat(),
        )
        from app.services.observability_service import record_operation
        record_operation(
            operation="exam_generation", status="failed", started_at=operation_started_at,
            task_id=task_id, stage="failed", metadata={"errorType": type(exc).__name__},
        )
        stage_timer.finish("failed", metadata={"errorType": type(exc).__name__})
        return {"status": "failed", "taskId": task_id, "errorCode": error_code}


@celery_app.task
def generate_study_plan(task_id: str):
    operation_started_at = perf_counter()
    client = get_supabase_client()
    rows = client.table("processing_tasks").select("*").eq("id", task_id).limit(1).execute().data
    if not rows or rows[0]["status"] not in {"queued", "running"}:
        return None
    row = rows[0]
    metadata = dict(row.get("metadata") or {})
    restore_trace_metadata(metadata, user_id=row["user_id"])
    stage_timer = StageTimer("study_plan_generation_stage", task_id=task_id)
    stage_timer.transition("signals_and_scheduling")
    task_service.update_task(
        user_id=row["user_id"], task_id=task_id, status="running", stage="parsing",
        progress=15, attempts=int(row.get("attempts", 0)) + 1,
        started_at=datetime.now(UTC).isoformat(), error_code=None, error_message=None,
    )
    try:
        from app.models.study_plan import StudyPlanRequest
        from app.services import study_plan_service
        payload = StudyPlanRequest(**metadata["request"])
        task_service.update_task(user_id=row["user_id"], task_id=task_id, status="running", stage="embedding", progress=45)
        result = study_plan_service.generate_plan(
            user_id=row["user_id"], subject_id=payload.subject_id,
            exam_date=payload.exam_date, daily_minutes=payload.daily_minutes, title=payload.title,
            weekend_extra=payload.weekend_extra, reserve_final_day=payload.reserve_final_day,
            preserve_existing=payload.preserve_existing,
            mode=payload.mode, exam_event_id=str(payload.exam_event_id) if payload.exam_event_id else None,
            available_minutes=payload.available_minutes, auto_replan=payload.auto_replan,
        )
        stage_timer.transition("model_guidance")
        task_service.update_task(user_id=row["user_id"], task_id=task_id, status="running", stage="indexing", progress=82)
        result["tasks"] = asyncio.run(study_plan_service.enrich_task_guidance(
            user_id=row["user_id"], plan=result["plan"], tasks=result["tasks"],
        ))
        metadata.update({"currentStage": "ready", "planId": result["plan"]["id"], "taskCount": len(result["tasks"])})
        task_service.update_task(
            user_id=row["user_id"], task_id=task_id, status="succeeded", stage="ready",
            progress=100, metadata=metadata, finished_at=datetime.now(UTC).isoformat(),
        )
        from app.services.observability_service import record_operation
        record_operation(
            operation="study_plan_generation", status="succeeded",
            started_at=operation_started_at, task_id=task_id, stage="ready",
            metadata={"planId": result["plan"]["id"], "taskCount": len(result["tasks"])},
        )
        stage_timer.finish()
        return {"status": "succeeded", "taskId": task_id, "planId": result["plan"]["id"]}
    except Exception as exc:
        metadata["currentStage"] = "failed"
        task_service.update_task(
            user_id=row["user_id"], task_id=task_id, status="failed", stage="failed", progress=100,
            metadata=metadata, error_code="study_plan_generation_failed", error_message=str(exc)[:2000],
            finished_at=datetime.now(UTC).isoformat(),
        )
        from app.services.observability_service import record_operation
        record_operation(
            operation="study_plan_generation", status="failed",
            started_at=operation_started_at, task_id=task_id, stage="failed",
            metadata={"errorType": type(exc).__name__},
        )
        stage_timer.finish("failed", metadata={"errorType": type(exc).__name__})
        return {"status": "failed", "taskId": task_id}


@celery_app.task
def review_learning_interaction(user_id: str, subject_id: str, session_id: str,
                                question: str, answer: str, role: str,
                                trace_metadata: dict | None = None):
    restore_trace_metadata(trace_metadata, user_id=user_id)
    prompt = f"""复盘一次学习互动，只提取跨会话仍有价值的稳定信息。不要保存聊天原文、知识常识或一次性细节。
仅提议明确的学习偏好、稳定习惯、反复存在的困难或长期目标，内容写明其性质。禁止把掌握度、正确率、考试成绩/日期/临时目标、自报信心、待复习状态保存为长期记忆；这些由业务数据库维护。自动提案必须等待用户确认。
返回 JSON：{{"eventType":"qa","memoryCandidates":[{{"kind":"explicit_preference|correction|weak_point|error_pattern|effective_strategy","target":"assistant_memory|user_profile","content":"简短可执行记忆","confidence":0.0,"importance":50,"reason":""}}],"skillCandidates":[{{"name":"稳定方法名","description":"何时有效","instructions":"可复用步骤","confidence":0.0}}],"summary":"会话摘要"}}
角色：{role}\n问题：{question}\n回答：{answer}"""
    result = asyncio.run(generate_json_async(prompt))
    client = get_supabase_client()
    candidates = result.get("memoryCandidates", [])[:3]
    candidate_fingerprints = [
        hashlib.sha256(str(item.get("content", "")).strip().casefold().encode("utf-8")).hexdigest()[:16]
        for item in candidates if str(item.get("content", "")).strip()
    ]
    event = client.table("learning_events").insert({
        "user_id": user_id, "subject_id": subject_id, "session_id": session_id,
        "event_type": result.get("eventType", "qa"),
        "payload": {"role": role, "questionLength": len(question), "answerLength": len(answer),
                    "candidateFingerprints": candidate_fingerprints},
    }).select("id").execute().data[0]
    summary = str(result.get("summary", "")).strip()
    if summary:
        summary_payload = {
            "user_id": user_id, "subject_id": subject_id, "session_id": session_id,
            "summary": summary, "ended_at": datetime.now(UTC).isoformat(),
        }
        try:
            vector = embed_texts([summary])[0]
            summary_payload["embedding"] = "[" + ",".join(str(float(value)) for value in vector) + "]"
            summary_payload["embedding_model"] = settings.embedding_model
        except (EmbeddingError, IndexError):
            pass
        client.table("session_summaries").upsert(
            summary_payload, on_conflict="user_id,session_id",
        ).execute()
    updates = []
    for candidate in candidates:
        try:
            fingerprint = hashlib.sha256(
                str(candidate.get("content", "")).strip().casefold().encode("utf-8")
            ).hexdigest()[:16]
            if candidate.get("kind") in {"weak_point", "error_pattern"}:
                evidence = (
                    client.table("learning_events").select("id", count="exact")
                    .eq("user_id", user_id).eq("subject_id", subject_id)
                    .contains("payload", {"candidateFingerprints": [fingerprint]}).execute()
                )
                if int(evidence.count or len(evidence.data or [])) < 3:
                    continue
            updates.append(hermes_memory_service.request_write(
                user_id=user_id, action="add", target=candidate.get("target", "assistant_memory"),
                subject_id=subject_id, old_text=None, content=candidate.get("content"),
                confidence=float(candidate.get("confidence", 0.5)),
                importance=int(candidate.get("importance", 50)), reason=candidate.get("reason"),
                require_approval=None, source_event_id=event["id"],
            ))
        except Exception:
            continue
    skill_updates = []
    for candidate in result.get("skillCandidates", [])[:2]:
        name = str(candidate.get("name", "")).strip()[:120]
        instructions = str(candidate.get("instructions", "")).strip()
        if not name or not instructions or float(candidate.get("confidence", 0)) < 0.65:
            continue
        existing = client.table("procedural_skills").select("*").eq("user_id", user_id).eq("name", name).limit(1).execute().data
        if existing:
            evidence_count = int(existing[0].get("evidence_count", 1)) + 1
            status_value = "active" if evidence_count >= 3 else "candidate"
            updated = client.table("procedural_skills").update({
                "description": str(candidate.get("description", ""))[:500],
                "instructions": instructions[:4000], "evidence_count": evidence_count,
                "confidence": min(float(candidate.get("confidence", 0.65)) + evidence_count * 0.03, 1),
                "status": status_value, "version": int(existing[0].get("version", 1)) + 1,
            }).eq("id", existing[0]["id"]).eq("user_id", user_id).select("*").execute().data[0]
        else:
            updated = client.table("procedural_skills").insert({
                "user_id": user_id, "subject_id": subject_id, "name": name,
                "description": str(candidate.get("description", ""))[:500],
                "instructions": instructions[:4000], "confidence": float(candidate.get("confidence", 0.65)),
            }).select("*").execute().data[0]
        skill_updates.append({"id": updated["id"], "name": name, "status": updated["status"]})
    return {"eventId": event["id"], "memoryUpdates": updates, "skillUpdates": skill_updates}


@celery_app.task(name="app.worker.tasks.cleanup_expired_assets")
def cleanup_expired_assets(user_id: str | None = None):
    from app.services.retention_service import sweep
    return sweep(user_id=user_id)


@celery_app.task(name='app.worker.tasks.cleanup_abandoned_uploads')
def cleanup_abandoned_uploads():
    from app.services.upload_cleanup_service import sweep
    return sweep()
