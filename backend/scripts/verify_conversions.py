"""Local-only transactional acceptance for migration 043; all fixtures roll back."""
import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from psycopg.types.json import Jsonb
from app.config.settings import settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--api', action='store_true')
    args = parser.parse_args()
    if urlparse(settings.database_url or '').hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise SystemExit('Refusing non-local database')
    with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
        if not conn.execute("select to_regclass('public.learning_conversions')").fetchone()[0]:
            if not args.apply:
                raise SystemExit('Missing migration 043; use --apply locally')
            conn.execute((Path(__file__).resolve().parents[1]/'migrations/043_unified_conversions.sql').read_text(encoding='utf-8'))
            conn.commit()
            print('Applied local migration 043')
        elif args.apply:
            migration = (Path(__file__).resolve().parents[1]/'migrations/043_unified_conversions.sql').read_text(encoding='utf-8')
            start, end = migration.index('create function public.enqueue_conversion'), migration.index('revoke all on function public.enqueue_conversion')
            functions = migration[start:end].replace('create function', 'create or replace function')
            functions = functions.replace('create trigger cancel_deleted_conversion after delete on public.learning_conversions for each row execute function public.cancel_deleted_conversion();', '')
            conn.execute(functions)
            conn.execute('create index if not exists conversions_source_wrong_answer on public.learning_conversions(user_id,source_wrong_answer_id,created_at desc)')
            conn.commit()
            print('Refreshed local conversion RPCs')
        conn.execute("select set_config('request.jwt.claims', '{\"role\":\"service_role\"}', true)")
        owner, foreign, subject, foreign_subject, material = [uuid4() for _ in range(5)]
        for uid in [owner, foreign]:
            conn.execute('insert into auth.users(id) values(%s)', (uid,))
        for sid, uid in [(subject, owner), (foreign_subject, foreign)]:
            conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Conversion rollback')", (sid, uid))
        conn.execute("insert into materials(id,user_id,subject_id,filename,content_type,file_size,status) values(%s,%s,%s,'source.txt','text/plain',10,'ready')", (material, owner, subject))
        block = conn.execute("insert into content_blocks(user_id,subject_id,material_id,block_type,content_text,page_number,sequence_index,parser_name,parser_version,source_hash) values(%s,%s,%s,'paragraph','Canonical course evidence',7,0,'test','1',%s) returning id", (owner, subject, material, str(uuid4()))).fetchone()[0]
        topic = conn.execute("select (resolve_course_topic(%s,%s,'Eigenvalues')).id", (owner, subject)).fetchone()[0]
        citations = conn.execute('select note_source_citations(%s,%s,%s)', (owner, subject, [block])).fetchone()[0]
        sections = {'sections': [{'id':'s1','title':'Definition','body':'Course definition','citationIds':[str(block)]}]}
        note = conn.execute('select save_note(%s,%s,null,null,%s)', (owner, subject, Jsonb({'title':'Source note','mode':'standard','citationIds':[str(block)],'topicIds':[str(topic)],'content':sections}))).fetchone()[0]
        source = {'kind':'notes','id':note['id'],'version':1}
        snapshot = {'source':source,'title':'Source note','content':sections,'topicIds':[str(topic)],'citations':citations,'warnings':[]}

        def enqueue(target='flashcards', request=None, digest='same', src=None, count=1):
            return conn.execute('select enqueue_conversion(%s,%s,%s,%s,%s,%s,%s,%s)',
                (owner,subject,request or uuid4(),digest,Jsonb(src or source),target,Jsonb({'count':count,'mode':'standard'}),Jsonb(snapshot))).fetchone()[0]
        def claim(job):
            return conn.execute('select claim_conversion(%s)', (job['id'],)).fetchone()[0]
        def finish(job, draft):
            return conn.execute('select finish_conversion(%s,%s,%s)', (job['id'],job['claim_token'],Jsonb(draft))).fetchone()[0]
        def rejects(code, operation):
            try:
                with conn.transaction(): operation()
            except psycopg.Error as exc:
                assert exc.sqlstate == code, (exc.sqlstate,str(exc))
            else: raise AssertionError('Invalid conversion accepted')
        request = uuid4()
        first = enqueue(request=request)
        assert enqueue(request=request)['id'] == first['id']
        rejects('40001', lambda: enqueue(request=request,digest='different'))
        rejects('40001', lambda: enqueue(src={**source,'version':2}))
        rejects('22023', lambda: enqueue(target='notes'))
        job = claim(first)
        assert claim(first) is None
        draft = {'title':'Converted cards','content':{'cards':[{'id':'c1','front':'Definition?','back':'Course definition','knowledgeKey':'Eigenvalues','citationIds':[str(block)]}]}}
        result = finish(job,draft)
        assert finish(job,draft)['result_artifact_id'] == result['result_artifact_id']
        assert conn.execute('select count(*) from flashcard_review_state where artifact_id=%s',(result['result_artifact_id'],)).fetchone()[0] == 1
        assert conn.execute('select generation_params->>\'conversionId\' from artifacts where id=%s',(result['result_artifact_id'],)).fetchone()[0] == first['id']
        assert conn.execute('select count(*) from learning_conversions where source_artifact_id=%s or result_artifact_id=%s',(note['id'],result['result_artifact_id'])).fetchone()[0] == 1
        cancelled = claim(enqueue())
        conn.execute("select transition_conversion(%s,%s,'cancel')",(owner,cancelled['id']))
        rejects('40001',lambda:finish(cancelled,draft))
        retry = claim(enqueue())
        conn.execute("select transition_conversion(%s,%s,'fail',%s,'model failure')",(owner,retry['id'],retry['claim_token']))
        conn.execute("select transition_conversion(%s,%s,'retry')",(owner,retry['id']))
        retry2 = claim(retry)
        rejects('40001',lambda:finish(retry,draft))
        finish(retry2,draft)
        lease = claim(enqueue())
        conn.execute("update processing_tasks set started_at=now()-interval '21 minutes' where id=%s",(lease['id'],))
        lease2 = claim(lease)
        assert lease2['claim_token'] != lease['claim_token']
        rejects('40001',lambda:finish(lease,draft))
        finish(lease2,draft)
        exhausted = claim(enqueue())
        for index in range(3):
            conn.execute("select transition_conversion(%s,%s,'fail',%s,'failure')",(owner,exhausted['id'],exhausted['claim_token']))
            if index<2:
                conn.execute("select transition_conversion(%s,%s,'retry')",(owner,exhausted['id']))
                exhausted=claim(exhausted)
        rejects('40001',lambda:conn.execute("select transition_conversion(%s,%s,'retry')",(owner,exhausted['id'])))
        quiz = claim(enqueue(target='quiz',count=2))
        question = {'questionType':'single_choice','stem':'Eigenvalues?','options':['A','B'],'correctAnswer':['A'],'explanation':'Definition','knowledgeKey':'Eigenvalues','citationIds':[str(block)]}
        before = conn.execute('select count(*) from exam_blueprints where user_id=%s',(owner,)).fetchone()[0]
        rejects('22023', lambda:finish(quiz,{'title':'Quiz','questions':[question,{**question,'citationIds':[]}]}))
        assert conn.execute('select count(*) from exam_blueprints where user_id=%s',(owner,)).fetchone()[0] == before
        exam = finish(quiz,{'title':'Quiz','questions':[question,{**question,'stem':'Eigenvalue conditions?','correctAnswer':'A'}]})
        assert exam['result_exam_id'] and conn.execute('select count(*) from exam_questions where exam_id=%s',(exam['result_exam_id'],)).fetchone()[0] == 2
        foreign_blueprint = conn.execute("insert into exam_blueprints(user_id,subject_id,title,duration_minutes,total_points,specification) values(%s,%s,'Foreign',30,5,'{}') returning id",(foreign,foreign_subject)).fetchone()[0]
        foreign_exam = conn.execute("insert into exams(user_id,subject_id,blueprint_id,title,duration_minutes,total_points) values(%s,%s,%s,'Foreign',30,5) returning id",(foreign,foreign_subject,foreign_blueprint)).fetchone()[0]
        rejects('23503',lambda:conn.execute('update learning_conversions set result_exam_id=%s where id=%s',(foreign_exam,cancelled['id'])))
        material_source = {'kind':'material','id':str(material)}
        note_job = claim(enqueue(target='notes',src=material_source))
        published = finish(note_job,{'title':'Converted note','content':sections})
        assert conn.execute('select count(*) from artifact_versions where artifact_id=%s',(published['result_artifact_id'],)).fetchone()[0] == 1
        tutor = claim(enqueue(target='tutor'))
        assert finish(tutor,{})['result_href'].startswith('/study-room?conversionId=')
        map_job = claim(enqueue(target='mind_map'))
        finish(map_job,{'title':'Map','content':{'nodes':[{'id':'root','parentId':None,'title':'Definition','citationIds':[str(block)]}],'edges':[]}})
        changed = claim(enqueue())
        conn.execute("update content_blocks set content_text='Changed evidence' where id=%s",(block,))
        rejects('40001', lambda:finish(changed,draft))
        conn.execute("update content_blocks set content_text='Canonical course evidence' where id=%s",(block,))
        temporary_material = conn.execute("insert into materials(user_id,subject_id,filename,content_type,file_size,status) values(%s,%s,'Temporary','text/plain',1,'ready') returning id",(owner,subject)).fetchone()[0]
        deleting = enqueue(src={'kind':'material','id':str(temporary_material)})
        conn.execute('delete from materials where id=%s',(temporary_material,))
        assert conn.execute('select status from processing_tasks where id=%s',(deleting['id'],)).fetchone()[0] == 'cancelled'
        rejects('23503',lambda:conn.execute('update learning_conversions set user_id=%s where id=%s',(foreign,changed['id'])))
        conn.execute('set local role authenticated')
        conn.execute("select set_config('request.jwt.claims','{}',true)")
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(owner),))
        assert conn.execute('select count(*) from learning_conversions').fetchone()[0] > 0
        rejects('42501',lambda:conn.execute("update learning_conversions set target='tutor' where id=%s",(first['id'],)))
        rejects('42501',lambda:conn.execute('select claim_conversion(%s)',(changed['id'],)))
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(foreign),))
        assert conn.execute('select count(*) from learning_conversions where user_id=%s',(owner,)).fetchone()[0] == 0
        conn.rollback()
        print('PASS: deduplication, claim fencing, cancellation, retries, lease recovery, atomic artifact/note/quiz publication, source change rejection, scope FKs and read-only RLS; fixtures rolled back')
        if args.api:
            if urlparse(settings.supabase_url or '').hostname not in {'localhost','127.0.0.1','::1'}: raise SystemExit('Refusing non-local Supabase')
            from fastapi.testclient import TestClient
            from app.main import app
            from app.api.deps import get_current_user
            from app.models.user import CurrentUser
            row = conn.execute('select id,user_id from subjects order by created_at limit 1').fetchone()
            if not row: raise SystemExit('No existing local subject for read-only API checks')
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=str(row[1]),email='test@example.com')
            try:
                with TestClient(app) as client:
                    assert client.get('/api/v1/conversions',params={'subject_id':str(row[0])}).status_code == 200
                    assert client.get('/api/v1/conversions/capabilities').status_code == 200
                    assert client.get('/api/v1/conversions',params={'subject_id':str(uuid4())}).status_code == 404
            finally: app.dependency_overrides.pop(get_current_user,None)
            with TestClient(app) as client:
                assert client.get('/api/v1/conversions/capabilities').status_code == 401
            print('PASS: real local Supabase read-only conversion APIs 200, foreign subject 404, anonymous 401 (test auth override; no model calls)')


if __name__ == '__main__':
    main()
