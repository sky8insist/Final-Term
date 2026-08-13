from fastapi import HTTPException, status

from app.db.supabase_client import get_supabase_client
from app.db.vector_store import VectorStoreError, search_chunk_vectors
from app.services.embedding_service import EmbeddingError, embed_texts
from app.services.lightrag_service import LightRAGServiceError, build_workspace, extract_chunk_markers, search_context
from app.services.subject_service import get_subject


def _clean_question(question: str) -> str:
    cleaned = question.strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Question is required",
        )
    if len(cleaned) > 4000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Question must be 4000 characters or fewer",
        )
    return cleaned


def _normalize_top_k(top_k: int | None) -> int:
    if top_k is None:
        return 5
    return min(max(top_k, 1), 20)


def _get_subject_embedding_dimension(user_id: str, subject_id: str) -> int:
    client = get_supabase_client()
    response = (
        client.table("material_chunks")
        .select("embedding_dimensions")
        .eq("user_id", user_id)
        .eq("subject_id", subject_id)
        .not_.is_("embedding", "null")
        .limit(1)
        .execute()
    )
    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No indexed material found for this subject",
        )
    dimension = response.data[0].get("embedding_dimensions")
    if not dimension:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No indexed material found for this subject",
        )
    return int(dimension)


def search_subject_context(
    *,
    user_id: str,
    subject_id: str,
    question: str,
    top_k: int | None = None,
    material_ids: list[str] | None = None,
    block_types: list[str] | None = None,
    page_from: int | None = None,
    page_to: int | None = None,
    start_time: float | None = None,
    end_time: float | None = None,
    min_confidence: float | None = None,
) -> dict:
    get_subject(user_id=user_id, subject_id=subject_id)
    cleaned_question = _clean_question(question)
    normalized_top_k = _normalize_top_k(top_k)
    warnings: list[str] = []
    embedding_dimension = None
    try:
        embedding_dimension = _get_subject_embedding_dimension(user_id=user_id, subject_id=subject_id)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        warnings.append("vector_index_unavailable")
    workspace = build_workspace(user_id=user_id, subject_id=subject_id)
    raw_context = ""
    if embedding_dimension:
        try:
            workspace, raw_context = search_context(
                user_id=user_id,
                subject_id=subject_id,
                question=cleaned_question,
                top_k=normalized_top_k,
                embedding_dimension=embedding_dimension,
            )
        except LightRAGServiceError:
            warnings.append("lightrag_unavailable")
    lightrag_citations = extract_chunk_markers(raw_context)
    citations: list[dict] = []
    seen: dict[str, dict] = {}

    def add(item: dict, source: str, rank: int) -> None:
        key = str(item.get("blockId") or f"{item.get('materialId')}:{item.get('chunkIndex')}:{item.get('pageNumber')}:{item.get('startTime')}")
        if key in seen:
            existing = seen[key]
            existing["rrfScore"] += 1 / (60 + rank)
            existing["retrievalSources"] = sorted(set(existing.get("retrievalSources", [])) | {source})
            existing["retrievalSource"] = "+".join(existing["retrievalSources"])
            return
        seen[key] = item
        item["retrievalSource"] = source
        item["retrievalSources"] = [source]
        item["rrfScore"] = 1 / (60 + rank)
        citations.append(item)

    for rank, item in enumerate(lightrag_citations, start=1):
        if material_ids and item.get("materialId") not in material_ids:
            continue
        add(item, "lightrag", rank)

    try:
        rpc = get_supabase_client().rpc("search_content_blocks", {
            "query_text": cleaned_question,
            "target_user_id": user_id,
            "target_subject_id": subject_id,
            "target_material_ids": material_ids,
            "target_block_types": block_types,
            "min_confidence": min_confidence,
            "result_limit": normalized_top_k * 2,
        }).execute()
        keyword_rows = rpc.data or []
    except Exception:
        keyword_rows = []
    for rank, row in enumerate(keyword_rows, start=1):
        page = row.get("page_number")
        start = row.get("start_time")
        end = row.get("end_time")
        if page_from is not None and (page is None or page < page_from):
            continue
        if page_to is not None and (page is None or page > page_to):
            continue
        if start_time is not None and (end is None or end < start_time):
            continue
        if end_time is not None and (start is None or start > end_time):
            continue
        add({
            "blockId": str(row["id"]), "materialId": str(row["material_id"]),
            "filename": row.get("filename", "Unknown source"), "chunkIndex": None,
            "chunkText": row.get("content_text", ""), "blockType": row.get("block_type"),
            "pageNumber": page, "startTime": start, "endTime": end,
            "boundingBox": row.get("bounding_box"),
            "structuredData": row.get("structured_data") or {},
            "confidence": row.get("confidence"), "score": row.get("rank"),
        }, "keyword", rank)

    vector_rows = []
    if embedding_dimension:
        try:
            query_vector = embed_texts([cleaned_question])[0]
            vector_rows = search_chunk_vectors(
                user_id=user_id, subject_id=subject_id, query_vector=query_vector,
                limit=normalized_top_k * 2, material_ids=material_ids,
            )
        except (EmbeddingError, VectorStoreError, IndexError):
            warnings.append("vector_search_unavailable")
    for rank, row in enumerate(vector_rows, start=1):
        metadata = row.get("metadata") or {}
        add({
            "blockId": str(row["content_block_id"]) if row.get("content_block_id") else None,
            "materialId": str(row["material_id"]), "filename": row.get("filename", "Unknown source"),
            "chunkIndex": row.get("chunk_index"), "chunkText": row.get("content", ""),
            "pageNumber": row.get("page_number"), "blockType": row.get("block_type"),
            "boundingBox": row.get("bounding_box"),
            "startTime": row.get("start_time"), "endTime": row.get("end_time"),
            "confidence": metadata.get("confidence"),
            "score": float(row["score"]) if row.get("score") is not None else None,
        }, "vector", rank)

    citations.sort(key=lambda item: item.get("rrfScore", 0), reverse=True)
    citations = citations[:normalized_top_k]
    for item in citations:
        item["id"] = str(
            item.get("blockId")
            or f"{item.get('materialId')}:{item.get('chunkIndex', 0)}"
        )
    structured_context = "\n\n".join(
        f"[{item.get('filename')} page={item.get('pageNumber')} time={item.get('startTime')}-{item.get('endTime')}]\n{item.get('chunkText', '')}"
        for item in citations if item.get("retrievalSource") != "lightrag"
    )
    combined_context = raw_context
    if structured_context:
        combined_context = f"{raw_context}\n\n{structured_context}".strip()
    return {
        "subjectId": subject_id,
        "question": cleaned_question,
        "workspace": workspace,
        "rawContext": combined_context,
        "citations": citations,
        "retrieval": {
            "mode": "hybrid",
            "sources": sorted({source for item in citations for source in item.get("retrievalSources", [item["retrievalSource"]])}),
            "resultCount": len(citations),
            "warnings": warnings,
        },
    }
