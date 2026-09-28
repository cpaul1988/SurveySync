"""Exercise real controls for the three broken commands and explicit level layout."""
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

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'repair-evidence'
BASE='http://127.0.0.1:18769'


def main():
    OUT.mkdir(exist_ok=True)
    report={'status':'FAIL','checks':[]}
    with tempfile.TemporaryDirectory() as temp, (OUT/'ui-server.log').open('w', encoding='utf-8') as log:
        server=subprocess.Popen([sys.executable,'-m','uvicorn','fieldbook_sync.app:app','--host','127.0.0.1','--port','18769'],cwd=ROOT,env=dict(os.environ,SURVEYSYNC_CONFIG_ROOT=temp+'/config',SURVEYSYNC_FIELD_ROOT=temp+'/field'),stdout=log,stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(BASE+'/api/v9/release-notes',timeout=2): pass
                    break
                except Exception: time.sleep(.2)
            else: raise TimeoutError('UI server failed to start')
            with sync_playwright() as pw:
                browser=pw.chromium.launch()
                page=browser.new_page(viewport={'width':1488,'height':940})
                errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.route('**/api/v9/update/check',lambda route:route.fulfill(json={'update_available':False,'version':'9.4.2'}))
                try:
                    page.goto(BASE,wait_until='domcontentloaded')
                    expect(page.locator('#productSplash')).to_be_hidden(timeout=15000)
                    expect(page.locator('#releaseDone')).to_be_visible()
                    page.locator('#releaseDone').click()
                    for menu,command,view in [('dataMenu','project-data','projectData'),('dataMenu','data-inspector','dataInspector'),('helpMenu','support-center','supportCenter')]:
                        page.locator(f'[data-menu="{menu}"]').click()
                        page.locator(f'#{menu} [data-command="{command}"]').click()
                        expect(page.locator('body')).to_have_attribute('data-active-view',view)
                        report['checks'].append(command)
                    for command,view in [('project-data','projectData'),('data-inspector','dataInspector'),('project-qa','qa')]:
                        page.locator(f'.quick-actions [data-command="{command}"]').click()
                        expect(page.locator('body')).to_have_attribute('data-active-view',view)
                    page.locator('.module-tab[data-module="ControlSync"]').click()
                    page.locator('#moduleNav .module-nav-btn').filter(has_text='Level').first.click()
                    expect(page.locator('#levelRowLayout')).to_be_visible()
                    page.locator('#levelRowLayout').select_option('station_rows')
                    expect(page.locator('#levelRowLayout')).to_have_value('station_rows')
                    page.screenshot(path=str(OUT/'level-layout-controls.png'))
                    assert not errors, errors
                    report.update(status='PASS',errors=errors)
                except Exception:
                    page.screenshot(path=str(OUT/'ui-failure.png'))
                    report['errors']=errors
                    raise
                finally:
                    browser.close()
        finally:
            server.terminate()
            server.wait(timeout=10)
            (OUT/'ui-results.json').write_text(json.dumps(report,indent=2), encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
