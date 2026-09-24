/* SurveySync 9.3.1 Survey Data Inspector */
(() => {
  const q=id=>document.getElementById(id);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let current=null;
  async function req(path,opt={}) {
    const r=await fetch('/api/v9/data-inspector'+path,opt);
    let d={};try{d=await r.json()}catch{d={detail:await r.text()}}
    if(!r.ok)throw new Error(d.detail||`HTTP ${r.status}`);
    return d;
  }
  const post=(path,data={})=>req(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});

  function render(d){
    current=d;
    const range=d.numeric_point_id_min==null?'—':`${d.numeric_point_id_min}–${d.numeric_point_id_max}`;
    q('inspectorResult').innerHTML=`<div class="metrics"><div class="metric"><b>${d.row_count||0}</b><small>records</small></div><div class="metric"><b>${d.unique_code_count||0}</b><small>unique codes</small></div><div class="metric"><b>${(d.duplicate_point_ids||[]).length}</b><small>duplicate IDs</small></div><div class="metric"><b>${d.missing_elevation_count||0}</b><small>missing Z</small></div></div><div class="notice"><b>${esc(d.source_name)}</b><br>${esc(d.format)} · Point range ${esc(range)} · ${esc(d.crs_status)} · ${esc(d.units_status)}<br>SHA-256: <code>${esc(String(d.source_sha256||'').slice(0,20))}…</code>${d.cached?' · cached':''}</div>${(d.coordinate_outliers_suspected||[]).length?`<div class="notice warn"><b>Coordinate review:</b> suspected remote outliers: ${d.coordinate_outliers_suspected.map(esc).join(', ')}</div>`:''}`;
    const headers=d.headers||[],preview=d.preview||[];
    q('inspectorPreview').innerHTML=preview.length?`<div class="topo-scroll"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${preview.map(row=>`<tr>${headers.map(h=>`<td>${esc(row[h])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:'';
    const targets=d.targets||[];
    q('inspectorTargets').innerHTML=targets.length?targets.map(t=>`<button class="secondary" data-inspector-target="${esc(t.id)}" title="${esc(t.reason)}">Send to ${esc(t.label)}</button>`).join(''):'<span class="muted">No downstream workflow has enough mapped fields yet.</span>';
    q('inspectorTargets').querySelectorAll('[data-inspector-target]').forEach(b=>b.onclick=()=>handoff(b.dataset.inspectorTarget));
  }

  function handoff(target){
    if(!current)return;
    const path=current.normalized_path||current.source_path;
    if(target==='topo'){
      localStorage.setItem('surveysync-inspector-topo-path',path);
      switchModule('TopoSync');switchView('rodQc','Rod Height Bust QC');window.topoLoadInspectorPath?.(path);
    }else if(target==='control'){
      switchModule('ControlSync');switchView('control','Average & QC');if(q('controlPath'))q('controlPath').value=path;toast('Inspector source loaded into ControlSync path.');
    }else if(target==='point_ranges'){
      switchModule('ReportSync');switchView('reports','Point Range Report');if(q('rangeSource'))q('rangeSource').value='file';if(q('rangePath'))q('rangePath').value=path;toast('Inspector source loaded into Point Range.');
    }
  }

  async function loadRecent(){
    try{
      const d=await req('/recent');
      q('inspectorRecent').innerHTML=(d.items||[]).map(x=>`<div class="support-row"><div><b>${esc(x.source_name)}</b><div class="muted">${esc(x.inspected_utc)} · ${x.row_count} rows · ${esc(x.format)}</div><div class="path-text">${esc(x.source_path)}</div></div><button class="secondary" data-reinspect="${esc(x.source_path)}">Inspect</button></div>`).join('')||'<p class="muted">No cached sources yet.</p>';
      q('inspectorRecent').querySelectorAll('[data-reinspect]').forEach(b=>b.onclick=()=>{q('inspectorPath').value=b.dataset.reinspect;inspect(false)});
    }catch(e){q('inspectorRecent').textContent=e.message}
  }
  async function inspect(force){
    const path=q('inspectorPath').value.trim();if(!path){toast('Choose a survey file first.');return}
    q('inspectorStatus').textContent='Inspecting survey source…';
    try{const d=await post('/inspect',{file_path:path,force_refresh:!!force});render(d);q('inspectorStatus').textContent=d.cached?'Loaded cached inspection.':'Inspection complete.';await loadRecent()}catch(e){q('inspectorStatus').textContent=e.message;toast(e.message)}
  }

  q('inspectorBrowse')?.addEventListener('click',async()=>{const path=await chooseFile(['Survey files (*.csv;*.txt;*.tsv;*.pnezd;*.asc;*.job;*.jxl;*.xml)','All files (*.*)'],pathDirectory(q('inspectorPath').value));if(path)q('inspectorPath').value=path});
  q('inspectorRun')?.addEventListener('click',()=>inspect(false));
  q('inspectorRefresh')?.addEventListener('click',()=>inspect(true));
  q('inspectorClearCache')?.addEventListener('click',async()=>{if(!confirm('Clear cached Survey Data Inspector results? Original survey files are not touched.'))return;try{const d=await post('/cache/clear',{});toast(`Cleared ${d.removed} cached files`);current=null;q('inspectorResult').innerHTML='';q('inspectorPreview').innerHTML='';q('inspectorTargets').innerHTML='';await loadRecent()}catch(e){toast(e.message)}});

  window.dataInspectorEnter=()=>loadRecent();
})();
