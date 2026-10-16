/* FieldBookSync content adapter. SurveySync owns navigation, identity and theme. */
'use strict';
(() => {
  let frame = null, context = null, ready = false, requestSerial = 0;
  let wantedTab = 'dashboard', pendingAction = null, deadline = null;
  const tabs = new Set(['dashboard','review','map','index','batch','profiles','training','engine','history','options','help']);
  const el = id => document.getElementById(id);
  const key = p => p?.project_id ? `${p.project_id}|${p.root}` : '__none__';
  const accepts = source => !!frame && source === frame.contentWindow;
  function message(text, retry = false) {
    const note = el('fieldbookLoadMessage');
    if (!note) return;
    note.textContent = text;
    el('fieldbookLoadStatus').hidden = false;
    el('fieldbookRetry').hidden = !retry;
  }
  function theme() {
    if (!ready || !frame) return;
    const child = frame.contentWindow, root = document.documentElement;
    const computed = getComputedStyle(root), variables = {};
    for (const name of computed) if (name.startsWith('--')) variables[name] = computed.getPropertyValue(name);
    child.ssFieldBookClient?.applyTheme({...root.dataset}, variables);
  }
  function dispose() {
    clearTimeout(deadline); deadline = null; ready = false;
    frame?.remove(); frame = null; context = null;
  }
  function finish() {
    if (!ready || !frame) return;
    const child = frame.contentWindow;
    child.ssFieldBookClient?.setTab(wantedTab);
    theme();
    if (pendingAction) {
      const action = pendingAction; pendingAction = null;
      child.ssFieldBookClient?.action(action.name, action.value);
    }
  }
  async function ensure(supportOnly = false, force = false) {
    const serial = ++requestSerial;
    try {
      const response = await fetch('/api/v9/fieldbook/context', {cache:'no-store'});
      const current = await response.json();
      if (serial !== requestSerial) return;
      if (!response.ok) throw new Error(current.detail || 'Project context unavailable.');
      if (current.project_id && !current.bound) throw new Error('FieldBookSync is not attached to this project. Reopen the project before continuing.');
      if (frame && (force || key(current) !== key(context))) dispose();
      if (!current.project_id && !supportOnly && !frame) {
        message('Open or create a SurveySync project to use FieldBookSync. Feedback remains available from Help.');
        el('fieldbookProjectActions').hidden = false;
        return;
      }
      el('fieldbookProjectActions').hidden = true;
      context = current;
      if (frame) { finish(); return; }
      ready = false;
      message(current.project_id ? `Opening FieldBookSync for ${current.name}…` : 'Opening feedback without a project…');
      const iframe = document.createElement('iframe');
      iframe.id = 'fieldbookFrame'; iframe.title = 'FieldBookSync workspace';
      iframe.allow = 'clipboard-read; clipboard-write; fullscreen';
      iframe.src = '/fieldbook?' + new URLSearchParams({embedded:'1',ss_project:current.token,
        support:current.project_id ? '0' : '1'});
      frame = iframe;
      el('fieldbookFrameMount').append(iframe);
      deadline = setTimeout(() => {
        if (frame === iframe && !ready) message('FieldBookSync did not finish loading. Your saved project has not been reset. Retry the view.', true);
      }, 30000);
    } catch (error) {
      if (serial === requestSerial) message(error.message, true);
    }
  }
  function enter(tab) {
    wantedTab = tabs.has(tab) ? tab : 'dashboard';
    ensure(!!pendingAction);
  }
  function onReady(source, error = '') {
    if (!accepts(source)) return;
    clearTimeout(deadline);
    if (error) { message(`FieldBookSync could not load: ${error}`, true); return; }
    ready = true;
    el('fieldbookLoadStatus').hidden = true;
    finish();
  }
  function changedTab(source, tab) {
    if (!accepts(source) || !tabs.has(tab)) return;
    wantedTab = tab;
    if (typeof activeModule !== 'undefined' && activeModule === 'FieldBookSync' && activeView !== 'fieldbook:' + tab) {
      switchView('fieldbook:' + tab);
    }
  }
  function openAction(name, value = '') {
    pendingAction = {name, value};
    switchModule('FieldBookSync');
  }
  function syncProject(project) {
    if (context && key(project) !== key(context)) {
      ++requestSerial; dispose(); pendingAction = null; wantedTab = 'dashboard';
      if (activeModule === 'FieldBookSync') switchView('fieldbook:dashboard');
    }
  }
  function mayChangeProject() {
    if (!ready || !frame || !frame.contentWindow.ssFieldBookClient?.hasPendingEdits()) return true;
    return window.confirm('The FieldBookSync workspace contains entered values, selected files, or an open dialog. Switching projects closes this view. Continue?');
  }
  function command(cmd) {
    if (!ready) { message('FieldBookSync is still loading. Try the command again when it is ready.'); return; }
    frame.contentWindow.ssFieldBookClient?.action('command', cmd);
  }
  function parentCommand(source, cmd) {
    if (!accepts(source)) return;
    const allowed = new Set(['new-project','open-project','manage-projects','settings','fullscreen','check-update','about','exit-app']);
    if (allowed.has(cmd)) runCommand(cmd);
  }
  window.ssFieldBook = {enter, onReady, changedTab, openAction, syncProject, mayChangeProject,
    command, parentCommand, theme, lastTab:() => wantedTab};
  document.addEventListener('DOMContentLoaded', () => {
    el('fieldbookRetry').onclick = () => {
      if (mayChangeProject()) ensure(!!pendingAction || context?.token === '__none__', true);
    };
    document.addEventListener('click', event => {
      const button = event.target.closest('[data-fbs-command]');
      if (button) { closeMenus(); command(button.dataset.fbsCommand); }
    });
    new MutationObserver(theme).observe(document.documentElement, {attributes:true,
      attributeFilter:['data-theme','data-theme-mode','data-product-theme','data-accent']});
  });
  window.addEventListener('pywebviewready', () => {
    if (frame) frame.contentWindow.dispatchEvent(new Event('pywebviewready'));
  });
})();
