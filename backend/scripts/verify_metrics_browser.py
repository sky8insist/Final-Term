"""Real local browser + normal Supabase password/JWT auth. Disposable accounts only.

No auth overrides, storage-state injection, production endpoints, model calls, or
existing browser profiles. Only explicit fault scenarios intercept API responses.
"""
import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
import psycopg
from psycopg.types.json import Jsonb
from playwright.async_api import async_playwright, expect
from app.config.settings import settings
from app.db.supabase_client import get_supabase_client
from app.services.workspace_cache_service import get_redis_client

LOCAL = {'localhost', '127.0.0.1', '::1'}


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


async def ready(url, process):
    async with httpx.AsyncClient(trust_env=False) as client:
        for _ in range(150):
            if process.poll() is not None: raise RuntimeError('Isolated service exited during startup')
            try:
                if (await client.get(url, timeout=1)).status_code == 200: return
            except httpx.HTTPError: pass
            await asyncio.sleep(.2)
    raise RuntimeError('Isolated service did not become ready')


def seed(conn, owner):
    subject, topic = uuid4(), uuid4()
    conn.execute("insert into subjects(id,user_id,name) values(%s,%s,'浏览器验收科目')", (subject, owner))
    conn.execute("insert into knowledge_points(id,user_id,subject_id,knowledge_key,title) values(%s,%s,%s,'browser-fixture','浏览器验收知识点')", (topic, owner, subject))
    now = datetime.now(UTC)
    recs = [uuid4() for _ in range(23)]
    for index, rid in enumerate(recs):
        snapshot = {'title': f'浏览器验收建议 {index+1:02}', 'subjectName': '浏览器验收科目', 'reasons': ['合成验收依据：检查历史与界面，不代表真实学习效果'],
                    'priorityScore': .72, 'inputSignals': {'mastery': .2, 'assessmentCount': 2, 'dueReview': True},
                    'scoreComponents': {'need': .72}, 'algorithmVersions': {'recommendation': 'next-action-v2', 'studySignal': 'study-signal-v2-confidence'}}
        conn.execute("insert into recommendation_audits(id,user_id,subject_id,knowledge_point_id,algorithm_version,snapshot,created_at) values(%s,%s,%s,%s,'next-action-v2',%s,%s)",
                     (rid, owner, subject, topic, Jsonb(snapshot), now-timedelta(seconds=index+100)))
    for index in range(65):
        event = ['recommendation.impression', 'recommendation.clicked', 'session.accepted', 'session.completed'][index] if index < 4 else 'step.completed'
        payload = {'recommendationId': str(recs[0]), 'kind': 'notes'}
        if event == 'session.completed':
            payload.update(before={'masteryScore': .2, 'assessmentCount': 2}, after={'masteryScore': .7, 'assessmentCount': 3})
        conn.execute("insert into product_events(user_id,subject_id,event_type,source_table,source_id,revision,algorithm_version,payload,created_at) values(%s,%s,%s,'browser-fixture',%s,'1','guided-session-v1',%s,%s)",
                     (owner, subject, event, uuid4(), Jsonb(payload), now-timedelta(seconds=index)))
    for kind in ('guided_session', 'plan_task', 'due_flashcard', 'quiz_remediation'):
        for age in (8, 1):
            start = now-timedelta(days=age)
            conn.execute("insert into learning_metric_cohorts(user_id,subject_id,kind,source_id,revision,algorithm_version,starts_at,deadline,completed_at) values(%s,%s,%s,%s,'1','browser-fixture-v1',%s,%s,%s)",
                         (owner, subject, kind, uuid4(), start, start+timedelta(days=7), start+timedelta(hours=1) if age == 8 else None))
    for index in range(11):
        has_prediction = index < 6
        reason = 'available' if has_prediction or index == 10 else 'no_snapshot' if index < 8 else 'no_response'
        conn.execute("insert into mastery_prediction_coverage(id,user_id,subject_id,known_outcome,has_prediction,reason) values(%s,%s,%s,%s,%s,%s)",
                     (uuid4(), owner, subject, index != 10, has_prediction, reason))
    for score, correct in ((.2, False), (.8, True), (.2, False), (.8, True)):
        conn.execute("insert into mastery_prediction_samples(id,user_id,subject_id,attempt_id,question_id,prediction,actual) values(%s,%s,%s,%s,%s,%s,%s)",
                     (uuid4(), owner, subject, uuid4(), uuid4(), Jsonb({'score': score, 'algorithmVersion': 'mastery-v2'}), correct))
    conn.commit()
    return recs


async def run(args):
    for value in (settings.database_url, settings.supabase_url, settings.redis_url):
        if urlparse(value or '').hostname not in LOCAL: raise RuntimeError('Only local DB/Supabase/Redis permitted')
    if not settings.supabase_anon_key or not settings.supabase_jwt_secret: raise RuntimeError('Local auth configuration required')
    os.environ['NO_PROXY'] = os.environ['no_proxy'] = 'localhost,127.0.0.1,::1'
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).isoformat()
    report = {'schemaVersion': 1, 'startedAt': stamp, 'scope': 'learning-metrics', 'mode': 'real-headless-browser',
              'auth': 'normal local Supabase password sign-in and backend JWT verification; no overrides',
              'data': 'committed disposable synthetic fixtures; not learning efficacy', 'cases': [], 'screenshots': [],
              'limitations': ['one local Windows browser engine; not human or multi-device UAT', 'fault cases simulate network errors/delay only', 'no model/worker/long-term or production acceptance']}
    processes, users = [], []
    credentials = [(f'browser-{uuid4().hex}@example.test', secrets.token_urlsafe(24)) for _ in range(2)]
    console_errors, auth_success, api_bearer = [], [], []
    client = get_supabase_client()
    with psycopg.connect(settings.database_url, connect_timeout=5) as conn, tempfile.TemporaryDirectory(prefix='examai-browser-') as temp:
        logs = []
        try:
            if not conn.execute("select to_regclass('mastery_prediction_coverage')").fetchone()[0]: raise RuntimeError('Migration 057 required')
            for email, password in credentials:
                created = client.auth.admin.create_user({'email': email, 'password': password, 'email_confirm': True})
                users.append(created.user.id)
            recs = seed(conn, users[0])
            api_port, web_port = free_port(), free_port()
            while api_port == web_port: web_port = free_port()
            api_url, web_url = f'http://127.0.0.1:{api_port}', f'http://127.0.0.1:{web_port}'
            env = dict(os.environ, FRONTEND_ORIGIN=web_url)
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            for name in ('api', 'web'):
                logs.append(open(Path(temp)/f'{name}.log', 'w', encoding='utf-8'))
            processes.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(api_port), '--no-access-log'],
                cwd=ROOT, env=env, stdout=logs[0], stderr=subprocess.STDOUT, creationflags=creationflags))
            env.update(VITE_API_BASE_URL=api_url, VITE_SUPABASE_URL=settings.supabase_url, VITE_SUPABASE_ANON_KEY=settings.supabase_anon_key)
            processes.append(subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(web_port), '--strictPort'],
                cwd=ROOT.parent/'frontend', env=env, stdout=logs[1], stderr=subprocess.STDOUT, creationflags=creationflags))
            await ready(api_url+'/openapi.json', processes[0]); await ready(web_url, processes[1])
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel='msedge' if args.browser == 'edge' else 'chrome', headless=True)
                report.update(browser=args.browser, browserVersion=browser.version, playwrightVersion=version('playwright'), viewports=['1365x900', '1024x768'])
                context = await browser.new_context(viewport={'width': 1365, 'height': 900}, locale='zh-CN', timezone_id='Asia/Shanghai')
                page = await context.new_page(); page.set_default_timeout(12000)
                page.on('pageerror', lambda error: console_errors.append(type(error).__name__))
                page.on('response', lambda response: auth_success.append(True) if '/auth/v1/token' in response.url and response.status == 200 else None)
                page.on('request', lambda request: api_bearer.append(True) if request.url.startswith(api_url+'/api/v1/recommendations') and request.headers.get('authorization', '').startswith('Bearer ') else None)
                async def local_only(route):
                    if urlparse(route.request.url).hostname in LOCAL: await route.continue_()
                    else: await route.abort()
                await context.route('**/*', local_only)

                async def check(name, action):
                    try:
                        await action()
                        report['cases'].append({'name': name, 'status': 'passed'})
                        print('PASS: '+name, flush=True)
                    except Exception as exc:
                        message = str(exc)[:1800]
                        for _, password in credentials: message = message.replace(password, '[redacted]')
                        report['cases'].append({'name': name, 'status': 'failed', 'error': message})
                        print('FAIL: '+name+' ('+type(exc).__name__+')', flush=True)

                async def screenshot(name):
                    await page.screenshot(path=str(args.output_dir/name))
                    report['screenshots'].append(name)

                async def login(index):
                    await page.goto(web_url+'/learning-metrics')
                    await expect(page.get_by_role('heading', name='欢迎回来', exact=True)).to_be_visible()
                    await page.get_by_label('邮箱或账户名', exact=True).fill(credentials[index][0])
                    await page.get_by_label('密码', exact=True).fill(credentials[index][1])
                    await page.get_by_role('button', name='登录', exact=True).click()
                    await expect(page.get_by_role('heading', name='学习记录', exact=True)).to_be_visible()
                    await expect(page.get_by_role('button', name='刷新记录', exact=True)).to_be_enabled()

                await login(0)
                report['cases'].append({'name': 'protected redirect and real password/JWT login', 'status': 'passed'})
                print('PASS: protected redirect and real password/JWT login', flush=True)

                async def populated():
                    await expect(page.get_by_role('combobox', name='统计窗口')).to_have_value('30')
                    await expect(page.locator('#calibration strong').first).to_have_text('60.0%')
                    await expect(page.get_by_role('region', name='各类安排的完成情况').locator('tbody tr')).to_have_count(4)
                    await expect(page.get_by_role('region', name='推荐历史').locator('tbody tr')).to_have_count(20)
                    await page.get_by_role('heading', name='学习记录', exact=True).scroll_into_view_if_needed()
                    await screenshot('desktop-1365.png')
                await check('populated metrics / denominator / default window', populated)

                async def window_race():
                    started = asyncio.Event()
                    async def delay(route):
                        response = await route.fetch(); started.set(); await asyncio.sleep(1.2); await route.fulfill(response=response)
                    pattern = '**/api/v1/recommendations/learning-outcomes?days=7'
                    await page.route(pattern, delay)
                    await page.get_by_role('combobox', name='统计窗口').select_option('7')
                    await asyncio.wait_for(started.wait(), 10)
                    await page.get_by_role('combobox', name='统计窗口').select_option('90')
                    region = page.get_by_role('region', name='各类安排的完成情况')
                    await expect(region.locator('tbody tr').first.locator('td').nth(1)).to_have_text('1')
                    await asyncio.sleep(1.4)
                    await expect(region.locator('tbody tr').first.locator('td').nth(1)).to_have_text('1')
                    await page.unroute(pattern, delay)
                    await page.get_by_role('combobox', name='统计窗口').select_option('30')
                    await expect(page.get_by_role('button', name='刷新记录', exact=True)).to_be_enabled()
                await check('slow old window response cannot overwrite new selection', window_race)

                async def paging():
                    await page.get_by_role('button', name='加载更早的推荐', exact=True).click()
                    await expect(page.get_by_role('region', name='推荐历史').locator('tbody tr')).to_have_count(23)
                    row = page.get_by_role('region', name='推荐历史').get_by_role('row').filter(has_text='浏览器验收建议 01')
                    trigger = row.get_by_role('button', name=re.compile('查看'))
                    await trigger.focus(); await page.keyboard.press('Enter')
                    await expect(page.get_by_role('heading', name='推荐依据与后续行动', exact=True)).to_be_focused()
                    assert parse_qs(urlparse(page.url).query)['recommendationId'] == [str(recs[0])]
                    await expect(page.locator('#recommendation-detail ol > li')).to_have_count(30)
                    await page.get_by_role('button', name='加载更早的行动', exact=True).click()
                    await expect(page.locator('#recommendation-detail ol > li')).to_have_count(60)
                    await page.get_by_role('button', name='加载更早的行动', exact=True).click()
                    await expect(page.locator('#recommendation-detail ol > li')).to_have_count(65)
                    await page.get_by_text('查看计算时的信号与规则', exact=True).focus(); await page.keyboard.press('Space')
                    await expect(page.get_by_role('heading', name='输入信号', exact=True)).to_be_visible()
                    await page.get_by_role('heading', name='推荐依据与后续行动', exact=True).scroll_into_view_if_needed()
                    await screenshot('audit-keyboard.png')
                await check('real history/event pagination and keyboard detail disclosure', paging)

                async def reload_detail():
                    await page.reload()
                    await expect(page.locator('#recommendation-detail ol > li')).to_have_count(30)
                    assert parse_qs(urlparse(page.url).query)['recommendationId'] == [str(recs[0])]
                await check('detail URL survives browser reload', reload_detail)

                async def close_focus():
                    await page.get_by_role('button', name='关闭详情', exact=True).click()
                    await expect(page.locator('#recommendation-detail')).to_be_hidden()
                    trigger = page.get_by_role('region', name='推荐历史').get_by_role('row').filter(has_text='浏览器验收建议 01').get_by_role('button', name=re.compile('查看'))
                    await expect(trigger).to_be_focused()
                await check('closing detail restores keyboard focus to originating row', close_focus)

                async def error_recovery():
                    pattern = '**/api/v1/recommendations/prediction-coverage?*'
                    async def unavailable(route): await route.fulfill(status=503, json={'detail': '浏览器验收：模拟覆盖率暂时不可用'})
                    await page.route(pattern, unavailable)
                    await page.get_by_role('button', name='刷新记录', exact=True).click()
                    await expect(page.get_by_role('alert')).to_contain_text('模拟覆盖率暂时不可用')
                    await expect(page.get_by_role('region', name='各类安排的完成情况').locator('tbody tr')).to_have_count(4)
                    await page.unroute(pattern, unavailable)
                    await page.get_by_role('button', name='重新读取', exact=True).click()
                    await expect(page.locator('#calibration strong').first).to_have_text('60.0%')
                    await expect(page.get_by_role('alert')).to_have_count(0)
                await check('explicit 503 fault: independent sections survive and retry recovers', error_recovery)

                async def desktop_layout():
                    await page.set_viewport_size({'width': 1024, 'height': 768})
                    await page.get_by_role('heading', name='学习记录', exact=True).scroll_into_view_if_needed()
                    assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    await expect(page.get_by_role('combobox', name='统计窗口')).to_be_visible()
                    await screenshot('desktop-1024.png')
                    await page.set_viewport_size({'width': 1365, 'height': 900})
                await check('supported desktop widths 1365 and 1024 render without document overflow', desktop_layout)

                async def switch_empty():
                    await page.get_by_role('button', name='退出登录', exact=True).click()
                    await expect(page.get_by_role('heading', name='欢迎回来', exact=True)).to_be_visible()
                    await login(1)
                    await expect(page.get_by_text('暂无推荐历史。返回仪表盘读取建议后，这里会保存当时的依据。', exact=True)).to_be_visible()
                    await expect(page.get_by_text('还没有同时具备首次预测和已发布结果的校准样本。', exact=True)).to_be_visible()
                    assert '浏览器验收建议' not in await page.locator('body').inner_text()
                    await page.get_by_role('heading', name='学习记录', exact=True).scroll_into_view_if_needed()
                    await screenshot('empty-account.png')
                await check('same-browser logout/login isolates empty second account', switch_empty)

                async def foreign_detail():
                    await page.goto(web_url+'/learning-metrics?recommendationId='+str(recs[0]))
                    await expect(page.get_by_role('alert')).to_contain_text('推荐记录不存在')
                    assert '浏览器验收建议' not in await page.locator('body').inner_text()
                    await page.get_by_role('button', name='关闭详情', exact=True).click()
                    await expect(page.get_by_role('heading', name='当时为什么这样建议', exact=True)).to_be_focused()
                await check('real JWT second account cannot read first account audit', foreign_detail)
                report['authObserved'] = bool(auth_success) and bool(api_bearer)
                report['pageErrorCount'] = len(console_errors)
                if not report['authObserved'] or console_errors: report['cases'].append({'name': 'real auth traffic and browser runtime', 'status': 'failed'})
                else: report['cases'].append({'name': 'real auth traffic and browser runtime', 'status': 'passed'})
                await context.close(); await browser.close()
        except Exception as exc:
            report['setupError'] = type(exc).__name__
            print('FAIL: browser setup/run ('+type(exc).__name__+')', flush=True)
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
            for handle in logs: handle.close()
            conn.rollback()
            emails = [email for email, _ in credentials]
            found = [str(row[0]) for row in conn.execute('select id from auth.users where email=any(%s)', (emails,)).fetchall()]
            for uid in found:
                # Logout can write snapshots. Delete this exact UUID namespace only.
                redis = get_redis_client()
                for prefix in ('workspace:v1', 'workspace:v2'):
                    keys = list(redis.scan_iter(match=f'{prefix}:{uid}:*', count=100))
                    if keys: redis.delete(*keys)
                conn.execute('delete from auth.users where id=%s', (uid,))
            conn.commit()
            assert conn.execute('select count(*) from auth.users where email=any(%s)', (emails,)).fetchone()[0] == 0
            for table in ('recommendation_audits', 'product_events', 'learning_metric_cohorts', 'mastery_prediction_samples', 'mastery_prediction_coverage'):
                assert conn.execute(f'select count(*) from {table} where user_id=any(%s::uuid[])', (found,)).fetchone()[0] == 0
            report['cleanup'] = 'exact generated accounts, cascades, own Redis snapshots and isolated processes removed'
            report['finishedAt'] = datetime.now(UTC).isoformat()
            report['status'] = 'failed' if report.get('setupError') or any(row['status'] != 'passed' for row in report['cases']) else 'passed'
            (args.output_dir/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'caseCount': len(report['cases']), 'output': str(args.output_dir)}, ensure_ascii=False), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', choices=('edge', 'chrome'), default='edge')
    parser.add_argument('--output-dir', type=Path, default=ROOT.parent/'docs/acceptance/metrics_browser_20261027')
    raise SystemExit(asyncio.run(run(parser.parse_args())))
