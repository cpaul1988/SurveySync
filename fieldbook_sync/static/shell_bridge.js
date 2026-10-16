/* Same-origin adapter: legacy processing UI is content, never a second shell. */
'use strict';
(() => {
  const params = new URLSearchParams(location.search);
  if (window.top === window) {
    const next = new URLSearchParams({module:'FieldBookSync'});
    for (const key of ['feedback','feedback_type','feedback_log','rod_height_qc']) {
      if (params.has(key)) next.set(key, params.get(key));
    }
    location.replace('/?' + next);
    return;
  }
  if (params.get('embedded') !== '1' || window.parent.location.origin !== location.origin || !window.parent.ssFieldBook) return;
  document.documentElement.dataset.ssEmbedded = '1';
  if (params.get('support') === '1') document.documentElement.dataset.supportOnly = '1';
  const host = window.parent.ssFieldBook, token = params.get('ss_project') || '__none__';
  const transport = window.fetch.bind(window);
  let enteredValues = false;
  // Capture this view's token, not a mutable global. Late requests from a stale
  // view must be rejected, including uploads and downloads bypassing api().
  function scoped(value) {
    const url = new URL(value, location.href);
    return url.origin === location.origin && url.pathname.startsWith('/api/');
  }
  function downloadUrl(value) {
    const url = new URL(value, location.href);
    if (scoped(url)) url.searchParams.set('ss_project', token);
    return url.href;
  }
  window.ssFieldbookDownload = value => { location.href = downloadUrl(value); };
  window.fetch = async (input, options = {}) => {
    const value = input instanceof Request ? input.url : input;
    if (!scoped(value)) return transport(input, options);
    const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
    headers.set('X-SurveySync-Project', token);
    const response = await transport(input, {...options, headers});
    const method = String(options.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (response.ok && method !== 'GET' && !String(value).includes('/feedback')) enteredValues = false;
    return response;
  };
  const open = XMLHttpRequest.prototype.open, send = XMLHttpRequest.prototype.send;
  const scopedXhr = new WeakSet();
  XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    if (scoped(url)) scopedXhr.add(this); else scopedXhr.delete(this);
    return open.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function(body) {
    if (scopedXhr.has(this)) this.setRequestHeader('X-SurveySync-Project', token);
    return send.call(this, body);
  };
  // pywebview installs the native picker bridge in the top-level window only.
  Object.defineProperty(window, 'pywebview', {configurable:true, get:() => window.parent.pywebview});
  document.addEventListener('input', event => {
    if (event.isTrusted) enteredValues = true;
  }, true);
  document.addEventListener('click', event => {
    const anchor = event.target.closest('a[href]');
    if (anchor && scoped(anchor.href)) anchor.href = downloadUrl(anchor.href);
  }, true);
  document.addEventListener('keydown', event => {
    const mod = event.ctrlKey || event.metaKey, key = event.key.toLowerCase();
    const cmd = mod && key === 'n' ? 'new-project' : mod && key === 'o' ?
      (event.shiftKey ? 'manage-projects' : 'open-project') : event.key === 'F11' ? 'fullscreen' : '';
    if (cmd) { event.preventDefault(); event.stopImmediatePropagation(); host.parentCommand(window, cmd); }
  }, true);
  function action(name, value) {
    let result;
    if (name === 'feedback') result = openFeedbackWizard(value);
    else if (name === 'feedback_log') result = openFeedbackLog();
    else if (name === 'rod_height_qc') result = document.getElementById('rodBustBtn')?.click();
    else if (name === 'command') result = command(value);
    Promise.resolve(result).catch(error => toast(error.message, 'error'));
  }
  window.ssFieldBookClient = {
    ready:error => host.onReady(window, error || ''),
    changedTab:tab => host.changedTab(window, tab),
    parentCommand:cmd => host.parentCommand(window, cmd),
    setTab:tab => {
      const selected = document.querySelector('.view.active')?.id;
      if (selected !== `tab-${tab}`) switchTab(tab);
    },
    action,
    hasPendingEdits:() => enteredValues || !!document.querySelector('#modal:not(.hidden)') ||
      [...document.querySelectorAll('input[type=file]')].some(input => input.files?.length),
    applyTheme:(data, variables) => {
      const root = document.documentElement;
      for (const key of ['theme','themeMode','productTheme','accent']) if (data[key]) root.dataset[key] = data[key];
      for (const [name,value] of Object.entries(variables)) root.style.setProperty(name, value);
      if (typeof updateOptionControls === 'function') updateOptionControls();
    },
  };
})();
