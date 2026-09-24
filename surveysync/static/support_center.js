/* SurveySync 9.3.1 Support Center */
(() => {
  const q=id=>document.getElementById(id);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function req(path,opt={}) {
    const r=await fetch('/api/v9/support'+path,opt);
    let d={}; try{d=await r.json()}catch{d={detail:await r.text()}}
    if(!r.ok) throw new Error(d.detail||`HTTP ${r.status}`);
    return d;
  }
  const post=(path,data={})=>req(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  let last=null;

  function statusBadge(value){
    const v=String(value||'local_only').replaceAll('_',' ');
    return `<span class="brand-badge">${esc(v.toUpperCase())}</span>`;
  }
  function render(data){
    last=data;
    const counts=data.error_counts||{};
    if(q('supportMetrics')) q('supportMetrics').innerHTML=[
      ['Local',counts.local_only||0],['Pending',counts.pending||0],
      ['Synced',counts.synced||0],['Resolved',counts.resolved||0]
    ].map(([label,n])=>`<div class="metric"><b>${n}</b><small>${label}</small></div>`).join('');

    const errors=Array.isArray(data.errors)?data.errors:[];
    if(q('supportErrors')) q('supportErrors').innerHTML=errors.length?errors.map(e=>{
      const sync=e.sync||{};
      return `<div class="support-row"><div><b>${esc(e.code||e.error_id)}</b> ${statusBadge(sync.status)}<div class="muted">${esc(e.created_utc||'')} · ${esc(e.component||'')}</div><div>${esc(e.message||'')}</div><details><summary>Technical detail</summary><pre>${esc(e.detail||'No stack detail recorded.')}</pre></details></div><div class="support-actions"><button class="secondary" data-sync-error="${esc(e.error_id)}">Sync</button><button class="primary" data-report-error="${esc(e.error_id)}">Report This Error</button></div></div>`;
    }).join(''):'<p class="muted">No local SurveySync errors are recorded.</p>';

    const feedback=Array.isArray(data.feedback)?data.feedback:[];
    if(q('supportFeedback')) q('supportFeedback').innerHTML=feedback.length?feedback.map(f=>{
      const local=f.local_sync||{};
      const state=f.tracker_status||local.status||'local_only';
      const released=f.released_in?` · released in ${esc(f.released_in)}`:'';
      return `<div class="support-row"><div><b>${esc(f.intake_id||f.report_id)}</b> ${statusBadge(state)}<div>${esc(f.title||'Untitled feedback')}</div><div class="muted">${esc(f.report_type||'')} · v${esc(f.app_version||'')}${released}</div></div></div>`;
    }).join(''):'<p class="muted">No Feedback Wizard reports are stored in the active workspace.</p>';

    const rec=data.recovery||{};
    if(q('supportRecovery')) {
      if(rec.unclean_shutdown_detected){
        const snap=rec.latest_recovery_snapshot;
        q('supportRecovery').innerHTML=`<div class="notice warn"><b>Interrupted SurveySync session detected.</b><br>${rec.previous_project_matches_current?'The currently open project matches the interrupted session.':'Open the project used by the interrupted session to enable restore.'}${snap?`<br>Latest recovery snapshot: ${esc(snap.created_utc||'')}`:''}</div><div class="row"><button id="supportRestoreRecovery" class="primary" ${rec.restore_available?'':'disabled'}>Restore Latest Recovery Snapshot</button><button id="supportDismissRecovery" class="secondary">Dismiss</button></div>`;
        q('supportRestoreRecovery')?.addEventListener('click',async()=>{
          if(!confirm('Restore the latest automatic recovery snapshot? SurveySync will create a safety snapshot before restoring.')) return;
          try{await post('/recovery/restore-latest',{confirmed:true});location.reload()}catch(e){toast(e.message)}
        });
        q('supportDismissRecovery')?.addEventListener('click',async()=>{try{await post('/recovery/dismiss',{});await load()}catch(e){toast(e.message)}});
      }else{
        q('supportRecovery').innerHTML='<div class="notice good"><b>Session state is clean.</b><br>Automatic project recovery snapshots remain available in Review & Operations.</div>';
      }
    }
    q('supportErrors')?.querySelectorAll('[data-sync-error]').forEach(b=>b.onclick=async()=>{try{await post('/errors/sync',{error_ids:[b.dataset.syncError]});toast('Error log synced');await load()}catch(e){toast(e.message)}});
    q('supportErrors')?.querySelectorAll('[data-report-error]').forEach(b=>b.onclick=async()=>{try{const d=await post('/errors/report',{error_id:b.dataset.reportError});toast(d.sync?.intake_id?`Reported as ${d.sync.intake_id}`:'Report saved locally; sync is pending');await load()}catch(e){toast(e.message)}});
  }

  async function load(){
    try{
      const data=await req('/summary');
      render(data);
      if(q('supportStatus')) q('supportStatus').textContent=data.auto_sync?.scheduled?'Retrying pending diagnostics in the background.':'Support state refreshed.';
      return data;
    }catch(e){
      if(q('supportStatus')) q('supportStatus').textContent=e.message;
      throw e;
    }
  }

  async function downloadDiagnostics(){
    const r=await fetch('/api/v9/diagnostics/export',{method:'POST'});
    if(!r.ok) throw new Error((await r.text())||`HTTP ${r.status}`);
    const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');
    const disposition=r.headers.get('content-disposition')||'';
    const match=/filename="?([^"]+)"?/i.exec(disposition);
    a.href=url;a.download=match?.[1]||'SurveySync_Diagnostics.zip';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
  }

  q('supportRefresh')?.addEventListener('click',()=>load().catch(e=>toast(e.message)));
  q('supportSyncAll')?.addEventListener('click',async()=>{try{await post('/errors/sync',{error_ids:[]});toast('Pending error logs synced');await load()}catch(e){toast(e.message)}});
  q('supportRefreshFeedback')?.addEventListener('click',async()=>{try{const d=await post('/feedback/refresh',{local_report_ids:[]});toast(d.available?'Feedback status refreshed':d.message||'Tracker status unavailable');await load()}catch(e){toast(e.message)}});
  q('supportDiagnostics')?.addEventListener('click',()=>downloadDiagnostics().catch(e=>toast(e.message)));
  q('supportOpenFeedback')?.addEventListener('click',()=>openGlobalFeedbackWizard());

  window.supportEnter=()=>load().catch(()=>{});
  window.supportStartup=async()=>{
    try{
      const data=await req('/summary');
      const rec=data.recovery||{};
      if(!rec.unclean_shutdown_detected) return;
      if(rec.restore_available){
        if(confirm('SurveySync detected that the previous session did not close normally. Restore the latest automatic recovery snapshot for this project?')){
          await post('/recovery/restore-latest',{confirmed:true});location.reload();return;
        }
      }
      toast('SurveySync detected an interrupted previous session. Open Support Center to review recovery options.');
    }catch{}
  };
  setTimeout(()=>window.supportStartup?.(),1400);
})();
