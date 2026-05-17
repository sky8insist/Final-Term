from datetime import UTC, datetime

from fastapi import HTTPException, UploadFile, status

from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.db.vector_store import VectorStoreError, update_chunk_embeddings
from app.services.chunk_service import build_chunk_records
from app.services.embedding_service import EmbeddingError, embed_texts
from app.services.file_service import validate_upload_file
from app.services.lightrag_service import LightRAGServiceError, build_workspace, index_material
from app.services.parse_service import DocumentParseError, parse_document_bytes
from app.services.subject_service import get_subject

MATERIAL_SELECT = (
    "id,subject_id,filename,content_type,file_size,status,error_message,created_at,updated_at"
)


def _to_material(row: dict) -> dict:
    return {
        "id": row["id"],
        "subjectId": row["subject_id"],
        "filename": row["filename"],
        "contentType": row["content_type"],
        "fileSize": row["file_size"],
        "status": row["status"],
        "errorMessage": row.get("error_message"),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _clean_filename(filename: str | None) -> str:
    cleaned = (filename or "").strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Filename is required",
        )
    if len(cleaned) > 512:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Filename must be 512 characters or fewer",
        )
    return cleaned


def list_materials(user_id: str, subject_id: str | None = None) -> list[dict]:
    client = get_supabase_client()
    query = (
        client.table("materials")
        .select(MATERIAL_SELECT)
        .eq("user_id", user_id)
        .order("created_at", desc=True)
    )

    if subject_id:
        get_subject(user_id=user_id, subject_id=subject_id)
        query = query.eq("subject_id", subject_id)

    response = query.execute()
    return [_to_material(row) for row in response.data]


def _insert_material(
    *,
    client,
    user_id: str,
    subject_id: str,
    filename: str,
    content_type: str,
    file_size: int,
) -> dict:
    payload = {
        "user_id": user_id,
        "subject_id": subject_id,
        "filename": filename,
        "content_type": content_type,
        "file_size": file_size,
        "status": "processing",
        "error_message": None,
    }
    response = client.table("materials").insert(payload).select(MATERIAL_SELECT).execute()
    return response.data[0]


def _update_material_status(
    *,
    client,
    user_id: str,
    material_id: str,
    status_value: str,
    error_message: str | None = None,
) -> dict:
    payload = {
        "status": status_value,
        "error_message": error_message,
    }
    response = (
        client.table("materials")
        .update(payload)
        .eq("id", material_id)
        .eq("user_id", user_id)
        .select(MATERIAL_SELECT)
        .execute()
    )
    return response.data[0]


def _insert_material_chunks(
    *,
    client,
    user_id: str,
    subject_id: str,
    material_id: str,
    records: list[dict],
) -> list[dict]:
    payload = [
        {
            "user_id": user_id,
            "subject_id": subject_id,
            "material_id": material_id,
            "chunk_index": record["chunk_index"],
            "content": record["content"],
            "metadata": record["metadata"],
        }
        for record in records
    ]
    response = (
        client.table("material_chunks")
        .insert(payload)
        .select("id,user_id,subject_id,material_id,chunk_index,content,metadata,created_at")
        .execute()
    )
    return response.data


def _insert_lightrag_index(
    *,
    client,
    user_id: str,
    subject_id: str,
    material_id: str,
    workspace: str,
) -> None:
    payload = {
        "user_id": user_id,
        "subject_id": subject_id,
        "material_id": material_id,
        "workspace": workspace,
        "status": "indexing",
        "error_message": None,
        "indexed_at": None,
    }
    client.table("lightrag_material_index").insert(payload).execute()


def _update_lightrag_index_status(
    *,
    client,
    user_id: str,
    material_id: str,
    status_value: str,
    error_message: str | None = None,
) -> None:
    payload: dict = {
        "status": status_value,
        "error_message": error_message,
    }
    if status_value == "indexed":
        payload["indexed_at"] = datetime.now(UTC).isoformat()
    (
        client.table("lightrag_material_index")
        .update(payload)
        .eq("user_id", user_id)
        .eq("material_id", material_id)
        .execute()
    )


def create_uploaded_material(user_id: str, subject_id: str, file: UploadFile) -> dict:
    get_subject(user_id=user_id, subject_id=subject_id)
    file_size = validate_upload_file(file)
    filename = _clean_filename(file.filename)
    content_type = file.content_type or "application/octet-stream"
    file.file.seek(0)
    file_bytes = file.file.read()

    client = get_supabase_client()
    material_row = _insert_material(
        client=client,
        user_id=user_id,
        subject_id=subject_id,
        filename=filename,
        content_type=content_type,
        file_size=file_size,
    )

    try:
        text = parse_document_bytes(
            file_bytes,
            filename=filename,
            content_type=content_type,
        )
        chunk_records = build_chunk_records(text)
        if not chunk_records:
            raise DocumentParseError("No extractable text found in this file")

        chunks = _insert_material_chunks(
            client=client,
            user_id=user_id,
            subject_id=subject_id,
            material_id=material_row["id"],
            records=chunk_records,
        )
        embeddings = embed_texts([chunk["content"] for chunk in chunks])
        update_chunk_embeddings(
            user_id=user_id,
            subject_id=subject_id,
            material_id=material_row["id"],
            chunks=chunks,
            embeddings=embeddings,
            embedding_model=settings.embedding_model,
        )
        embedding_dimension = len(embeddings[0])
        workspace = build_workspace(user_id=user_id, subject_id=subject_id)
        _insert_lightrag_index(
            client=client,
            user_id=user_id,
            subject_id=subject_id,
            material_id=material_row["id"],
            workspace=workspace,
        )
        index_material(
            user_id=user_id,
            subject_id=subject_id,
            material_id=material_row["id"],
            filename=filename,
            chunks=chunks,
            embedding_dimension=embedding_dimension,
        )
        _update_lightrag_index_status(
            client=client,
            user_id=user_id,
            material_id=material_row["id"],
            status_value="indexed",
        )
        material_row = _update_material_status(
            client=client,
            user_id=user_id,
            material_id=material_row["id"],
            status_value="ready",
        )
    except DocumentParseError as exc:
        material_row = _update_material_status(
            client=client,
            user_id=user_id,
            material_id=material_row["id"],
            status_value="failed",
            error_message=str(exc),
        )
    except (EmbeddingError, VectorStoreError) as exc:
        material_row = _update_material_status(
            client=client,
            user_id=user_id,
            material_id=material_row["id"],
            status_value="failed",
            error_message=str(exc),
        )
    except LightRAGServiceError as exc:
        _update_lightrag_index_status(
            client=client,
            user_id=user_id,
            material_id=material_row["id"],
            status_value="failed",
            error_message=str(exc),
        )
        material_row = _update_material_status(
            client=client,
            user_id=user_id,
            material_id=material_row["id"],
            status_value="failed",
            error_message=str(exc),
        )
    except Exception:
        material_row = _update_material_status(
            client=client,
            user_id=user_id,
            material_id=material_row["id"],
            status_value="failed",
            error_message="Material processing failed",
        )

    return _to_material(material_row)
