import asyncio
import re
from difflib import SequenceMatcher
from hashlib import sha256

from app.config.settings import settings
from app.services.external_search_service import ExternalSearchError, search_public_knowledge_async
from app.services.retrieval_service import search_subject_context


def _tokens(value: object) -> set[str]:
    text = re.sub(r"\s+", "", str(value or "").casefold())
    latin = set(re.findall(r"[a-z0-9]{2,}", text))
    cjk = set(re.findall(r"[\u4e00-\u9fff]", text))
    cjk.update(text[index:index + 2] for index in range(max(0, len(text) - 1)))
    return {item for item in latin | cjk if item.strip()}


def _overlap(left: object, right: object) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def _query_plan(topic: str) -> list[str]:
    return [
        topic,
        f"{topic} 定义 核心概念 关键关系",
        f"{topic} 作用 应用 常见误区 对比",
    ]


def _public_query(topic: str) -> str:
    core = re.sub(r"(?:的)?(?:作用|意义|特点|定义|概念|区别|联系|应用)$", "", topic.strip()).strip()
    return core if len(core) >= 2 else topic


def _knowledge_points(*, user_id: str, subject_id: str) -> list[dict]:
    try:
        from app.db.supabase_client import get_supabase_client
        return (
            get_supabase_client().table("knowledge_points")
            .select("knowledge_key,title,description,chapter,importance")
            .eq("user_id", user_id).eq("subject_id", subject_id)
            .order("importance", desc=True).limit(200).execute().data
        ) or []
    except Exception:
        return []


def _importance(candidate: dict, knowledge_points: list[dict]) -> float:
    text = " ".join(str(candidate.get(key) or "") for key in ("filename", "title", "chunkText"))
    best = 0.5
    for point in knowledge_points:
        label = " ".join(str(point.get(key) or "") for key in ("knowledge_key", "title", "description", "chapter"))
        match = max(_overlap(label, text), _overlap(text, label))
        if match > 0.12:
            best = max(best, float(point.get("importance", 50)) / 100)
    return min(max(best, 0), 1)


def _rank(candidate: dict, *, topic: str, knowledge_points: list[dict]) -> dict:
    title = str(candidate.get("title") or candidate.get("filename") or "")
    text = f"{title}\n{candidate.get('chunkText') or ''}"
    lexical = max(_overlap(topic, text), _overlap(text, topic))
    normalized_title = re.sub(r"\W+", "", title.casefold())
    normalized_core = re.sub(r"\W+", "", _public_query(topic).casefold())
    title_match = 1.0 if normalized_title == normalized_core else 0.6 if normalized_core and normalized_core in normalized_title else 0.0
    semantic = float(candidate.get("score") or 0)
    rrf = min(max(float(candidate.get("rrfScore") or 0) - 0.015, 0) * 30, 0.35)
    relevance = min(max(lexical, title_match, semantic, rrf), 1)
    importance = _importance(candidate, knowledge_points)
    if candidate.get("sourceType") == "external":
        authority = {"high": 1.0, "medium": 0.75, "unrated": 0.45}.get(
            str(candidate.get("trustLevel") or "unrated"), 0.45,
        )
    else:
        authority = 1.0
    final_score = relevance * 0.60 + importance * 0.25 + authority * 0.15
    return {
        **candidate,
        "relevanceScore": round(relevance, 4),
        "importanceScore": round(importance, 4),
        "authorityScore": round(authority, 4),
        "finalScore": round(final_score, 4),
    }


def _deduplicate(candidates: list[dict], limit: int) -> list[dict]:
    selected: list[tuple[dict, str]] = []
    material_counts: dict[str, int] = {}
    for candidate in sorted(candidates, key=lambda item: item["finalScore"], reverse=True):
        text = re.sub(r"\W+", "", str(candidate.get("chunkText") or "").casefold())
        if not text:
            continue
        if any(SequenceMatcher(None, text[:1000], prior[1][:1000]).ratio() >= 0.86 for prior in selected):
            continue
        material = str(candidate.get("materialId") or candidate.get("filename") or "unknown")
        if candidate.get("sourceType") != "external" and material_counts.get(material, 0) >= 4:
            continue
        material_counts[material] = material_counts.get(material, 0) + 1
        selected.append((candidate, text))
        if len(selected) >= limit:
            break
    return [item[0] for item in selected]


async def retrieve_exam_evidence(
    *, user_id: str, subject_id: str, topic: str, question_count: int,
    material_ids: list[str] | None, knowledge_policy: str,
) -> dict:
    queries = _query_plan(topic)
    public_query = _public_query(topic)
    async def course_query(query: str):
        return await asyncio.wait_for(asyncio.to_thread(
            search_subject_context,
            user_id=user_id, subject_id=subject_id, question=query,
            top_k=min(10, max(6, question_count // 2)), material_ids=material_ids,
        ), timeout=settings.exam_retrieval_timeout_seconds)

    course_calls = [course_query(query) for query in queries]
    external_requested = knowledge_policy != "course_only"
    external_call = asyncio.create_task(
        search_public_knowledge_async(public_query, max_results=5),
    ) if external_requested else None
    results = await asyncio.gather(*course_calls, return_exceptions=True)

    warnings: list[str] = []
    merged: dict[str, dict] = {}
    retrieval_sources: set[str] = set()
    for result in results:
        if isinstance(result, Exception):
            warnings.append("course_query_failed")
            continue
        retrieval_sources.update(result.get("retrieval", {}).get("sources", []))
        warnings.extend(result.get("retrieval", {}).get("warnings", []))
        for rank, item in enumerate(result.get("citations", []), start=1):
            key = str(item.get("id") or item.get("blockId") or f"{item.get('materialId')}:{item.get('pageNumber')}:{rank}")
            if key in merged:
                merged[key]["rrfScore"] = float(merged[key].get("rrfScore") or 0) + 1 / (60 + rank)
            else:
                merged[key] = {**item, "id": key, "sourceType": "material"}

    if not merged:
        if external_call:
            external_call.cancel()
            await asyncio.gather(external_call, return_exceptions=True)
        raise ValueError("No relevant indexed course material was found for this topic")

    external_rows: list[dict] = []
    if external_call:
        try:
            external_rows = await external_call
        except ExternalSearchError:
            warnings.append("external_knowledge_unavailable")
        for row in external_rows:
            citation_id = "external:" + sha256(row["url"].encode("utf-8")).hexdigest()[:16]
            merged[citation_id] = {
                "id": citation_id, "materialId": citation_id, "filename": row["title"],
                "title": row["title"], "chunkText": row["content"], "sourceType": "external",
                "url": row["url"], "publishedAt": row.get("publishedAt"),
                "accessedAt": row["accessedAt"], "trustLevel": row["trustLevel"],
                "score": row.get("score"), "retrievalSource": row.get("provider", "public_search"),
            }

    points = await asyncio.to_thread(_knowledge_points, user_id=user_id, subject_id=subject_id)
    ranked = [_rank(item, topic=topic, knowledge_points=points) for item in merged.values()]
    course_candidates = [
        item for item in ranked
        if item["sourceType"] == "material" and item["relevanceScore"] >= 0.20
    ]
    external_candidates = [
        item for item in ranked
        if item["sourceType"] == "external" and item["relevanceScore"] >= 0.16
    ]
    if not course_candidates:
        raise ValueError("No relevant indexed course material was found for this topic")
    course_ranked = _deduplicate(course_candidates, 12)
    external_ranked = _deduplicate(external_candidates, 4)
    citations = sorted(course_ranked + external_ranked, key=lambda item: item["finalScore"], reverse=True)
    return {
        "citations": citations,
        "retrieval": {
            "mode": "exam_hybrid_ranked",
            "queries": queries,
            "publicQuery": public_query,
            "relevanceThresholds": {"course": 0.20, "external": 0.16},
            "sources": sorted(retrieval_sources | ({"public_knowledge"} if external_rows else set())),
            "courseEvidenceCount": len(course_ranked),
            "externalEvidenceCount": len(external_ranked),
            "externalAttempted": external_requested,
            "externalUsed": bool(external_ranked),
            "warnings": sorted(set(warnings)),
        },
    }
