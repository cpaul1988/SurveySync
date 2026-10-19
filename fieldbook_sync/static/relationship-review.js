/* Original-page evidence rendering. No image pixels or result values are changed. */
(function (root) {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const bounded = (value, max) => Array.isArray(value) ? value.slice(0, max) : [];
  const records = (value, max) => bounded(value,max).filter(v => v && typeof v === 'object' && !Array.isArray(v));
  const ids = value => bounded(value,128).filter(v => typeof v === 'string');
  const point = value => Array.isArray(value) && value.length === 2 && value.every(n => typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 1000);
  const box = value => Array.isArray(value) && value.length === 4 && point(value.slice(0,2)) && point(value.slice(2)) && value[0] < value[2] && value[1] < value[3];
  const verdict = value => value === true ? 'Agrees' : value === false ? 'Disagrees' : 'Unverified';
  function rectangle(bbox, kind, label) {
    if (!box(bbox)) return '';
    return `<rect class="spatial-${kind}" x="${bbox[0]}" y="${bbox[1]}" width="${bbox[2]-bbox[0]}" height="${bbox[3]-bbox[1]}"><title>${esc(label)}</title></rect>`;
  }
  function overlayHtml(evidence, pipeIndex = -1) {
    const graph = evidence?.spatial_evidence || {}, pipe = evidence?.pipes?.[pipeIndex];
    const textIds = new Set(ids(pipe?.association_text_ids)), pathIds = new Set(ids(pipe?.association_path_ids));
    const contents = [];
    for (const region of records(graph.text_regions, 256)) {
      if (pipe && !textIds.has(region.id)) continue;
      contents.push(rectangle(region.bbox, 'text', `OCR text: ${region.text || ''}`));
    }
    for (const structure of records(graph.structures, 64)) {
      contents.push(rectangle(structure.bbox, 'structure', `Measured closed boundary; PointID ${structure.point_id || 'ambiguous'}`));
    }
    for (const anchor of records(graph.point_anchors, 128)) {
      contents.push(rectangle(anchor.bbox, 'anchor', `Independent exact PointID: ${anchor.point_id || ''}`));
    }
    for (const path of records(graph.paths, 128)) {
      if (pipe && !pathIds.has(path.id)) continue;
      const points = bounded(path.points, 512);
      if (points.length < 2 || !points.every(point) || path.evidence !== 'original_pixels') continue;
      const ambiguous = path.branched || graph.status !== 'complete' || path.original_resolution_verified !== true;
      contents.push(`<polyline class="spatial-path${ambiguous ? ' spatial-ambiguous' : ''}" points="${points.map(p => p.join(',')).join(' ')}"><title>${esc(path.id)} · measured ink${ambiguous ? ' · ambiguous' : ''}</title></polyline>`);
      for (const end of bounded(path.endpoints, 2)) if (point(end)) contents.push(`<circle class="spatial-endpoint" cx="${end[0]}" cy="${end[1]}" r="4"/>`);
    }
    if (pipe) contents.push(rectangle(pipe.leader_bbox, 'model', 'Model proposed leader region; compare with measured ink'));
    return `<svg class="spatial-overlay" viewBox="0 0 1000 1000" preserveAspectRatio="none" role="img" aria-label="Original page OCR regions, measured leaders and structure boundaries">${contents.join('')}</svg>`;
  }
  function summaryHtml(evidence) {
    const graph = evidence?.spatial_evidence || {};
    return `<div class="relationship-verdicts"><span>Numbers: <b>${verdict(evidence?.numerical_agreement)}</b></span><span>Pipe records: <b>${verdict(evidence?.pipe_record_agreement)}</b></span><span>Relationship: <b>${esc(graph.status === 'complete' ? (evidence?.relationship_status || 'unverified') : 'unverified')}</b></span></div>`;
  }
  function detailsHtml(evidence, pipeIndex = -1, includeSummary = true) {
    const graph = evidence?.spatial_evidence || {};
    const summary = includeSummary ? summaryHtml(evidence) : '';
    const message = graph.status === 'partial' ? 'The geometry limit was reached. All partial paths need review.' : graph.status === 'complete' ? 'Measured paths are review proposals. Verify every pipe against the original handwriting.' : 'No measured relationship is available. Review the original page and correct the pipe fields below.';
    const selected = pipeIndex >= 0 ? [[pipeIndex, evidence?.pipes?.[pipeIndex]]] : bounded(evidence?.pipes, 64).map((p,i) => [i,p]);
    const regions = new Map(records(graph.text_regions, 256).map(r => [r.id,r]));
    const associations = records(graph.associations, 256);
    const rows = selected.filter(([,p]) => p).map(([index,pipe]) => {
      const textIds = ids(pipe.association_text_ids);
      const snippets = textIds.map(id => regions.get(id)?.text).filter(Boolean).map(text => `<div class="raw-ocr">${esc(text)}</div>`).join('');
      const alternatives = associations.filter(a => textIds.includes(a.text_id)).flatMap(a => records(a.candidates, 64));
      const destinations = [...new Set(alternatives.map(a => a.point_id).filter(Boolean))];
      return `<div class="relationship-pipe"><strong>Pipe ${index+1}: ${esc(graph.status === 'complete' ? (pipe.association_status || 'unverified') : 'unverified')}</strong>${snippets || '<div class="hint">No complete independently located text record.</div>'}${destinations.length ? `<div class="hint">Candidate PointIDs: ${destinations.map(esc).join(', ')}</div>` : ''}<div class="hint">${bounded(pipe.association_flags, 12).map(flag => esc(String(flag).replaceAll('_',' ').toLowerCase())).join(' · ')}</div></div>`;
    }).join('');
    return `${summary}<p class="hint">${message}</p>${rows}`;
  }
  function controlsHtml(evidence) {
    const options = bounded(evidence?.pipes,64).map((_,i) => `<option value="${i}">Pipe ${i+1}</option>`).join('');
    return `${summaryHtml(evidence)}<div class="relationship-controls"><label class="check"><input id="relationshipOverlayToggle" type="checkbox" checked/> Evidence overlay</label><label>Show <select id="relationshipPipeSelect" class="control"><option value="-1">All proposals</option>${options}</select></label></div><div class="relationship-legend"><span class="text-key">Text</span><span class="path-key">Measured leader</span><span class="structure-key">Structure boundary</span><span class="anchor-key">Exact PointID</span></div><details class="relationship-evidence-details"><summary>Pipe evidence and review notes</summary><div id="relationshipDetails">${detailsHtml(evidence,-1,false)}</div></details>`;
  }
  const api = {overlayHtml, detailsHtml, controlsHtml};
  root.FieldBookRelationships = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window === 'undefined' ? globalThis : window);
