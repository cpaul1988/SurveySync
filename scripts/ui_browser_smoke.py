"""Real local-server Chromium UI checks. No mock release notes or static assets."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'ui-evidence'
BASE = 'http://127.0.0.1:18767'
SEEN = 'surveysync-release-notes-seen-v2'
RELEASE = '9.4.0-beta.3'
MODULES = ['Home', 'FieldBookSync', 'ControlSync', 'UtilitySync', 'TopoSync',
           'COGOSync', 'BoundarySync', 'GISSync', 'ReportSync', 'QASync', 'CrewSync']


def request(path, data=None):
    raw = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(BASE + path, data=raw,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as result:
        return json.load(result)


def image_check(page):
    # Observe actual dismissal, rather than hiding the splash just for the test.
    expect(page.locator('#productSplash')).to_be_hidden(timeout=15000)
    page.wait_for_function('''() => [...document.images].filter(i=>i.getClientRects().length)
      .every(i=>i.complete && i.naturalWidth>0)''', timeout=10000)
    assert page.locator('.module-tab img').count() == 11


def main():
    OUT.mkdir(exist_ok=True)
    report = {'release': RELEASE, 'screens': [], 'checks': []}
    with tempfile.TemporaryDirectory(prefix='surveysync-ui-') as tmp:
        env = dict(os.environ, SURVEYSYNC_CONFIG_ROOT=tmp + '/config',
                   SURVEYSYNC_FIELD_ROOT=tmp + '/field', PYTHONUNBUFFERED='1')
        with (OUT / 'server.log').open('w', encoding='utf-8') as log:
            server = subprocess.Popen([sys.executable, '-m', 'uvicorn',
                'fieldbook_sync.app:app', '--host', '127.0.0.1', '--port', '18767'],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    try:
                        assert request('/api/v9/release-notes')['release_id'] == RELEASE
                        break
                    except Exception:
                        if server.poll() is not None:
                            raise RuntimeError('UI server exited; see server.log')
                        time.sleep(.2)
                else:
                    raise RuntimeError('UI server did not become ready')
                with sync_playwright() as pw:
                    browser = pw.chromium.launch()
                    context = browser.new_context(viewport={'width': 1488, 'height': 940})
                    context.tracing.start(screenshots=True, snapshots=True)
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.route('**/api/v9/update/check', lambda route: route.fulfill(
                        json={'update_available': False, 'current_version': '9.4.0', 'channel': 'beta'}))
                    try:
                        for mode in ('dark', 'light'):
                            request('/api/v9/config/ui', {'appearance': mode, 'theme': 'edsi', 'accent': 'default'})
                            page.goto(BASE, wait_until='domcontentloaded')
                            if mode == 'dark':
                                expect(page.locator('#releaseDone')).to_be_visible(timeout=15000)
                                assert page.evaluate('(key)=>localStorage.getItem(key)', SEEN) is None
                                image_check(page)
                                page.screenshot(path=str(OUT / 'release-notes-dark.png'))
                                page.locator('#modalClose').click()
                                page.reload(wait_until='domcontentloaded')
                                expect(page.locator('#releaseDone')).to_be_visible()
                                page.locator('#releaseDone').click()
                                assert page.evaluate('(key)=>localStorage.getItem(key)', SEEN) == RELEASE
                                report['checks'].append('Notes shown; close leaves unread; Continue acknowledges')
                            else:
                                expect(page.locator('#modal')).to_have_class('modal hidden')
                            for module in MODULES:
                                page.goto(BASE + ('/fieldbook' if module == 'FieldBookSync' else '/?module=' + module),
                                          wait_until='domcontentloaded')
                                expect(page.locator('html')).to_have_attribute('data-theme', mode)
                                expect(page.locator('html')).to_have_attribute('data-product-theme', 'edsi')
                                if module != 'FieldBookSync':
                                    expect(page.locator('#whatsNewVersion')).to_have_text('v' + RELEASE)
                                    expect(page.locator('#moduleNav .module-nav-btn').first).to_be_visible()
                                image_check(page)
                                actual = page.evaluate("""() => ({font:getComputedStyle(document.body).fontSize,
                                    panel:getComputedStyle(document.documentElement).getPropertyValue('--panel').trim()})""")
                                assert actual['font'] == '14px', (module, actual)
                                assert actual['panel'] in ('#1b1f24', '#fff'), (module, actual)
                                filename = module + '-' + mode + '.png'
                                page.screenshot(path=str(OUT / filename))
                                report['screens'].append(filename)
                            page.goto(BASE, wait_until='domcontentloaded')
                            page.locator('#openReleaseNotes').click()
                            expect(page.locator('#releaseDone')).to_be_visible()
                            page.locator('#releaseDone').click()
                        page.evaluate('(key)=>localStorage.removeItem(key)', SEEN)
                        page.route('**/api/v9/status', lambda route: route.fulfill(status=503, json={'detail': 'Injected status failure'}))
                        page.goto(BASE, wait_until='domcontentloaded')
                        expect(page.locator('#releaseDone')).to_be_visible()
                        page.locator('#releaseDone').click()
                        page.unroute('**/api/v9/status')
                        report['checks'].append('Release notes remain available when status API fails')
                        page.route('**/api/v9/release-notes', lambda route: route.fulfill(status=503, json={'detail': 'Injected notes failure'}))
                        page.goto(BASE, wait_until='domcontentloaded')
                        expect(page.locator('#retryReleaseNotes')).to_be_attached()
                        page.unroute('**/api/v9/release-notes')
                        page.locator('#retryReleaseNotes').click()
                        expect(page.locator('#whatsNewVersion')).to_have_text('v' + RELEASE)
                        report['checks'].append('Failed notes offer a working retry')
                        for width in (1024, 1366):
                            page.set_viewport_size({'width': width, 'height': 768})
                            page.goto(BASE, wait_until='domcontentloaded')
                            image_check(page)
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                            page.screenshot(path=str(OUT / f'Home-{width}.png'))
                        assert not errors, errors
                        report['checks'].append('No uncaught JavaScript errors across 22 module/theme screens')
                        report['checks'].append('Actual startup splash dismisses before screenshots')
                        report['result'] = 'PASS'
                    except Exception:
                        page.screenshot(path=str(OUT / 'failure.png'))
                        report['result'] = 'FAIL'
                        report['errors'] = errors
                        raise
                    finally:
                        (OUT / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
                        context.tracing.stop(path=str(OUT / 'trace.zip'))
                        browser.close()
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
