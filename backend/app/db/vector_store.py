from collections.abc import Sequence

import psycopg

from app.config.settings import settings


class VectorStoreError(RuntimeError):
    pass


def _vector_literal(vector: Sequence[float]) -> str:
    if not vector:
        raise VectorStoreError("Cannot store an empty embedding vector")
    return "[" + ",".join(str(float(value)) for value in vector) + "]"


def update_chunk_embeddings(
    *,
    user_id: str,
    subject_id: str,
    material_id: str,
    chunks: list[dict],
    embeddings: list[list[float]],
    embedding_model: str,
) -> int:
    if len(chunks) != len(embeddings):
        raise VectorStoreError("Chunk and embedding counts did not match")
    if not chunks:
        return 0
    if not settings.database_url:
        raise VectorStoreError("DATABASE_URL is not configured")

    dimensions = len(embeddings[0])
    if dimensions == 0:
        raise VectorStoreError("Cannot store an empty embedding vector")
    if any(len(vector) != dimensions for vector in embeddings):
        raise VectorStoreError("Embedding dimensions were inconsistent")

    updated_count = 0
    try:
        with psycopg.connect(settings.database_url) as connection:
            with connection.cursor() as cursor:
                for chunk, embedding in zip(chunks, embeddings, strict=True):
                    cursor.execute(
                        """
                        update public.material_chunks
                        set
                            embedding = %s::vector,
                            embedding_model = %s,
                            embedding_dimensions = %s,
                            embedded_at = now()
                        where id = %s
                          and user_id = %s
                          and subject_id = %s
                          and material_id = %s
                        """,
                        (
                            _vector_literal(embedding),
                            embedding_model,
                            len(embedding),
                            chunk["id"],
                            user_id,
                            subject_id,
                            material_id,
                        ),
                    )
                    updated_count += cursor.rowcount
            connection.commit()
    except psycopg.Error as exc:
        raise VectorStoreError("Embedding vectors could not be stored") from exc

    if updated_count != len(chunks):
        raise VectorStoreError("Not all chunk embeddings were stored")

    return updated_count


def upsert_vectors(collection: str, vectors: list[dict]) -> dict:
    return {
        "collection": collection,
        "count": len(vectors),
    }


def search_vectors(collection: str, query_vector: list[float], limit: int = 5) -> list[dict]:
    return []


def search_chunk_vectors(
    *, user_id: str, subject_id: str, query_vector: list[float], limit: int,
    material_ids: list[str] | None = None,
) -> list[dict]:
    if not settings.database_url:
        raise VectorStoreError("DATABASE_URL is not configured")
    conditions = ["mc.user_id = %s", "mc.subject_id = %s", "mc.embedding is not null"]
    filter_params: list = [user_id, subject_id]
    if material_ids:
        conditions.append("mc.material_id = any(%s::uuid[])")
        filter_params.append(material_ids)
    vector_literal = _vector_literal(query_vector)
    params = [vector_literal, *filter_params, vector_literal, vector_literal, limit]
    sql = f"""
        select mc.id, mc.material_id, mc.content_block_id, m.filename,
               mc.chunk_index, mc.content, mc.block_type, mc.page_number,
               mc.bounding_box, mc.start_time, mc.end_time, mc.metadata,
               1 - (mc.embedding <=> %s::vector) as score
        from public.material_chunks mc
        join public.materials m on m.id = mc.material_id
        where {' and '.join(conditions)}
          and m.status = 'ready'
          and vector_dims(mc.embedding) = vector_dims(%s::vector)
        order by mc.embedding <=> %s::vector
        limit %s
    """
    try:
        with psycopg.connect(settings.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                columns = [description.name for description in cursor.description]
                return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    except psycopg.Error as exc:
        raise VectorStoreError("Vector search failed") from exc
