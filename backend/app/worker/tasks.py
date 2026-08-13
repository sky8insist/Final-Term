from datetime import UTC, datetime
import hashlib

from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.services import hermes_memory_service, material_service, task_service
from app.services.material_service import ProcessingCancelled
from app.worker.celery_app import celery_app
from app.services.llm_service import generate_json_async
from app.services.embedding_service import EmbeddingError, embed_texts
from app.services.observability_service import user_id_context
import asyncio
from time import perf_counter


@celery_app.task(bind=True)
def process_material(self, task_id: str):
    operation_started_at = perf_counter()
    client = get_supabase_client()
    rows = client.table("processing_tasks").select("*").eq("id", task_id).limit(1).execute()
    if not rows.data or rows.data[0]["status"] == "cancelled":
        return None
    row = rows.data[0]
    user_id, subject_id, material_id = row["user_id"], row["subject_id"], row["material_id"]
    user_id_context.set(user_id)
    attempts = int(row.get("attempts", 0)) + 1
    task_service.update_task(
        user_id=user_id, task_id=task_id, status="running", stage="parsing",
        progress=10, attempts=attempts, started_at=datetime.now(UTC).isoformat(),
    )
    material_rows = client.table("materials").select("*").eq("id", material_id).eq("user_id", user_id).limit(1).execute()
    asset_rows = client.table("material_assets").select("*").eq("material_id", material_id).eq("user_id", user_id).eq("asset_type", "original").limit(1).execute()
    if not material_rows.data or not asset_rows.data:
        raise RuntimeError("Material source is unavailable")
    material, asset = material_rows.data[0], asset_rows.data[0]
    data = client.storage.from_(asset["bucket"]).download(asset["object_path"])
    task_metadata = dict(row.get("metadata") or {})
    try:
        def report(stage: str, progress: int):
            current = task_service.get_task(user_id=user_id, task_id=task_id)
            if current["status"] == "cancelled":
                raise ProcessingCancelled("Processing cancelled by user")
            if stage in {"parsing", "embedding", "indexing", "ready"}:
                material_service._update_material_status(
                    client=client, user_id=user_id, material_id=material_id,
                    status_value=stage,
                )
            task_service.update_task(
                user_id=user_id, task_id=task_id, status="running" if stage != "ready" else "succeeded",
                stage=stage, progress=progress,
            )
        def parser_event(event: str, details: dict):
            current = task_service.get_task(user_id=user_id, task_id=task_id)
            if current["status"] == "cancelled":
                raise ProcessingCancelled("Processing cancelled by user")
            mineru_metadata = {
                **dict(task_metadata.get("mineru") or {}),
                **details,
                "event": event,
                "updatedAt": datetime.now(UTC).isoformat(),
            }
            task_metadata["parseProvider"] = "mineru-v4"
            task_metadata["mineru"] = mineru_metadata
            state_progress = {
                "uploaded": 18, "waiting-file": 20, "pending": 24,
                "running": 30, "converting": 36, "done": 40,
                "completed": 42, "failed": 18,
            }
            state = str(details.get("state") or event)
            task_service.update_task(
                user_id=user_id, task_id=task_id, status="running", stage="parsing",
                progress=state_progress.get(state, 20), metadata=task_metadata,
            )
        result = material_service.process_material_bytes(
            user_id=user_id, subject_id=subject_id, material_row=material,
            filename=material["filename"], content_type=material["content_type"], file_bytes=data,
            on_stage=report,
            resume_batch_id=(task_metadata.get("mineru") or {}).get("batchId"),
            on_parser_event=parser_event,
        )
        if result["status"] != "ready":
            raise RuntimeError(result.get("errorMessage") or "Material processing failed")
        task_service.update_task(
            user_id=user_id, task_id=task_id, status="succeeded", stage="ready",
            progress=100, finished_at=datetime.now(UTC).isoformat(),
        )
        from app.services.observability_service import record_operation
        record_operation(
            operation="material_processing", status="succeeded", started_at=operation_started_at,
            task_id=task_id, material_id=material_id, stage="ready",
        )
        return result
    except ProcessingCancelled:
        # DELETE /tasks/{id} is authoritative. Never overwrite cancellation
        # with running/failed when a stage finishes after the request.
        from app.services.observability_service import record_operation
        record_operation(operation="material_processing", status="cancelled", started_at=operation_started_at,
                         task_id=task_id, material_id=material_id, stage="cancelled")
        return {"status": "cancelled", "taskId": task_id}
    except Exception as exc:
        max_attempts = int(row.get("max_attempts", settings.task_max_retries))
        if attempts >= max_attempts:
            task_service.update_task(
                user_id=user_id, task_id=task_id, status="failed", stage="failed",
                error_code="processing_failed", error_message=str(exc)[:2000],
                finished_at=datetime.now(UTC).isoformat(),
            )
            from app.services.observability_service import record_operation
            record_operation(operation="material_processing", status="failed", started_at=operation_started_at,
                             task_id=task_id, material_id=material_id, stage="failed",
                             metadata={"attempts": attempts, "errorType": type(exc).__name__})
            return {"status": "failed", "taskId": task_id, "attempts": attempts}
        task_service.update_task(
            user_id=user_id, task_id=task_id, status="queued", stage="queued",
            progress=0, error_code="retry_scheduled", error_message=str(exc)[:2000],
        )
        material_service._update_material_status(
            client=client, user_id=user_id, material_id=material_id,
            status_value="queued", error_message=str(exc)[:2000],
        )
        raise self.retry(
            exc=exc, countdown=min(2 ** attempts, 60), max_retries=max_attempts - 1,
        )


@celery_app.task
def review_learning_interaction(user_id: str, subject_id: str, session_id: str,
                                question: str, answer: str, role: str):
    user_id_context.set(user_id)
    prompt = f"""复盘一次学习互动，只提取跨会话仍有价值的稳定信息。不要保存聊天原文、知识常识或一次性细节。
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
def cleanup_expired_assets():
    client = get_supabase_client()
    rows = (
        client.table("material_assets").select("id,bucket,object_path")
        .lt("expires_at", datetime.now(UTC).isoformat()).execute().data
    )
    removed = 0
    for row in rows:
        try:
            client.storage.from_(row["bucket"]).remove([row["object_path"]])
            client.table("material_assets").delete().eq("id", row["id"]).execute()
            removed += 1
        except Exception:
            continue
    return {"removed": removed}
