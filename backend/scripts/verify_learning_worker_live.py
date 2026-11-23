"""Real local Redis + isolated Celery worker. Commits disposable fixtures, then deletes only its own user/queue/results."""
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
from celery.contrib.testing.worker import start_worker
from app.config.settings import settings
from app.worker.celery_app import celery_app
from app.worker.tasks import process_learning_job


def main():
    for value in (settings.database_url,settings.supabase_url,settings.redis_url):
        if urlparse(value or '').hostname not in {'localhost','127.0.0.1','::1'}:raise SystemExit('Local DB/Supabase/Redis required')
    os.environ['NO_PROXY']='localhost,127.0.0.1,::1';os.environ['no_proxy']=os.environ['NO_PROXY']
    owner,subject=uuid4(),uuid4()
    queue='acceptance.learning.'+uuid4().hex
    results=[]
    original_eager=celery_app.conf.task_always_eager
    celery_app.conf.task_always_eager=False
    with psycopg.connect(settings.database_url,connect_timeout=5) as conn:
        try:
            conn.execute('insert into auth.users(id) values(%s)',(owner,))
            conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Disposable isolated learning worker acceptance')",(subject,owner))
            conn.execute("insert into knowledge_points(user_id,subject_id,title,knowledge_key) values(%s,%s,'Fixture','fixture')",(owner,subject))
            conn.execute("insert into knowledge_mastery(user_id,subject_id,knowledge_key,mastery,confidence,attempts) values(%s,%s,'fixture',.4,.7,3)",(owner,subject))
            event_job=conn.execute("select id from learning_job_outbox where user_id=%s and kind='projection_refresh'",(owner,)).fetchone()[0]
            conn.execute('update learning_job_outbox set available_at=now() where id=%s',(event_job,))
            conn.execute('insert into daily_review_schedules(user_id,subject_id,enabled,hour) values(%s,%s,true,0)',(owner,subject))
            daily_job=conn.execute("insert into learning_job_outbox(user_id,subject_id,kind,day) values(%s,%s,'daily_review',(now() at time zone 'Asia/Shanghai')::date) returning id",(owner,subject)).fetchone()[0]
            conn.commit()
            with start_worker(celery_app,pool='solo',queues=[queue],hostname=queue,perform_ping_check=False,shutdown_timeout=15,without_heartbeat=True):
                event_status=[]
                for _ in range(3):
                    result=process_learning_job.apply_async(args=[str(event_job)],queue=queue);results.append(result)
                    event_status.append(result.get(timeout=20,disable_sync_subtasks=False)['status'])
                assert event_status==['succeeded','skipped','skipped'],event_status
                assert conn.execute('select version from learning_projection_versions where user_id=%s',(owner,)).fetchone()[0]==1
                daily_status=[]
                for _ in range(3):
                    result=process_learning_job.apply_async(args=[str(daily_job)],queue=queue);results.append(result)
                    daily_status.append(result.get(timeout=20,disable_sync_subtasks=False)['status'])
                assert daily_status==['succeeded','skipped','skipped'],daily_status
                assert conn.execute('select count(*) from daily_learning_reviews where user_id=%s',(owner,)).fetchone()[0]==1
                assert conn.execute('select status from daily_learning_reviews where user_id=%s',(owner,)).fetchone()[0]=='pending'
                assert conn.execute('select count(*) from review_tasks where user_id=%s',(owner,)).fetchone()[0]==0
                print('PASS: real Redis transport + isolated solo Celery worker + actual Supabase RPC; event delivery x3 changes epoch once, daily delivery x3 publishes one pending report, no automatic plan writes')
        finally:
            conn.rollback()
            # Exact generated owner ID; cascading cleanup cannot match a preexisting user.
            conn.execute('delete from auth.users where id=%s',(owner,));conn.commit()
            for result in results:result.forget()
            with celery_app.connection_for_write() as connection:
                connection.default_channel.queue_delete(queue=queue)
            celery_app.conf.task_always_eager=original_eager
            print(f'CLEANUP: disposable user/data, {len(results)} task results and named isolated queue removed; existing business queues untouched')


if __name__=='__main__':main()
