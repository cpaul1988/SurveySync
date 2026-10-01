/* Reusable local-coordinate workspace state. Never persist record selection. */
(() => {
  'use strict';
  class RecordSelection {
    constructor() { this.ids = new Set(); this.active = null; }
    replace(ids) { this.ids = new Set(ids); this.active = this.ids.values().next().value || null; }
    toggle(id) {
      if (this.ids.has(id)) this.ids.delete(id); else this.ids.add(id);
      this.active = this.ids.has(id) ? id : this.ids.values().next().value || null;
    }
    clear() { this.replace([]); }
  }
  const presets = {
    control: {left: 210, right: 340, bottom: 280},
    boundary: {left: 190, right: 280, bottom: 220},
    topo: {left: 230, right: 320, bottom: 380}
  };
  const limits = {left: [160, 340], right: [240, 460], bottom: [180, 520]};
  class WorkspaceLayout {
    constructor(root, key) {
      this.root = root; this.key = key; this.state = {...presets.control};
      try {
        const saved = JSON.parse(localStorage.getItem(key));
        for (const axis of Object.keys(limits)) if (Number.isFinite(saved?.[axis])) {this.set(axis, saved[axis]);this.restored = true;}
      } catch (error) { this.storageError = error.message; }
      this.apply();
      for (const handle of root.querySelectorAll('[data-workspace-size]')) this.bind(handle);
    }
    set(axis, value) { const [min, max] = limits[axis]; this.state[axis] = Math.min(max, Math.max(min, value)); }
    apply() {
      for (const [axis, value] of Object.entries(this.state)) {
        this.root.style.setProperty(`--workspace-${axis}`, value + 'px');
        const handle = this.root.querySelector(`[data-workspace-size="${axis}"]`);
        if (handle) {
          handle.setAttribute('aria-valuenow', Math.round(value));
          handle.setAttribute('aria-valuemin', limits[axis][0]);
          handle.setAttribute('aria-valuemax', limits[axis][1]);
        }
      }
    }
    preset(name) { this.state = {...presets[name] || presets.control}; this.apply(); }
    save() {
      try { localStorage.setItem(this.key, JSON.stringify(this.state)); return true; }
      catch (error) { this.storageError = error.message; return false; }
    }
    bind(handle) {
      const axis = handle.dataset.workspaceSize;
      let drag = null;
      handle.addEventListener('pointerdown', event => {
        if (this.root.closest('fieldset')?.disabled) return;
        drag = {start: axis === 'bottom' ? event.clientY : event.clientX, size: this.state[axis]};
        handle.setPointerCapture(event.pointerId); event.preventDefault();
      });
      handle.addEventListener('pointermove', event => {
        if (!drag) return;
        const delta = (axis === 'bottom' ? event.clientY : event.clientX) - drag.start;
        this.set(axis, drag.size + delta * (axis === 'right' ? -1 : 1)); this.apply();
      });
      handle.addEventListener('pointerup', () => { drag = null; });
      handle.addEventListener('pointercancel', () => { drag = null; });
      handle.addEventListener('keydown', event => {
        if (this.root.closest('fieldset')?.disabled) return;
        const negative = axis === 'bottom' ? 'ArrowUp' : 'ArrowLeft';
        const positive = axis === 'bottom' ? 'ArrowDown' : 'ArrowRight';
        if (![negative, positive, 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        let value = this.state[axis] + (event.key === positive ? 20 : -20) * (axis === 'right' ? -1 : 1);
        if (event.key === 'Home') value = limits[axis][0];
        if (event.key === 'End') value = limits[axis][1];
        this.set(axis, value); this.apply();
      });
    }
  }
  window.SurveyWorkspace = Object.freeze({RecordSelection, WorkspaceLayout});
})();
