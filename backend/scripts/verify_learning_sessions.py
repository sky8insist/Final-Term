"""Local-only P1 migration and rollback database acceptance; no model calls."""
import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg
from psycopg.types.json import Jsonb
from app.config.settings import settings
from app.services.study_session_service import build_steps


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    url = settings.database_url or ""
    if urlparse(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("Refusing a non-local database")
    with psycopg.connect(url, connect_timeout=5) as conn:
        for filename, table, column in [("026_learning_interactions.sql", "learning_interactions", "session_id"),
                                        ("033_guided_sessions.sql", "study_sessions", "version"),
                                        ("034_adaptive_assessments.sql", "exams", "assessment_mode")]:
            installed = conn.execute("select exists(select 1 from information_schema.columns where table_schema='public' and table_name=%s and column_name=%s)", (table, column)).fetchone()[0]
            if not installed:
                if not args.apply: raise SystemExit(f"Missing {filename}; use --apply")
                conn.execute((Path(__file__).resolve().parents[1] / "migrations" / filename).read_text(encoding="utf-8"))
                conn.commit()
                print(f"Applied locally: {filename}")
        recent_window = conn.execute("select position('recentResults' in prosrc)>0 from pg_proc where oid='public.guard_adaptive_grade()'::regprocedure").fetchone()[0]
        if not recent_window:
            if not args.apply: raise SystemExit("Missing 035_adaptive_recent_window.sql; use --apply")
            conn.execute((Path(__file__).resolve().parents[1] / "migrations" / "035_adaptive_recent_window.sql").read_text(encoding="utf-8"))
            conn.commit()
            print("Applied locally: 035_adaptive_recent_window.sql")
        progress_guard = conn.execute("select exists(select 1 from pg_policies where schemaname='public' and tablename='processing_tasks' and policyname='Owners read progress processing_tasks')").fetchone()[0]
        if not progress_guard:
            if not args.apply: raise SystemExit("Missing 037_learning_progress_integrity.sql; use --apply")
            conn.execute((Path(__file__).resolve().parents[1] / "migrations" / "037_learning_progress_integrity.sql").read_text(encoding="utf-8"))
            conn.commit()
            print("Applied locally: 037_learning_progress_integrity.sql")
        conn.execute("notify pgrst, 'reload schema'")
        conn.commit()
        conn.execute("select set_config('request.jwt.claims', '{\"role\":\"service_role\"}', true)")
        owner, foreign, subject, sid = [uuid4() for _ in range(4)]
        for user in [owner, foreign]: conn.execute("insert into auth.users(id) values(%s)", (user,))
        conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'P1 rollback acceptance')", (subject, owner))
        topic = conn.execute("select (resolve_course_topic(%s,%s,'P1 Topic')).id", (owner, subject)).fetchone()[0]
        values = {"id": str(sid), "subject_id": str(subject), "knowledge_point_id": str(topic),
                  "goal": "P1 Topic", "minutes": 30, "context": {}, "steps": build_steps(30)}
        assert conn.execute("select (save_guided_session(%s,%s,null)).version", (owner, Jsonb(values))).fetchone()[0] == 1
        values.update(status="active", current_step=0)
        assert conn.execute("select (save_guided_session(%s,%s,1)).version", (owner, Jsonb(values))).fetchone()[0] == 2
        try:
            with conn.transaction(): conn.execute("select save_guided_session(%s,%s,1)", (owner, Jsonb(values)))
        except psycopg.errors.SerializationFailure: pass
        else: raise AssertionError("Stale session accepted")
        assert conn.execute("select count(*) from study_session_steps where session_id=%s", (sid,)).fetchone()[0] == 5
        invalid = {**values, "steps": [{**values["steps"][0], "kind": "invalid"}]}
        try:
            with conn.transaction(): conn.execute("select save_guided_session(%s,%s,2)", (owner, Jsonb(invalid)))
        except psycopg.errors.CheckViolation: pass
        else: raise AssertionError("Invalid step accepted")
        assert conn.execute("select version from study_sessions where id=%s", (sid,)).fetchone()[0] == 2
        assert conn.execute("select count(*) from study_session_steps where session_id=%s", (sid,)).fetchone()[0] == 5
        print("PASS: session atomic snapshot, stale version rejection and rollback")
        blueprint = conn.execute("insert into exam_blueprints(user_id,subject_id,title,duration_minutes,total_points,specification) values(%s,%s,'test',30,10,'{}') returning id", (owner, subject)).fetchone()[0]
        exam = conn.execute("insert into exams(user_id,subject_id,blueprint_id,title,duration_minutes,total_points,assessment_mode) values(%s,%s,%s,'test',30,10,'adaptive') returning id", (owner, subject, blueprint)).fetchone()[0]
        attempt = conn.execute("insert into exam_attempts(user_id,subject_id,exam_id,expires_at,max_score) values(%s,%s,%s,now()+interval '30 min',10) returning id", (owner, subject, exam)).fetchone()[0]
        questions = []
        for _ in range(4):
            qid = conn.execute("insert into questions(user_id,subject_id,question_type,knowledge_key,difficulty) values(%s,%s,'single_choice','P1 Topic','medium') returning id", (owner, subject)).fetchone()[0]
            questions.append(qid)
            conn.execute("insert into question_versions(question_id,version,stem,correct_answer,explanation) values(%s,1,'test','\"A\"','test')", (qid,))
        def grade(qid, confidence=0.5):
            conn.execute("insert into grading_results(user_id,attempt_id,question_id,earned_points,max_points,is_correct,feedback,learner_confidence) values(%s,%s,%s,0,2,false,'test',%s)", (owner, attempt, qid, confidence))
        for qid in questions[:3]: grade(qid)
        state = conn.execute("select adaptive_state from exam_attempts where id=%s", (attempt,)).fetchone()[0]
        assert state["paused"] and state["consecutiveWrong"] == 3
        try:
            with conn.transaction(): grade(questions[3])
        except psycopg.errors.CheckViolation: pass
        else: raise AssertionError("Paused quiz accepted a grade")
        resumed = conn.execute("select (resume_adaptive_quiz(%s,%s,%s)).adaptive_state", (owner, attempt, "Reviewed the topic and corrected the misunderstanding.")).fetchone()[0]
        assert not resumed["paused"] and resumed["resumeCount"] == 1
        grade(questions[3], 0.9)
        # A second high-confidence wrong answer after reset pauses again.
        conn.execute("delete from grading_results where attempt_id=%s and question_id=%s", (attempt, questions[0]))
        grade(questions[0], 0.9)
        assert conn.execute("select adaptive_state->>'reason' from exam_attempts where id=%s", (attempt,)).fetchone()[0] == "两次高信心错误"
        print("PASS: consecutive-error and confidence stop policies, blocked writes, remediation resume")
        window_attempt = conn.execute("insert into exam_attempts(user_id,subject_id,exam_id,expires_at,max_score) values(%s,%s,%s,now()+interval '30 min',10) returning id", (owner, subject, exam)).fetchone()[0]
        for correct in [False, False, True, False, False]:
            qid = conn.execute("insert into questions(user_id,subject_id,question_type,knowledge_key,difficulty) values(%s,%s,'single_choice','P1 Topic','medium') returning id", (owner, subject)).fetchone()[0]
            conn.execute("insert into grading_results(user_id,attempt_id,question_id,earned_points,max_points,is_correct,feedback) values(%s,%s,%s,%s,2,%s,'test')", (owner, window_attempt, qid, 2 if correct else 0, correct))
        window_state = conn.execute("select adaptive_state from exam_attempts where id=%s", (window_attempt,)).fetchone()[0]
        assert window_state["reason"] == "近期正确率低于40%" and len(window_state["recentResults"]) == 5
        print("PASS: five-question recent accuracy window")
        # A browser cannot forge pause/mastery/mode or read fixed answers.
        conn.execute("set local role authenticated")
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(owner),))
        conn.execute("select set_config('request.jwt.claims',%s,true)", (f'{{"sub":"{owner}","role":"authenticated"}}',))
        assert conn.execute("select count(*) from study_sessions where id=%s", (sid,)).fetchone()[0] == 1
        assert conn.execute("update exam_attempts set adaptive_state='{}' where id=%s returning id", (attempt,)).fetchone() is None
        assert conn.execute("update exams set assessment_mode='formal' where id=%s returning id", (exam,)).fetchone() is None
        assert conn.execute("select count(*) from question_versions where question_id=%s", (questions[0],)).fetchone()[0] == 0
        conn.execute("reset role")
        conn.execute("update exams set assessment_mode='formal' where id=%s", (exam,))
        conn.execute("set local role authenticated")
        assert conn.execute("select count(*) from grading_results where attempt_id=%s", (attempt,)).fetchone()[0] == 0
        conn.execute("reset role")
        conn.execute("update exam_attempts set status='graded' where id=%s", (attempt,))
        conn.execute("set local role authenticated")
        assert conn.execute("select count(*) from grading_results where attempt_id=%s", (attempt,)).fetchone()[0] == 4
        print("PASS: partial formal grades hidden by RLS; graded results released")
        for table in ["processing_tasks", "learning_interactions", "learning_events"]:
            assert conn.execute("select count(*) from pg_policies where schemaname='public' and tablename=%s and cmd<>'SELECT'", (table,)).fetchone()[0] == 0
        assert not conn.execute("select has_function_privilege('authenticated','public.save_guided_session(uuid,jsonb,integer)','EXECUTE')").fetchone()[0]
        print("PASS: browser cannot forge task receipts, evaluated interactions or learning events")
        conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(foreign),))
        conn.execute("select set_config('request.jwt.claims',%s,true)", (f'{{"sub":"{foreign}","role":"authenticated"}}',))
        assert conn.execute("select count(*) from study_sessions where id=%s", (sid,)).fetchone()[0] == 0
        assert conn.execute("select count(*) from study_session_steps where session_id=%s", (sid,)).fetchone()[0] == 0
        print("PASS: cross-owner RLS, server-only progression/mode/pause and hidden fixed answers")
        conn.rollback()
        print("All acceptance rows rolled back; no learner data changed.")


if __name__ == "__main__": main()
