from fastapi import HTTPException

from app.db.supabase_client import get_supabase_client
from app.services.course_service import _owned
from app.services.parse_service import AUDIO_CONTENT_TYPES
from app.services.subject_service import get_subject
from app.services.task_service import TASK_SELECT, _serialize

SELECT='id,subject_id,material_id,title,source_kind,version,created_at'


def rpc(name,values):
    try:return get_supabase_client().rpc(name,values).execute().data
    except Exception as exc:
        code=getattr(exc,'code',None)
        if code in {'40001','40P01'}:raise HTTPException(409,'课堂版本已更新，请刷新转录后重试') from exc
        if code in {'42501','23503'}:raise HTTPException(404,'课堂或音频来源不存在') from exc
        if code in {'22023','23514'}:raise HTTPException(422,'转录尚未就绪或知识点无效') from exc
        raise


def list_lectures(*,user_id,subject_id):
    get_subject(user_id=user_id,subject_id=subject_id)
    return get_supabase_client().table('lectures').select(SELECT).eq('user_id',user_id).eq('subject_id',subject_id).order('created_at',desc=True).limit(100).execute().data


def audio_materials(*,user_id,subject_id):
    get_subject(user_id=user_id,subject_id=subject_id)
    return get_supabase_client().table('materials').select('id,filename,status,content_type').eq('user_id',user_id).eq('subject_id',subject_id).in_('content_type',sorted(AUDIO_CONTENT_TYPES)).order('created_at',desc=True).limit(100).execute().data


def attach(*,user_id,subject_id,material_id,title,source_kind):
    get_subject(user_id=user_id,subject_id=subject_id)
    return rpc('attach_lecture',{'p_user':user_id,'p_subject':subject_id,'p_material':material_id,'p_title':title,'p_kind':source_kind})


def get_lecture(*,user_id,lecture_id,subject_id):
    root=_owned(table='lectures',row_id=lecture_id,user_id=user_id,subject_id=subject_id)
    material=_owned(table='materials',row_id=root['material_id'],user_id=user_id,subject_id=subject_id)
    db=get_supabase_client()
    tasks=db.table('processing_tasks').select(TASK_SELECT).eq('user_id',user_id).eq('subject_id',subject_id).eq('material_id',material['id']).order('created_at',desc=True).limit(1).execute().data
    segments=db.table('audio_segments').select('segment_index,start_time,end_time,status,attempts').eq('user_id',user_id).eq('subject_id',subject_id).eq('material_id',material['id']).order('segment_index').limit(1000).execute().data
    return {**{key:root[key] for key in SELECT.split(',')},'status':material['status'],'error':material.get('error_message'),
        'task':_serialize(tasks[0]) if tasks else None,'segments':segments}


def transcript(*,user_id,lecture_id,offset,limit,block_id=None):
    return rpc('lecture_transcript',{'p_user':user_id,'p_lecture':lecture_id,'p_offset':offset,'p_limit':limit,'p_block':block_id})


def align(*,user_id,lecture_id,block_id,topic_id,version):
    return rpc('align_lecture_topic',{'p_user':user_id,'p_lecture':lecture_id,'p_block':block_id,'p_topic':topic_id,'p_version':version})


def selected_context(*,user_id,subject_id,material_id,citations):
    db=get_supabase_client()
    lectures=db.table('lectures').select('id').eq('user_id',user_id).eq('subject_id',subject_id).eq('material_id',material_id).limit(1).execute().data
    if not lectures:return {'topicIds':[],'lectureId':None}
    rows=db.table('lecture_topic_links').select('block_id,knowledge_point_id,source_text,start_time,end_time').eq('lecture_id',lectures[0]['id']).eq('user_id',user_id).eq('subject_id',subject_id).in_('block_id',[row['id'] for row in citations]).execute().data
    by_id={row['id']:row for row in citations}
    ids={row['knowledge_point_id'] for row in rows if row['block_id'] in by_id
         and row['source_text']==by_id[row['block_id']]['chunkText']
         and row['start_time']==by_id[row['block_id']].get('startTime') and row['end_time']==by_id[row['block_id']].get('endTime')}
    topics=db.table('knowledge_points').select('id').eq('user_id',user_id).eq('subject_id',subject_id).eq('archived',False).in_('id',sorted(ids)).execute().data if ids else []
    return {'topicIds':[row['id'] for row in topics],'lectureId':lectures[0]['id']}
