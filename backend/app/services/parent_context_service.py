"""Expand selected child evidence without changing its text, ID or location."""
from app.config.settings import settings


def _allowed(row: dict, *, block_types=None, page_from=None, page_to=None,
             start_time=None, end_time=None, min_confidence=None) -> bool:
    if block_types and row.get("blockType") not in block_types: return False
    page, start, end = row.get("pageNumber"), row.get("startTime"), row.get("endTime")
    if page_from is not None and (page is None or page < page_from): return False
    if page_to is not None and (page is None or page > page_to): return False
    if start_time is not None and (end is None or end < start_time): return False
    if end_time is not None and (start is None or start > end_time): return False
    confidence = row.get("confidence")
    return min_confidence is None or (confidence is not None and confidence >= min_confidence)


def expand_parent_context(*, client, user_id: str, subject_id: str, citations: list[dict], **filters) -> dict:
    ids = sorted({str(item["blockId"]) for item in citations if item.get("blockId")})
    if not ids: return {"expandedCount": 0, "unavailable": False}
    try:
        rows = client.rpc("parent_context_blocks", {"p_user_id": user_id, "p_subject_id": subject_id, "p_block_ids": ids}).execute().data
        by_anchor = {}
        for row in rows:
            if row["anchorBlockId"] in ids: by_anchor.setdefault(row["anchorBlockId"], []).append(row)
    except Exception:
        return {"expandedCount": 0, "unavailable": True}
    count = 0
    for item in citations:
        members = [row for row in by_anchor.get(str(item.get("blockId")), [])
                   if str(row["materialId"]) == str(item["materialId"]) and _allowed(row, **filters)]
        if not members: continue
        # A block belongs to one current section. Keep only the parent of the
        # selected child if present, never an unrelated neighbouring section.
        parent_id = item.get("parentChunkId") or members[0]["parentChunkId"]
        members = [row for row in members if row["parentChunkId"] == parent_id]
        anchor = next((row for row in members if row["blockId"] == str(item.get("blockId"))), None)
        if not anchor: continue
        remaining = max(0, settings.retrieval_parent_context_chars - len(str(item.get("chunkText") or "")))
        chosen = []
        for row in sorted(members, key=lambda row: (abs(row["sequence"] - anchor["sequence"]), row["sequence"])):
            if row["blockId"] == anchor["blockId"]: continue
            text = str(row.get("text") or "").strip()
            label = f"[block={row['blockId']} page={row.get('pageNumber')} time={row.get('startTime')}-{row.get('endTime')}]\n"
            cost = len(text) + len(label) + 2
            if not text or cost > remaining: continue
            chosen.append(row); remaining -= cost
        if not chosen: continue
        chosen.sort(key=lambda row: row["sequence"])
        item.update(parentChunkId=parent_id, contextExpanded=True, contextBlocks=chosen)
        item["contextText"] = str(item.get("chunkText") or "") + "\n\n" + "\n\n".join(
            f"[block={row['blockId']} page={row.get('pageNumber')} time={row.get('startTime')}-{row.get('endTime')}]\n{row['text']}"
            for row in chosen)
        count += 1
    return {"expandedCount": count, "unavailable": False}
