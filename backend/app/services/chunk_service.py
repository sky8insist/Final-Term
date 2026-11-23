import re
from uuid import uuid4


def _normalize_text(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip()).strip()


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 120) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")
    if overlap < 0:
        raise ValueError("overlap must be greater than or equal to 0")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    cleaned = _normalize_text(text)
    if not cleaned:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = start + chunk_size
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start = end - overlap

    return chunks


def build_chunk_records(text: str, chunk_size: int = 800, overlap: int = 120) -> list[dict]:
    chunks = chunk_text(text=text, chunk_size=chunk_size, overlap=overlap)
    return [
        {
            "chunk_index": index,
            "content": content,
            "metadata": {
                "chunk_size": chunk_size,
                "overlap": overlap,
                "char_count": len(content),
            },
        }
        for index, content in enumerate(chunks)
    ]


def build_block_chunk_records(
    blocks: list[dict], chunk_size: int = 800, overlap: int = 120,
) -> list[dict]:
    """Split each content block independently so every chunk remains traceable."""
    records: list[dict] = []
    for block in sorted(blocks, key=lambda item: int(item.get("sequence_index", 0))):
        text = str(block.get("content_text", ""))
        for block_chunk_index, content in enumerate(
            chunk_text(text=text, chunk_size=chunk_size, overlap=overlap),
        ):
            records.append({
                "chunk_index": len(records),
                "content": content,
                "content_block_id": block.get("id"),
                "block_type": block.get("block_type"),
                "page_number": block.get("page_number"),
                "bounding_box": block.get("bounding_box"),
                "start_time": block.get("start_time"),
                "end_time": block.get("end_time"),
                "metadata": {
                    "chunk_size": chunk_size,
                    "overlap": overlap,
                    "char_count": len(content),
                    "block_chunk_index": block_chunk_index,
                    "block_sequence_index": block.get("sequence_index"),
                    "parser_name": block.get("parser_name"),
                    "parser_version": block.get("parser_version"),
                    "confidence": block.get("confidence"),
                },
            })
    return records


def sentence_chunks(text: str, chunk_size: int = 800, overlap: int = 120) -> list[str]:
    """Prefer complete sentences/lines; use the baseline only for oversized units."""
    # Reuse baseline argument validation without changing its public behavior.
    chunk_text("", chunk_size, overlap)
    text = _normalize_text(text)
    if not text: return []
    units = [unit.strip() for unit in re.split(r"(?<=[。！？!?])\s*|(?<=\.)\s+|\n+", text) if unit.strip()]
    units = [part for unit in units for part in (chunk_text(unit, chunk_size, overlap) if len(unit) > chunk_size else [unit])]
    result = []; start = 0
    while start < len(units):
        end = start + 1; size = len(units[start])
        while end < len(units) and size + 1 + len(units[end]) <= chunk_size:
            size += 1 + len(units[end]); end += 1
        result.append("\n".join(units[start:end]))
        if end == len(units): break
        start = end - 1 if end - start > 1 and len(units[end - 1]) <= overlap else end
    return result


def _table_chunks(block: dict, chunk_size: int) -> list[str]:
    rows = (block.get("structured_data") or {}).get("rows")
    if not isinstance(rows, list) or not rows or any(not isinstance(row, list) for row in rows):
        # Opaque HTML/merged cells must remain atomic until a trustworthy row
        # representation is available. Never cut a cell by character count.
        text = str(block.get("content_text") or "").strip()
        return [text] if text else []
    def render(row):
        return "| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", "<br>") for cell in row) + " |"
    header = render(rows[0]) + "\n" + render(["---"] * len(rows[0]))
    if len(rows) == 1: return [header]
    result = []; current = header
    for row in rows[1:]:
        line = render(row)
        if current != header and len(current) + 1 + len(line) > chunk_size:
            result.append(current); current = header
        current += "\n" + line
    if current != header: result.append(current)
    return result


def _heading_level(block: dict) -> int:
    from app.services.document_structure_service import heading_level
    return heading_level(block)[0]


def _related_neighbours(left: dict, right: dict) -> bool:
    target = right.get('source_hash')
    return bool(target) and left.get('page_number') == right.get('page_number') and any(ref.get('sourceHash') == target and ref.get('sequenceIndex') == right['sequence_index']
        for ref in ((left.get('metadata') or {}).get('documentStructure') or {}).get('relations', []))


def build_structure_chunk_bundle(blocks: list[dict], chunk_size: int = 800,
                                 overlap: int = 120, parent_size: int = 4000) -> dict:
    """Bounded heading sections as parents; traceable sentence/row children."""
    chunk_text("", chunk_size, overlap)
    if parent_size < chunk_size: raise ValueError("parent_size must be at least chunk_size")
    ordered = [block for block in sorted(blocks, key=lambda item: int(item.get("sequence_index", 0)))
               if str(block.get("content_text") or "").strip()]
    if any(not block.get("id") for block in ordered): raise ValueError("Persist blocks before constructing parent chunks")
    groups = []; group = []; path = []; group_path = []; size = 0
    for block in ordered:
        heading = block.get("block_type") == "heading"
        text = str(block["content_text"])
        same_page = bool(group) and group[-1].get('page_number') == block.get('page_number')
        formula_neighbour = same_page and (block.get("block_type") == "formula" or (group and group[-1].get("block_type") == "formula"))
        related = group and (_related_neighbours(group[-1], block) or _related_neighbours(block, group[-1]))
        if group and (heading or (size + len(text) + 1 > parent_size and not formula_neighbour and not related)):
            groups.append((group, group_path)); group = []; size = 0
        if heading:
            level = _heading_level(block)
            path = [(n, title) for n, title in path if n < level] + [(level, text.strip())]
        if not group: group_path = [title for _, title in path]
        group.append(block); size += len(text) + 1
    if group: groups.append((group, group_path))
    parents = []; records = []
    for parent_index, (group, headings) in enumerate(groups):
        parent_id = str(uuid4())
        parents.append({"id": parent_id, "parent_index": parent_index, "heading_path": headings,
                        "block_ids": [str(block["id"]) for block in group], "strategy_version": "structure-v2"})
        for block in group:
            kind = block.get("block_type")
            chunks = _table_chunks(block, chunk_size) if kind == "table" else (
                [str(block["content_text"]).strip()] if kind in {"formula", "heading"} else sentence_chunks(str(block["content_text"]), chunk_size, overlap))
            for local_index, content in enumerate(chunks):
                records.append({"chunk_index": len(records), "content": content, "parent_chunk_id": parent_id,
                    "content_block_id": str(block["id"]), "block_type": kind,
                    "page_number": block.get("page_number"), "bounding_box": block.get("bounding_box"),
                    "start_time": block.get("start_time"), "end_time": block.get("end_time"),
                    "metadata": {"strategy": "structure", "strategy_version": "structure-v2", "chunk_size": chunk_size,
                        "overlap": overlap, "char_count": len(content), "block_chunk_index": local_index,
                        "block_sequence_index": block.get("sequence_index"), "heading_path": headings,
                        "oversized_atomic": kind in {"table", "formula", "heading"} and len(content) > chunk_size,
                        "confidence": block.get("confidence"), "parser_name": block.get("parser_name"),
                        "documentStructure": (block.get('metadata') or {}).get('documentStructure'),
                        "parser_version": block.get("parser_version")}})
    return {"parents": parents, "records": records}
