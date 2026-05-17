import asyncio
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np
from lightrag import LightRAG, QueryParam
from lightrag.utils import EmbeddingFunc

from app.config.settings import settings
from app.services.embedding_service import embed_texts
from app.services.llm_service import generate_text_async

CHUNK_MARKER_PATTERN = re.compile(
    r"\[material_id=(?P<material_id>[^\]\s]+)\s+filename=(?P<filename>.*?)\s+chunk_index=(?P<chunk_index>\d+)\]"
)


class LightRAGServiceError(RuntimeError):
    pass


def build_workspace(user_id: str, subject_id: str) -> str:
    safe_user = re.sub(r"[^A-Za-z0-9_]+", "_", user_id)
    safe_subject = re.sub(r"[^A-Za-z0-9_]+", "_", subject_id)
    return f"user_{safe_user}_subject_{safe_subject}"


def _configure_postgres_env(workspace: str) -> None:
    if not settings.database_url:
        raise LightRAGServiceError("DATABASE_URL is not configured")

    parsed = urlparse(settings.database_url)
    if not parsed.hostname or not parsed.username or not parsed.path:
        raise LightRAGServiceError("DATABASE_URL is invalid")

    os.environ["POSTGRES_HOST"] = parsed.hostname
    os.environ["POSTGRES_PORT"] = str(parsed.port or 5432)
    os.environ["POSTGRES_USER"] = unquote(parsed.username)
    os.environ["POSTGRES_PASSWORD"] = unquote(parsed.password or "")
    os.environ["POSTGRES_DATABASE"] = unquote(parsed.path.lstrip("/"))
    os.environ["POSTGRES_WORKSPACE"] = workspace


async def _lightrag_embed(texts: list[str], **_kwargs) -> np.ndarray:
    return np.array(embed_texts(texts), dtype=np.float32)


async def _lightrag_llm(
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list[dict] | None = None,
    **kwargs,
) -> str:
    if history_messages:
        history_text = "\n".join(
            f"{message.get('role', 'user')}: {message.get('content', '')}"
            for message in history_messages
        )
        prompt = f"{history_text}\n\n{prompt}"
    return await generate_text_async(prompt, system_prompt=system_prompt, **kwargs)


def _build_rag(workspace: str, embedding_dimension: int) -> LightRAG:
    if embedding_dimension <= 0:
        raise LightRAGServiceError("Embedding dimension is invalid")

    _configure_postgres_env(workspace)
    Path(settings.lightrag_working_dir).mkdir(parents=True, exist_ok=True)
    return LightRAG(
        working_dir=settings.lightrag_working_dir,
        workspace=workspace,
        graph_storage="NetworkXStorage",
        vector_storage="PGVectorStorage",
        embedding_func=EmbeddingFunc(
            embedding_dim=embedding_dimension,
            func=_lightrag_embed,
            model_name=settings.embedding_model,
        ),
        llm_model_func=_lightrag_llm,
        llm_model_name=settings.llm_model,
    )


async def _index_material_async(
    *,
    user_id: str,
    subject_id: str,
    material_id: str,
    filename: str,
    chunks: list[dict],
    embedding_dimension: int,
) -> str:
    workspace = build_workspace(user_id=user_id, subject_id=subject_id)
    rag = _build_rag(workspace=workspace, embedding_dimension=embedding_dimension)
    await rag.initialize_storages()

    document = "\n\n".join(
        f"[material_id={material_id} filename={filename} chunk_index={chunk['chunk_index']}]\n{chunk['content']}"
        for chunk in chunks
    )
    await rag.ainsert(document, ids=material_id, file_paths=filename)
    return workspace


async def _search_async(
    *,
    user_id: str,
    subject_id: str,
    question: str,
    top_k: int,
    embedding_dimension: int,
) -> tuple[str, str]:
    workspace = build_workspace(user_id=user_id, subject_id=subject_id)
    rag = _build_rag(workspace=workspace, embedding_dimension=embedding_dimension)
    await rag.initialize_storages()
    context = await rag.aquery(
        question,
        QueryParam(
            mode="hybrid",
            only_need_context=True,
            top_k=top_k,
            chunk_top_k=top_k,
            enable_rerank=False,
        ),
    )
    return workspace, str(context or "")


def index_material(
    *,
    user_id: str,
    subject_id: str,
    material_id: str,
    filename: str,
    chunks: list[dict],
    embedding_dimension: int,
) -> str:
    try:
        return asyncio.run(
            _index_material_async(
                user_id=user_id,
                subject_id=subject_id,
                material_id=material_id,
                filename=filename,
                chunks=chunks,
                embedding_dimension=embedding_dimension,
            )
        )
    except Exception as exc:
        if isinstance(exc, LightRAGServiceError):
            raise
        raise LightRAGServiceError("LightRAG indexing failed") from exc


def search_context(
    *,
    user_id: str,
    subject_id: str,
    question: str,
    top_k: int,
    embedding_dimension: int,
) -> tuple[str, str]:
    try:
        return asyncio.run(
            _search_async(
                user_id=user_id,
                subject_id=subject_id,
                question=question,
                top_k=top_k,
                embedding_dimension=embedding_dimension,
            )
        )
    except Exception as exc:
        if isinstance(exc, LightRAGServiceError):
            raise
        raise LightRAGServiceError("LightRAG retrieval failed") from exc


def extract_chunk_markers(raw_context: str) -> list[dict]:
    seen: set[tuple[str, int]] = set()
    citations: list[dict] = []
    matches = list(CHUNK_MARKER_PATTERN.finditer(raw_context))
    for index, match in enumerate(matches):
        material_id = match.group("material_id")
        chunk_index = int(match.group("chunk_index"))
        key = (material_id, chunk_index)
        if key in seen:
            continue
        seen.add(key)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_context)
        citations.append(
            {
                "materialId": material_id,
                "filename": match.group("filename").strip(),
                "chunkIndex": chunk_index,
                "chunkText": raw_context[start:end].strip(),
                "score": None,
            }
        )
    return citations
