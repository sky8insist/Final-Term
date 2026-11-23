"""Offline grounding benchmark; optional local rollback-only audit persistence check."""
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config.settings import settings
from app.services.grounding_eval_service import evaluate_grounding_cases
from app.services.grounding_service import verify_answer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = evaluate_grounding_cases(json.loads((root / 'evals/grounding_cases.json').read_text(encoding='utf-8')))
    if report['failures']: raise SystemExit(f'Grounding regression: {report["failures"]}')
    if args.db:
        if urlparse(settings.database_url or '').hostname not in {'localhost', '127.0.0.1', '::1'}:
            raise SystemExit('Local database required')
        import psycopg
        from psycopg.types.json import Jsonb
        with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
            owner, foreign, subject = [uuid4() for _ in range(3)]
            for uid in (owner, foreign): conn.execute('insert into auth.users(id) values(%s)', (uid,))
            conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'Grounding rollback')", (subject, owner))
            audit = verify_answer(answer='Matrix is an array[99].', citations=[{'id': 'fixture', 'text': 'Matrix is an array.'}])
            assert not audit['passed'] and audit['reason'] == 'fabricated_citation'
            refusal = '资料中未找到足够依据。'
            msg = conn.execute("insert into chat_messages(user_id,subject_id,role,content,citations,metadata) values(%s,%s,'assistant',%s,'[]',%s) returning id,metadata", (owner, subject, refusal, Jsonb({'grounding': audit}))).fetchone()
            assert msg[1]['grounding']['invalidCitationNumbers'] == [99]
            conn.execute('set local role authenticated')
            conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(owner),))
            row = conn.execute('select content,citations,metadata from chat_messages where id=%s', (msg[0],)).fetchone()
            assert row[0] == refusal and row[1] == [] and row[2]['grounding']['passed'] is False
            conn.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(foreign),))
            assert conn.execute('select count(*) from chat_messages where id=%s', (msg[0],)).fetchone()[0] == 0
            conn.rollback()
        report['localAuditPersistence'] = 'passed; fixtures rolled back'
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__': main()
