from app.db.supabase_client import get_supabase_client
from app.models.content import ContentBlock

CONTENT_BLOCK_SELECT = "id,material_id,parent_block_id,block_type,content_text,structured_data,page_number,bounding_box,start_time,end_time,sequence_index,parser_name,parser_version,confidence,source_hash,metadata,created_at"


def insert_content_blocks(*, user_id: str, subject_id: str, material_id: str, blocks: list[dict]) -> list[dict]:
    payload = []
    for block in blocks:
        validated = ContentBlock(**block).model_dump()
        payload.append({"user_id": user_id, "subject_id": subject_id, "material_id": material_id, **validated})
    if not payload:
        return []
    response = get_supabase_client().table("content_blocks").upsert(
        payload, on_conflict="material_id,parser_name,parser_version,source_hash",
    ).select(CONTENT_BLOCK_SELECT).execute()
    return response.data


def list_content_blocks(*, user_id: str, material_id: str, block_type: str | None = None) -> list[dict]:
    query = (
        get_supabase_client().table("content_blocks").select(CONTENT_BLOCK_SELECT)
        .eq("user_id", user_id).eq("material_id", material_id).order("sequence_index")
    )
    if block_type:
        query = query.eq("block_type", block_type)
    return query.execute().data
