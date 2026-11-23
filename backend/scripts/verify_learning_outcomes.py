"""Local SQL + actual Supabase API; generated disposable users only, no models."""
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
    for value in (settings.database_url, settings.supabase_url):
        if urlparse(value or '').hostname not in {'localhost', '127.0.0.1', '::1'}:
            raise SystemExit('Local database/Supabase required')
    os.environ['NO_PROXY'] = 'localhost,127.0.0.1,::1'
    os.environ['no_proxy'] = os.environ['NO_PROXY']
    owner, other, subject, topic, session, plan, task, artifact = [uuid4() for _ in range(8)]
    previous = app.dependency_overrides.copy()
    with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
        migration = (Path(__file__).resolve().parents[1] / 'migrations/056_learning_outcome_cohorts.sql').read_text(encoding='utf-8')
        if not conn.execute("select to_regclass('public.learning_metric_cohorts')").fetchone()[0]:
            if not args.apply: raise SystemExit('Missing 056; use --apply locally')
            conn.execute(migration)
            conn.commit()
            print('Applied local 056')
        elif args.apply:
            for sql in re.findall(r'create function .*?\$\$;', migration, re.S):
                conn.execute(sql.replace('create function', 'create or replace function', 1))
            conn.execute('revoke all on function capture_response_prediction(),capture_released_mastery_samples(uuid),capture_learning_cohort(),learning_outcome_metrics(uuid,integer) from public,anon,authenticated')
            conn.execute('grant execute on function learning_outcome_metrics(uuid,integer) to service_role')
            conn.execute("notify pgrst,'reload schema'")
            conn.commit()
        def metrics(uid=owner):
            return conn.execute('select learning_outcome_metrics(%s,30)', (uid,)).fetchone()[0]
        try:
            for uid in (owner, other): conn.execute('insert into auth.users(id) values(%s)', (uid,))
            conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Disposable outcome acceptance')", (subject, owner))
            conn.execute("insert into knowledge_points(id,user_id,subject_id,knowledge_key,title) values(%s,%s,%s,'fixture','Fixture')", (topic, owner, subject))
            assert metrics()['cohorts'] == metrics()['masteryCalibration'] == []
            conn.execute("insert into study_sessions(id,user_id,subject_id,knowledge_point_id,goal,minutes,context) values(%s,%s,%s,%s,'Fixture',30,'{\"algorithmVersion\":\"guided-session-v1\"}')", (session, owner, subject, topic))
            conn.execute("update study_sessions set status='active' where id=%s", (session,))
            conn.execute("update study_sessions set status='active',version=version+1 where id=%s", (session,))
            assert metrics()['cohorts'][0]['total'] == metrics()['cohorts'][0]['pending'] == 1
            assert metrics()['cohorts'][0]['completionRate'] is None
            conn.execute("update study_sessions set status='completed' where id=%s", (session,))
            assert metrics()['cohorts'][0]['mature'] == 0
            # Source RPC deletes/reinserts stable step IDs: one remedial cohort only.
            failed, passed = uuid4(), uuid4()
            for step_id, seq, ratio in ((failed, 1, .4), (passed, 3, .9)):
                values = (step_id, session, owner, subject, seq, Jsonb({'scoreRatio': ratio}))
                sql = "insert into study_session_steps(id,session_id,user_id,subject_id,sequence_index,kind,title,estimated_minutes,status,output) values(%s,%s,%s,%s,%s,'quiz','Fixture',5,'completed',%s)"
                conn.execute(sql, values)
                conn.execute('delete from study_session_steps where id=%s', (step_id,))
                conn.execute(sql, values)
            assert conn.execute("select count(*),count(completed_at) from learning_metric_cohorts where user_id=%s and kind='quiz_remediation'", (owner,)).fetchone() == (1, 1)
            conn.execute("insert into study_plans(id,user_id,subject_id,title,exam_date,daily_minutes,strategy) values(%s,%s,%s,'Fixture',current_date+10,30,'{\"algorithmVersion\":\"exam-state-scheduler-v3\"}')", (plan, owner, subject))
            conn.execute("insert into review_tasks(id,user_id,subject_id,plan_id,knowledge_key,task_type,title,scheduled_date,estimated_minutes,priority) values(%s,%s,%s,%s,'fixture','review','Fixture',current_date,10,1)", (task, owner, subject, plan))
            conn.execute('delete from review_tasks where id=%s', (task,))
            assert conn.execute("select count(*) from learning_metric_cohorts where source_id=%s", (task,)).fetchone()[0] == 1
            conn.execute("insert into artifacts(id,user_id,subject_id,artifact_type,title,content) values(%s,%s,%s,'flashcards','Fixture','{\"cards\":[{\"id\":\"card\",\"front\":\"Fixture\",\"back\":\"Fixture\"}]}')", (artifact, owner, subject))
            conn.execute("update flashcard_review_state set next_review=now()+interval '2 days',version=version+1 where artifact_id=%s", (artifact,))
            conn.execute("insert into flashcard_review_logs(id,user_id,subject_id,artifact_id,card_id,rating,expected_version,content_version,state_before,state_after,result) values(%s,%s,%s,%s,'card','again',0,1,'{}','{}','{}')", (uuid4(), owner, subject, artifact))
            assert conn.execute("select count(*),count(completed_at) from learning_metric_cohorts where source_id=%s", (artifact,)).fetchone() == (2, 1)
            # Mature synthetic cohorts while preserving completion offsets, not real elapsed learning.
            conn.execute("update learning_metric_cohorts set starts_at=starts_at-interval '8 days',deadline=deadline-interval '8 days',completed_at=completed_at-interval '8 days' where user_id=%s", (owner,))
            result = metrics()
            groups = {row['kind']: row for row in result['cohorts']}
            assert groups['guided_session']['completionRate'] == groups['quiz_remediation']['completionRate'] == 1
            assert groups['plan_task']['completionRate'] == 0
            assert groups['due_flashcard']['completionRate'] == 1  # Second schedule is not yet mature.
            assert groups['due_flashcard']['pending'] == 1
            conn.execute("update learning_metric_cohorts set completed_at=deadline+interval '1 second' where source_id=%s and kind='guided_session'", (session,))
            group = next(row for row in metrics()['cohorts'] if row['kind'] == 'guided_session')
            assert group['late'] == 1 and group['completionRate'] == 0
            conn.execute("insert into learning_metric_cohorts(user_id,subject_id,kind,source_id,revision,algorithm_version,starts_at,deadline,completed_at) select %s,%s,'plan_task',gen_random_uuid(),'1','scale-fixture',now()-interval '8 days',now()-interval '1 day',case when n%%2=0 then now()-interval '2 days' end from generate_series(1,2001) n", (owner, subject))
            scale = next(row for row in metrics()['cohorts'] if row['algorithmVersion'] == 'scale-fixture')
            assert scale['mature'] == 2001 and scale['completedWithinHorizon'] == 1000
            conn.execute('savepoint rollback_cohort')
            conn.execute("update study_sessions set status='active' where id=%s", (session,))
            conn.execute('rollback to savepoint rollback_cohort')
            print('PASS: stable cohorts, incomplete-window null, seven-day maturity, late exclusion, deleted task denominator, step dedup, scheduled/early flashcard review')
            blueprint, exam, attempt = [uuid4() for _ in range(3)]
            conn.execute("insert into exam_blueprints(id,user_id,subject_id,title,duration_minutes,total_points,specification) values(%s,%s,%s,'Fixture',10,10,'{}')", (blueprint, owner, subject))
            conn.execute("insert into exams(id,user_id,subject_id,blueprint_id,title,duration_minutes,total_points) values(%s,%s,%s,%s,'Fixture',10,10)", (exam, owner, subject, blueprint))
            conn.execute("insert into exam_attempts(id,user_id,subject_id,exam_id,expires_at) values(%s,%s,%s,%s,now()+interval '1 hour')", (attempt, owner, subject, exam))
            for index, (prediction, correct, version) in enumerate(((.2, False, 'mastery-v2'), (.8, True, 'mastery-v2'), (.8, False, 'comparison-fixture'))):
                question, response = uuid4(), uuid4()
                conn.execute("insert into questions(id,user_id,subject_id,knowledge_key,question_type,difficulty) values(%s,%s,%s,'fixture','single_choice','medium')", (question, owner, subject))
                conn.execute("insert into knowledge_mastery(user_id,subject_id,knowledge_key,mastery,metadata) values(%s,%s,'fixture',%s,%s) on conflict(user_id,subject_id,knowledge_key) do update set mastery=excluded.mastery,metadata=excluded.metadata", (owner, subject, prediction, Jsonb({'assessmentCount': 2, 'lastEvidence': {'algorithmVersion': version}})))
                conn.execute("insert into exam_responses(id,user_id,attempt_id,question_id,response,mastery_prediction) values(%s,%s,%s,%s,'\"A\"','{\"score\":1}')", (response, owner, attempt, question))
                snapshot = conn.execute('select mastery_prediction from exam_responses where id=%s', (response,)).fetchone()[0]
                assert snapshot['score'] == prediction
                conn.execute("update knowledge_mastery set mastery=.99 where user_id=%s and subject_id=%s", (owner, subject))
                conn.execute("update exam_responses set response='\"B\"',mastery_prediction='{\"score\":0}' where id=%s", (response,))
                assert conn.execute('select mastery_prediction from exam_responses where id=%s', (response,)).fetchone()[0] == snapshot
                conn.execute("insert into grading_results(user_id,attempt_id,question_id,earned_points,max_points,is_correct,feedback) values(%s,%s,%s,%s,1,%s,'Fixture')", (owner, attempt, question, int(correct), correct))
                assert metrics()['masteryCalibration'] == []
            cold_question = uuid4()
            conn.execute("insert into questions(id,user_id,subject_id,knowledge_key,question_type,difficulty) values(%s,%s,%s,'cold','single_choice','medium')", (cold_question, owner, subject))
            conn.execute("insert into knowledge_mastery(user_id,subject_id,knowledge_key,mastery) values(%s,%s,'cold',.9)", (owner, subject))
            conn.execute("insert into exam_responses(user_id,attempt_id,question_id,response,mastery_prediction) values(%s,%s,%s,'\"A\"','{\"score\":1}')", (owner, attempt, cold_question))
            assert conn.execute('select mastery_prediction from exam_responses where question_id=%s', (cold_question,)).fetchone()[0] == {}
            conn.execute("insert into grading_results(user_id,attempt_id,question_id,earned_points,max_points,is_correct,feedback) values(%s,%s,%s,1,1,true,'Fixture')", (owner, attempt, cold_question))
            conn.execute("update exam_attempts set status='graded' where id=%s", (attempt,))
            conn.execute("update exam_attempts set status='graded' where id=%s", (attempt,))
            calibration = {row['algorithmVersion']: row for row in metrics()['masteryCalibration']}
            assert calibration['mastery-v2']['sampleCount'] == 2
            assert abs(calibration['mastery-v2']['brierScore'] - .04) < .000001
            assert abs(calibration['mastery-v2']['expectedCalibrationError'] - .2) < .000001
            assert abs(calibration['comparison-fixture']['brierScore'] - .64) < .000001
            assert conn.execute('select count(*) from mastery_prediction_samples where user_id=%s', (owner,)).fetchone()[0] == 3
            adaptive_attempt, adaptive_question = uuid4(), uuid4()
            conn.execute("update exams set assessment_mode='adaptive' where id=%s", (exam,))
            conn.execute("insert into exam_attempts(id,user_id,subject_id,exam_id,expires_at) values(%s,%s,%s,%s,now()+interval '1 hour')", (adaptive_attempt, owner, subject, exam))
            conn.execute("insert into questions(id,user_id,subject_id,knowledge_key,question_type,difficulty) values(%s,%s,%s,'fixture','single_choice','medium')", (adaptive_question, owner, subject))
            conn.execute("insert into exam_responses(user_id,attempt_id,question_id,response) values(%s,%s,%s,'\"A\"')", (owner, adaptive_attempt, adaptive_question))
            conn.execute("insert into grading_results(user_id,attempt_id,question_id,earned_points,max_points,is_correct,feedback) values(%s,%s,%s,1,1,true,'Fixture')", (owner, adaptive_attempt, adaptive_question))
            assert conn.execute('select count(*) from mastery_prediction_samples where user_id=%s', (owner,)).fetchone()[0] == 4
            assert metrics(other)['cohorts'] == metrics(other)['masteryCalibration'] == []
            assert not conn.execute("select has_function_privilege('authenticated','learning_outcome_metrics(uuid,integer)','execute')").fetchone()[0]
            assert not conn.execute("select has_table_privilege('service_role','learning_metric_cohorts','update')").fetchone()[0]
            conn.execute('set local role authenticated')
            conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(other),))
            assert conn.execute('select count(*) from mastery_prediction_samples').fetchone()[0] == 0
            assert conn.execute('select count(*) from learning_metric_cohorts').fetchone()[0] == 0
            conn.execute('reset role')
            conn.commit()
            print('PASS: prospective immutable prediction, formal release, no self-confidence requirement, Brier .04/.64, ECE .2, version groups, RLS/private permissions')
            with TestClient(app) as client:
                app.dependency_overrides.pop(get_current_user, None)
                assert client.get('/api/v1/recommendations/learning-outcomes').status_code == 401
                app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(owner), email=None)
                response = client.get('/api/v1/recommendations/learning-outcomes')
                assert response.status_code == 200, response.text
                assert response.headers['cache-control'] == 'no-store'
                assert len(response.json()['masteryCalibration']) == 2
                assert next(row for row in response.json()['cohorts'] if row['algorithmVersion'] == 'scale-fixture')['total'] == 2001
                assert client.get('/api/v1/recommendations/learning-outcomes', params={'days': 91}).status_code == 422
                app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(other), email=None)
                assert client.get('/api/v1/recommendations/learning-outcomes').json()['cohorts'] == []
            print('PASS: actual Supabase/API 200, 401, 422, no-store and owner scope (test auth override)')
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous)
            conn.rollback()
            for table in ('grading_results', 'exam_responses', 'exam_attempts', 'exams', 'questions', 'exam_blueprints'):
                conn.execute(f'delete from {table} where user_id in (%s,%s)', (owner, other))
            conn.execute('delete from auth.users where id in (%s,%s)', (owner, other))
            conn.commit()
            assert conn.execute('select count(*) from learning_metric_cohorts where user_id in (%s,%s)', (owner, other)).fetchone()[0] == 0
            assert conn.execute('select count(*) from mastery_prediction_samples where user_id in (%s,%s)', (owner, other)).fetchone()[0] == 0
            print('PASS: exact disposable-user cleanup and cohort/sample privacy cascades')


if __name__ == '__main__': main()
