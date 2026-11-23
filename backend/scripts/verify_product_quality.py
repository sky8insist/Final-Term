"""Local disposable SQL + Supabase/API verification, no model calls or real-user writes."""
import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient
from app.api.deps import get_current_user
from app.config.settings import settings
from app.main import app
from app.models.user import CurrentUser


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    for url in (settings.database_url, settings.supabase_url):
        if urlparse(url or '').hostname not in {'localhost', '127.0.0.1', '::1'}:
            raise SystemExit('Local database and Supabase required')
    os.environ['NO_PROXY'] = 'localhost,127.0.0.1,::1'
    os.environ['no_proxy'] = os.environ['NO_PROXY']
    owner, other, subject, foreign_subject, topic = [uuid4() for _ in range(5)]
    previous = app.dependency_overrides.copy()
    with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
        if not conn.execute("select to_regclass('public.product_events')").fetchone()[0]:
            if not args.apply: raise SystemExit('Missing 055; use --apply locally')
            conn.execute((Path(__file__).resolve().parents[1] / 'migrations/055_product_quality_audit.sql').read_text(encoding='utf-8'))
            conn.commit()
            print('Applied local 055')
        elif args.apply:
            migration = (Path(__file__).resolve().parents[1] / 'migrations/055_product_quality_audit.sql').read_text(encoding='utf-8')
            for sql in re.findall(r'create function .*?\$\$;', migration, re.S):
                conn.execute(sql.replace('create function', 'create or replace function', 1))
            for sql in re.findall(r'create index .*?;', migration):
                conn.execute(sql.replace('create index', 'create index if not exists', 1))
            conn.execute('revoke all on function public.record_recommendation_feedback(uuid,uuid,text),public.product_quality_metrics(uuid,integer),public.capture_product_event(),public.validate_session_recommendation(),public.capture_released_calibration(uuid) from public,anon,authenticated')
            conn.execute('grant execute on function public.record_recommendation_feedback(uuid,uuid,text),public.product_quality_metrics(uuid,integer) to service_role')
            conn.execute('revoke all on public.recommendation_audits,public.product_events from service_role')
            conn.execute('grant select,insert,delete on public.recommendation_audits,public.product_events to service_role')
            conn.execute("notify pgrst,'reload schema'")
            conn.commit()
        try:
            for uid in (owner, other): conn.execute('insert into auth.users(id) values(%s)', (uid,))
            for sid, uid in ((subject, owner), (foreign_subject, other)):
                conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Disposable quality acceptance')", (sid, uid))
            conn.execute("insert into knowledge_points(id,user_id,subject_id,knowledge_key,title) values(%s,%s,%s,'quality','Fixture topic')", (topic, owner, subject))
            conn.commit()
            with TestClient(app) as client:
                app.dependency_overrides.pop(get_current_user, None)
                assert client.get('/api/v1/recommendations/quality-metrics').status_code == 401
                app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(owner), email=None)
                before = client.get('/api/v1/recommendations/quality-metrics').json()
                assert before['recommendationCohorts'] == [] and before['sessionMasteryGain']['meanDeltaPoints'] is None
                response = client.get('/api/v1/recommendations/next-actions', params={'subject_id': str(subject), 'audit': True})
                assert response.status_code == 200, response.text
                assert response.headers['cache-control'] == 'no-store'
                action = response.json()['actions'][0]
                rid = action['recommendationId']
                detail = client.get(f'/api/v1/recommendations/{rid}/audit').json()
                assert detail['events'] == []  # Delivery is not exposure.
                assert detail['recommendation']['snapshot']['inputSignals']['attemptCount'] == 0
                for event in ('clicked', 'impression'):
                    for expected in (True, False, False):
                        response = client.post(f'/api/v1/recommendations/{rid}/feedback', json={'event': event})
                        assert response.status_code == 200 and response.json()['recorded'] is expected
                assert client.post(f'/api/v1/recommendations/{rid}/feedback', json={'event': 'session.completed'}).status_code == 422
                assert client.post(f'/api/v1/recommendations/{rid}/feedback', json={'event': 'clicked', 'score': 1}).status_code == 422
                request_id = str(uuid4())
                payload = {'requestId': request_id, 'subjectId': str(subject), 'knowledgePointId': str(topic), 'recommendationId': rid}
                response = client.post('/api/v1/study-sessions', json=payload)
                assert response.status_code == 200, response.text
                session = response.json()
                assert session['context']['recommendationId'] == rid
                assert client.post('/api/v1/study-sessions', json=payload).json()['id'] == request_id
                response = client.post(f'/api/v1/study-sessions/{request_id}/actions', json={'version': session['version'], 'action': 'accept'})
                assert response.status_code == 200, response.text
                metrics = client.get('/api/v1/recommendations/quality-metrics').json()
                cohort = metrics['recommendationCohorts'][0]
                assert cohort['delivered'] == cohort['impressions'] == cohort['clicks'] == cohort['accepted'] == 1
                assert cohort['completed'] == 0 and cohort['acceptanceRate'] == 1
                assert metrics['sessionMasteryGain']['sampleCount'] == 0
                app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(other), email=None)
                assert client.get(f'/api/v1/recommendations/{rid}/audit').status_code == 404
                assert client.post(f'/api/v1/recommendations/{rid}/feedback', json={'event': 'clicked'}).status_code == 404
                assert client.get('/api/v1/recommendations/quality-metrics').json()['eventCounts'] == {}
                print('PASS: actual Supabase/API delivery vs exposure, repeated feedback, canonical acceptance, attribution, no-data, ownership/auth')
            # Synthetic canonical transitions in a rollback-only transaction: no generated learning content.
            conn.rollback()
            conn.execute("insert into knowledge_mastery(user_id,subject_id,knowledge_key,mastery) values(%s,%s,'quality',.2)", (owner, subject))
            first = conn.execute("select payload from product_events where user_id=%s and event_type='mastery.changed'", (owner,)).fetchone()[0]
            assert 'deltaPoints' not in first and 'before' not in first
            conn.execute("update knowledge_mastery set mastery=.7,attempts=1 where user_id=%s and subject_id=%s", (owner, subject))
            delta = conn.execute("select payload from product_events where user_id=%s and event_type='mastery.changed' and payload ? 'deltaPoints'", (owner,)).fetchone()[0]
            assert abs(delta['deltaPoints'] - 50) < 0.00001
            summary = {'before': {'masteryScore': .2, 'assessmentCount': 1}, 'after': {'masteryScore': .7, 'assessmentCount': 2}}
            conn.execute("update study_sessions set status='completed',summary=%s where id=%s", (Jsonb(summary), request_id))
            conn.execute("update study_sessions set version=version+1 where id=%s", (request_id,))
            result = conn.execute('select product_quality_metrics(%s,7)', (owner,)).fetchone()[0]
            assert result['eventCounts']['session.completed'] == 1 and abs(result['sessionMasteryGain']['meanDeltaPoints'] - 50) < .00001
            step = conn.execute('select id from study_session_steps where session_id=%s order by sequence_index limit 1', (request_id,)).fetchone()[0]
            conn.execute("update study_session_steps set status='completed' where id=%s", (step,))
            conn.execute("update study_session_steps set status='completed' where id=%s", (step,))
            assert conn.execute("select count(*) from product_events where user_id=%s and event_type='step.completed'", (owner,)).fetchone()[0] == 1
            # Wrong topic and expired attributions are rejected within session creation.
            mismatch_topic = uuid4()
            conn.execute("insert into knowledge_points(id,user_id,subject_id,knowledge_key,title) values(%s,%s,%s,'mismatch','Mismatch')", (mismatch_topic, owner, subject))
            for topic_value, expire in ((mismatch_topic, False), (topic, True)):
                conn.execute('savepoint invalid_attribution')
                if expire: conn.execute("update recommendation_audits set created_at=now()-interval '8 days' where id=%s", (rid,))
                try:
                    conn.execute("insert into study_sessions(id,user_id,subject_id,knowledge_point_id,goal,minutes,context) values(%s,%s,%s,%s,'Fixture',30,%s)",
                                 (uuid4(), owner, subject, topic_value, Jsonb({'recommendationId': rid})))
                except psycopg.Error as exc:
                    assert exc.sqlstate == '22023'
                else: raise AssertionError('Invalid attribution accepted')
                conn.execute('rollback to savepoint invalid_attribution')
            blueprint, exam, attempt, question, plan, task = [uuid4() for _ in range(6)]
            conn.execute("insert into exam_blueprints(id,user_id,subject_id,title,duration_minutes,total_points,specification) values(%s,%s,%s,'Fixture',10,10,'{}')", (blueprint, owner, subject))
            conn.execute("insert into exams(id,user_id,subject_id,blueprint_id,title,duration_minutes,total_points) values(%s,%s,%s,%s,'Fixture',10,10)", (exam, owner, subject, blueprint))
            conn.execute("insert into exam_attempts(id,user_id,subject_id,exam_id,expires_at) values(%s,%s,%s,%s,now()+interval '1 hour')", (attempt, owner, subject, exam))
            conn.execute("insert into questions(id,user_id,subject_id,knowledge_key,question_type,difficulty) values(%s,%s,%s,'quality','single_choice','medium')", (question, owner, subject))
            conn.execute("insert into grading_results(user_id,attempt_id,question_id,earned_points,max_points,is_correct,feedback,learner_confidence) values(%s,%s,%s,0,1,false,'Fixture',.8)", (owner, attempt, question))
            assert conn.execute("select count(*) from product_events where user_id=%s and event_type='grade.calibrated'", (owner,)).fetchone()[0] == 0
            conn.execute("update exam_attempts set status='graded',submitted_at=now() where id=%s", (attempt,))
            conn.execute("update exam_attempts set status='graded' where id=%s", (attempt,))
            conn.execute("update exam_attempts set adaptive_state='{\"paused\":true,\"resumeCount\":0,\"reason\":\"fixture\"}' where id=%s", (attempt,))
            conn.execute("update exam_attempts set adaptive_state=adaptive_state||'{\"count\":3}' where id=%s", (attempt,))
            conn.execute("update exam_attempts set adaptive_state='{\"paused\":false,\"resumeCount\":1}' where id=%s", (attempt,))
            conn.execute("update exam_attempts set adaptive_state=adaptive_state||'{\"paused\":true}' where id=%s", (attempt,))
            conn.execute("insert into study_plans(id,user_id,subject_id,title,exam_date,daily_minutes,strategy) values(%s,%s,%s,'Fixture',current_date+10,30,'{\"algorithmVersion\":\"exam-state-scheduler-v3\"}')", (plan, owner, subject))
            conn.execute("insert into study_plan_events(user_id,subject_id,plan_id,event_type,reason) values(%s,%s,%s,'replanned','Fixture')", (owner, subject, plan))
            conn.execute("insert into review_tasks(id,user_id,subject_id,plan_id,knowledge_key,task_type,title,scheduled_date,estimated_minutes,priority) values(%s,%s,%s,%s,'quality','review','Fixture',current_date,10,1)", (task, owner, subject, plan))
            conn.execute("update review_tasks set status='completed' where id=%s", (task,))
            conn.execute("update review_tasks set status='pending' where id=%s", (task,))
            conn.execute("update review_tasks set status='completed' where id=%s", (task,))
            result = conn.execute('select product_quality_metrics(%s,7)', (owner,)).fetchone()[0]
            assert result['eventCounts']['adaptive.stopped'] == 2
            assert result['eventCounts']['plan.replanned'] == result['eventCounts']['task.completed'] == 1
            assert result['learnerConfidenceCalibration']['sampleCount'] == 1
            assert abs(result['learnerConfidenceCalibration']['brierScore'] - .64) < .00001
            # RLS and private RPC permission checks.
            assert not conn.execute("select has_function_privilege('authenticated','product_quality_metrics(uuid,integer)','execute')").fetchone()[0]
            assert not conn.execute("select has_function_privilege('anon','capture_released_calibration(uuid)','execute')").fetchone()[0]
            assert not conn.execute("select has_table_privilege('authenticated','product_events','insert')").fetchone()[0]
            assert not conn.execute("select has_table_privilege('service_role','recommendation_audits','update')").fetchone()[0]
            conn.execute('set local role authenticated')
            conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(owner),))
            assert conn.execute('select count(*) from product_events').fetchone()[0] > 0
            conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(other),))
            assert conn.execute('select count(*) from product_events').fetchone()[0] == 0
            conn.execute('reset role')
            conn.rollback()
            assert conn.execute("select count(*) from product_events where user_id=%s and event_type in ('mastery.changed','session.completed','step.completed')", (owner,)).fetchone()[0] == 0
            print('PASS: real SQL before/after, missing baseline, session gain, step/task dedup, stop/resume, replan, confidence Brier=.64, RLS/private RPC, rollback')
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous)
            conn.rollback()
            conn.execute('delete from auth.users where id in (%s,%s)', (owner, other))
            conn.commit()
            assert conn.execute('select count(*) from recommendation_audits where user_id in (%s,%s)', (owner, other)).fetchone()[0] == 0
            assert conn.execute('select count(*) from product_events where user_id in (%s,%s)', (owner, other)).fetchone()[0] == 0
            print('PASS: exact disposable-user cleanup and audit/event cascades')


if __name__ == '__main__': main()
