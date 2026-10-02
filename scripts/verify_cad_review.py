"""Exercise real CAD upload/selection/closure/report controls against a disposable project."""
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
import ezdxf
from playwright.sync_api import expect, sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'remaining-evidence'
BASE='http://127.0.0.1:18779'


def api(path,data=None):
    req=urllib.request.Request(BASE+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=40) as response:return json.load(response)


def main():
    OUT.mkdir(exist_ok=True)
    report={'status':'FAIL','checks':[]}
    with tempfile.TemporaryDirectory(prefix='cad-qa-') as tmp,(OUT/'cad-server.log').open('w',encoding='utf-8') as log:
        root=Path(tmp);dxf=root/'survey.dxf';doc=ezdxf.new();doc.layers.new('Record');doc.layers.new('Details')
        m=doc.modelspace()
        m.add_line((2000,1000),(2010,1000),dxfattribs={'layer':'Record'})
        m.add_line((2010,1000),(2010,1010),dxfattribs={'layer':'Record'})
        m.add_line((2010,1010),(2000,1000.05),dxfattribs={'layer':'Record'})
        m.add_circle((2004,1004),1,dxfattribs={'layer':'Details'})
        m.add_text('Retained <survey>',dxfattribs={'insert':(2001,1008),'layer':'Details'})
        m.add_ray((2000,1000),(1,0));doc.saveas(dxf);original=dxf.read_bytes()
        source=root/'points.csv';source.write_text('PointID,Northing,Easting,Elevation,Description\n001A,1002,2002,10,CP\n',encoding='utf-8')
        server=subprocess.Popen([sys.executable,'-m','uvicorn','fieldbook_sync.app:app','--host','127.0.0.1','--port','18779'],cwd=ROOT,env=dict(os.environ,SURVEYSYNC_CONFIG_ROOT=str(root/'config'),SURVEYSYNC_FIELD_ROOT=str(root/'field')),stdout=log,stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                try:api('/api/v9/status');break
                except OSError:time.sleep(.2)
            else:raise TimeoutError('CAD server unavailable')
            api('/api/v9/project/create',{'parent_folder':str(root/'projects'),'name':'CAD Acceptance','crs':'EPSG:2278','horizontal_units':'us_survey_feet','vertical_units':'us_survey_feet'})
            api('/api/v9/points/import',{'file_path':str(source)})
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path=os.environ.get('SURVEYSYNC_TEST_CHROMIUM') or None,args=['--no-sandbox'] if sys.platform!='win32' else [])
                page=browser.new_page(viewport={'width':1600,'height':1100},accept_downloads=True)
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.route('**/api/v9/update/check',lambda r:r.fulfill(json={'update_available':False}))
                page.goto(BASE,wait_until='domcontentloaded');expect(page.locator('#productSplash')).to_be_hidden(timeout=20000)
                expect(page.locator('#releaseDone')).to_be_visible();page.locator('#releaseDone').click()
                page.locator('.module-tab[data-module="BoundarySync"]').click()
                page.locator('#moduleNav .module-nav-btn').filter(has_text='CAD Drawing').click()
                expect(page.locator('#cadImport')).to_be_enabled()
                page.locator('#cadFile').set_input_files(str(dxf));page.locator('#cadImport').click()
                expect(page.locator('#cadMessage')).to_contain_text('Choose units')
                page.locator('#cadUnits').select_option('us_survey_feet');page.locator('#cadAligned').check();page.locator('#cadImport').click()
                expect(page.locator('#cadReport')).to_be_enabled(timeout=50000)
                expect(page.locator('#cadEntities tr')).to_have_count(5)
                expect(page.locator('#cadSummary')).to_contain_text('1 unsupported')
                expect(page.locator('#cadSummary')).to_contain_text('1 survey points')
                page.locator('#cadImportReport').locator('..').locator('summary').click()
                expect(page.locator('#cadImportReport')).to_contain_text('RAY')
                page.locator('#cadLayers [data-layer="Details"]').uncheck()
                expect(page.locator('#cadEntities tr')).to_have_count(3)
                page.locator('#cadEntities [data-entity]').first.click()
                expect(page.locator('#cadEvidence')).to_contain_text('LINE')
                expect(page.locator('#cadEntities [data-entity]').first).to_be_focused()
                for i in range(3):page.locator('#cadEntities [data-add]').nth(i).click()
                expect(page.locator('#cadChain .cad-chain')).to_have_count(3)
                page.locator('#cadClosure').click();expect(page.locator('#cadClosureResult')).to_contain_text('WITHIN TOLERANCE REVIEW REQUIRED')
                expect(page.locator('#cadClosureResult')).to_contain_text('0.050000 ft')
                page.locator('#cadChain [data-reverse="1"]').check();page.locator('#cadClosure').click()
                expect(page.locator('#cadClosureResult')).to_contain_text('INVESTIGATE')
                page.locator('#cadChain [data-reverse="1"]').uncheck()
                page.locator('#cadIssues [data-issue]').first.click()
                expect(page.locator('#cadEvidence')).to_contain_text('LINE')
                page.locator('#cadReviewer').fill('Acceptance tester')
                page.locator('#cadDecisionNote').fill('Checked original source; retain for review')
                page.locator('#cadDecisionStatus').select_option('confirmed')
                page.locator('#cadSaveDecision').click()
                expect(page.locator('#cadMessage')).to_contain_text('Decision and audit history saved')
                expect(page.locator('#cadIssues [data-issue]').first).to_contain_text('confirmed')
                with page.expect_download() as download:page.locator('#cadReport').click()
                package=ZipFile(io.BytesIO(Path(download.value.path()).read_bytes()))
                exported=json.loads(package.read('CAD_Review.json'))
                assert exported['closure']['status']=='WITHIN_TOLERANCE_REVIEW_REQUIRED'
                assert len(exported['unsupported'])==1
                decision_export=json.loads(package.read('CAD_Workflow.json'))
                assert decision_export['review_state']['history'][0]['status']=='confirmed'
                assert b'Acceptance tester' in package.read('CAD_Review.html')
                report['checks'].append('Explicit alignment/units, real DXF upload, layer/table/finding selection, ordered chain/reverse, unsupported report and actual ZIP download')
                page.locator('#cadTool').select_option('pan');canvas=page.locator('#cadCanvas');canvas.scroll_into_view_if_needed();box=canvas.bounding_box();assert box
                page.mouse.move(box['x']+100,box['y']+100);page.mouse.down();page.mouse.move(box['x']+140,box['y']+130);page.mouse.up()
                page.locator('#cadZoomIn').click();page.locator('#cadFit').click();page.locator('#cadTool').select_option('identify')
                # Fit uses exact DXF bounds: x 2000..2010, y 1000..1010; point at 2002,1002.
                box=canvas.bounding_box();scale=min((box['width']-50)/10,390/10)
                canvas.click(position={'x':box['width']/2-3*scale,'y':220+3*scale})
                expect(page.locator('#cadEvidence')).to_contain_text('Survey point 001A')
                review=page.locator('#cadHistory').input_value()
                for mode in ('light','dark'):
                    api('/api/v9/config/ui',{'appearance':mode,'theme':'carbon','accent':'default'})
                    page.reload(wait_until='domcontentloaded');expect(page.locator('#productSplash')).to_be_hidden(timeout=20000)
                    page.locator('.module-tab[data-module="BoundarySync"]').click();page.locator('#moduleNav .module-nav-btn').filter(has_text='CAD Drawing').click()
                    expect(page.locator('#cadImport')).to_be_enabled();page.locator('#cadHistory').select_option(review);page.locator('#cadOpen').click();expect(page.locator('#cadEntities tr')).to_have_count(5)
                    canvas.scroll_into_view_if_needed();page.screenshot(path=str(OUT/f'cad-{mode}.png'),full_page=True)
                page.set_viewport_size({'width':900,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.locator('#cadIssues [data-issue]').first.click()
                expect(page.locator('#cadDecisionStatus')).to_have_value('confirmed')
                revised=root/'revised.dxf'
                next(iter(m.query('LINE'))).dxf.end=(2011,1000,0)
                doc.saveas(revised)
                page.locator('#cadFile').set_input_files(str(revised));page.locator('#cadAligned').check();page.locator('#cadUnits').select_option('us_survey_feet');page.locator('#cadImport').click()
                expect(page.locator('#cadSummary')).to_contain_text('revised.dxf',timeout=50000)
                expect(page.locator('#cadReport')).to_be_enabled()
                page.locator('#cadBefore').select_option(review);page.locator('#cadCompare').click()
                expect(page.locator('#cadComparisonSummary')).to_contain_text('unchanged representations')
                page.locator('#cadChanges [data-change]').first.click()
                expect(page.locator('#cadEvidence')).to_contain_text('changed_candidate')
                with page.expect_download() as revision_download:page.locator('#cadReport').click()
                revision_package=ZipFile(io.BytesIO(Path(revision_download.value.path()).read_bytes()))
                revision_data=json.loads(revision_package.read('CAD_Workflow.json'))
                assert revision_data['comparison']['before']['review_id']==review
                assert not revision_data['review_state']['history']
                assert any(c['kind']=='changed_candidate' for c in revision_data['comparison']['changes'])
                assert dxf.read_bytes()==original
                page.screenshot(path=str(OUT/'cad-revision-comparison.png'),full_page=True)
                report['checks'].append('Saved/reopened finding decisions, immutable audit history, revised DXF comparison, selected overlay and exact decision/comparison export')

                page.screenshot(path=str(OUT/'cad-narrow.png'),full_page=True)
                api('/api/v9/project/create',{'parent_folder':str(root/'projects'),'name':'Other','crs':'EPSG:2278'})
                page.locator('#cadReport').click();expect(page.locator('#cadMessage')).to_contain_text('Project changed')
                expect(page.locator('#cadControls')).to_have_attribute('disabled','');expect(page.locator('#cadReport')).to_be_disabled();expect(page.locator('#cadClosure')).to_be_disabled();expect(page.locator('#cadImport')).to_be_disabled();expect(page.locator('#cadEntities tr')).to_have_count(0)
                assert dxf.read_bytes()==original;assert not errors,errors
                report['checks'].append('Plan identification of survey point; pan/zoom; retained review reopening; light/dark/narrow layout; stale-project report refusal and original-byte preservation')
                browser.close()
            report['status']='PASS'
        finally:
            (OUT/'cad-acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait()
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
