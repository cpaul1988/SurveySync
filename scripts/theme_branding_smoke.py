"""Exercise theme-only co-branding on the actual application, including switches.

No mocked image, theme, or release-note responses. Test data uses temporary
configuration folders and is never written into a user's existing project.
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
import urllib.request

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'ui-evidence'
BASE = 'http://127.0.0.1:18768'
RELEASE = '9.4.0-beta.4'
CLIENT_THEMES = ('edsi', 'edsidark', 'edsilight')
NORMAL_THEMES = ('classic', 'slate', 'midnight', 'lightpro', 'contrast', 'carbon',
                 'obsidian', 'teal', 'violet', 'graphite', 'frost', 'arctic', 'sandstone')
MODULES = ('Home', 'ControlSync', 'UtilitySync', 'TopoSync', 'COGOSync',
           'BoundarySync', 'GISSync', 'ReportSync', 'QASync', 'CrewSync')


def request(path, data=None):
    encoded = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(BASE + path, data=encoded,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as result:
        return json.load(result)


def assert_brand(page, client):
    """Verify every visible product mark without transient :visible reindexing."""
    expect(page.locator('#productSplash')).to_be_hidden(timeout=15000)
    expect(page.locator('#startupSplash')).to_be_hidden(timeout=15000)
    # nth() locators filtered by :visible can change identity while a splash fades.
    # Enumerate stable DOM positions, then inspect visibility individually.
    marks = page.locator('[data-ss-brand]')
    visible_clients = 0
    visible_marks = 0
    for mark in marks.all():
        if not mark.is_visible():
            continue
        visible_marks += 1
        globe = mark.locator('> .ss-brand-globe')
        expect(globe).to_be_visible()
        expect(globe).to_have_attribute('src', '/surveysync-static/surveysync_globe.svg')
        assert globe.evaluate('(el)=>getComputedStyle(el).filter') == 'none'
        expect(mark.locator('> .ss-client-logo')).to_have_count(1)
        edsi = mark.locator('> .ss-client-logo')
        if client:
            expect(edsi).to_be_visible()
            edsi.evaluate('(img)=>img.decode()')
            box, parent = edsi.bounding_box(), mark.bounding_box()
            assert box['width'] > 0
            assert box['x'] + box['width'] <= parent['x'] + parent['width'] + 1
            visible_clients += 1
        else:
            expect(edsi).to_be_hidden()
        globe.evaluate('(img)=>img.decode()')
    assert visible_marks >= 2
    assert page.locator('img[src*="edsi"]:visible').count() == visible_clients
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def choose_theme(page, key, fieldbook=False):
    # Real Options controls invoke the production theme handler.
    expect(page.locator('#productSplash')).to_be_hidden(timeout=15000)
    if fieldbook:
        page.evaluate("switchTab('options')")
        page.locator(f'[data-theme-choice="{key}"]').click()
    else:
        page.evaluate("switchView('settings')")
        page.locator('#globalTheme').select_option(key)
    expect(page.locator('html')).to_have_attribute('data-product-theme', key)
    assert_brand(page, key in CLIENT_THEMES)
    for _ in range(50):
        if request('/api/v9/config/ui')['theme'] == key:
            return
        time.sleep(.1)
    raise AssertionError('Theme preference did not persist')


def main():
    OUT.mkdir(exist_ok=True)
    result = {'release': RELEASE, 'checks': [], 'result': 'FAIL'}
    with tempfile.TemporaryDirectory(prefix='surveysync-brand-') as tmp:
        env = dict(os.environ, SURVEYSYNC_CONFIG_ROOT=tmp + '/config',
                   SURVEYSYNC_FIELD_ROOT=tmp + '/field')
        with (OUT / 'theme-branding-server.log').open('w', encoding='utf-8') as log:
            server = subprocess.Popen([sys.executable, '-m', 'uvicorn',
                'fieldbook_sync.app:app', '--host', '127.0.0.1', '--port', '18768'],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    try:
                        request('/api/v9/release-notes')
                        break
                    except Exception:
                        if server.poll() is not None:
                            raise RuntimeError('Branding server failed; see its log')
                        time.sleep(.2)
                else:
                    raise RuntimeError('Branding server timed out')
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=os.getenv('SURVEYSYNC_BROWSER_EXECUTABLE') or None)
                    context = browser.new_context(viewport={'width': 1488, 'height': 940})
                    # Do not access localStorage in about:blank or sandboxed frames.
                    context.add_init_script(f"if(window===window.top&&location.origin==='{BASE}'){{localStorage.setItem('surveysync-release-notes-seen-v2','{RELEASE}')}}")
                    errors = []
                    context.on('page', lambda page: page.on('pageerror', lambda error: errors.append(str(error))))
                    page = context.new_page()
                    try:
                        page.goto(BASE, wait_until='domcontentloaded')
                        expect(page.locator('#whatsNewVersion')).to_have_text('v' + RELEASE)
                        expect(page.locator('#productSplash')).to_be_hidden()
                        expect(page.locator('html')).to_have_attribute('data-product-theme', 'classic')
                        assert_brand(page, False)
                        result['checks'].append('Fresh configuration is globe-only')
                        for fieldbook in (False, True):
                            page.goto(BASE + ('/fieldbook' if fieldbook else '/'), wait_until='domcontentloaded')
                            if not fieldbook:
                                expect(page.locator('#productSplash')).to_be_hidden()
                            for key in NORMAL_THEMES:
                                choose_theme(page, 'edsi', fieldbook)
                                choose_theme(page, key, fieldbook)
                            for key in CLIENT_THEMES:
                                choose_theme(page, key, fieldbook)
                                page.reload(wait_until='domcontentloaded')
                                expect(page.locator('html')).to_have_attribute('data-product-theme', key)
                                assert_brand(page, True)
                            result['checks'].append(('FieldBookSync' if fieldbook else 'Home') +
                                ': all 16 themes, EDSI-to-normal removal, and persisted client themes')

                        page.goto(BASE, wait_until='domcontentloaded')
                        expect(page.locator('#whatsNewVersion')).to_have_text('v' + RELEASE)
                        field = context.new_page()
                        field.goto(BASE + '/fieldbook', wait_until='domcontentloaded')
                        expect(field.locator('html')).to_have_attribute('data-product-theme', 'edsilight')
                        choose_theme(page, 'classic')
                        expect(field.locator('html')).to_have_attribute('data-product-theme', 'classic')
                        assert_brand(field, False)
                        choose_theme(field, 'edsi', True)
                        expect(page.locator('html')).to_have_attribute('data-product-theme', 'edsi')
                        assert_brand(page, True)
                        field.close()
                        result['checks'].append('Theme branding synchronizes between both open shells')

                        for key in ('edsi', 'classic'):
                            choose_theme(page, key)
                            for module in MODULES:
                                page.goto(BASE + '/?module=' + module, wait_until='domcontentloaded')
                                expect(page.locator('#whatsNewVersion')).to_have_text('v' + RELEASE)
                                expect(page.locator('html')).to_have_attribute('data-product-theme', key)
                                expect(page.locator('#productSplash')).to_be_hidden()
                                assert_brand(page, key in CLIENT_THEMES)
                            page.evaluate('openAboutSurveySync()')
                            assert_brand(page, key in CLIENT_THEMES)
                            page.evaluate('closeModalShell();openReleaseNotes(false)')
                            assert_brand(page, key in CLIENT_THEMES)
                            page.evaluate("applyProductTheme('edsi'===document.documentElement.dataset.productTheme?'classic':'edsi',false)")
                            assert_brand(page, key not in CLIENT_THEMES)
                            page.evaluate('closeModalShell()')
                        result['checks'].append('All module routes, About and release notes obey the same rule live')

                        for key in ('classic', 'edsi'):
                            for mode in ('dark', 'light'):
                                request('/api/v9/config/ui', {'appearance': mode, 'theme': key, 'accent': 'default'})
                                for route, name in (('/', 'Home'), ('/fieldbook', 'FieldBookSync')):
                                    page.goto(BASE + route, wait_until='domcontentloaded')
                                    expect(page.locator('html')).to_have_attribute('data-theme', mode)
                                    expect(page.locator('html')).to_have_attribute('data-product-theme', key)
                                    if route == '/':
                                        expect(page.locator('#productSplash')).to_be_hidden()
                                    assert_brand(page, key in CLIENT_THEMES)
                                    page.screenshot(path=str(OUT / f'Brand-{name}-{key}-{mode}.png'))
                        for width in (1024, 1366, 900):
                            page.set_viewport_size({'width': width, 'height': 768})
                            for route in ('/', '/fieldbook'):
                                page.goto(BASE + route, wait_until='domcontentloaded')
                                if route == '/':
                                    expect(page.locator('#productSplash')).to_be_hidden()
                                assert_brand(page, True)
                        result['checks'].append('Co-branding light/dark previews and 900/1024/1366px layouts')
                        assert not errors, errors
                        result['result'] = 'PASS'
                    except Exception:
                        result['exception'] = traceback.format_exc()
                        result['url'] = page.url
                        result['theme'] = page.locator('html').get_attribute('data-product-theme')
                        page.screenshot(path=str(OUT / 'theme-branding-failure.png'))
                        raise
                    finally:
                        result['errors'] = errors
                        (OUT / 'theme-branding-results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
                        browser.close()
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
