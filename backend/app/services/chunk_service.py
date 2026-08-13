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
