"""Real linked Visual QA controls against a disposable local project; no cloud data."""
from __future__ import annotations
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
from zipfile import ZipFile
from playwright.sync_api import expect, sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'remaining-evidence'
BASE='http://127.0.0.1:18773'


def api(path,data=None):
    request=urllib.request.Request(BASE+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)


def main():
    OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='visual-qa-') as tmp, (OUT/'visual-qa-server.log').open('w',encoding='utf-8') as log:
        root=Path(tmp)
        source=root/'points.csv'
        source.write_text('PointID,Northing,Easting,Elevation,Description\n001A,1000,2000,10,ROAD\n002,1005,2005,14,ROAD\n003,1010,2010,,TREE\n004,1015,2015,11,ROAD\n',encoding='utf-8')
        original=source.read_bytes()
        server=subprocess.Popen([sys.executable,'-m','uvicorn','fieldbook_sync.app:app','--host','127.0.0.1','--port','18773'],cwd=ROOT,env=dict(os.environ,SURVEYSYNC_CONFIG_ROOT=str(root/'config'),SURVEYSYNC_FIELD_ROOT=str(root/'field')),stdout=log,stderr=subprocess.STDOUT)
        report={'status':'FAIL','checks':[]}
        try:
            for _ in range(100):
                try:api('/api/v9/status');break
                except OSError:time.sleep(.2)
            else:raise TimeoutError('Visual QA server unavailable')
            api('/api/v9/project/create',{'parent_folder':str(root/'projects'),'name':'Visual QA Acceptance','crs':'EPSG:2278','horizontal_units':'us_survey_feet','vertical_units':'us_survey_feet'})
            api('/api/v9/points/import',{'file_path':str(source)})
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path=os.environ.get('SURVEYSYNC_TEST_CHROMIUM') or None,args=['--no-sandbox'] if sys.platform!='win32' else [])
                context=browser.new_context(viewport={'width':1488,'height':1000},accept_downloads=True)
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.route('**/api/v9/update/check',lambda r:r.fulfill(json={'update_available':False}))
                page.goto(BASE,wait_until='domcontentloaded')
                expect(page.locator('#productSplash')).to_be_hidden(timeout=20000)
                expect(page.locator('#releaseDone')).to_be_visible();page.locator('#releaseDone').click()
                page.locator('.module-tab[data-module="QASync"]').click()
                page.locator('#moduleNav .module-nav-btn').filter(has_text='Visual Survey QA').click()
                expect(page.locator('#vqControls')).to_be_enabled(timeout=15000)
                expect(page.locator('#vqPoints tr')).to_have_count(4)
                expect(page.locator('#vqExport')).to_be_disabled()
                page.locator('#vqIssues [data-issue]').filter(has_text='elevation jump').first.click()
                expect(page.locator('#vqEvidence')).to_contain_text('screening flag')
                expect(page.locator('#vqPoints .vq-selected')).to_have_count(1)
                page.locator('#vqSearch').fill('001A')
                expect(page.locator('#vqPoints tr')).to_have_count(1)
                page.locator('#vqPoints button').click()
                page.locator('#vqOriginal').click()
                expect(page.locator('#vqOriginalResult')).to_contain_text('"elevation": 10')
                page.locator('#vqSearch').fill('')
                page.locator('#vqReason').fill('Independent field notes confirm the selected anomaly.')
                page.locator('#vqDecision').select_option('confirmed')
                page.locator('#vqSave').click()
                expect(page.locator('#vqMessage')).to_contain_text('review saved')
                page.locator('#vqRefresh').click()
                expect(page.locator('#vqControls')).to_be_enabled()
                expect(page.locator('#vqIssues')).to_contain_text('confirmed')
                report['checks'].append('Actual issue/table selection, original source observation read, and review persistence')
                page.locator('#vqSearch').fill('002')
                page.locator('#vqPoints button').click()
                page.locator('#vqOffset').fill('-4')
                page.locator('#vqAdd').click()
                expect(page.locator('#vqChanges')).to_contain_text('14 → 10')
                page.locator('#vqReason').fill('Field notes verify a four-foot rod offset at 002.')
                page.locator('#vqExport').click()
                expect(page.locator('#vqMessage')).to_contain_text('confirm')
                page.locator('#vqConfirm').check()
                with page.expect_download() as downloaded:page.locator('#vqExport').click()
                path=Path(downloaded.value.path())
                with ZipFile(io.BytesIO(path.read_bytes())) as z:
                    evidence=json.loads(z.read('review_evidence.json'))
                    assert next(p for p in evidence['corrected_points'] if p['point_id']=='002')['elevation']==10
                    assert evidence['changes'][0]['original']['elevation']==14
                expect(page.locator('#vqControls')).to_be_enabled()
                page.locator('#vqReportTitle').fill('BRT QA Review Acceptance')
                page.locator('#vqPreparedBy').fill('Independent reviewer')
                with page.expect_download() as report_download:page.locator('#vqReport').click()
                with ZipFile(Path(report_download.value.path())) as package:
                    evidence=json.loads(package.read('review_evidence.json'))
                    assert len(evidence['points'])==4  # Search still filters to 002; report is full scope.
                    assert evidence['correction_exports'][0]['changes'][0]['corrected_elevation']==10
                    assert any((i.get('review') or {}).get('decision')=='confirmed' for i in evidence['issues'])
                    assert b'001A' in package.read('findings.csv')
                    assert package.read('QA_Review.pdf').startswith(b'%PDF')
                    (OUT/'qa-review-sample.pdf').write_bytes(package.read('QA_Review.pdf'))
                report['checks'].append('Actual report button downloads PDF/CSV package with full-scope saved reviews and correction history')
                assert source.read_bytes()==original
                expect(page.locator('#vqControls')).to_be_enabled()
                page.locator('#vqSearch').fill('')
                page.locator('#vqKind').select_option('missing_z')
                expect(page.locator('#vqPoints tr')).to_have_count(1)
                expect(page.locator('#vqPoints')).to_contain_text('003')
                page.locator('#vqKind').select_option('')
                # In the full extent the last point is upper-right; exercise actual canvas picking.
                page.locator('#vqFit').click()
                box=page.locator('#vqCanvas').bounding_box();assert box
                # Equal x/y span: scale is constrained by height (360 - 70) / 15.
                page.locator('#vqCanvas').click(position={'x':box['width']/2+min((box['width']-70)/15,290/15)*7.5,'y':180-min((box['width']-70)/15,290/15)*7.5})
                expect(page.locator('#vqEvidence')).to_contain_text('Point 004')
                report['checks'].append('Canvas pick, issue filter, confirmation gate, downloaded corrected ZIP and original-byte preservation')
                # Real workspace controls: distinct UUIDs for duplicate names and source visibility.
                second_source=root/'duplicate.csv'
                second_source.write_text('PointID,Northing,Easting,Elevation,Description\n001A,1007,2003,10,DUPLICATE\n',encoding='utf-8')
                api('/api/v9/points/import',{'file_path':str(second_source)})
                page.locator('#vqRefresh').click()
                expect(page.locator('#vqPoints tr')).to_have_count(5)
                page.locator('#vqSearch').fill('001A')
                expect(page.locator('#vqPoints tr')).to_have_count(2)
                boxes=page.locator('#vqPoints [data-select-record]')
                assert len(set(boxes.evaluate_all('(els)=>els.map(e=>e.dataset.selectRecord)')))==2
                boxes.nth(0).check();boxes.nth(1).check()
                expect(boxes.nth(1)).to_be_focused()
                boxes.nth(1).press('Space')
                expect(page.locator('#vqSelectedCount')).to_contain_text('1 selected')
                expect(boxes.nth(1)).to_be_focused()
                boxes.nth(1).press('Space')
                expect(boxes.nth(1)).to_be_focused()
                expect(page.locator('#vqSelectedCount')).to_contain_text('2 selected')
                expect(page.locator('#vqPoints .vq-selected')).to_have_count(2)
                page.locator('#vqScope').select_option('selected')
                expect(page.locator('#vqPoints tr')).to_have_count(2)
                page.locator('#vqSources [data-source]').last.uncheck()
                expect(page.locator('#vqPoints tr')).to_have_count(1)
                expect(page.locator('#vqSelectedCount')).to_contain_text('2 selected')
                page.locator('#vqSources [data-source]').last.check()
                page.locator('#vqScope').select_option('all');page.locator('#vqSearch').fill('')
                page.locator('#vqFit').click();page.locator('#vqTool').select_option('box')
                canvas=page.locator('#vqCanvas');canvas.scroll_into_view_if_needed()
                box=canvas.bounding_box();assert box
                page.mouse.move(box['x']+2,box['y']+2);page.mouse.down()
                page.mouse.move(box['x']+box['width']-2,box['y']+box['height']-2,steps=5);page.mouse.up()
                expect(page.locator('#vqSelectedCount')).to_contain_text('5 selected')
                page.locator('#vqScope').select_option('selected')
                expect(page.locator('#vqPoints tr')).to_have_count(5)
                page.locator('#vqColumns summary').click()
                page.locator('#vqColumns [data-column="5"]').uncheck()
                assert page.locator('#vqPoints tr').first.locator('td').nth(5).is_hidden()
                page.locator('#vqScope').select_option('visible');page.locator('#vqTool').select_option('pan')
                page.locator('#vqIn').click()
                assert 0 < page.locator('#vqPoints tr').count() < 5
                # Fit selected restores all selected visible sources, without table feedback refitting.
                page.locator('#vqFitSelected').click()
                expect(page.locator('#vqPoints tr')).to_have_count(5)
                page.locator('#vqScope').select_option('all');page.locator('#vqClearSelection').click()
                expect(page.locator('#vqSelectedCount')).to_contain_text('0 selected')
                page.locator('#vqLayout').select_option('topo')
                handle=page.locator('[data-workspace-size="left"]');handle.focus();handle.press('ArrowRight')
                expect(handle).to_have_attribute('aria-valuenow','250')
                handle.scroll_into_view_if_needed();h=handle.bounding_box();assert h
                page.mouse.move(h['x']+h['width']/2,h['y']+20);page.mouse.down()
                page.mouse.move(h['x']+h['width']/2+30,h['y']+20,steps=4);page.mouse.up()
                expect(handle).to_have_attribute('aria-valuenow','280')
                page.locator('#vqSaveLayout').click()
                expect(page.locator('#vqMessage')).to_contain_text('layout saved')
                page.reload(wait_until='domcontentloaded')
                expect(page.locator('#productSplash')).to_be_hidden(timeout=20000)
                page.locator('.module-tab[data-module="QASync"]').click()
                page.locator('#moduleNav .module-nav-btn').filter(has_text='Visual Survey QA').click()
                expect(page.locator('#vqControls')).to_be_enabled()
                expect(page.locator('[data-workspace-size="left"]')).to_have_attribute('aria-valuenow','280')
                expect(page.locator('#vqSelectedCount')).to_contain_text('0 selected')
                page.locator('#vqIntegrations').locator('..').locator('summary').click()
                expect(page.locator('#vqIntegrations')).to_contain_text('planned')
                report['checks'].append('Duplicate UUID multi-selection, source visibility, no-Ctrl box select, columns, viewport scope, pointer/keyboard splitters and persisted layout')
                for mode in ('light','dark'):
                    api('/api/v9/config/ui',{'appearance':mode,'theme':'carbon','accent':'default'})
                    page.reload(wait_until='domcontentloaded')
                    expect(page.locator('#productSplash')).to_be_hidden(timeout=20000)
                    page.locator('.module-tab[data-module="QASync"]').click()
                    page.locator('#moduleNav .module-nav-btn').filter(has_text='Visual Survey QA').click()
                    expect(page.locator('#vqControls')).to_be_enabled()
                    page.locator('#vqIssues [data-issue]').first.click()
                    page.locator('.survey-workspace-toolbar').scroll_into_view_if_needed()
                    page.screenshot(path=str(OUT/f'visual-qa-{mode}.png'),full_page=True)
                    assert page.locator('.survey-workspace-toolbar').evaluate('(e)=>e.scrollHeight<=e.clientHeight+1')
                    page.locator('#vqEvidence').scroll_into_view_if_needed()
                    page.screenshot(path=str(OUT/f'visual-qa-evidence-{mode}.png'),full_page=True)
                page.set_viewport_size({'width':900,'height':900})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth+1')
                page.screenshot(path=str(OUT/'visual-qa-narrow.png'),full_page=True)
                page.locator('#vqReason').fill('Stale project should reject this decision.')
                api('/api/v9/project/create',{'parent_folder':str(root/'projects'),'name':'Second Project','crs':'EPSG:2278'})
                page.locator('#vqSave').click()
                expect(page.locator('#vqMessage')).to_contain_text('Project changed')
                expect(page.locator('#vqControls')).to_have_attribute('disabled', '')
                expect(page.locator('#vqSave')).to_be_disabled()
                expect(page.locator('#vqAdd')).to_be_disabled()
                expect(page.locator('#vqPoints tr')).to_have_count(0)
                report['checks'].append('Light/dark/narrow views and stale-project refusal')
                assert not errors,errors
                browser.close()
            report['status']='PASS'
        finally:
            (OUT/'visual-qa-acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            server.terminate()
            try:server.wait(timeout=20)
            except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
