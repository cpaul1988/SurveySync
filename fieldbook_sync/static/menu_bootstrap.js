(() => {
  'use strict';
  const q = (s, r=document) => r.querySelector(s);
  const qa = (s, r=document) => [...r.querySelectorAll(s)];

  function closeMenus(except=null){
    qa('.desktop-menu').forEach(m => { if (m !== except) m.classList.add('hidden'); });
    qa('.menu-trigger').forEach(b => {
      if (!except || b.dataset.menu !== except.id) b.classList.remove('open');
    });
  }

  function openMenu(button){
    const id = button?.dataset?.menu;
    const menu = id ? document.getElementById(id) : null;
    if (!menu) return;
    const wasOpen = !menu.classList.contains('hidden');
    closeMenus();
    if (wasOpen) return;
    const r = button.getBoundingClientRect();
    menu.style.left = `${Math.max(4, Math.min(r.left, window.innerWidth - 260))}px`;
    menu.style.top = `${Math.min(r.bottom, window.innerHeight - 40)}px`;
    menu.classList.remove('hidden');
    button.classList.add('open');
  }

  // Bind as early as possible and use event delegation so a later UI error cannot
  // leave the native-style menu bar inert.
  document.addEventListener('click', (event) => {
    const trigger = event.target.closest?.('.menu-trigger');
    if (trigger) {
      event.preventDefault();
      event.stopPropagation();
      openMenu(trigger);
      return;
    }
    if (!event.target.closest?.('.desktop-menu')) closeMenus();
  }, true);

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeMenus();
  }, true);

  window.addEventListener('blur', () => closeMenus());
  window.addEventListener('resize', () => closeMenus());
  window.__fbsMenuBootstrapReady = true;
  window.FBSMenuBootstrap = { closeMenus, openMenu };
})();
