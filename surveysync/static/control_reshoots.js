/* ControlSync reshoot handoff. Raw returns stay staged until reviewed. */
(() => {
  'use strict';
  const q=id=>document.getElementById(id);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let requests=[],run=null;
  const message=text=>{q('reshootMessage').textContent=text};
  async function json(url,body){const response=await fetch(url,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});if(!response.ok){let detail;try{detail=(await response.json()).detail}catch{}throw Error(detail||`Request failed (${response.status})`)}return response.json()}
  async function download(url,name){const response=await fetch(url,{cache:'no-store'});if(!response.ok){let detail;try{detail=(await response.json()).detail}catch{}throw Error(detail||`Download failed (${response.status})`)}const link=document.createElement('a'),blob=await response.blob(),object=URL.createObjectURL(blob);link.href=object;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(object),1000)}
  const metric=v=>v==null?'—':Number(v).toFixed(4);
  function render(){
    const previous=q('reshootControl').value;
    const failed=(run?.results||[]).filter(x=>x.status==='RESHOOT');
    q('reshootControl').innerHTML=failed.map(x=>`<option value="${esc(x.control_id)}">${esc(x.control_id)} · ${esc(x.reason)}</option>`).join('')||'<option value="">Run Control QC to find failed controls</option>';
    if(failed.some(x=>x.control_id===previous))q('reshootControl').value=previous;
    q('reshootRequests').innerHTML=requests.map(x=>{const before=x.before?.selected||{},after=x.return?.preview?.selected||{},preview=x.return?.preview||{},review=x.review||{};
      const comparison=x.return?`<div class="notice ${preview.status==='PASS'&&preview.uses_returned_shot?'good':'warn'}"><b>Before ${esc(x.before.status)} → Preview ${esc(preview.status)}</b> · ${esc(preview.reason)}<br>H residual ${metric(before.max_horizontal_residual)} → ${metric(after.max_horizontal_residual)} · V residual ${metric(before.max_vertical_residual)} → ${metric(after.max_vertical_residual)}<br>Selected shots: ${esc((after.point_ids||[]).join(', ')||'none')} · Field QC: ${esc(after.field_validation?.status||'UNVERIFIED')}${x.return.ignored_point_ids?.length?`<br>Other source points ignored: ${esc(x.return.ignored_point_ids.join(', '))}`:''}</div>`:'';
      return `<div class="card-sub" style="margin-top:12px"><b>Control ${esc(x.control_id)} · ${esc(x.status)}</b> · ${esc(x.crew)}<br><small>Request ${esc(x.id.slice(0,12))} · Assigned ${esc(x.reserved_point_ids.join(', '))}</small><p>${esc(x.instructions)}</p>${comparison}${review.decision?`<p>Reviewed by ${esc(review.reviewer)}: ${esc(review.note)}</p>`:''}<div class="row"><button class="secondary" data-action="package" data-id="${esc(x.id)}">Crew packet</button>${x.status==='OPEN'?`<button class="secondary" data-action="stage" data-id="${esc(x.id)}">Stage returned file</button>`:''}${x.status==='STAGED'?`<button class="primary" data-action="approve" data-id="${esc(x.id)}" ${preview.status==='PASS'&&preview.uses_returned_shot?'':'disabled'}>Approve passing return</button><button class="secondary" data-action="reject" data-id="${esc(x.id)}">Reject return</button>`:''}${x.status==='APPROVED'?`<button class="primary" data-action="export" data-id="${esc(x.id)}">Download approved control</button>`:''}</div></div>`;
    }).join('')||'<p class="muted">No reshoot requests in this project.</p>';
  }
  async function refresh(qcRun){if(arguments.length)run=qcRun||null;try{requests=(await json('/api/v9/control/reshoots')).requests;render()}catch(e){message(e.message)}}
  window.controlReshootRefresh=refresh;
  q('reshootCreate').onclick=async()=>{try{if(!run?.run_id||!q('reshootControl').value)throw Error('Choose a failed control from the current QC run.');await json('/api/v9/control/reshoots',{run_id:run.run_id,control_id:q('reshootControl').value,crew:q('reshootCrew').value,instructions:q('reshootInstructions').value});await refresh();message('Reshoot request issued. Download its crew packet.')}catch(e){message(e.message)}};
  q('reshootBrowse').onclick=async()=>{const path=await chooseFile(['Control returns (*.csv;*.txt;*.tsv;*.job;*.jxl;*.xml)','All files (*.*)']);if(path)q('reshootReturnPath').value=path};
  q('reshootRequests').onclick=async e=>{const button=e.target.closest('button[data-action]');if(!button)return;const id=button.dataset.id,action=button.dataset.action,base='/api/v9/control/reshoots/'+encodeURIComponent(id);button.disabled=true;try{
    if(action==='package')await download(base+'/crew-package','Control_Reshoot_Request.zip');
    else if(action==='export')await download(base+'/approved-package','Control_Reshoot_Approved.zip');
    else if(action==='stage'){if(!q('reshootReturnPath').value.trim())throw Error('Choose the crew’s returned file.');await json(base+'/return',{file_path:q('reshootReturnPath').value.trim()});await refresh();message('Returned shots staged. Check the before/after QC evidence before approving.')}
    else {const reviewer=q('reshootReviewer').value.trim(),note=q('reshootReviewNote').value.trim();if(!reviewer||note.length<3)throw Error('Enter reviewer and a review note of at least three characters.');if(action==='approve'&&!confirm('Approve this passing return, add its shots to the project, and create a new active QC solution?'))return;await json(base+'/review',{decision:action==='approve'?'APPROVE':'REJECT',reviewer,note});await refresh();if(action==='approve')await loadControls();message(action==='approve'?'Returned shots approved. Download the reviewed control package.':'Returned file rejected; project control is unchanged.')}
  }catch(error){message(error.message)}finally{button.disabled=false}};
})();
