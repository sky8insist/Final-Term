from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.db.vector_store import VectorStoreError, update_chunk_embeddings
from app.services.chunk_service import build_block_chunk_records
from app.services.content_service import insert_content_blocks
from app.services.embedding_service import EmbeddingError, embed_texts
from app.services.file_service import validate_upload_file
from app.services.lightrag_service import LightRAGServiceError, build_workspace, delete_material_index, index_material
from app.services.parse_service import DocumentParseError, parse_document_blocks
from app.services.mineru_parser import parse_material
from app.services.subject_service import get_subject
from app.services.security_service import scan_untrusted_text
from app.services.audio_service import AudioProcessingError, AudioSegment, split_audio_bytes
from app.services.multimodal_service import analyze_transcript, transcribe_audio
from app.services.parse_service import AUDIO_CONTENT_TYPES, build_audio_blocks


class ProcessingCancelled(RuntimeError):
    """Raised by the worker stage callback when the user cancels a task."""


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


def get_material_source(*, user_id: str, material_id: str, expires_in: int = 300) -> dict:
    client = get_supabase_client()
    materials = (
        client.table("materials").select(MATERIAL_SELECT)
        .eq("id", material_id).eq("user_id", user_id).limit(1).execute().data
    )
    if not materials:
        raise HTTPException(status_code=404, detail="Material not found")
    assets = (
        client.table("material_assets").select("bucket,object_path,content_type")
        .eq("material_id", material_id).eq("user_id", user_id)
        .eq("asset_type", "original").limit(1).execute().data
    )
    if not assets:
        raise HTTPException(status_code=404, detail="Original material file is unavailable")
    asset = assets[0]
    signed = client.storage.from_(asset["bucket"]).create_signed_url(
        asset["object_path"], min(max(expires_in, 60), 3600),
    )
    url = (
        signed.get("signedURL") or signed.get("signedUrl")
        or (signed.get("data") or {}).get("signedUrl")
    ) if isinstance(signed, dict) else None
    if not url:
        raise HTTPException(status_code=502, detail="Unable to create material preview URL")
    return {
        "materialId": material_id, "filename": materials[0]["filename"],
        "contentType": asset["content_type"], "url": url,
        "expiresIn": min(max(expires_in, 60), 3600),
    }


def _insert_material(
    *,
    client,
    user_id: str,
    subject_id: str,
    filename: str,
    content_type: str,
    file_size: int,
    status_value: str = "processing",
    source_hash: str | None = None,
) -> dict:
    payload = {
        "user_id": user_id,
        "subject_id": subject_id,
        "filename": filename,
        "content_type": content_type,
        "file_size": file_size,
        "status": status_value,
        "error_message": None,
        "source_hash": source_hash,
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
            "content_block_id": record.get("content_block_id"),
            "block_type": record.get("block_type"),
            "page_number": record.get("page_number"),
            "bounding_box": record.get("bounding_box"),
            "start_time": record.get("start_time"),
            "end_time": record.get("end_time"),
        }
        for record in records
    ]
    response = (
        client.table("material_chunks")
        .upsert(payload, on_conflict="material_id,chunk_index")
        .select(
            "id,user_id,subject_id,material_id,content_block_id,chunk_index,content,"
            "block_type,page_number,bounding_box,start_time,end_time,metadata,created_at"
        )
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
    client.table("lightrag_material_index").upsert(
        payload, on_conflict="user_id,material_id",
    ).execute()


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


def _store_audio_segments(
    *, client, user_id: str, subject_id: str, material_id: str,
    segments: list[AudioSegment],
) -> dict[int, str | None]:
    asset_ids: dict[int, str | None] = {}
    for segment in segments:
        if not segment.derived:
            asset_ids[segment.index] = None
            continue
        digest = sha256(segment.data).hexdigest()
        object_path = (
            f"{user_id}/{subject_id}/{material_id}/audio-segments/"
            f"{segment.index + 1:04d}-{digest[:12]}.wav"
        )
        client.storage.from_(settings.material_storage_bucket).upload(
            path=object_path, file=segment.data,
            file_options={"content-type": segment.content_type, "upsert": "true"},
        )
        response = client.table("material_assets").upsert({
            "user_id": user_id, "subject_id": subject_id, "material_id": material_id,
            "asset_type": "audio_segment", "bucket": settings.material_storage_bucket,
            "object_path": object_path, "content_type": segment.content_type,
            "file_size": len(segment.data), "sha256": digest,
            "metadata": {
                "segmentIndex": segment.index, "startTime": segment.start_time,
                "endTime": segment.end_time,
            },
            "expires_at": (
                datetime.now(UTC) + timedelta(days=settings.original_file_retention_days)
            ).isoformat(),
        }, on_conflict="bucket,object_path").select("id").execute()
        asset_ids[segment.index] = response.data[0]["id"] if response.data else None
    return asset_ids


def _store_mineru_artifacts(
    *, client, user_id: str, subject_id: str, material_id: str,
    bundle: bytes | None, markdown: bytes | None, metadata: dict | None,
) -> None:
    artifacts = [
        ("mineru_result", "result.zip", "application/zip", bundle),
        ("mineru_markdown", "full.md", "text/markdown; charset=utf-8", markdown),
    ]
    for asset_type, name, content_type, payload in artifacts:
        if not payload:
            continue
        digest = sha256(payload).hexdigest()
        object_path = f"{user_id}/{subject_id}/{material_id}/mineru/{digest[:16]}-{name}"
        client.storage.from_(settings.material_storage_bucket).upload(
            path=object_path, file=payload,
            file_options={"content-type": content_type, "upsert": "true"},
        )
        client.table("material_assets").upsert({
            "user_id": user_id, "subject_id": subject_id, "material_id": material_id,
            "asset_type": asset_type, "bucket": settings.material_storage_bucket,
            "object_path": object_path, "content_type": content_type,
            "file_size": len(payload), "sha256": digest,
            "metadata": metadata or {},
            "expires_at": (
                datetime.now(UTC) + timedelta(days=settings.original_file_retention_days)
            ).isoformat(),
        }, on_conflict="bucket,object_path").execute()


def _parse_material_blocks(
    *, client, user_id: str, subject_id: str, material_id: str,
    filename: str, content_type: str, file_bytes: bytes, on_stage=None,
    resume_batch_id: str | None = None, on_parser_event=None,
) -> list[dict]:
    suffix = Path(filename).suffix.lower()
    if content_type not in AUDIO_CONTENT_TYPES and suffix not in {".mp3", ".wav", ".m4a"}:
        parsed = parse_material(
            file_bytes, filename=filename, content_type=content_type,
            material_id=material_id, resume_batch_id=resume_batch_id,
            on_event=on_parser_event,
        )
        _store_mineru_artifacts(
            client=client, user_id=user_id, subject_id=subject_id,
            material_id=material_id, bundle=parsed.bundle,
            markdown=parsed.markdown, metadata=parsed.metadata,
        )
        return parsed.blocks
    try:
        audio_segments, _duration = split_audio_bytes(
            file_bytes, filename=filename, content_type=content_type,
        )
    except AudioProcessingError as exc:
        raise DocumentParseError(str(exc)) from exc
    asset_ids = _store_audio_segments(
        client=client, user_id=user_id, subject_id=subject_id,
        material_id=material_id, segments=audio_segments,
    )
    blocks: list[dict] = []
    for index, segment in enumerate(audio_segments):
        if on_stage:
            on_stage("parsing", min(15 + round(25 * index / max(len(audio_segments), 1)), 40))
        existing = (
            client.table("audio_segments").select("*")
            .eq("user_id", user_id).eq("material_id", material_id)
            .eq("segment_index", segment.index).limit(1).execute().data
        )
        row = existing[0] if existing else None
        if row and row.get("status") == "ready" and row.get("transcription"):
            transcription = row["transcription"]
        else:
            attempts = int(row.get("attempts", 0)) + 1 if row else 1
            segment_row = {
                "user_id": user_id, "subject_id": subject_id, "material_id": material_id,
                "asset_id": asset_ids.get(segment.index), "segment_index": segment.index,
                "start_time": segment.start_time, "end_time": segment.end_time,
                "status": "transcribing", "attempts": attempts,
                "transcription": None, "error_message": None,
            }
            client.table("audio_segments").upsert(
                segment_row, on_conflict="material_id,segment_index",
            ).execute()
            try:
                transcription = transcribe_audio(
                    segment.data, content_type=segment.content_type,
                    filename=segment.filename,
                )
            except Exception as exc:
                client.table("audio_segments").update({
                    "status": "failed", "error_message": str(exc)[:2000],
                }).eq("user_id", user_id).eq("material_id", material_id).eq(
                    "segment_index", segment.index,
                ).execute()
                raise
            client.table("audio_segments").update({
                "status": "ready", "transcription": transcription, "error_message": None,
            }).eq("user_id", user_id).eq("material_id", material_id).eq(
                "segment_index", segment.index,
            ).execute()
        segment_blocks = build_audio_blocks(
            transcription, audio_time_offset=segment.start_time,
            analyze_audio_transcript=False, audio_segment_index=segment.index,
        )
        blocks.extend(segment_blocks)
    transcript = "\n".join(block["content_text"] for block in blocks if block["content_text"].strip())
    if blocks and transcript:
        blocks[0]["structured_data"]["analysis"] = analyze_transcript(transcript)
    for sequence, block in enumerate(blocks):
        block["sequence_index"] = sequence
    return blocks


def process_material_bytes(
    *, user_id: str, subject_id: str, material_row: dict, filename: str,
    content_type: str, file_bytes: bytes, on_stage=None,
    resume_batch_id: str | None = None, on_parser_event=None,
) -> dict:
    client = get_supabase_client()
    try:
        if on_stage:
            on_stage("parsing", 15)
        content_blocks = _parse_material_blocks(
            client=client, user_id=user_id, subject_id=subject_id,
            material_id=material_row["id"], filename=filename,
            content_type=content_type, file_bytes=file_bytes, on_stage=on_stage,
            resume_batch_id=resume_batch_id, on_parser_event=on_parser_event,
        )
        for block in content_blocks:
            scan = scan_untrusted_text(block["content_text"])
            if scan["suspicious"]:
                block["metadata"] = {**block.get("metadata", {}), "promptInjectionRisk": scan}
                client.table("security_events").insert({
                    "user_id": user_id, "material_id": material_row["id"],
                    "event_type": "uploaded_prompt_injection", "severity": scan["severity"],
                    "details": {"sourceHash": block["source_hash"], "matchedPatterns": scan["matchedPatterns"]},
                }).execute()
        stored_blocks = insert_content_blocks(
            user_id=user_id, subject_id=subject_id,
            material_id=material_row["id"], blocks=content_blocks,
        )
        chunk_records = build_block_chunk_records(stored_blocks)
        if not chunk_records:
            raise DocumentParseError("No extractable text found in this file")

        chunks = _insert_material_chunks(
            client=client,
            user_id=user_id,
            subject_id=subject_id,
            material_id=material_row["id"],
            records=chunk_records,
        )
        if on_stage:
            on_stage("embedding", 45)
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
        prior_index = (
            client.table("lightrag_material_index").select("status")
            .eq("user_id", user_id).eq("material_id", material_row["id"]).execute().data
        )
        if prior_index:
            delete_material_index(
                user_id=user_id, subject_id=subject_id, material_id=material_row["id"],
                embedding_dimension=embedding_dimension,
            )
        _insert_lightrag_index(
            client=client,
            user_id=user_id,
            subject_id=subject_id,
            material_id=material_row["id"],
            workspace=workspace,
        )
        if on_stage:
            on_stage("indexing", 75)
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
        if on_stage:
            on_stage("ready", 100)
    except ProcessingCancelled:
        _update_material_status(
            client=client,
            user_id=user_id,
            material_id=material_row["id"],
            status_value="failed",
            error_message="Processing cancelled by user",
        )
        raise
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
        # LightRAG is an optional graph enhancement. At this point parsing,
        # chunks and vector embeddings have already succeeded, so keep the
        # material available through keyword/vector retrieval and record the
        # graph failure separately. Cleanup is intentionally avoided here:
        # the same unavailable backend could otherwise block this fallback.
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
            status_value="ready",
        )
        if on_stage:
            on_stage("ready", 100)
    except Exception:
        material_row = _update_material_status(
            client=client,
            user_id=user_id,
            material_id=material_row["id"],
            status_value="failed",
            error_message="Material processing failed",
        )

    return _to_material(material_row)


def create_uploaded_material(user_id: str, subject_id: str, file: UploadFile) -> dict:
    get_subject(user_id=user_id, subject_id=subject_id)
    file_size = validate_upload_file(file)
    filename = _clean_filename(file.filename)
    content_type = file.content_type or "application/octet-stream"
    file.file.seek(0)
    file_bytes = file.file.read()
    material_row = _insert_material(
        client=get_supabase_client(), user_id=user_id, subject_id=subject_id,
        filename=filename, content_type=content_type, file_size=file_size,
        source_hash=sha256(file_bytes).hexdigest(),
    )
    return process_material_bytes(
        user_id=user_id, subject_id=subject_id, material_row=material_row,
        filename=filename, content_type=content_type, file_bytes=file_bytes,
    )


def create_queued_material(
    *, user_id: str, subject_id: str, filename: str, content_type: str,
    file_size: int, source_hash: str,
) -> dict:
    row = _insert_material(
        client=get_supabase_client(), user_id=user_id, subject_id=subject_id,
        filename=_clean_filename(filename), content_type=content_type,
        file_size=file_size, status_value="queued", source_hash=source_hash,
    )
    return _to_material(row)
