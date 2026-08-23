import asyncio
import os
import re
import threading
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np
from lightrag import LightRAG, QueryParam
from lightrag.utils import EmbeddingFunc, Tokenizer

from app.config.settings import settings
from app.services.embedding_service import embed_texts
from app.services.llm_service import generate_text_async

CHUNK_MARKER_PATTERN = re.compile(
    r"\[material_id=(?P<material_id>[^\]\s]+)\s+filename=(?P<filename>.*?)"
    r"\s+chunk_index=(?P<chunk_index>\d+)"
    r"(?:\s+block_id=(?P<block_id>[^\]\s]+))?"
    r"(?:\s+block_type=(?P<block_type>[^\]\s]+))?"
    r"(?:\s+page_number=(?P<page_number>[^\]\s]+))?"
    r"(?:\s+start_time=(?P<start_time>[^\]\s]+))?"
    r"(?:\s+end_time=(?P<end_time>[^\]\s]+))?\]"
)
_RAG_ENV_LOCK = threading.RLock()
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class LightRAGServiceError(RuntimeError):
    pass


class _UnicodeCodepointTokenizer:
    """Deterministic offline tokenizer used for LightRAG chunk boundaries."""

    @staticmethod
    def encode(content: str) -> list[int]:
        return [ord(character) for character in content]

    @staticmethod
    def decode(tokens: list[int]) -> str:
        return "".join(chr(token) for token in tokens)


def _resolve_working_dir() -> Path:
    """Resolve relative LightRAG storage paths from the repository root."""
    configured = Path(settings.lightrag_working_dir).expanduser()
    return configured if configured.is_absolute() else PROJECT_ROOT / configured


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
    working_dir = _resolve_working_dir()
    working_dir.mkdir(parents=True, exist_ok=True)
    return LightRAG(
        working_dir=str(working_dir),
        workspace=workspace,
        tokenizer=Tokenizer(
            model_name="unicode-codepoint",
            tokenizer=_UnicodeCodepointTokenizer(),
        ),
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

    def marker(chunk: dict) -> str:
        return (
            f"[material_id={material_id} filename={filename} chunk_index={chunk['chunk_index']}"
            f" block_id={chunk.get('content_block_id') or '-'}"
            f" block_type={chunk.get('block_type') or '-'}"
            f" page_number={chunk.get('page_number') or '-'}"
            f" start_time={chunk.get('start_time') if chunk.get('start_time') is not None else '-'}"
            f" end_time={chunk.get('end_time') if chunk.get('end_time') is not None else '-'}]"
        )

    document = "\n\n".join(
        f"{marker(chunk)}\n{chunk['content']}" for chunk in chunks
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


async def _delete_material_async(*, user_id: str, subject_id: str,
                                 material_id: str, embedding_dimension: int) -> None:
    workspace = build_workspace(user_id=user_id, subject_id=subject_id)
    rag = _build_rag(workspace=workspace, embedding_dimension=embedding_dimension)
    await rag.initialize_storages()
    try:
        await rag.adelete_by_doc_id(material_id, delete_llm_cache=False)
    finally:
        await rag.finalize_storages()


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
        with _RAG_ENV_LOCK:
            return asyncio.run(
                asyncio.wait_for(
                    _index_material_async(
                        user_id=user_id,
                        subject_id=subject_id,
                        material_id=material_id,
                        filename=filename,
                        chunks=chunks,
                        embedding_dimension=embedding_dimension,
                    ),
                    timeout=settings.lightrag_index_timeout_seconds,
                )
            )
    except TimeoutError as exc:
        timeout_seconds = settings.lightrag_index_timeout_seconds
        raise LightRAGServiceError(
            f"LightRAG indexing timed out after {timeout_seconds:g} seconds"
        ) from exc
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
        with _RAG_ENV_LOCK:
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


def delete_material_index(*, user_id: str, subject_id: str,
                          material_id: str, embedding_dimension: int) -> None:
    try:
        with _RAG_ENV_LOCK:
            asyncio.run(_delete_material_async(
                user_id=user_id, subject_id=subject_id, material_id=material_id,
                embedding_dimension=embedding_dimension,
            ))
    except Exception as exc:
        raise LightRAGServiceError("LightRAG material deletion failed") from exc


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
        def optional_text(name: str) -> str | None:
            value = match.groupdict().get(name)
            return None if not value or value == "-" else value

        def optional_float(name: str) -> float | None:
            value = optional_text(name)
            try:
                return float(value) if value is not None else None
            except ValueError:
                return None

        page_text = optional_text("page_number")
        citations.append(
            {
                "blockId": optional_text("block_id"),
                "materialId": material_id,
                "filename": match.group("filename").strip(),
                "chunkIndex": chunk_index,
                "chunkText": raw_context[start:end].strip(),
                "blockType": optional_text("block_type"),
                "pageNumber": int(page_text) if page_text and page_text.isdigit() else None,
                "startTime": optional_float("start_time"),
                "endTime": optional_float("end_time"),
                "score": None,
            }
        )
    return citations
