"""Local PostgreSQL + actual Supabase/API, disposable users, no model calls."""
import argparse
import os
import re
import sys
from datetime import UTC, datetime
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
    owner, other, subject, blueprint, exam, attempt = [uuid4() for _ in range(6)]
    overrides = app.dependency_overrides.copy()
    with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
        migration = (Path(__file__).resolve().parents[1]/'migrations/057_prediction_coverage.sql').read_text(encoding='utf-8')
        if not conn.execute("select to_regclass('mastery_prediction_coverage')").fetchone()[0]:
            if not args.apply: raise SystemExit('Missing 057; use --apply locally')
            conn.execute(migration); conn.commit(); print('Applied local 057')
        elif args.apply:
            for sql in re.findall(r'create function .*?\$\$;', migration, re.S):
                conn.execute(sql.replace('create function', 'create or replace function', 1))
            conn.execute('revoke all on function capture_prediction_coverage(),prediction_coverage_metrics(uuid,integer) from public,anon,authenticated')
            conn.execute('grant execute on function prediction_coverage_metrics(uuid,integer) to service_role')
            conn.execute("notify pgrst,'reload schema'"); conn.commit()
        def coverage(): return conn.execute('select prediction_coverage_metrics(%s,30)', (owner,)).fetchone()[0]
        try:
            for uid in (owner, other): conn.execute('insert into auth.users(id) values(%s)', (uid,))
            conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Disposable metrics acceptance')", (subject, owner))
            conn.execute("insert into knowledge_mastery(user_id,subject_id,knowledge_key,mastery,metadata) values(%s,%s,'fixture',.7,'{\"assessmentCount\":2}')", (owner, subject))
            conn.execute("insert into exam_blueprints(id,user_id,subject_id,title,duration_minutes,total_points,specification) values(%s,%s,%s,'Fixture',10,10,'{}')", (blueprint, owner, subject))
            conn.execute("insert into exams(id,user_id,subject_id,blueprint_id,title,duration_minutes,total_points) values(%s,%s,%s,%s,'Fixture',10,10)", (exam, owner, subject, blueprint))
            conn.execute("insert into exam_attempts(id,user_id,subject_id,exam_id,expires_at) values(%s,%s,%s,%s,now()+interval '1 hour')", (attempt, owner, subject, exam))
            grades = []
            for kind in ('available', 'no_snapshot', 'no_response', 'unknown'):
                question, grade = uuid4(), uuid4(); grades.append(grade)
                key = 'cold' if kind == 'no_snapshot' else 'fixture'
                conn.execute("insert into questions(id,user_id,subject_id,knowledge_key,question_type,difficulty) values(%s,%s,%s,%s,'single_choice','medium')", (question, owner, subject, key))
                if kind != 'no_response':
                    conn.execute("insert into exam_responses(user_id,attempt_id,question_id,response) values(%s,%s,%s,'\"A\"')", (owner, attempt, question))
                conn.execute("insert into grading_results(id,user_id,attempt_id,question_id,earned_points,max_points,is_correct,feedback) values(%s,%s,%s,%s,0,1,%s,'Fixture')", (grade, owner, attempt, question, None if kind == 'unknown' else False))
            assert coverage()['releasedGrades'] == 0 and coverage()['coverageRate'] is None
            conn.execute("update exam_attempts set status='graded' where id=%s", (attempt,))
            conn.execute("update exam_attempts set status='graded' where id=%s", (attempt,))
            result = coverage()
            assert result['releasedGrades'] == 4 and result['knownOutcomes'] == 3 and result['predictionSamples'] == 1
            assert result['noResponse'] == result['noSnapshot'] == result['unknownOutcomes'] == 1
            assert abs(result['coverageRate']-1/3) < .000001
            # Simulate an already-published adaptive grade predating this instrumentation.
            conn.execute('delete from mastery_prediction_coverage where id=%s', (grades[0],))
            conn.execute("update exams set assessment_mode='adaptive' where id=%s", (exam,))
            fresh_question = uuid4()
            conn.execute("insert into questions(id,user_id,subject_id,knowledge_key,question_type,difficulty) values(%s,%s,%s,'fixture','single_choice','medium')", (fresh_question, owner, subject))
            conn.execute("insert into grading_results(user_id,attempt_id,question_id,earned_points,max_points,is_correct,feedback) values(%s,%s,%s,0,1,false,'Fixture')", (owner, attempt, fresh_question))
            assert coverage()['releasedGrades'] == 4
            assert not conn.execute('select exists(select 1 from mastery_prediction_coverage where id=%s)', (grades[0],)).fetchone()[0]
            assert not conn.execute("select has_function_privilege('authenticated','prediction_coverage_metrics(uuid,integer)','execute')").fetchone()[0]
            assert not conn.execute("select has_table_privilege('service_role','mastery_prediction_coverage','insert')").fetchone()[0]
            conn.execute('set local role authenticated')
            conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(other),))
            assert conn.execute('select count(*) from mastery_prediction_coverage').fetchone()[0] == 0
            conn.execute('reset role')
            print('PASS: formal publication, frozen denominator, unknown/no-response/no-snapshot, adaptive no old-grade backfill, RLS/private writes')
            recs = [uuid4() for _ in range(5)]; stamp = datetime.now(UTC).isoformat()
            for rid in recs:
                conn.execute("insert into recommendation_audits(id,user_id,subject_id,algorithm_version,snapshot,created_at) values(%s,%s,%s,'fixture',%s,%s)",
                             (rid, owner, subject, Jsonb({'title': 'Fixture', 'subjectName': 'Fixture', 'reasons': ['Synthetic audit only']}), stamp))
            events = [uuid4() for _ in range(5)]
            for eid in events:
                conn.execute("insert into product_events(id,user_id,subject_id,event_type,source_table,source_id,revision,algorithm_version,payload,created_at) values(%s,%s,%s,'step.completed','fixture',%s,'1','fixture',%s,%s)",
                             (eid, owner, subject, eid, Jsonb({'recommendationId': str(recs[0])}), stamp))
            conn.commit()
            with TestClient(app) as client:
                app.dependency_overrides.pop(get_current_user, None)
                assert client.get('/api/v1/recommendations/history').status_code == 401
                assert client.get('/api/v1/recommendations/prediction-coverage').status_code == 401
                app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(owner), email=None)
                page = client.get('/api/v1/recommendations/history', params={'limit': 2})
                assert page.status_code == 200 and page.headers['cache-control'] == 'no-store', page.text
                first = page.json(); seen = [row['id'] for row in first['items']]; cursor = first['nextCursor']
                newer = uuid4()
                conn.execute("insert into recommendation_audits(id,user_id,subject_id,algorithm_version,snapshot) values(%s,%s,%s,'fixture','{}')", (newer, owner, subject)); conn.commit()
                while cursor:
                    page = client.get('/api/v1/recommendations/history', params={'limit': 2, 'cursor': cursor}).json()
                    seen += [row['id'] for row in page['items']]; cursor = page['nextCursor']
                assert seen == sorted((str(rid) for rid in recs), reverse=True)
                assert len(seen) == len(set(seen)) == 5
                cursor = None; seen = []
                while True:
                    query = {'limit': 2, **({'cursor': cursor} if cursor else {})}
                    page = client.get(f'/api/v1/recommendations/{recs[0]}/audit', params=query).json()
                    seen += [row['id'] for row in page['events']]; cursor = page['nextCursor']
                    if not cursor: break
                assert seen == sorted((str(eid) for eid in events), reverse=True)
                assert client.get(f'/api/v1/recommendations/{recs[0]}/audit', params={'cursor': first['nextCursor']}).status_code == 422
                assert client.get('/api/v1/recommendations/history', params={'cursor': 'broken'}).status_code == 422
                assert client.get('/api/v1/recommendations/history', params={'limit': 0}).status_code == 422
                response = client.get('/api/v1/recommendations/prediction-coverage')
                assert response.status_code == 200 and response.json()['releasedGrades'] == 4
                app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(other), email=None)
                assert client.get('/api/v1/recommendations/history').json()['items'] == []
                assert client.get('/api/v1/recommendations/history', params={'cursor': first['nextCursor']}).status_code == 422
                assert client.get(f'/api/v1/recommendations/{recs[0]}/audit').status_code == 404
                assert client.get('/api/v1/recommendations/prediction-coverage').json()['coverageRate'] is None
            print('PASS: actual Supabase/API same-time UUID pagination, concurrent insert, scopes/422/404/401, no-store, coverage')
        finally:
            app.dependency_overrides.clear(); app.dependency_overrides.update(overrides)
            conn.rollback()
            for table in ('grading_results', 'exam_responses', 'exam_attempts', 'exams', 'questions', 'exam_blueprints'):
                conn.execute(f'delete from {table} where user_id in (%s,%s)', (owner, other))
            conn.execute('delete from auth.users where id in (%s,%s)', (owner, other)); conn.commit()
            for table in ('mastery_prediction_coverage', 'recommendation_audits', 'product_events'):
                assert conn.execute(f'select count(*) from {table} where user_id in (%s,%s)', (owner, other)).fetchone()[0] == 0
            print('PASS: exact temporary-user cleanup and privacy cascades')


if __name__ == '__main__': main()
