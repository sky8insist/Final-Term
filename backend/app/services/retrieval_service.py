import re
from time import perf_counter

from fastapi import HTTPException, status
from app.config.settings import settings
from app.services.reranker_service import RerankerError, classify_intent, rerank, select_diverse
from app.services.parent_context_service import expand_parent_context

from app.db.supabase_client import get_supabase_client
from app.db.vector_store import VectorStoreError, search_chunk_vectors
from app.services.embedding_service import EmbeddingError, embed_texts
from app.services.lightrag_service import LightRAGServiceError, build_workspace, extract_chunk_markers, search_context
from app.services.subject_service import get_subject
from app.services.observability_service import record_operation


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


def _definition_query(question: str) -> str | None:
    """Create a deterministic lexical query for definition-style questions."""
    cleaned = question.strip().rstrip("?？.!。 ")
    english = re.fullmatch(
        r"what\s+is\s+(.+?)(?:'s|’s)\s+definition(?:\s+of\s+.+)?",
        cleaned, flags=re.IGNORECASE,
    )
    if english:
        return re.sub(r"\s+et\s+al\.?$", "", english.group(1).strip(), flags=re.IGNORECASE)
    english = re.fullmatch(r"how\s+(?:does|do)\s+(.+?)\s+define\s+.+", cleaned, flags=re.IGNORECASE)
    if english:
        return re.sub(r"\s+et\s+al\.?$", "", english.group(1).strip(), flags=re.IGNORECASE)
    english = re.fullmatch(r"what\s+does\s+(.+?)\s+mean(?:\s+.+)?", cleaned, flags=re.IGNORECASE)
    if english:
        return english.group(1).strip()
    english = re.fullmatch(r"what\s+(?:is|are)\s+(.+)", cleaned, flags=re.IGNORECASE)
    if english:
        term = english.group(1).strip()
        return f"{term} defined" if term else None
    english = re.fullmatch(r"define\s+(.+)", cleaned, flags=re.IGNORECASE)
    if english:
        term = english.group(1).strip()
        return f"{term} defined" if term else None
    chinese = re.fullmatch(r"什么是\s*(.+)", cleaned)
    if not chinese:
        chinese = re.fullmatch(r"(.+?)\s*是什么", cleaned)
    if chinese:
        term = chinese.group(1).strip()
        return f"{term} 定义" if term else None
    return None


def _concise_keyword_query(question: str) -> str | None:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9'-]*|[\u4e00-\u9fff]{2,}", question)
    stopwords = {
        "how", "does", "do", "what", "which", "why", "when", "where", "who",
        "is", "are", "the", "a", "an", "and", "or", "by", "of", "on", "in",
        "according", "mean", "means", "example", "examples", "describe", "describes",
    }
    compact = [
        re.sub(r"(?:'s|’s)$", "", token)
        for token in tokens
        if token.casefold() not in stopwords
    ]
    value = " ".join(compact[:8]).strip()
    return value if value and value.casefold() != question.strip().casefold() else None


def _expand_page_context(*, client, user_id: str, subject_id: str, citations: list[dict]) -> None:
    """Attach the surrounding slide text so split headings and answers stay together."""
    pairs = {
        (str(item.get("materialId")), int(item["pageNumber"]))
        for item in citations
        if item.get("materialId") and item.get("pageNumber") is not None
    }
    if not pairs:
        return
    try:
        rows = (
            client.table("content_blocks")
            .select("material_id,page_number,sequence_index,content_text")
            .eq("user_id", user_id)
            .eq("subject_id", subject_id)
            .in_("material_id", sorted({material_id for material_id, _ in pairs}))
            .in_("page_number", sorted({page for _, page in pairs}))
            .order("sequence_index")
            .execute()
            .data
        )
    except Exception:
        return
    page_text: dict[tuple[str, int], list[str]] = {}
    for row in rows or []:
        key = (str(row.get("material_id")), int(row.get("page_number")))
        if key not in pairs:
            continue
        text = re.sub(r"<[^>]+>", "", str(row.get("content_text") or "")).strip()
        if text and (not page_text.get(key) or page_text[key][-1] != text):
            page_text.setdefault(key, []).append(text)
    for item in citations:
        if item.get("pageNumber") is None:
            continue
        key = (str(item.get("materialId")), int(item["pageNumber"]))
        expanded = "\n".join(page_text.get(key, []))[:5000].strip()
        if expanded and len(expanded) > len(str(item.get("chunkText") or "")):
            item["chunkText"] = expanded
            item["contextExpanded"] = True


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


def _subject_has_lightrag_index(*, client, user_id: str, subject_id: str) -> bool:
    try:
        response = (
            client.table("lightrag_material_index")
            .select("id")
            .eq("user_id", user_id)
            .eq("subject_id", subject_id)
            .eq("status", "indexed")
            .limit(1)
            .execute()
        )
        return bool(response.data)
    except Exception:
        return False


def _hydrate_lightrag(*, client, user_id: str, subject_id: str, markers: list[dict]) -> list[dict]:
    """Graph text/markers are hints; only owned canonical DB chunks are evidence."""
    if not markers: return []
    material_ids = sorted({item["materialId"] for item in markers})
    indices = sorted({item["chunkIndex"] for item in markers})
    rows = []; offset = 0
    while True:
        page = (client.table("material_chunks")
                .select("id,parent_chunk_id,material_id,chunk_index,content,content_block_id,block_type,page_number,start_time,end_time,bounding_box,metadata,materials!inner(filename,status,user_id,subject_id)")
                .eq("user_id", user_id).eq("subject_id", subject_id)
                .eq("materials.user_id", user_id).eq("materials.subject_id", subject_id).eq("materials.status", "ready")
                .in_("material_id", material_ids).in_("chunk_index", indices).order("material_id").order("chunk_index")
                .range(offset, offset + 499).execute().data)
        rows.extend(page)
        if len(page) < 500: break
        offset += 500
    by_key = {(str(row["material_id"]), row["chunk_index"]): row for row in rows}
    result = []
    for marker in markers:
        row = by_key.get((marker["materialId"], marker["chunkIndex"]))
        if not row: continue
        result.append({**marker, "chunkText": row["content"], "filename": row["materials"]["filename"],
            "chunkId": str(row["id"]) if row.get("id") else None, "parentChunkId": row.get("parent_chunk_id"),
            "blockId": str(row["content_block_id"]) if row.get("content_block_id") else None,
            "blockType": row.get("block_type"), "pageNumber": row.get("page_number"),
            "startTime": row.get("start_time"), "endTime": row.get("end_time"),
            "boundingBox": row.get("bounding_box"), "confidence": (row.get("metadata") or {}).get("confidence")})
    return result


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
    strategy: str = "adaptive",
) -> dict:
    operation_started = perf_counter()
    get_subject(user_id=user_id, subject_id=subject_id)
    cleaned_question = _clean_question(question)
    if strategy not in {"baseline", "adaptive"}: raise HTTPException(422, "Invalid retrieval strategy")
    intent = classify_intent(cleaned_question)
    normalized_top_k = _normalize_top_k(top_k if top_k is not None else
        (5 if strategy == "baseline" else {"definition": 3, "problem": 6, "comparison": 8, "general": 5}[intent]))
    candidate_k = max(settings.retrieval_candidate_k, normalized_top_k)
    client = get_supabase_client()
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
    has_lightrag_index = _subject_has_lightrag_index(
        client=client, user_id=user_id, subject_id=subject_id,
    )
    if embedding_dimension and has_lightrag_index:
        try:
            workspace, raw_context = search_context(
                user_id=user_id,
                subject_id=subject_id,
                question=cleaned_question,
                top_k=candidate_k,
                embedding_dimension=embedding_dimension,
            )
        except LightRAGServiceError:
            warnings.append("lightrag_unavailable")
    elif embedding_dimension:
        warnings.append("lightrag_unavailable")
    record_operation(
        operation="retrieval", stage="lightrag", status="succeeded",
        started_at=operation_started,
        metadata={"available": has_lightrag_index, "warningCount": len(warnings)},
    )
    stage_started = perf_counter()
    try:
        lightrag_citations = _hydrate_lightrag(client=client, user_id=user_id, subject_id=subject_id,
            markers=extract_chunk_markers(raw_context)[:candidate_k])
    except Exception:
        lightrag_citations = []
        warnings.append("lightrag_scope_verification_unavailable")
    citations: list[dict] = []
    seen: dict[str, dict] = {}

    def add(item: dict, source: str, rank: int) -> None:
        # Apply every caller constraint to all three retrievers, before providers
        # or the answer model see any source text.
        if material_ids and item.get("materialId") not in material_ids: return
        if block_types and item.get("blockType") not in block_types: return
        page, start, end = item.get("pageNumber"), item.get("startTime"), item.get("endTime")
        if page_from is not None and (page is None or page < page_from): return
        if page_to is not None and (page is None or page > page_to): return
        if start_time is not None and (end is None or end < start_time): return
        if end_time is not None and (start is None or start > end_time): return
        confidence = item.get("confidence")
        if min_confidence is not None and (confidence is None or confidence < min_confidence): return
        key = str(item.get("chunkId") or item.get("blockId") or f"{item.get('materialId')}:{item.get('chunkIndex')}:{item.get('pageNumber')}:{item.get('startTime')}")
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

    def keyword_search(query: str) -> list[dict]:
        try:
            rpc = client.rpc("search_content_blocks", {
                "query_text": query,
                "target_user_id": user_id,
                "target_subject_id": subject_id,
                "target_material_ids": material_ids,
                "target_block_types": block_types,
                "min_confidence": min_confidence,
                # Retrieve a broader lexical candidate set before fusion. This
                # matters for author-definition queries, where the definitive
                # page can otherwise be just below an early generic strategy
                # match.
                "result_limit": min(candidate_k * 2, 160),
            }).execute()
            return rpc.data or []
        except Exception:
            return []

    def add_keyword_rows(rows: list[dict], source: str) -> None:
        for rank, row in enumerate(rows, start=1):
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
                "chunkId": (row.get("structured_data") or {}).get("retrievalChunkId"),
                "parentChunkId": (row.get("structured_data") or {}).get("parentChunkId"),
                "filename": row.get("filename", "Unknown source"), "chunkIndex": (row.get("structured_data") or {}).get("chunkIndex"),
                "chunkText": row.get("content_text", ""), "blockType": row.get("block_type"),
                "pageNumber": page, "startTime": start, "endTime": end,
                "boundingBox": row.get("bounding_box"),
                "structuredData": row.get("structured_data") or {},
                "confidence": row.get("confidence"), "score": row.get("rank"),
            }, source, rank)

    add_keyword_rows(keyword_search(cleaned_question), "keyword")
    definition_query = _definition_query(cleaned_question)
    if definition_query and definition_query.casefold() != cleaned_question.casefold():
        add_keyword_rows(keyword_search(definition_query), "keyword_definition")
    concise_query = _concise_keyword_query(cleaned_question)
    if concise_query:
        add_keyword_rows(keyword_search(concise_query), "keyword_concise")
    record_operation(
        operation="retrieval", stage="keyword", status="succeeded",
        started_at=stage_started, metadata={"candidateCount": len(citations)},
    )

    stage_started = perf_counter()
    vector_rows = []
    if embedding_dimension:
        try:
            query_vector = embed_texts([cleaned_question])[0]
            vector_rows = search_chunk_vectors(
                user_id=user_id, subject_id=subject_id, query_vector=query_vector,
                limit=candidate_k, material_ids=material_ids,
            )
        except (EmbeddingError, VectorStoreError, IndexError):
            warnings.append("vector_search_unavailable")
    for rank, row in enumerate(vector_rows, start=1):
        metadata = row.get("metadata") or {}
        add({
            "blockId": str(row["content_block_id"]) if row.get("content_block_id") else None,
            "chunkId": str(row["id"]) if row.get("id") else None, "parentChunkId": row.get("parent_chunk_id"),
            "materialId": str(row["material_id"]), "filename": row.get("filename", "Unknown source"),
            "chunkIndex": row.get("chunk_index"), "chunkText": row.get("content", ""),
            "pageNumber": row.get("page_number"), "blockType": row.get("block_type"),
            "boundingBox": row.get("bounding_box"),
            "startTime": row.get("start_time"), "endTime": row.get("end_time"),
            "confidence": metadata.get("confidence"),
            "score": float(row["score"]) if row.get("score") is not None else None,
        }, "vector", rank)

    # A one-token definition query is an extracted author name (for example,
    # "How does Chandler define strategy?").  Prefer source blocks that name
    # that author, while retaining all fused candidates and their evidence.
    author_hint = definition_query or ""
    if re.fullmatch(r"[A-Za-z][A-Za-z'-]*", author_hint):
        author_hint = author_hint.casefold()
        for item in citations:
            if author_hint in str(item.get("chunkText") or "").casefold():
                item["rrfScore"] += 0.1
    record_operation(
        operation="retrieval", stage="vector", status="succeeded",
        started_at=stage_started,
        metadata={"candidateCount": len(vector_rows), "dimensions": embedding_dimension},
    )

    citations.sort(key=lambda item: item.get("rrfScore", 0), reverse=True)
    candidates = citations[:candidate_k]
    stage_started = perf_counter()
    reranker_mode = "none" if strategy == "baseline" else settings.reranker_mode
    reranker_used = reranker_mode
    try:
        ranked = rerank(cleaned_question, candidates, reranker_mode)
    except RerankerError:
        ranked = candidates; reranker_used = "none"
        warnings.append("reranker_unavailable")
    citations = ranked[:normalized_top_k] if strategy == "baseline" else select_diverse(ranked, normalized_top_k)
    record_operation(operation="retrieval", stage="rerank", status="succeeded", started_at=stage_started,
        metadata={"candidateCount": len(candidates), "reranker": reranker_used, "requestedReranker": reranker_mode})
    expansion = {"expandedCount": 0, "unavailable": False}
    if strategy == "adaptive":
        expansion = expand_parent_context(client=client, user_id=user_id, subject_id=subject_id, citations=citations,
            block_types=block_types, page_from=page_from, page_to=page_to, start_time=start_time,
            end_time=end_time, min_confidence=min_confidence)
        if expansion["unavailable"]: warnings.append("parent_context_unavailable")
    # Legacy decks retain page expansion as an explicit baseline, but primary
    # evidence text/coordinates are preserved even in that mode.
    if strategy == "baseline" and not block_types and min_confidence is None and start_time is None and end_time is None:
        copies = [dict(item) for item in citations]
        _expand_page_context(client=client, user_id=user_id, subject_id=subject_id, citations=copies)
        for item, expanded in zip(citations, copies, strict=True):
            if expanded.get("contextExpanded"):
                item.update(contextText=expanded["chunkText"], contextExpanded=True)
    for item in citations:
        item["id"] = str(
            item.get("chunkId") or item.get("blockId")
            or f"{item.get('materialId')}:{item.get('chunkIndex', 0)}"
        )
    structured_context = "\n\n".join(
        f"[{item.get('filename')} page={item.get('pageNumber')} time={item.get('startTime')}-{item.get('endTime')}]\n{item.get('contextText', item.get('chunkText', ''))}"
        for item in citations
    )
    # Never append unfiltered graph prose, dropped candidates or foreign markers.
    combined_context = structured_context
    result = {
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
            "strategy": strategy, "intent": intent, "candidateK": candidate_k,
            "candidateCount": len(candidates), "topK": normalized_top_k,
            "reranker": reranker_used, "requestedReranker": reranker_mode,
            "queryRewrites": [value for value in [definition_query, concise_query] if value],
            "pipelineVersion": "retrieval-v3-parent-child", "parentContext": expansion,
        },
    }
    record_operation(
        operation="retrieval", stage="complete", status="succeeded",
        started_at=operation_started,
        metadata={"resultCount": len(citations), "warnings": warnings, "topK": normalized_top_k},
    )
    return result
