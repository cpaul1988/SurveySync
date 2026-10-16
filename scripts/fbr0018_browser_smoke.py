"""Real-server browser acceptance for the persistent FieldBookSync workspace.

No survey engine or project-context endpoints are mocked. External update and
feedback configuration checks are isolated so QA never contacts the live Intake.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'ui-evidence' / 'fbr0018'
BASE = 'http://127.0.0.1:18770'


def request(path, data=None, token=None):
    raw = None if data is None else json.dumps(data).encode()
    headers = {'Content-Type':'application/json'}
    if token: headers['X-SurveySync-Project'] = token
    req = urllib.request.Request(BASE + path, data=raw, headers=headers)
    for attempt in range(30):
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            body = error.read().decode()
            if error.code != 409 or not ('busy' in body or 'still finishing' in body) or attempt == 29:
                raise AssertionError(f'{path}: {error.code} {body}') from error
            time.sleep(.2)


def wait_workspace(page):
    expect(page.locator('#fieldbookFrame')).to_be_visible(timeout=30000)
    expect(page.locator('#fieldbookLoadStatus')).to_be_hidden(timeout=45000)
    return page.frame_locator('#fieldbookFrame')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'release':(ROOT / 'RELEASE_ID.txt').read_text().strip(), 'checks':[]}
    with tempfile.TemporaryDirectory(prefix='ss-fbr0018-') as tmp:
        env = dict(os.environ, SURVEYSYNC_CONFIG_ROOT=tmp+'/config', SURVEYSYNC_FIELD_ROOT=tmp+'/field')
        with (OUT/'server.log').open('w', encoding='utf-8') as log:
            server = subprocess.Popen([sys.executable,'-m','uvicorn','fieldbook_sync.app:app',
                '--host','127.0.0.1','--port','18770'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    try:
                        request('/api/v9/fieldbook/context')
                        break
                    except (OSError, AssertionError):
                        if server.poll() is not None: raise RuntimeError('UI server exited; inspect server.log')
                        time.sleep(.2)
                else: raise RuntimeError('UI server did not start')
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=os.getenv('SURVEYSYNC_BROWSER_EXECUTABLE') or None)
                    context = browser.new_context(viewport={'width':1488,'height':940})
                    context.tracing.start(screenshots=True, snapshots=True)
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.route('**/api/v9/update/check', lambda route: route.fulfill(json={'update_available':False}))
                    page.route('**/api/feedback/config', lambda route: route.fulfill(json={'submit_url':'','intake_url':''}))
                    try:
                        page.goto(BASE,wait_until='domcontentloaded')
                        expect(page.locator('#releaseDone')).to_be_visible(timeout=20000)
                        page.locator('#releaseDone').click()
                        page.evaluate('openGlobalFeedbackWizard()')
                        child = wait_workspace(page)
                        expect(child.locator('#modalTitle')).to_have_text('SurveySync Feedback')
                        expect(child.locator('.feedback-type').first).to_be_visible()
                        assert request('/api/v9/fieldbook/context')['project_id'] == ''
                        child.locator('#modalClose').click()
                        report['checks'].append('Feedback wizard opens without a project in the shared shell')

                        project = request('/api/v9/project/create', {'parent_folder':tmp+'/projects','name':'test'})
                        page.evaluate('refresh()')
                        child = wait_workspace(page)
                        expect(page.locator('#projectPill')).to_have_text('test')
                        expect(child.locator('#sideProjectName')).to_have_text('test')
                        expect(child.locator('.sidebar')).to_be_hidden()
                        expect(child.locator('.desktop-menubar')).to_be_hidden()
                        expect(page.locator('.module-sidebar')).to_be_visible()
                        actual = request('/api/v9/fieldbook/context')
                        assert actual['bound'] and actual['project_id'] == project['project_id']
                        assert Path(actual['fieldbook_root']) == Path(project['root'])/'Modules'/'FieldBookSync'
                        report['checks'].append('Shared sidebar and underlying project ID/name/storage all match test')

                        frame = page.locator('#fieldbookFrame').element_handle().content_frame()
                        frame.evaluate('window.fbrRetentionSentinel = {value:"kept"}')
                        top_origin = page.evaluate('performance.timeOrigin')
                        frame_origin = frame.evaluate('performance.timeOrigin')
                        child.locator('#surveyFiles').set_input_files({'name':'pending.txt','mimeType':'text/plain','buffer':b'pending selection'})
                        page.locator('#moduleNav [data-view="fieldbook:review"]').click()
                        expect(child.locator('#tab-review')).to_be_visible()
                        options = child.locator('#reviewFilter option').evaluate_all('(xs)=>xs.map(x=>x.value)')
                        child.locator('#reviewFilter').select_option(options[-1])
                        for _ in range(5):
                            page.locator('[data-module="ControlSync"]').click()
                            page.locator('[data-module="FieldBookSync"]').click()
                            expect(child.locator('#tab-review')).to_be_visible()
                        assert page.evaluate('performance.timeOrigin') == top_origin
                        assert frame.evaluate('performance.timeOrigin') == frame_origin
                        assert frame.evaluate('fbrRetentionSentinel.value') == 'kept'
                        assert child.locator('#reviewFilter').input_value() == options[-1]
                        assert child.locator('#surveyFiles').evaluate('(x)=>x.files[0].name') == 'pending.txt'
                        report['checks'].append('Ten module switches preserve document, review filter and selected import file')
                        child.locator('#surveyFiles').set_input_files([])

                        for theme,mode in [('edsi','dark'),('edsi','light'),('classic','dark'),('classic','light')]:
                            page.evaluate('([theme,mode])=>{applyProductTheme(theme);applyAppearance(mode)}',[theme,mode])
                            expect(child.locator('html')).to_have_attribute('data-product-theme',theme)
                            expect(child.locator('html')).to_have_attribute('data-theme',mode)
                            page.wait_for_function('''() => {
                              const root=document.documentElement, child=document.getElementById('fieldbookFrame').contentDocument.documentElement;
                              return ['--panel','--bg','--text','--accent'].every(name =>
                                getComputedStyle(root).getPropertyValue(name).trim()===getComputedStyle(child).getPropertyValue(name).trim());
                            }''')
                            page.screenshot(path=str(OUT/f'FieldBook-{theme}-{mode}.png'))
                        report['checks'].append('FieldBook content inherits actual shared colors in four theme/appearance combinations')

                        page.evaluate('window.fbrPickerCalls=0;window.pywebview={api:{choose_save_file:async()=>{window.fbrPickerCalls++;return null}}}')
                        frame.evaluate('saveProjectAs()')
                        assert page.evaluate('window.fbrPickerCalls') == 1
                        report['checks'].append('Embedded native save picker delegates to the main-window bridge')

                        # Cancellation retains the live view. The next accepted switch disposes
                        # only that project view and the backend rejects its captured token.
                        child.locator('#resultSearch').press_sequentially('pending edit')
                        page.once('dialog', lambda dialog: dialog.dismiss())
                        cancelled = page.evaluate('''async()=>{try{await jpost('/api/v9/project/create',
                          {parent_folder:statusData.project.root+'/..',name:'cancelled'});return false}catch(e){return e.message.includes('cancelled')}}''')
                        assert cancelled
                        assert request('/api/v9/status')['project']['name'] == 'test'
                        frame.evaluate('document.activeElement?.blur()')
                        other = request('/api/v9/project/create', {'parent_folder':tmp+'/projects','name':'second'})
                        page.evaluate('refresh()')
                        child = wait_workspace(page)
                        expect(page.locator('#projectPill')).to_have_text('second')
                        expect(child.locator('#sideProjectName')).to_have_text('second')
                        assert frame.is_detached()
                        assert request('/api/v9/fieldbook/context')['project_id'] == other['project_id']
                        try:
                            request('/api/project/download', token=actual['token'])
                            raise AssertionError('Stale download accepted')
                        except AssertionError as error:
                            assert '409' in str(error)
                        report['checks'].append('Cancelled changes retain data; accepted changes use a fresh view and reject stale downloads')

                        page.reload(wait_until='domcontentloaded')
                        child = wait_workspace(page)
                        expect(child.locator('#sideProjectName')).to_have_text('second')
                        # Backward-compatible direct links route through the same main shell.
                        page.goto(BASE+'/fieldbook?feedback=1',wait_until='domcontentloaded')
                        child = wait_workspace(page)
                        expect(page.locator('#moduleName')).to_have_text('FieldBookSync')
                        expect(child.locator('#modalTitle')).to_have_text('SurveySync Feedback')
                        report['checks'].append('Reload and legacy feedback deep links retain the authoritative project')
                        assert not errors, errors
                        report['result'] = 'PASS'
                    except Exception:
                        report['result'] = 'FAIL'; report['exception'] = traceback.format_exc()
                        page.screenshot(path=str(OUT/'failure.png'))
                        raise
                    finally:
                        report['errors'] = errors
                        (OUT/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
                        context.tracing.stop(path=str(OUT/'trace.zip'))
                        browser.close()
            finally:
                server.terminate()
                try: server.wait(timeout=10)
                except subprocess.TimeoutExpired: server.kill(); server.wait()
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
