"""Durable jobs are claimed in PostgreSQL; Celery deliveries only carry IDs."""
from app.db.supabase_client import get_supabase_client
from app.services import daily_review_service
from app.services.subject_service import get_subject
from fastapi import HTTPException


def rpc(name,values):return get_supabase_client().rpc(name,values).execute().data


def user_rpc(name,values):
    try:return rpc(name,values)
    except Exception as exc:
        code=getattr(exc,'code',None)
        if code=='42501':raise HTTPException(404,'任务或科目不存在') from exc
        if code in {'40001','40P01'}:raise HTTPException(409,'任务或设置已变化，或重试次数已耗尽，请刷新查看') from exc
        if code=='22023':raise HTTPException(422,'请检查复盘日期及自动生成开关；过期任务不能重试') from exc
        raise


def schedule(*,user_id,subject_id):
    get_subject(user_id=user_id,subject_id=subject_id)
    client=get_supabase_client()
    rows=client.table('daily_review_schedules').select('enabled,hour,version').eq('user_id',user_id).eq('subject_id',subject_id).limit(1).execute().data
    jobs=(client.table('learning_job_outbox').select('id,day,status,attempts,error_code,result_id')
          .eq('user_id',user_id).eq('subject_id',subject_id).eq('kind','daily_review').order('created_at',desc=True).limit(1).execute().data)
    return {**(rows[0] if rows else {'enabled':False,'hour':22,'version':0}),'timezone':'Asia/Shanghai','latestJob':jobs[0] if jobs else None}


def save_schedule(*,user_id,subject_id,enabled,hour,version):
    return user_rpc('save_daily_review_schedule',{'p_user':user_id,'p_subject':subject_id,'p_enabled':enabled,'p_hour':hour,'p_version':version})


def run(job_id):
    job=rpc('claim_learning_job',{'p_job':job_id})
    if not job:return {'status':'skipped'}
    try:
        if job['kind']=='daily_review':
            source=daily_review_service.rpc('daily_learning_source',{'p_user':job['user_id'],'p_subject':job['subject_id'],'p_day':job['day']})
            report=daily_review_service.build_learning_review_graph().invoke({'source':source})['report']
            result=rpc('publish_daily_review_job',{'p_job':job_id,'p_token':job['claim_token'],'p_source':source,'p_report':report})
            return {'status':'succeeded','resultId':result['id']}
        if job['kind']=='projection_refresh':
            result=rpc('consume_learning_projection_job',{'p_job':job_id,'p_token':job['claim_token']})
            return {'status':'succeeded',**result}
        raise ValueError('Unknown learning job kind')
    except Exception as exc:
        rpc('finish_learning_job',{'p_job':job_id,'p_token':job['claim_token'],'p_error':type(exc).__name__})
        return {'status':'retry_or_dead'}


def sweep():
    from app.worker.tasks import process_learning_job
    rpc('enqueue_daily_review_jobs',{})
    rpc('enqueue_learning_due_events',{})
    dispatched=failed=0
    for job_id in rpc('ready_learning_jobs',{}):
        try:process_learning_job.delay(job_id);dispatched+=1
        except Exception:failed+=1  # Durable queued row remains eligible next sweep.
    return {'dispatched':dispatched,'dispatchFailed':failed}


def list_jobs(*,user_id,subject_id):
    get_subject(user_id=user_id,subject_id=subject_id)
    return (get_supabase_client().table('learning_job_outbox').select('id,kind,day,status,attempts,max_attempts,manual_retries,error_code,available_at,result_id,created_at')
            .eq('user_id',user_id).eq('subject_id',subject_id).order('created_at',desc=True).limit(50).execute().data)


def retry(*,user_id,job_id):
    return user_rpc('retry_learning_job',{'p_user':user_id,'p_job':job_id})
