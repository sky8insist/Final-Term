"""Evidence-bound heading sections. No model calls or automatic Topic writes."""
import json

from fastapi import HTTPException

from app.db.supabase_client import get_supabase_client
from app.services.chunk_service import _heading_level
from app.services.course_service import _owned

MAX_BLOCKS = 2000
MAX_SECTIONS = 60
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
SNAPSHOT_FIELDS = 'id,block_type,content_text,sequence_index,page_number,metadata,structured_data'


def split_sections(blocks: list[dict]) -> list[dict]:
    """Every block belongs to one contiguous section, including the preamble."""
    if len(blocks) > MAX_BLOCKS:
        raise HTTPException(422, '资料超过 2000 个内容块，请拆分文件后再生成章节')
    sections = []
    path = []
    for block in sorted(blocks, key=lambda row: (row['sequence_index'], row['id'])):
        heading = block['block_type'] == 'heading' and bool((block.get('content_text') or '').strip())
        if heading:
            level = _heading_level(block)
            title = block['content_text'].strip()
            path = [(depth, text) for depth, text in path if depth < level] + [(level, title)]
            if len(title) > 300:
                raise HTTPException(422, '检测到超过 300 字的标题，请校对解析结果后重试')
            sections.append({'sourceBlockId': block['id'], 'title': title,
                             'chapterTitle': path[0][1], 'headingPath': [text for _, text in path],
                             'blockIds': [], 'pageNumber': block.get('page_number')})
        if not sections:
            sections.append({'sourceBlockId': None, 'title': '正文前言', 'chapterTitle': None,
                             'headingPath': [], 'blockIds': [], 'pageNumber': block.get('page_number')})
        sections[-1]['blockIds'].append(block['id'])
    if len(sections) > MAX_SECTIONS:
        raise HTTPException(422, '章节超过 60 节，请拆分文件后再生成提案')
    return sections


def rpc(name: str, values: dict):
    try:
        return get_supabase_client().rpc(name, values).execute().data
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if code == '42501':
            raise HTTPException(404, '资料或提案不存在') from exc
        if code in {'40001', '40P01'}:
            raise HTTPException(409, '资料或提案已变化，请刷新后重新生成或确认') from exc
        if code in {'22023', '23514'}:
            raise HTTPException(422, '资料未入库、章节无效或知识点已归档') from exc
        raise


def prepare(*, user_id: str, subject_id: str, material_id: str):
    material = _owned(table='materials', row_id=material_id, user_id=user_id, subject_id=subject_id)
    if material['status'] != 'ready':
        raise HTTPException(409, '资料入库后才能生成章节提案')
    # Explicit pagination prevents the PostgREST default 1000-row cap from
    # silently truncating chapter membership. SQL rechecks the entire snapshot.
    blocks = []
    client = get_supabase_client()
    for start in range(0, MAX_BLOCKS + 1, 500):
        rows = (client.table('content_blocks').select(SNAPSHOT_FIELDS)
                .eq('user_id', user_id).eq('subject_id', subject_id).eq('material_id', material_id)
                .order('sequence_index').order('id').range(start, min(start + 499, MAX_BLOCKS)).execute().data)
        blocks.extend(rows)
        if len(rows) < min(500, MAX_BLOCKS + 1 - start):
            break
    sections = split_sections(blocks)
    if len(json.dumps(blocks, ensure_ascii=False).encode('utf-8')) > MAX_SNAPSHOT_BYTES:
        raise HTTPException(422, '章节来源快照超过 4 MB，请拆分资料后再生成')
    return rpc('prepare_material_outline', {'p_user': user_id, 'p_material': material_id,
               'p_snapshot': blocks, 'p_sections': sections})


def get_outline(*, user_id: str, subject_id: str, material_id: str):
    _owned(table='materials', row_id=material_id, user_id=user_id, subject_id=subject_id)
    return rpc('read_material_outline', {'p_user': user_id, 'p_material': material_id})


def decide(*, user_id: str, proposal_id: str, version: int, action: str, title: str | None):
    return rpc('decide_material_topic', {'p_user': user_id, 'p_proposal': proposal_id,
               'p_version': version, 'p_action': action, 'p_title': title})
