import asyncio
import html
import io
import json
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image, ImageDraw

from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.services.llm_service import LLMServiceError, generate_json_async
from app.services.retrieval_service import search_subject_context
from app.services.mastery_service import record_performance
from app.services.export_font_service import load_export_font

ARTIFACT_SELECT = "id,subject_id,artifact_type,title,content,citations,generation_params,model_name,prompt_version,version,is_user_edited,created_at,updated_at"


def _validate_mind_map(content: dict) -> dict:
    nodes = content.get("nodes") or []
    if not nodes:
        raise HTTPException(status_code=502, detail="Mind map generation returned no nodes")
    ids = {str(node.get("id")) for node in nodes if node.get("id")}
    if len(ids) != len(nodes):
        raise HTTPException(status_code=502, detail="Mind map node IDs must be unique")
    roots = 0
    root_id = None
    for index, node in enumerate(nodes):
        node["id"] = str(node["id"])
        parent = node.get("parentId")
        if parent is None:
            roots += 1
            root_id = node["id"]
        elif str(parent) not in ids:
            raise HTTPException(status_code=502, detail="Mind map contains an invalid parent node")
        node.setdefault("order", index)
        node.setdefault("nodeType", "concept")
        node.setdefault("citationIds", [])
    if roots != 1:
        raise HTTPException(status_code=502, detail="Mind map must contain exactly one root")
    children: dict[str, list[str]] = {}
    for node in nodes:
        if node.get("parentId") is not None:
            children.setdefault(str(node["parentId"]), []).append(str(node["id"]))
    visited: set[str] = set()
    active: set[str] = set()
    def walk(node_id: str):
        if node_id in active:
            raise HTTPException(status_code=502, detail="Mind map contains a cycle")
        if node_id in visited:
            return
        active.add(node_id)
        for child_id in children.get(node_id, []):
            walk(child_id)
        active.remove(node_id)
        visited.add(node_id)
    walk(str(root_id))
    if visited != ids:
        raise HTTPException(status_code=502, detail="Mind map contains nodes disconnected from the root")
    return content


def _normalize_content(artifact_type: str, result: dict, count: int) -> tuple[str, dict]:
    title = str(result.get("title") or "复习资料").strip()[:300]
    if artifact_type == "mind_map":
        content = _validate_mind_map({"title": title, "nodes": result.get("nodes", [])})
        if any(not node.get("citationIds") for node in content["nodes"]):
            raise HTTPException(status_code=502, detail="Every mind map node must cite source material")
    elif artifact_type == "flashcards":
        cards = (result.get("cards") or [])[:count]
        if not cards:
            raise HTTPException(status_code=502, detail="Flashcard generation returned no cards")
        for card in cards:
            card.setdefault("id", str(uuid4()))
            card.setdefault("citationIds", [])
            card.setdefault("difficulty", "medium")
            if not card.get("citationIds"):
                raise HTTPException(status_code=502, detail="Every flashcard must cite source material")
        content = {"title": title, "cards": cards}
    else:
        content = {**result, "title": title}
        if not any(key in result for key in ("sections", "items", "formulas", "terms", "rows")):
            raise HTTPException(status_code=502, detail="Artifact generation returned invalid content")
        for key in ("sections", "items", "formulas", "terms", "rows"):
            for item in result.get(key, []) or []:
                if isinstance(item, dict) and not item.get("citationIds"):
                    raise HTTPException(status_code=502, detail="Every artifact item must cite source material")
    return title, content


def _validate_citation_ids(value, allowed: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "citationIds":
                if not isinstance(child, list) or not child or any(str(item) not in allowed for item in child):
                    raise HTTPException(status_code=502, detail="Artifact contains an invalid source citation")
            else:
                _validate_citation_ids(child, allowed)
    elif isinstance(value, list):
        for child in value:
            _validate_citation_ids(child, allowed)


async def generate_artifact(*, user_id: str, subject_id: str, artifact_type: str,
                            scope: str | None, material_ids: list[str] | None,
                            mode: str | None, count: int) -> dict:
    context = await asyncio.to_thread(
        search_subject_context,
        user_id=user_id, subject_id=subject_id,
        question=scope or f"生成{artifact_type}所需的核心知识点",
        top_k=20, material_ids=material_ids,
    )
    if not context["citations"]:
        raise HTTPException(status_code=422, detail="No cited material is available for artifact generation")
    schema = {
        "outline": "title, sections:[{id,title,keyPoints,citationIds,examTips}]",
        "mind_map": "title, nodes:[{id,parentId,title,description,nodeType,mastery,citationIds,order}]，必须恰好一个parentId=null根节点",
        "flashcards": "title, cards:[{front,back,knowledgeKey,difficulty,citationIds}]",
        "formula_sheet": "title, formulas:[{name,latex,symbols,conditions,mistakes,citationIds}]",
        "glossary": "title, terms:[{term,definition,example,citationIds}]",
        "comparison": "title, rows:[{dimension,items,citationIds}]",
        "cheat_sheet": "title, sections:[{title,items,citationIds}]",
    }[artifact_type]
    prompt = f"""根据检索证据生成期末复习产物，严格返回 JSON。
类型：{artifact_type}；模式：{mode or 'knowledge'}；范围：{scope or '全部检索内容'}；最多条目：{count}
JSON结构：{schema}
每个 citationIds 只能引用下列编号。不得编造知识或引用。
证据：
{json.dumps(context['citations'], ensure_ascii=False)}"""
    allowed_citation_ids = {str(item["id"]) for item in context["citations"]}
    title = ""
    content: dict | None = None
    validation_feedback = ""
    for attempt in range(3):
        repair_prompt = prompt
        if validation_feedback:
            repair_prompt += (
                f"\n上一次结果未通过结构或引用检查：{validation_feedback}。"
                "请完整重写产物，不要解释错误；所有条目必须引用给定 citationIds。"
            )
        try:
            result = await generate_json_async(repair_prompt)
        except LLMServiceError as exc:
            if attempt == 2:
                raise HTTPException(status_code=502, detail="Artifact generation failed") from exc
            validation_feedback = "模型未返回有效 JSON"
            continue
        try:
            title, content = _normalize_content(artifact_type, result, count)
            _validate_citation_ids(content, allowed_citation_ids)
            break
        except HTTPException as exc:
            if attempt == 2:
                raise
            validation_feedback = str(exc.detail)
    if content is None:
        raise HTTPException(status_code=502, detail="Artifact generation failed quality validation")
    response = get_supabase_client().table("artifacts").insert({
        "user_id": user_id, "subject_id": subject_id, "artifact_type": artifact_type,
        "title": title, "content": content, "citations": context["citations"],
        "generation_params": {"scope": scope, "materialIds": material_ids, "mode": mode, "count": count},
        "model_name": settings.llm_model,
    }).select(ARTIFACT_SELECT).execute()
    return response.data[0]


def list_artifacts(*, user_id: str, subject_id: str, artifact_type: str | None = None) -> list[dict]:
    query = get_supabase_client().table("artifacts").select(ARTIFACT_SELECT).eq("user_id", user_id).eq("subject_id", subject_id)
    if artifact_type:
        query = query.eq("artifact_type", artifact_type)
    return query.order("created_at", desc=True).execute().data


def get_artifact(*, user_id: str, artifact_id: str) -> dict:
    response = get_supabase_client().table("artifacts").select(ARTIFACT_SELECT).eq("user_id", user_id).eq("id", artifact_id).limit(1).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return response.data[0]


def update_artifact(*, user_id: str, artifact_id: str, title: str | None, content: dict | None) -> dict:
    current = get_artifact(user_id=user_id, artifact_id=artifact_id)
    next_content = content or current["content"]
    if current["artifact_type"] == "mind_map":
        _validate_mind_map(next_content)
    payload = {"version": current["version"] + 1, "is_user_edited": True}
    if title is not None:
        payload["title"] = title
    if content is not None:
        payload["content"] = content
    response = get_supabase_client().table("artifacts").update(payload).eq("id", artifact_id).eq("user_id", user_id).select(ARTIFACT_SELECT).execute()
    return response.data[0]


def record_flashcard_review(*, user_id: str, artifact_id: str, card_id: str,
                            rating: str, response_seconds: float | None = None) -> dict:
    if rating not in {"again", "hard", "good"}:
        raise HTTPException(status_code=422, detail="Invalid flashcard rating")
    artifact = get_artifact(user_id=user_id, artifact_id=artifact_id)
    if artifact["artifact_type"] != "flashcards":
        raise HTTPException(status_code=409, detail="Artifact is not a flashcard deck")
    card = next(
        (item for item in artifact["content"].get("cards", []) if str(item.get("id")) == card_id),
        None,
    )
    if not card:
        raise HTTPException(status_code=404, detail="Flashcard not found")
    mastery = record_performance(
        user_id=user_id, subject_id=artifact["subject_id"],
        knowledge_key=str(card.get("knowledgeKey") or card.get("front") or "闪卡复习")[:200],
        correct=rating == "good", difficulty=str(card.get("difficulty") or "medium"),
        hints=1 if rating == "hard" else 0, response_seconds=response_seconds,
        self_rating={"again": 0.1, "hard": 0.5, "good": 0.9}[rating],
    )
    get_supabase_client().table("learning_events").insert({
        "user_id": user_id, "subject_id": artifact["subject_id"],
        "event_type": "flashcard_review",
        "payload": {
            "artifactId": artifact_id, "cardId": card_id, "rating": rating,
            "knowledgeKey": mastery["knowledge_key"],
        },
    }).execute()
    return {"rating": rating, "mastery": mastery}


def _mind_map_lines(content: dict) -> list[tuple[int, dict]]:
    nodes = content.get("nodes", [])
    by_parent: dict[str | None, list[dict]] = {}
    for node in nodes:
        parent = str(node["parentId"]) if node.get("parentId") is not None else None
        by_parent.setdefault(parent, []).append(node)
    lines: list[tuple[int, dict]] = []
    def walk(parent: str | None, depth: int):
        for node in sorted(by_parent.get(parent, []), key=lambda item: item.get("order", 0)):
            lines.append((depth, node))
            walk(str(node["id"]), depth + 1)
    walk(None, 0)
    return lines


def export_artifact(*, user_id: str, artifact_id: str, export_format: str) -> tuple[bytes, str, str]:
    artifact = get_artifact(user_id=user_id, artifact_id=artifact_id)
    content = artifact["content"]
    safe_name = "artifact-" + artifact_id
    if export_format == "json":
        return json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8"), "application/json", f"{safe_name}.json"
    lines = _mind_map_lines(content) if artifact["artifact_type"] == "mind_map" else []
    if export_format in {"markdown", "md"}:
        text = "\n".join(f"{'  ' * depth}- {node.get('label', node.get('title', ''))}: {node.get('description', '')}" for depth, node in lines)
        return text.encode("utf-8"), "text/markdown; charset=utf-8", f"{safe_name}.md"
    if export_format == "mermaid":
        body = ["mindmap"] + [f"{'  ' * (depth + 1)}{node['id']}[\"{str(node.get('label', node.get('title', ''))).replace(chr(34), chr(39))}\"]" for depth, node in lines]
        return "\n".join(body).encode("utf-8"), "text/plain; charset=utf-8", f"{safe_name}.mmd"
    if export_format == "svg":
        height = max(120, 52 * len(lines) + 40)
        rows = "".join(f'<text x="{20 + depth * 36}" y="{35 + i * 52}" font-size="18">{html.escape(str(node.get("label", node.get("title", ""))))}</text>' for i, (depth, node) in enumerate(lines))
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}"><rect width="100%" height="100%" fill="white"/>{rows}</svg>'
        return svg.encode("utf-8"), "image/svg+xml", f"{safe_name}.svg"
    if export_format in {"png", "jpg", "jpeg", "pdf"}:
        height = max(160, 42 * len(lines) + 40)
        image = Image.new("RGB", (1200, height), "white")
        draw = ImageDraw.Draw(image)
        font = load_export_font(18)
        for i, (depth, node) in enumerate(lines):
            draw.text((20 + depth * 32, 20 + i * 42), str(node.get("label", node.get("title", ""))), fill="black", font=font)
        buffer = io.BytesIO()
        if export_format == "pdf":
            image.save(buffer, format="PDF", resolution=150)
            return buffer.getvalue(), "application/pdf", f"{safe_name}.pdf"
        if export_format in {"jpg", "jpeg"}:
            image.save(buffer, format="JPEG", quality=92)
            return buffer.getvalue(), "image/jpeg", f"{safe_name}.jpg"
        image.save(buffer, format="PNG")
        return buffer.getvalue(), "image/png", f"{safe_name}.png"
    raise HTTPException(status_code=400, detail="Unsupported artifact export format")
