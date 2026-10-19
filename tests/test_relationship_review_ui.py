"""Execute the real relationship renderer and asynchronous review controller in Node."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "fieldbook_sync" / "static" / "relationship-review.js"
APP = ROOT / "fieldbook_sync" / "static" / "app.js"
NODE = shutil.which("node") or os.environ.get("CODEX_PRIMARY_RUNTIME_NODE")
pytestmark = pytest.mark.skipif(not NODE, reason="Node is required to execute browser JavaScript")


def run_js(body, payload=None):
    source = (
        """
const assert = require('node:assert/strict');
const fs = require('node:fs');
const R = require(process.argv[1]);
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
(async () => {
"""
        + body
        + """
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
"""
    )
    result = subprocess.run(
        [NODE, "-e", source, str(RENDERER)],
        input=json.dumps(payload),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else None


def fixture():
    return {
        "numerical_agreement": True,
        "pipe_record_agreement": False,
        "relationship_status": "conflict",
        "spatial_evidence": {
            "status": "complete",
            "text_regions": [
                {"id": "text-a", "bbox": [40, 50, 250, 90], "text": "DIP 4.2 8 PVC"},
                {"id": "text-b", "bbox": [700, 50, 950, 90], "text": "DIP 6.3 12 RCP"},
            ],
            "structures": [{"bbox": [420, 150, 580, 300], "point_id": "0001"}],
            "point_anchors": [{"bbox": [450, 200, 550, 230], "point_id": "0001"}],
            "paths": [
                {
                    "id": "path-a",
                    "points": [[200, 80], [420, 220]],
                    "endpoints": [[200, 80], [420, 220]],
                    "evidence": "original_pixels",
                    "original_resolution_verified": True,
                },
                {
                    "id": "path-b",
                    "points": [[580, 220], [800, 80]],
                    "endpoints": [[580, 220], [800, 80]],
                    "evidence": "original_pixels",
                    "original_resolution_verified": True,
                },
            ],
            "associations": [
                {"text_id": "text-a", "candidates": [{"point_id": "0001"}]},
                {"text_id": "text-b", "candidates": [{"point_id": "0002"}]},
            ],
        },
        "pipes": [
            {
                "association_status": "supported",
                "association_text_ids": ["text-a"],
                "association_path_ids": ["path-a"],
                "association_flags": ["HUMAN_REVIEW_REQUIRED"],
            },
            {
                "association_status": "conflict",
                "association_text_ids": ["text-b"],
                "association_path_ids": ["path-b"],
                "association_flags": ["MISSING_RECORD_SUPPORT"],
            },
        ],
    }


def test_renderer_keeps_number_record_and_relationship_verdicts_separate():
    run_js(
        r"""
const html = R.detailsHtml(input);
assert.match(html, /Numbers: <b>Agrees<\/b>/);
assert.match(html, /Pipe records: <b>Disagrees<\/b>/);
assert.match(html, /Relationship: <b>conflict<\/b>/);
assert.match(html, /review proposals/);
input.spatial_evidence.status = 'partial';
input.relationship_status = 'supported';
const partial = R.detailsHtml(input);
assert.match(partial, /Relationship: <b>unverified<\/b>/);
assert.match(partial, /All partial paths need review/);
assert.doesNotMatch(partial, /Pipe 1: supported/);
""",
        fixture(),
    )


def test_selected_pipe_filters_text_paths_and_details_but_keeps_structure_context():
    run_js(
        """
const html = R.overlayHtml(input, 1);
assert.match(html, /DIP 6.3 12 RCP/);
assert.doesNotMatch(html, /DIP 4.2 8 PVC/);
assert.match(html, /path-b/);
assert.doesNotMatch(html, /path-a/);
assert.equal((html.match(/<polyline /g)||[]).length, 1);
assert.match(html, /spatial-structure/);
assert.match(html, /spatial-anchor/);
const details = R.detailsHtml(input, 1);
assert.match(details, /Pipe 2: conflict/);
assert.doesNotMatch(details, /Pipe 1:/);
assert.match(details, /Candidate PointIDs: 0002/);
assert.doesNotMatch(details, /Candidate PointIDs: 0001/);
assert.match(R.controlsHtml(input), /value="-1">All proposals/);
""",
        fixture(),
    )


def test_ocr_point_ids_flags_and_path_labels_are_escaped():
    run_js(
        r"""
const attack = '<img src=x onerror="window.__unexpected=1"> & \'quoted\'';
input.spatial_evidence.text_regions[0].text = attack;
input.spatial_evidence.structures[0].point_id = attack;
input.spatial_evidence.point_anchors[0].point_id = attack;
input.spatial_evidence.paths[0].id = attack;
input.spatial_evidence.associations[0].candidates[0].point_id = attack;
input.pipes[0].association_flags = [attack];
for (const html of [R.overlayHtml(input), R.detailsHtml(input)]) {
  assert.doesNotMatch(html, /<img /);
  assert.match(html, /&lt;img src=x onerror=&quot;window/);
  assert.match(html, /&amp;/);
  assert.match(html, /&#39;/);
}
""",
        fixture(),
    )


@pytest.mark.parametrize("invalid", [[-1, 2], [1001, 2], ["1", 2], [1], None])
def test_out_of_original_coordinate_bounds_cannot_create_a_path(invalid):
    value = fixture()
    value["spatial_evidence"]["paths"][0]["points"][1] = invalid
    run_js(
        """
const html = R.overlayHtml(input);
assert.doesNotMatch(html, /path-a/);
assert.match(html, /path-b/);
assert.equal((html.match(/<polyline /g)||[]).length, 1);
""",
        value,
    )


def test_nonfinite_and_wrong_source_geometry_is_hidden_or_marked_ambiguous():
    run_js(
        """
input.spatial_evidence.paths[0].points[0] = [NaN, 20];
input.spatial_evidence.paths[1].evidence = 'enhanced_pixels';
assert.doesNotMatch(R.overlayHtml(input), /<polyline /);
input.spatial_evidence.paths[0].points[0] = [20, 20];
input.spatial_evidence.paths[0].original_resolution_verified = false;
assert.match(R.overlayHtml(input), /class="spatial-path spatial-ambiguous"/);
input.spatial_evidence.text_regions[0].bbox = [10, 10, 5, 20];
assert.doesNotMatch(R.overlayHtml(input), /DIP 4.2 8 PVC/);
""",
        fixture(),
    )


def test_malformed_graph_entries_and_non_array_ids_do_not_break_review():
    run_js(
        """
for (const name of ['text_regions','structures','point_anchors','paths','associations']) {
  input.spatial_evidence[name].unshift(null, 5, 'bad', []);
}
input.spatial_evidence.associations.push({text_id:'text-a', candidates:[null, 5, [], {point_id:'0001'}]});
input.pipes[0].association_path_ids = {invalid:'not iterable'};
input.pipes[0].association_text_ids = {invalid:'not iterable'};
assert.doesNotThrow(() => R.overlayHtml(input, 0));
assert.doesNotThrow(() => R.detailsHtml(input));
assert.doesNotThrow(() => R.controlsHtml(input));
assert.match(R.overlayHtml(input), /spatial-structure/);
""",
        fixture(),
    )


def test_large_graph_and_path_arrays_have_bounded_rendering():
    run_js(
        """
const graph = input.spatial_evidence;
graph.text_regions = Array.from({length:300}, () => graph.text_regions[0]);
graph.structures = Array.from({length:100}, () => graph.structures[0]);
graph.point_anchors = Array.from({length:200}, () => graph.point_anchors[0]);
graph.paths = Array.from({length:200}, () => ({...graph.paths[0], points:Array.from({length:700}, () => [10,20])}));
const html = R.overlayHtml(input);
assert.ok((html.match(/class="spatial-text"/g)||[]).length <= 256);
assert.ok((html.match(/class="spatial-structure"/g)||[]).length <= 64);
assert.ok((html.match(/class="spatial-anchor"/g)||[]).length <= 128);
assert.ok((html.match(/<polyline /g)||[]).length <= 128);
for (const match of html.matchAll(/<polyline[^>]* points="([^"]*)"/g)) {
  assert.ok(match[1].split(' ').length <= 512);
}
""",
        fixture(),
    )


def controller_source():
    source = APP.read_text(encoding="utf-8")
    start = source.index("const reviewPipeFields=")
    end = source.index("\nfunction bindReview(", start)
    declarations = re.search(r"^let reviewEvidenceIndex=.*;$", source, re.MULTILINE)
    assert declarations, "Review state declarations must be included in controller test"
    return declarations.group() + "\n" + source[start:end]


@pytest.mark.parametrize("late_failure", [False, True])
def test_late_graph_response_cannot_replace_a_more_recent_evidence_page(late_failure):
    # Execute the real controller with delayed transport and a minimal modal sink.
    body = (
        """
let resultsLoaded = true, resultsRevision = 1, currentReviewPoint = '0001', currentReviewIndex = 0;
const state = {project_revision:1, job:{running:false}};
const results = [{point_id:'0001', code:'MH', status:'YES', dip_status:'YES', pipes:[], evidence_records:[
  {page_id:'old-page', source_name:'Synthetic old', page_number:1, spatial_evidence_key:'old /?&'},
  {page_id:'new-page', source_name:'Synthetic new', page_number:2, spatial_evidence_key:'new'},
]}];
const sinks = {}, shown = [], pending = [], warnings = [];
const $ = selector => sinks[selector] ||= {};
const $$ = () => [];
const filteredResults = () => results;
const refreshResults = async () => {};
const api = url => new Promise((resolve,reject) => pending.push({url,resolve,reject}));
const FieldBookRelationships = {overlayHtml:R.overlayHtml, controlsHtml:R.controlsHtml};
const esc = value => String(value ?? '');
const fmt = value => String(value ?? '');
const bboxHtml = () => '';
const pipeEditor = () => '';
const openModal = (title,html) => shown.push(html);
const bindReview = () => {};
const injectTeachProfileControls = () => {};
const toast = message => warnings.push(message);
"""
        + controller_source()
        + r"""
const oldRequest = openResultReview('0001');
assert.equal(pending[0].url, '/api/fieldbook-spatial/old%20%2F%3F%26');
reviewEvidenceIndex = 1;
const newRequest = openResultReview('0001');
pending[1].resolve({status:'complete'});
await newRequest;
assert.equal(shown.length, 1);
assert.match(shown[0], /id="reviewImage" src="\/api\/page\/new-page"/);
assert.match(shown[0], /data-mode="original">Original/);
if (input) pending[0].reject(new Error('obsolete synthetic error'));
else pending[0].resolve({status:'complete'});
await oldRequest;
assert.equal(shown.length, 1, 'Late page response must not reopen old evidence');
assert.equal(warnings.length, 0, 'An obsolete graph failure must not toast over the active page');
"""
    )
    run_js(body, late_failure)


def test_engine_spotting_selector_and_private_download_use_real_event_handlers():
    source = APP.read_text(encoding="utf-8")
    handlers = "\n".join(
        line
        for line in source.splitlines()
        if line.startswith("$('#ocrMode')?.addEventListener")
        or line.startswith("$('#exportFieldbookBenchmarkBtn')?.addEventListener")
    )
    assert handlers.count("addEventListener") == 2
    run_js(
        """
const events = {}, controls = {
  '#ocrMode': {value:'blocks', addEventListener:(name,fn) => events.mode = fn},
  '#exportFieldbookBenchmarkBtn': {addEventListener:(name,fn) => events.download = fn},
};
let selectedProvider = 'auto', download;
const $ = selector => controls[selector];
const selectProvider = provider => {selectedProvider = provider;};
const fieldbookDownload = url => {download = url;};
"""
        + handlers
        + """
controls['#ocrMode'].value = 'spotting';
events.mode();
assert.equal(selectedProvider, 'hybrid');
selectedProvider = 'paddle';
events.mode();
assert.equal(selectedProvider, 'paddle');
events.download();
assert.equal(download, '/api/fieldbook-benchmark/export');
"""
    )
