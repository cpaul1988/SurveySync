#!/usr/bin/env python3
"""Render and exercise the real review UI with synthetic intercepted HTTP responses.

Requires Node, Playwright for Node, and an already installed Chromium executable.
This script installs nothing. It does not start SurveySync or open private pages.
The startup coordinator is disabled while the real review handlers, shell bridge,
HTML, and styles run against a two-page synthetic fixture.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

try:
    from scripts.benchmark_fieldbook import (
        BenchmarkError,
        evaluator_provenance,
        write_private_report,
    )
except ModuleNotFoundError:
    from benchmark_fieldbook import BenchmarkError, evaluator_provenance, write_private_report


ROOT = Path(__file__).resolve().parents[1]


NODE_RUNNER = r"""
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const config = JSON.parse(fs.readFileSync(0, 'utf8'));
const {chromium} = require(config.playwright_module);
const origin = 'http://127.0.0.1:18788';
const report = {
  status:'FAIL', kind:'synthetic_fieldbook_relationship_ui',
  created_utc:config.created_utc,
  scope:'Real review DOM, controller, shell bridge and CSS; intercepted synthetic API responses; startup coordinator disabled.',
  model_inference:false, backend_acceptance:false, release_or_security_clearance:false,
  evaluator:config.evaluator, source_files:config.source_files,
  checks:[], page_errors:[], unexpected_requests:[], screenshots:[],
};
const graph = (page) => ({
  status:'complete', coordinate_space:'original_normalized_1000',
  text_regions:[
    {id:'text-a',bbox:[55,140,300,190],text:'DIP 4.2 / 8 PVC — synthetic'},
    {id:'text-b',bbox:[690,140,965,190],text:'DIP 6.3 / 12 RCP <img src=x onerror="window.__unexpected=1">'},
  ],
  structures:[{bbox:[420,300,580,470],point_id:'0001'}],
  point_anchors:[{bbox:[447,366,554,399],point_id:'0001'}],
  paths:[
    {id:'path-a',points:[[230,190],[335,250],[420,380]],endpoints:[[230,190],[420,380]],evidence:'original_pixels',original_resolution_verified:true},
    {id:'path-b',points:[[580,380],[670,245],[820,190]],endpoints:[[580,380],[820,190]],evidence:'original_pixels',original_resolution_verified:true,branched:page==='b'},
  ],
  associations:[{text_id:'text-a',candidates:[{point_id:'0001'}]},{text_id:'text-b',candidates:[{point_id:'0001'},{point_id:'0002'}]}],
});
const pipes = [
  {dip:4.2,diameter_in:8,material:'PVC',azimuth_deg:270,connected_point_raw:null,leader_bbox:[225,185,425,385],association_status:'supported',association_text_ids:['text-a'],association_path_ids:['path-a'],association_flags:['HUMAN_REVIEW_REQUIRED']},
  {dip:6.3,diameter_in:12,material:'RCP',azimuth_deg:90,connected_point_raw:'0002',leader_bbox:[575,185,825,385],association_status:'ambiguous',association_text_ids:['text-b'],association_path_ids:['path-b'],association_flags:['MULTIPLE_CANDIDATE_POINT_IDS']},
];
const fixtureResults = [{point_id:'0001',code:'MH',status:'YES',dip_status:'YES',review_state:'UNREVIEWED',smart_confidence:60,qa_needs_review:true,pipes,
  evidence_records:['a','b'].map((page,i) => ({
    page_id:`synthetic-page-${page}`,source_name:`Synthetic book ${page.toUpperCase()}`,page_number:i+1,
    spatial_evidence_key:`synthetic-graph-${page}`,spatial_evidence:{},
    numerical_agreement:true,pipe_record_agreement:false,relationship_status:page==='a'?'conflict':'ambiguous',
    evidence_decision:'MANUAL_REVIEW',evidence_score:0.6,evidence_sources:['synthetic_fixture'],
    ocr_text:'Typeset synthetic fixture. No real field-book page or OCR model output.',pipes,
  })),
}];
function syntheticPage(page, enhanced) {
  const grid = enhanced ? '' : Array.from({length:20},(_,i) => `<path d="M0 ${i*70}H1000" stroke="#8fcbd2" stroke-width="1" opacity=".45"/>`).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1400" viewBox="0 0 1000 1400"><rect width="1000" height="1400" fill="#fffdf4"/>${grid}<g transform="scale(1 1.4)" fill="#26313f" font-family="Arial,sans-serif"><text x="52" y="60" font-size="23">SYNTHETIC QA PAGE ${page.toUpperCase()} — NO REAL FIELD NOTES</text><text x="55" y="175" font-size="21">DIP 4.2 / 8 PVC</text><text x="690" y="175" font-size="21">DIP 6.3 / 12 RCP</text><path d="M230 190L335 250L420 380M580 380L670 245L820 190" fill="none" stroke="#26313f" stroke-width="4"/><ellipse cx="500" cy="385" rx="80" ry="85" fill="none" stroke="#26313f" stroke-width="4"/><text x="455" y="390" font-size="30">0001</text><text x="52" y="600" font-size="19">Original coordinates: 0..1000 normalized on each axis.</text><text x="52" y="640" font-size="19">This diagram tests the review interface, not OCR accuracy.</text></g></svg>`;
}
function deferred() {
  let resolve;
  const promise = new Promise(done => {resolve=done;});
  return {promise,resolve};
}

(async () => {
  let browser, page;
  const holds = new Map(), graphRequests = [], downloads = [];
  const mime = {'.css':'text/css','.js':'application/javascript','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg'};
  try {
    browser = await chromium.launch({headless:true,executablePath:config.browser || undefined,args:process.platform==='win32'?[]:['--no-sandbox']});
    report.browser_version = browser.version();
    report.node_version = process.version;
    const context = await browser.newContext({viewport:{width:1600,height:1100},acceptDownloads:true,serviceWorkers:'block'});
    page = await context.newPage();
    page.on('pageerror', error => report.page_errors.push(error.message));
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if(url.origin !== origin) {
        report.unexpected_requests.push('External request blocked');
        return route.abort();
      }
      if(url.pathname === '/') {
        return route.fulfill({contentType:'text/html',body:'<!doctype html><html><body style="margin:0"><script>window.ssFieldBook={onReady(){},changedTab(){},parentCommand(){}};</script><iframe title="Synthetic FieldBook QA" name="fieldbook-test" src="/fieldbook?embedded=1&ss_project=synthetic-ui-project" style="border:0;width:100vw;height:100vh"></iframe></body></html>'});
      }
      if(url.pathname === '/fieldbook') {
        return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(config.root,'fieldbook_sync/static/index.html'),'utf8')});
      }
      const staticRoot = url.pathname.startsWith('/static/') ? path.join(config.root,'fieldbook_sync/static') : url.pathname.startsWith('/surveysync-static/') ? path.join(config.root,'surveysync/static') : null;
      if(staticRoot) {
        const file = path.resolve(staticRoot, url.pathname.replace(/^\/(?:static|surveysync-static)\//,''));
        if(!file.startsWith(staticRoot+path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) return route.fulfill({status:404,body:''});
        let body = fs.readFileSync(file);
        if(file === path.join(config.root,'fieldbook_sync/static/app.js')) {
          const source = body.toString('utf8');
          assert.match(source, /\ninit\(\);\s*$/);
          body = Buffer.from(source.replace(/\ninit\(\);\s*$/, '\n/* Synthetic harness supplies completed-run state. */\n'));
        }
        return route.fulfill({contentType:mime[path.extname(file)] || 'application/octet-stream',body});
      }
      if(url.pathname.startsWith('/api/page/synthetic-page-')) {
        return route.fulfill({contentType:'image/svg+xml',body:syntheticPage(url.pathname.endsWith('-b')?'b':'a',url.searchParams.has('enhanced'))});
      }
      if(url.pathname.startsWith('/api/fieldbook-spatial/')) {
        const key = decodeURIComponent(url.pathname.split('/').at(-1));
        const entry = {key,project:request.headers()['x-surveysync-project'],method:request.method()};
        graphRequests.push(entry);
        const hold = holds.get(key);
        if(hold) {hold.seen.resolve(); await hold.release.promise;}
        return route.fulfill({json:graph(key.endsWith('-b')?'b':'a')});
      }
      if(url.pathname === '/api/field-note-profiles') return route.fulfill({json:{profiles:[]}});
      if(url.pathname === '/api/fieldbook-benchmark/export') {
        downloads.push({project:url.searchParams.get('ss_project'),method:request.method()});
        return route.fulfill({contentType:'application/json',headers:{'Content-Disposition':'attachment; filename="synthetic-benchmark.json"'},body:JSON.stringify({fixture:'synthetic-only',results:fixtureResults})});
      }
      report.unexpected_requests.push(url.pathname);
      return route.abort();
    });
    await page.goto(origin, {waitUntil:'domcontentloaded'});
    await page.waitForLoadState('load');
    const frame = page.frame({name:'fieldbook-test'});
    assert.ok(frame, 'Embedded FieldBook frame must exist');
    await frame.waitForFunction(() => typeof openResultReview === 'function');
    await frame.evaluate(fixture => {
      results=fixture;resultsLoaded=true;resultsRevision=1;state={project_revision:1,job:{running:false},settings:{provider:'auto'}};
      document.documentElement.dataset.theme='light';document.documentElement.dataset.productTheme='classic';
      window.__reviewCompletions=0;
      const realOpen=openResultReview;
      openResultReview=async(...args)=>{try{return await realOpen(...args)}finally{window.__reviewCompletions++}};
    },fixtureResults);
    await frame.evaluate(() => openResultReview('0001'));
    await frame.locator('#reviewImage').waitFor({state:'visible'});
    await frame.waitForFunction(() => document.querySelector('#reviewImage')?.naturalWidth > 0);
    assert.match(await frame.locator('#reviewImage').getAttribute('src'), /\/api\/page\/synthetic-page-a$/);
    assert.equal(await frame.locator('.img-mode.active').getAttribute('data-mode'),'original');
    assert.equal(await frame.locator('.spatial-overlay').isVisible(),true);
    assert.equal(await frame.locator('.spatial-path').count(),2);
    assert.equal(graphRequests[0].project,'synthetic-ui-project');
    assert.equal(graphRequests[0].method,'GET');
    const summary = await frame.locator('.relationship-verdicts').innerText();
    assert.match(summary,/Numbers: Agrees/);assert.match(summary,/Pipe records: Disagrees/);assert.match(summary,/Relationship: conflict/);
    const visibleSummary = await frame.locator('.relationship-verdicts').evaluate(element => {
      const box=element.getBoundingClientRect();
      return box.top>=0 && box.bottom<=innerHeight;
    });
    assert.ok(visibleSummary,'The independent verdicts must be visible without scrolling');
    assert.ok(await frame.locator('#editNotes').evaluate(element => {
      const style=getComputedStyle(element),line=parseFloat(style.lineHeight)||parseFloat(style.fontSize)*1.2;
      return element.clientHeight-parseFloat(style.paddingTop)-parseFloat(style.paddingBottom)>=line*1.8;
    }),'Review notes must retain room for at least two readable lines');
    assert.doesNotMatch(await frame.locator('.image-stage').evaluate(element => getComputedStyle(element,':after').content),/enhanced analysis image/i);
    assert.equal(await frame.locator('#relationshipDetails img').count(),0);
    assert.equal(await frame.evaluate(() => window.__unexpected),undefined);
    const aligned = await frame.evaluate(() => {
      const image=document.querySelector('#reviewImage').getBoundingClientRect(),overlay=document.querySelector('.spatial-overlay').getBoundingClientRect();
      return ['x','y','width','height'].every(key => Math.abs(image[key]-overlay[key])<1);
    });
    assert.ok(aligned,'Overlay must cover the non-square original raster exactly');
    report.checks.push('original-first','canonical-scoped-graph-fetch','independent-verdicts','verdicts-visible-without-scrolling','readable-notes-editor','no-obsolete-enhanced-image-caption','escaped-ocr','non-square-image-overlay-alignment');
    await page.screenshot({path:path.join(config.output,'review-original-all.png')});
    report.screenshots.push('review-original-all.png');

    await frame.locator('#relationshipPipeSelect').selectOption('1');
    await frame.locator('.relationship-evidence-details > summary').click();
    assert.equal(await frame.locator('#relationshipDetails').isVisible(),true);
    assert.equal(await frame.locator('.spatial-path').count(),1);
    assert.equal(await frame.locator('.spatial-text').count(),1);
    assert.match(await frame.locator('.spatial-path title').textContent(),/path-b/);
    assert.match(await frame.locator('#relationshipDetails').innerText(),/Pipe 2: ambiguous/);
    assert.doesNotMatch(await frame.locator('#relationshipDetails').innerText(),/Pipe 1:/);
    assert.ok(await frame.locator('.spatial-structure').count()>0);
    await page.screenshot({path:path.join(config.output,'review-original-pipe-2.png')});
    report.screenshots.push('review-original-pipe-2.png');
    report.checks.push('selected-pipe-text-and-path-filter');
    await frame.locator('.img-mode[data-mode="enhanced"]').click();
    assert.match(await frame.locator('#reviewImage').getAttribute('src'),/\?enhanced=1$/);
    assert.equal(await frame.locator('.spatial-overlay').isVisible(),false,'Enhanced view must hide the original-coordinate SVG');
    await frame.locator('#relationshipPipeSelect').selectOption('0');
    assert.equal(await frame.locator('.spatial-overlay').isVisible(),false,'Changing the selected pipe in enhanced mode must keep SVG hidden');
    await frame.locator('#relationshipOverlayToggle').uncheck();
    await frame.locator('.img-mode[data-mode="original"]').click();
    assert.equal(await frame.locator('.spatial-overlay').isVisible(),false,'An unchecked overlay must remain hidden when returning to original');
    await frame.locator('#relationshipOverlayToggle').check();
    assert.equal(await frame.locator('.spatial-overlay').isVisible(),true);
    report.checks.push('enhanced-hides-original-overlay','hidden-overlay-stays-hidden-on-filter','toggle-retained-on-original');

    await frame.locator('.p-dip').first().fill('4.25');
    await frame.locator('#editNotes').fill('Synthetic unsaved correction');
    let hold={seen:deferred(),release:deferred()};
    holds.set('synthetic-graph-b',hold);
    const beforeRace=await frame.evaluate(() => window.__reviewCompletions);
    await frame.locator('#reviewEvidenceSelect').selectOption('1');
    await hold.seen.promise;
    await frame.locator('#reviewEvidenceSelect').selectOption('0');
    await frame.waitForFunction(count => window.__reviewCompletions>count,beforeRace);
    hold.release.resolve();holds.delete('synthetic-graph-b');
    await frame.waitForFunction(count => window.__reviewCompletions>=count+2,beforeRace);
    assert.match(await frame.locator('#reviewImage').getAttribute('src'),/synthetic-page-a$/);
    assert.equal(await frame.locator('#reviewEvidenceSelect').inputValue(),'0');
    report.checks.push('late-page-response-cannot-replace-current-page');
    const beforeSelect=await frame.evaluate(() => window.__reviewCompletions);
    await frame.locator('#reviewEvidenceSelect').selectOption('1');
    await frame.waitForFunction(count => window.__reviewCompletions>count,beforeSelect);
    assert.match(await frame.locator('#reviewImage').getAttribute('src'),/synthetic-page-b$/);
    assert.match(await frame.locator('.relationship-verdicts').innerText(),/Relationship: ambiguous/);
    assert.equal(await frame.locator('.p-dip').first().inputValue(),'4.25','Changing an evidence page must preserve an unsaved pipe correction');
    assert.equal(await frame.locator('#editNotes').inputValue(),'Synthetic unsaved correction','Changing an evidence page must preserve unsaved notes');
    assert.equal(await frame.evaluate(() => results[0].pipes[0].dip),4.2,'Consulting another page must not save or mutate raw/project values');
    report.checks.push('evidence-page-select-changes-image-and-graph');
    report.checks.push('evidence-page-selection-preserves-unsaved-draft');
    hold={seen:deferred(),release:deferred()};holds.set('synthetic-graph-a',hold);
    const beforeClose=await frame.evaluate(() => window.__reviewCompletions);
    await frame.locator('#reviewEvidenceSelect').selectOption('0');
    await hold.seen.promise;
    await frame.locator('#modalClose').click();
    hold.release.resolve();holds.delete('synthetic-graph-a');
    await frame.waitForFunction(count => window.__reviewCompletions>count,beforeClose);
    assert.equal(await frame.locator('#modal').isVisible(),false);
    report.checks.push('closing-review-invalidates-pending-page-request');

    await frame.evaluate(() => {document.querySelectorAll('.view').forEach(view => view.classList.toggle('active',view.id==='tab-engine'));selectProvider('auto');});
    await frame.locator('#ocrMode').selectOption('spotting');
    assert.equal(await frame.evaluate(() => selectedProvider),'hybrid');
    await frame.locator('#spottingModelDir').fill('C:\\Synthetic QA\\Paddle model');
    assert.equal(await frame.locator('#spottingModelDir').inputValue(),'C:\\Synthetic QA\\Paddle model');
    const downloaded = page.waitForEvent('download');
    await frame.locator('#exportFieldbookBenchmarkBtn').click();
    await (await downloaded).saveAs(path.join(config.output,'synthetic-benchmark-download.json'));
    assert.deepEqual(downloads,[{project:'synthetic-ui-project',method:'GET'}]);
    report.checks.push('spotting-selects-compatible-local-provider','local-model-path-input','private-download-preserves-project-scope');
    await frame.evaluate(() => openResultReview('0001'));
    await page.setViewportSize({width:960,height:1000});
    await frame.waitForFunction(() => document.querySelector('#reviewImage')?.naturalWidth>0);
    assert.equal(await frame.evaluate(() => document.documentElement.scrollWidth<=innerWidth+1),true);
    await page.screenshot({path:path.join(config.output,'review-narrow.png')});
    report.screenshots.push('review-narrow.png');
    report.checks.push('narrow-review-has-no-horizontal-page-overflow');
    assert.deepEqual(report.page_errors,[]);
    assert.deepEqual(report.unexpected_requests,[]);
    for(const [name,digest] of Object.entries(config.source_files)) {
      const current=require('node:crypto').createHash('sha256').update(fs.readFileSync(path.join(config.root,name))).digest('hex');
      assert.equal(current,digest,'UI source changed during verification; rerun against a stable worktree');
    }
    report.status='PASS';
  } catch(error) {
    report.failure=error.message;
    if(page) try {await page.screenshot({path:path.join(config.output,'review-failure.png')});report.screenshots.push('review-failure.png');}catch{}
    process.exitCode=1;
  } finally {
    if(browser) await browser.close();
    fs.writeFileSync(path.join(config.output,'ui-results.json'),JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify({status:report.status,checks:report.checks.length,failure:report.failure||null}));
  }
})().catch(error=>{console.error(error.message);process.exitCode=1});
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", default=os.environ.get("SURVEYSYNC_BROWSER_EXECUTABLE"))
    parser.add_argument(
        "--node", default=shutil.which("node") or os.environ.get("CODEX_PRIMARY_RUNTIME_NODE")
    )
    parser.add_argument("--playwright-module", default=None)
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".fieldbook-benchmark" / "ui")
    args = parser.parse_args(argv)
    if not args.node:
        parser.error("Node is not installed; supply --node with an existing executable")
    module_root = os.environ.get("CODEX_PRIMARY_RUNTIME_NODE_MODULES")
    playwright_module = args.playwright_module or (
        str(Path(module_root) / "playwright") if module_root else "playwright"
    )
    private_root = ROOT / ".fieldbook-benchmark"
    output = args.output_dir.absolute()
    if not output.is_relative_to(private_root) or output.resolve() != output:
        parser.error(
            "Synthetic QA output must be under this worktree's .fieldbook-benchmark directory"
        )
    sources = [
        "fieldbook_sync/static/app.js",
        "fieldbook_sync/static/relationship-review.js",
        "fieldbook_sync/static/index.html",
        "fieldbook_sync/static/styles.css",
        "fieldbook_sync/static/shell_bridge.js",
        "surveysync/static/fieldbook-standard.css",
        "surveysync/static/fieldbook_host.css",
        "surveysync/static/theme-branding.css",
    ]
    config = {
        "root": str(ROOT),
        "output": str(output),
        "browser": args.browser,
        "playwright_module": playwright_module,
        "evaluator": evaluator_provenance(),
        "source_files": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources
        },
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    config["evaluator"]["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    try:
        for name in (
            "ui-results.json",
            "review-original-all.png",
            "review-original-pipe-2.png",
            "review-narrow.png",
            "review-failure.png",
            "synthetic-benchmark-download.json",
        ):
            destination = output / name
            if destination.is_symlink() or (
                destination.exists() and destination.stat().st_nlink > 1
            ):
                raise BenchmarkError("Synthetic QA output files must not be symbolic or hard links")
        write_private_report(output / "ui-results.json", {"status": "RUNNING"}, overwrite=True)
        result = subprocess.run(
            [args.node, "-e", NODE_RUNNER],
            input=json.dumps(config),
            text=True,
            encoding="utf-8",
            cwd=ROOT,
            timeout=100,
            check=False,
        )
        return result.returncode
    except (BenchmarkError, OSError, subprocess.SubprocessError) as error:
        print(f"Synthetic UI verification could not complete: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
