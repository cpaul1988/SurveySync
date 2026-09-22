/* Standalone TopoSync review workflow. All evidence is server-generated. */
(() => {
  const q = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const base = '/api/v9/topo';
  let source = null, run = null, rules = [], roles = [], revision = 0, workspaceKey = null, busy = false;
  const thresholds = [
    ['min_offset_ft','Minimum offset (ft)',0.45,0.01,100],
    ['consistency_ft','Constant-offset tolerance (ft)',0.1,0.001,10],
    ['reject_scatter_ft','Reject scatter (ft)',0.4,0.001,100],
    ['max_chain_gap_ft','Maximum chain gap (ft)',150,0.01,10000],
    ['exclusion_radius_ft','Exclusion radius (ft)',25,0.01,1000],
    ['max_projection_ft','Maximum grade projection (ft)',1500,0.01,100000],
    ['context_points','Unaffected anchors per side',3,3,12],
    ['correlation_rows','Maximum start separation (rows)',12,0,1000],
    ['max_range_points','Maximum points per chain range',1000,1,10000]
  ];
  function message(text) { q('topoMessage').textContent = text; }
  function invalidate() {
    revision++; run = null;
    q('topoCsv').disabled = q('topoJson').disabled = q('topoCorrected').disabled = true;
    q('topoCorrectionConfirmed').checked = false;
    q('topoResults').replaceChildren();
    q('topoSummary').textContent = source ? 'Inputs changed. Analyze to refresh results.' : 'No analysis yet.';
    q('topoAnalyze').disabled = !source || busy;
  }
  async function request(path, options = {}) {
    const response = await fetch(base + path, options);
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || response.status));
    }
    return response;
  }
  const post = (path, data) => request(path, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  function renderRules() {
    q('topoRules').innerHTML = rules.map((r,i) => `<tr data-index="${i}"><td><input aria-label="Feature code" data-field="code" value="${escape(r.code)}"></td><td><input aria-label="Feature description" data-field="description" value="${escape(r.description)}"></td><td><select aria-label="Feature role" data-field="role">${roles.map(role=>`<option ${r.role===role?'selected':''}>${role}</option>`).join('')}</select></td><td><button type="button" data-remove="${i}">Remove</button></td></tr>`).join('');
  }
  q('topoRules').addEventListener('input', event => {
    const row = event.target.closest('tr'); if (!row || !event.target.dataset.field) return;
    rules[Number(row.dataset.index)][event.target.dataset.field] = event.target.value;
    q('topoCodesReviewed').checked = false; invalidate();
  });
  q('topoRules').addEventListener('click', event => {
    if (event.target.dataset.remove === undefined) return;
    rules.splice(Number(event.target.dataset.remove),1); renderRules(); q('topoCodesReviewed').checked=false; invalidate();
  });
  async function action(fn) {
    if (busy) return; busy=true; q('topoAnalyze').disabled=true;
    try { await fn(); } catch(error) { message(error.message); }
    finally { busy=false; q('topoAnalyze').disabled=!source; }
  }
  window.topoEnter = () => action(async () => {
    const response = await fetch('/api/v9/status');
    if (!response.ok) throw new Error('Could not verify the active project. Reopen TopoSync.');
    const status = await response.json();
    const key = String(status.project?.path || status.project?.root || status.project?.project_id || 'standalone');
    if (key !== workspaceKey) {
      source=null; invalidate(); q('topoSource').textContent=''; q('topoMapping').replaceChildren(); q('topoPreview').replaceChildren();
      q('topoOrderReviewed').checked=q('topoCodesReviewed').checked=q('topoUnitsReviewed').checked=false;
      const data=await (await request('/code-rules')).json(); rules=data.rules; roles=data.roles; workspaceKey=key; renderRules();
      message('Load a survey export. Confirm units and acquisition order before recommending corrections.');
    }
  });
  q('topoSettings').innerHTML=thresholds.map(([key,label,value,min,max])=>`<label>${escape(label)}<input id="topo_${key}" type="number" value="${value}" min="${min}" max="${max}" step="${key.endsWith('_ft')?'any':'1'}"></label>`).join('');
  for (const id of ['topoHorizontal','topoVertical','topoOrder','topoOrderReviewed','topoUnitsReviewed','topoCodesReviewed','topoSettings','topoMapping']) q(id).addEventListener('input',invalidate);
  for (const id of ['topoFile','topoHeader']) q(id).addEventListener('change',()=>{source=null; invalidate();q('topoSource').textContent='Load preview to use the selected file/header setting.';q('topoMapping').replaceChildren();q('topoPreview').replaceChildren();});
  q('topoLoad').onclick=()=>action(async()=>{
    const file=q('topoFile').files[0]; if(!file)throw new Error('Choose a survey file first.');
    source=null;invalidate(); const token=revision;
    const form=new FormData();form.append('file',file);form.append('header',q('topoHeader').value);
    const data=await(await request('/survey/preview',{method:'POST',body:form})).json();
    if(token!==revision)return;
    source=data; q('topoSource').textContent=`${file.name} · ${data.row_count} points · ${data.has_header?'header detected':'headerless'} · ${data.project||'standalone workspace'}`;
    q('topoMapping').innerHTML=['point_id','northing','easting','elevation','description'].map(key=>`<label>${key==='description'?'Feature code':escape(key.replaceAll('_',' '))}<select data-map="${key}"><option value="">Choose column</option>${data.headers.map(h=>`<option value="${escape(h)}" ${data.mapping[key]===h?'selected':''}>${escape(h)}</option>`).join('')}</select></label>`).join('');
    q('topoPreview').innerHTML=`<table><thead><tr>${data.headers.map(h=>`<th>${escape(h)}</th>`).join('')}</tr></thead><tbody>${data.preview.map(row=>`<tr>${data.headers.map(h=>`<td>${escape(row[h])}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
    message('Preview loaded. Verify the column mapping, units, code list and acquisition order.');
  });
  q('topoAddCode').onclick=()=>{rules.push({code:'',description:'',role:'unknown'});renderRules();q('topoCodesReviewed').checked=false;invalidate();};
  q('topoSaveCodes').onclick=()=>action(async()=>{const data=await(await post('/code-rules/save',rules)).json();message(`Saved ${data.saved} classifications in this workspace.`);});
  q('topoImportCodes').onclick=()=>action(async()=>{
    const file=q('topoCodesFile').files[0];if(!file)throw new Error('Choose a code list first.');
    invalidate();const token=revision;const form=new FormData();form.append('file',file);
    const data=await(await request('/code-rules/import',{method:'POST',body:form})).json();if(token!==revision)return;
    rules=data.rules;renderRules();q('topoCodesReviewed').checked=false;message('Imported code list replaces the defaults. Review all suggested classifications before analysis.');
  });
  function settings() {
    const result={horizontal_units:q('topoHorizontal').value,vertical_units:q('topoVertical').value,order:q('topoOrder').value,order_confirmed:q('topoOrderReviewed').checked,units_confirmed:q('topoUnitsReviewed').checked,classifications_reviewed:q('topoCodesReviewed').checked};
    for(const [key] of thresholds){const input=q(`topo_${key}`);if(!input.value||!input.checkValidity())throw new Error(`Check ${key.replaceAll('_',' ')}.`);result[key]=Number(input.value);}
    return result;
  }
  const signed=n=>n==null?'Blocked':`${n>=0?'+':''}${n.toFixed(4)}`;
  q('topoAnalyze').onclick=()=>action(async()=>{
    if(!source)throw new Error('Load a survey first.');invalidate();const token=revision;
    const mapping=Object.fromEntries([...q('topoMapping').querySelectorAll('select')].map(el=>[el.dataset.map,el.value]));
    message('Analyzing feature chains and range boundaries…');
    const data=await(await post('/analyze',{source_id:source.source_id,mapping,rules,settings:settings()})).json();
    if(token!==revision){message('Inputs changed during analysis. Run the check again.');return;}
    run=data;renderResults();message('Analysis complete. Open each range to inspect its evidence.');
  });
  function renderResults() {
    q('topoSummary').textContent=`${run.point_count} points · ${run.chain_count} chains · ${run.probable_count} probable ranges · ${run.suppressed_count} suppressed. Elevation units: ${run.settings.vertical_units}.`;
    q('topoResults').innerHTML=`<p>${run.warnings.map(escape).join(' ')}</p>`+(run.candidates.length?run.candidates.map(c=>`<details class="topo-candidate"><summary>${escape(c.start_point)} → ${escape(c.end_point)} · shift ${signed(c.estimated_rod_bust)} · score ${c.confidence}/100 · ${escape(c.status)}</summary><p>${escape(c.reason)}</p><p>Recommended correction: <strong>${signed(c.recommended_correction)}</strong> · Offset standard deviation: ${c.offset_std_dev.toFixed(4)}</p><p>Supporting features: ${c.supporting_features.map(escape).join(', ')}</p><p>${c.blockers.map(escape).join('; ')}</p><p><strong>Exact affected IDs:</strong> ${c.affected_point_ids.map(escape).join(', ')}</p><details><summary>Chain boundaries, exclusions and score breakdown</summary><pre>${escape(JSON.stringify({chains:c.chain_evidence,nearby_exclusions:c.excluded_nearby,conflicting_points:c.conflicting_surface_points,unclassified:c.unclassified_points,score:c.score_breakdown},null,2))}</pre></details><label><input type="checkbox" data-candidate="${escape(c.candidate_id)}" ${c.correction_ready?'':'disabled'}> Select this range for a reviewed copy</label></details>`).join(''):'<p>No supported offset candidate met the selected settings. This does not establish that the survey is error-free.</p>');
    q('topoCsv').disabled=q('topoJson').disabled=false;
    q('topoCorrected').disabled=!run.candidates.some(c=>c.correction_ready);
  }
  async function exportRun(kind) {
    if(!run)throw new Error('Analyze the current inputs first.');
    const selected=[...q('topoResults').querySelectorAll('[data-candidate]:checked')].map(el=>el.dataset.candidate);
    const payload={kind,candidate_ids:selected,review_reason:q('topoReason').value,confirmed:q('topoCorrectionConfirmed').checked};
    if(kind==='corrected'&&(!selected.length||!payload.confirmed||payload.review_reason.trim().length<3))throw new Error('Select eligible ranges, enter a review reason, and confirm your review.');
    if(window.pywebview?.api?.reveal_folder){
      const result=await(await post(`/runs/${run.run_id}/save-export`,payload)).json();
      q('topoExportPath').textContent=`Saved new file: ${result.path}`;await window.pywebview.api.reveal_folder(result.folder);
    }else{
      const response=kind==='corrected'?await post(`/runs/${run.run_id}/corrected-copy`,payload):await request(`/runs/${run.run_id}/export?format=${kind}`);
      const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download=`Rod_QC_${kind}_${run.run_id.slice(0,8)}.${kind==='json'?'json':'csv'}`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
    }
    message(kind==='corrected'?'Exported a separate reviewed copy. Original observations are unchanged.':'Report exported.');
  }
  q('topoCsv').onclick=()=>action(()=>exportRun('csv'));q('topoJson').onclick=()=>action(()=>exportRun('json'));q('topoCorrected').onclick=()=>action(()=>exportRun('corrected'));
})();
