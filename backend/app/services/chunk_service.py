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
