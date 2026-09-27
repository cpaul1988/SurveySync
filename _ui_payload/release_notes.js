const SS_RELEASE_SEEN_KEY='surveysync-release-notes-seen-v2';
let releaseNotesData={version:'',release_id:'',notes:[]};
let releaseNotesLoading=null;
function releaseLabel(d){return String(d?.release_id||d?.version||'').replace(/^v/,'')}
function notesWereSeen(id){try{return localStorage.getItem(SS_RELEASE_SEEN_KEY)===id}catch{return false}}
function markNotesSeen(id){try{localStorage.setItem(SS_RELEASE_SEEN_KEY,id)}catch(e){console.warn('Release-note acknowledgment could not be saved',e)}}
async function loadReleaseNotes(showOnUpgrade=true){
  if(releaseNotesLoading)return releaseNotesLoading;
  releaseNotesLoading=(async()=>{
    const controller=new AbortController();
    const timeout=setTimeout(()=>controller.abort(),8000);
    try{
      const d=await api('/api/v9/release-notes',{signal:controller.signal,cache:'no-store'});
      if(!d||!Array.isArray(d.notes)||!d.notes.length)throw new Error('The installed release notes are unavailable.');
      releaseNotesData=d;
      const id=String(d.release_id||d.version||'').trim(),label=releaseLabel(d);
      if($('#whatsNewTitle'))$('#whatsNewTitle').textContent=`What's new in SurveySync`;
      if($('#whatsNewVersion'))$('#whatsNewVersion').textContent=label?`v${label}`:'Latest';
      if($('#workspaceBuild'))$('#workspaceBuild').textContent=`SurveySync v${label}`;
      if($('#whatsNewList'))$('#whatsNewList').innerHTML=d.notes.slice(0,3).map(x=>`<li>${esc(x)}</li>`).join('');
      if(showOnUpgrade&&id&&!notesWereSeen(id))openReleaseNotes(true);
      return d;
    }catch(e){
      const message=e.name==='AbortError'?'Release notes took too long to load.':e.message;
      if($('#whatsNewList')){
        $('#whatsNewList').innerHTML=`<li>${esc(message)} <button id="retryReleaseNotes" class="link-btn" type="button">Retry</button></li>`;
        $('#retryReleaseNotes').onclick=()=>loadReleaseNotes(true);
      }
      console.warn('Release notes:',message);
      return null;
    }finally{clearTimeout(timeout);releaseNotesLoading=null}
  })();
  return releaseNotesLoading;
}
function openReleaseNotes(markSeen=false){
  const d=releaseNotesData||{},releaseId=String(d.release_id||d.version||'').trim();
  if(!Array.isArray(d.notes)||!d.notes.length){
    loadReleaseNotes(false).then(loaded=>{if(loaded)openReleaseNotes(markSeen);else toast('Release notes could not be loaded. Use Retry on Home.')});
    return;
  }
  openModalShell('release-notes');
  $('#modalBody').innerHTML=`<div class="release-dialog"><div class="brand-lockup"><img class="brand-lockup-icon" src="/surveysync-static/surveysync_globe.svg" alt=""><div><div class="brand-lockup-name">SurveySync</div><div class="brand-lockup-tagline">UNIFYING GLOBAL DATA</div></div></div><div class="eyebrow">WHAT'S NEW</div><h2>SurveySync v${esc(releaseLabel(d))}</h2><p class="muted">Installed release notes. Available without an internet connection.</p><ul class="release-list">${d.notes.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><div class="row"><button id="releaseDone" class="primary">Continue</button></div></div>`;
  $('#releaseDone').onclick=()=>{if(markSeen&&releaseId)markNotesSeen(releaseId);closeModalShell()};
}
