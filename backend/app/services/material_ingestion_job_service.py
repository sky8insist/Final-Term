"""Lease-fenced asynchronous ingestion; checkpoints avoid repeated paid stages."""
from contextlib import contextmanager
from hashlib import sha256
import json
from threading import Event, Thread
from uuid import uuid4

from fastapi import HTTPException
from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.models.content import ContentBlock
from app.services import material_service as material
from app.services import owner_io_service
from app.services.document_structure_service import enrich_document_structure
from app.services.security_service import scan_untrusted_text
from app.services.observability_service import bind_trace_metadata


class LeaseLost(RuntimeError):
    pass


def rpc(name, values):
    return get_supabase_client().rpc(name, values).execute().data


def pipeline_version(source_hash):
    return sha256(json.dumps(['ingestion-checkpoint-v1',source_hash,settings.embedding_model,
        settings.chunk_strategy,settings.chunk_parent_size,settings.enable_mineru,
        settings.mineru_model_version,settings.mineru_language,settings.vision_model,
        settings.transcription_model,settings.mock_external_apis],ensure_ascii=False).encode()).hexdigest()


@contextmanager
def lease(job):
    stop, failed = Event(), Event()
    values={'p_task':job['id'],'p_token':job['ingestion_token']}
    def touch(stage=None, metadata=None):
        if failed.is_set() or not rpc('touch_material_ingestion', {**values,'p_stage':stage,'p_metadata':metadata}):
            raise LeaseLost('Ingestion lease changed')
    def heartbeat():
        while not stop.wait(30):
            try: touch()
            except Exception: failed.set(); return
    thread=Thread(target=heartbeat,name='ingestion-heartbeat',daemon=True);thread.start()
    try: yield touch
    finally: stop.set();thread.join(timeout=6)


def optional_postprocessing(job, mat):
    # Canonical publication is already committed. Optional failures cannot
    # change success or cause paid ingestion stages to repeat.
    warnings={}
    try:
        from app.services.material_outline_service import prepare
        prepare(user_id=job['user_id'],subject_id=job['subject_id'],material_id=job['material_id'])
    except Exception: warnings['outlineWarning']='章节提案尚未生成，可在资料中心手动生成'
    if mat.get('upload_notes_mode'):
        try:
            from app.services.material_notes_service import enqueue_for_material
            enqueue_for_material(user_id=job['user_id'],subject_id=job['subject_id'],material_id=job['material_id'])
        except Exception: warnings['notesWarning']='笔记任务等待自动补投'
    return warnings


def execute(job, io_conn):
    client=get_supabase_client()
    user,subject,mid=job['user_id'],job['subject_id'],job['material_id']
    base={'p_task':job['id'],'p_token':job['ingestion_token']}
    with lease(job) as touch:
        def guard(stage=None, metadata=None):
            io_conn.execute('select 1')  # Lost IO-lock connection cannot publish.
            touch(stage, metadata)
        guard('parsing')
        mat=client.table('materials').select('*').eq('id',mid).eq('user_id',user).single().execute().data
        source=client.table('material_assets').select('*').eq('material_id',mid).eq('user_id',user).eq('asset_type','original').limit(1).execute().data
        if not source: raise RuntimeError('SourceUnavailable')
        asset=source[0]
        if (asset['bucket']!=settings.material_storage_bucket or not asset['object_path'].startswith(user+'/')
                or any(part in ('','.', '..') for part in asset['object_path'].split('/'))):
            raise RuntimeError('UnsafeSourcePath')
        version=pipeline_version(mat['source_hash'])
        saved=client.table('material_ingestion_checkpoints').select('*').eq('task_id',job['id']).eq('pipeline_version',version).execute().data
        checkpoints={row['stage']:row['payload'] for row in saved}
        def save(stage, payload):
            guard()
            rpc('save_material_checkpoint',{**base,'p_stage':stage,'p_version':version,'p_payload':payload})
        parsed=checkpoints.get('parsed')
        if parsed is None:
            data=client.storage.from_(asset['bucket']).download(asset['object_path'])
            if sha256(data).hexdigest()!=mat['source_hash']: raise RuntimeError('SourceHashMismatch')
            def parser_event(event, details):
                guard('parsing',{'mineru':{**details,'event':event}})
            raw=material._parse_material_blocks(client=client,user_id=user,subject_id=subject,material_id=mid,
                filename=mat['filename'],content_type=mat['content_type'],file_bytes=data,
                on_stage=lambda *_:guard('parsing'),on_parser_event=parser_event,
                resume_batch_id=(job.get('metadata',{}).get('mineru') or {}).get('batchId'))
            guard('parsing')
            raw,_=enrich_document_structure(raw)
            # Adopt IDs from an earlier legacy failed attempt where appropriate.
            old=client.table('content_blocks').select('id,parser_name,parser_version,source_hash').eq('material_id',mid).eq('user_id',user).execute().data
            known={(r['parser_name'],r['parser_version'],r['source_hash']):r['id'] for r in old}
            blocks=[]
            for item in raw:
                block=ContentBlock(**item).model_dump()
                scan=scan_untrusted_text(block['content_text'])
                if scan['suspicious']:block['metadata']={**block['metadata'],'promptInjectionRisk':scan}
                key=(block['parser_name'],block['parser_version'],block['source_hash'])
                block['id']=known.get(key,str(uuid4()));blocks.append(block)
            parsed={'blocks':blocks};save('parsed',parsed)
        guard('embedding')
        embedded=checkpoints.get('embedded')
        if embedded is None:
            blocks=parsed['blocks']
            bundle=material.build_structure_chunk_bundle(blocks,parent_size=settings.chunk_parent_size) if settings.chunk_strategy=='structure' else {
                'parents':[],'records':material.build_block_chunk_records(blocks)}
            if not bundle['records']: raise RuntimeError('NoExtractableText')
            vectors=material.embed_texts([r['content'] for r in bundle['records']])
            guard('embedding')
            embedded={**bundle,'vectors':vectors,'strategy':settings.chunk_strategy,'model':settings.embedding_model}
            save('embedded',embedded)
        guard('indexing')
        workspace=material.build_workspace(user_id=user,subject_id=subject)
        graph='indexed'
        try:
            # External graph calls can repeat after lost ack; same doc ID is
            # replaced. PostgreSQL publication is separately token-fenced.
            material.delete_material_index(user_id=user,subject_id=subject,material_id=mid,embedding_dimension=len(embedded['vectors'][0]))
            guard('indexing')
            material.index_material(user_id=user,subject_id=subject,material_id=mid,filename=mat['filename'],
                chunks=embedded['records'],embedding_dimension=len(embedded['vectors'][0]))
        except material.LightRAGServiceError:
            graph='failed'  # Preserve existing keyword/vector fallback contract.
        guard('indexing')
        result=rpc('publish_material_ingestion',{**base,'p_version':version,'p_graph_status':graph,'p_workspace':workspace})
        try:
            warnings=optional_postprocessing(job,mat)
            latest=client.table('processing_tasks').select('metadata').eq('id',job['id']).single().execute().data
            metadata={k:v for k,v in latest.get('metadata',{}).items() if k not in ('outlineWarning','notesWarning')}
            client.table('processing_tasks').update({'metadata':{**metadata,**warnings}}).eq('id',job['id']).eq('status','succeeded').execute()
        except Exception: pass
        return result


def run(task_id):
    rows=get_supabase_client().table('processing_tasks').select('user_id').eq('id',task_id).limit(1).execute().data
    if not rows:return {'status':'skipped'}
    try:
        with owner_io_service.hold_owner_io(rows[0]['user_id']) as conn:
            job=rpc('claim_material_ingestion',{'p_task':task_id})
            if not job:return {'status':'skipped'}
            with bind_trace_metadata(job.get('metadata'), user_id=job['user_id']):
                try:return execute(job,conn)
                except LeaseLost:return {'status':'lease_lost'}
                except Exception as exc:
                    accepted=rpc('fail_material_ingestion',{'p_task':task_id,'p_token':job['ingestion_token'],'p_error':type(exc).__name__})
                    return {'status':'retry_or_failed' if accepted else 'lease_lost'}
    except HTTPException as exc:
        if exc.status_code==409:return {'status':'busy'}
        raise


def sweep(*, user_id=None):
    from app.worker.tasks import process_material
    dispatched=failed=0
    for task_id in rpc('ready_material_ingestions',{'p_limit':50,'p_user':user_id}):
        try:process_material.delay(task_id);dispatched+=1
        except Exception:failed+=1
    return {'dispatched':dispatched,'dispatchFailed':failed}
