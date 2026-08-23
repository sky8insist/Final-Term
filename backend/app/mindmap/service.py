import asyncio

from fastapi import HTTPException

from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.mindmap.evaluator import evaluate_map, retry_reason
from app.mindmap.planner import MindMapValidationError, normalize_map
from app.mindmap.prompts import (
    SYSTEM_PROMPT,
    build_focus_question,
    build_generation_prompt,
    expand_query,
)
from app.services.llm_service import LLMServiceError, generate_json_async
from app.services.mastery_service import list_mastery
from app.services.retrieval_service import search_subject_context


ARTIFACT_SELECT = (
    "id,subject_id,artifact_type,title,content,citations,generation_params,"
    "model_name,prompt_version,version,is_user_edited,created_at,updated_at"
)


def _top_k(mode: str, focus_question: str) -> int:
    base = {"question": 10, "topic": 14, "chapter": 18}[mode]
    if len(focus_question) > 80:
        base += 2
    return min(base, 20)


def _attach_mastery(*, user_id: str, subject_id: str, content: dict) -> None:
    try:
        rows = list_mastery(user_id=user_id, subject_id=subject_id)
    except Exception:
        rows = []
    mastery_rows = [
        (str(row.get("knowledge_key") or "").casefold().strip(), row.get("mastery"))
        for row in rows
        if row.get("knowledge_key") and row.get("mastery") is not None
    ]
    for node in content["nodes"]:
        node["mastery"] = None
        label = str(node["label"]).casefold().strip()
        matches = [value for key, value in mastery_rows if key == label or key in label or label in key]
        if matches:
            try:
                node["mastery"] = min(max(float(matches[0]), 0), 1)
            except (TypeError, ValueError):
                node["mastery"] = None


async def generate_mind_map(*, user_id: str, subject_id: str, mode: str,
                            query: str | None, topic_id: str | None,
                            chapter_id: str | None, max_depth: int,
                            include_mastery: bool, material_ids: list[str] | None,
                            count: int) -> dict:
    try:
        subject, focus_question = build_focus_question(
            mode=mode, query=query, topic_id=topic_id, chapter_id=chapter_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    retrieval_query = expand_query(
        mode=mode, subject=subject, focus_question=focus_question,
    )
    context = await asyncio.to_thread(
        search_subject_context,
        user_id=user_id,
        subject_id=subject_id,
        question=retrieval_query,
        top_k=_top_k(mode, focus_question),
        material_ids=material_ids,
    )
    citations = context.get("citations") or []
    if not citations:
        raise HTTPException(
            status_code=422,
            detail="当前课程资料中没有找到足够内容生成该知识地图。",
        )

    allowed_source_ids = {str(item["id"]) for item in citations}
    content: dict | None = None
    feedback = ""
    last_error = "知识地图未通过结构校验"
    for attempt in range(2):
        prompt = build_generation_prompt(
            mode=mode,
            focus_question=focus_question,
            max_depth=max_depth,
            max_nodes=count,
            citations=citations,
            feedback=feedback,
        )
        try:
            result = await asyncio.wait_for(
                generate_json_async(
                    prompt,
                    system_prompt=SYSTEM_PROMPT,
                    temperature=0,
                    timeout=60,
                ),
                timeout=70,
            )
            candidate = normalize_map(
                result,
                focus_question=focus_question,
                mode=mode,
                max_depth=max_depth,
                max_nodes=count,
                allowed_source_ids=allowed_source_ids,
            )
            candidate["evaluation"] = evaluate_map(candidate)
            reason = retry_reason(candidate["evaluation"])
            if reason and attempt == 0:
                feedback = reason
                continue
            content = candidate
            break
        except asyncio.TimeoutError as exc:
            last_error = "模型生成超时"
            if attempt == 1:
                raise HTTPException(status_code=504, detail=last_error) from exc
            feedback = last_error
        except (LLMServiceError, MindMapValidationError) as exc:
            last_error = str(exc)
            if attempt == 1:
                raise HTTPException(status_code=502, detail=f"知识地图生成失败：{last_error}") from exc
            feedback = last_error

    if content is None:
        raise HTTPException(status_code=502, detail=f"知识地图生成失败：{last_error}")
    if include_mastery:
        _attach_mastery(user_id=user_id, subject_id=subject_id, content=content)

    response = (
        get_supabase_client()
        .table("artifacts")
        .insert({
            "user_id": user_id,
            "subject_id": subject_id,
            "artifact_type": "mind_map",
            "title": content["title"],
            "content": content,
            "citations": citations,
            "generation_params": {
                "mode": mode,
                "query": query,
                "topicId": topic_id,
                "chapterId": chapter_id,
                "focusQuestion": focus_question,
                "maxDepth": max_depth,
                "includeMastery": include_mastery,
                "materialIds": material_ids,
                "count": count,
                "retrieval": context.get("retrieval", {}),
            },
            "model_name": settings.llm_model,
            "prompt_version": "mind-map-2.0.0",
        })
        .select(ARTIFACT_SELECT)
        .execute()
    )
    return response.data[0]

