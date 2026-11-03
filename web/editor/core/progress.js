/**
 * Editor core: the one non-blocking progress indicator (lot L22).
 *
 * Purpose :  startTask() / track() register slow operations; every running task feeds ONE thin bar fixed at the very
 *            top of the window (#progress, 3 px, above the toolbar) and a small label chip
 *            (#progChip at the right end of the toolbar, e.g. "Export de l'image… 42 %", clickable to cancel when the
 *            task supports it).
 * Boundary:  DOM of #progress / #progChip / #main (aria-busy) only; no network call (core/api.js registers its fetches
 *            here). The bar is in editor.html from the first paint (boot indicator before any module ran); this module
 *            adopts it.
 * Invariants:
 *   - Never blocks: the bar has pointer-events:none and sits in the 3 px strip above the toolbar buttons (the toolbar
 *     has a 6 px top padding); the chip lives in #progSlot, the last toolbar item (flex basis 0, always in the layout),
 *     so showing it never moves or wraps the toolbar. Nothing here disables a control or sets a busy cursor.
 *   - Aggregate: several tasks share the bar. Determinate (percent) when at least one shown task knows its progress
 *     (mean of the known ones, never going back while the same tasks run), indeterminate stripe otherwise.
 *   - A task with `delay` (default 0 here, 300 ms for automatic fetches) is shown only if it is still running after
 *     the delay: fast calls never flash the bar.
 *   - fail() turns the bar red for ERR_MS, even before the show delay (the caller shows its existing toast;
 *     fail(msg) toasts for it).
 *   - All tasks ended: short fade (FADE_MS), then `hidden`.
 * Depends :  core/util.js, core/ui.js
 * Test    :  web scenario `progress` (tests/web/progress.py; .venv/bin/python -m tests.web.run progress) through the
 *            window.__editor.progress() hook.
 */
import { $ } from './util.js';
import { toast } from './ui.js';

const FADE_MS = 400, ERR_MS = 1500;
const tasks = new Map();          // id -> task record (running only)
const log = [];                   // last 40 finished / running task records (test hook, harmless)
let seq = 0, shownFrac = null, shownSet = '', errUntil = 0, hideTimer = null, errTimer = null;

// One record per task. `frac` null = unknown progress (indeterminate).
export function startTask(label, o) {
  o = o || {};
  const t = { id: ++seq, label: String(label || 'Chargement'), frac: o.progress == null ? null : clamp(o.progress),
    cancel: typeof o.cancel === 'function' ? o.cancel : null, covers: !!o.covers, auto: !!o.auto,
    shown: !(o.delay > 0), t0: Date.now(), t1: null, maxFrac: null, failed: false, everShown: false };
  if (!t.shown) t.timer = setTimeout(() => { t.timer = null; if (tasks.has(t.id)) { t.shown = true; paint(); } }, o.delay);
  tasks.set(t.id, t); log.push(t); if (log.length > 40) log.shift();
  paint();
  const handle = {
    id: t.id,
    set(frac, lab) {
      if (!tasks.has(t.id)) return handle;
      if (frac !== undefined) t.frac = frac == null ? null : clamp(frac);
      if (lab) t.label = String(lab);
      paint(); return handle;
    },
    done() { end(t, false); return handle; },
    fail(msg) { end(t, true); if (msg) toast(msg, 'err'); return handle; },
    get running() { return tasks.has(t.id); },
  };
  return handle;
}
// Run `work` (a promise or an async function) as one task; failure (throw) turns the bar red and rethrows.
export async function track(label, work, o) {
  const t = startTask(label, o);
  try {
    const r = await (typeof work === 'function' ? work(t) : work);
    t.done();
    return r;
  } catch (e) { t.fail(); throw e; }
}
// True while an explicit task that already covers its own fetches runs (save, validate…): core/api.js then skips its
// automatic per-fetch task, so one operation shows one label.
export const covered = () => [...tasks.values()].some((t) => t.covers);

function clamp(v) { v = +v; return Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : null; }
function end(t, failed) {
  if (!tasks.has(t.id)) return;
  if (t.timer) { clearTimeout(t.timer); t.timer = null; }
  tasks.delete(t.id); t.t1 = Date.now(); t.failed = failed;
  if (failed) {                   // red even for a fast failure: an error is worth one short flash
    errUntil = Date.now() + ERR_MS;
    clearTimeout(errTimer); errTimer = setTimeout(paint, ERR_MS + 20);
  }
  paint();
}

function els() {
  return { bar: $('#progress'), fill: $('#progress .pfill'), chip: $('#progChip'), main: $('#main') };
}
// Repaint the bar and the chip from the running tasks (cheap: a few attribute writes).
function paint() {
  const { bar, fill, chip, main } = els();
  if (!bar) return;
  const shown = [...tasks.values()].filter((t) => t.shown);
  shown.forEach((t) => { t.everShown = true; });
  const err = Date.now() < errUntil;
  bar.classList.toggle('err', err);
  if (!shown.length && !err) { hideBar(bar, chip, main); return; }
  clearTimeout(hideTimer); hideTimer = null;
  bar.hidden = false; bar.classList.remove('fade'); bar.classList.add('on');
  if (main) main.setAttribute('aria-busy', shown.length ? 'true' : 'false');
  const known = shown.filter((t) => t.frac != null);
  const set = shown.map((t) => t.id).join(',');
  if (known.length) {
    let f = known.reduce((s, t) => s + t.frac, 0) / known.length;
    if (set === shownSet && shownFrac != null) f = Math.max(f, shownFrac);    // same tasks: never step back
    shownFrac = f;
    known.forEach((t) => { t.maxFrac = Math.max(t.maxFrac == null ? 0 : t.maxFrac, t.frac); });
    bar.classList.remove('indet');
    fill.style.width = (f * 100).toFixed(1) + '%';
    bar.setAttribute('aria-valuenow', String(Math.round(f * 100)));
  } else if (shown.length) {
    shownFrac = null;
    bar.classList.add('indet');
    fill.style.width = '';
    bar.removeAttribute('aria-valuenow');
  }
  shownSet = set;
  // chip: the oldest shown task with a known progress, else the newest one; "+N" for the others
  const main1 = known.length ? known[0] : shown[shown.length - 1];
  const text = main1 ? main1.label + '…' + (main1.frac != null ? ' ' + Math.round(main1.frac * 100) + ' %' : '')
    + (shown.length > 1 ? ' · +' + (shown.length - 1) : '') : 'Erreur';
  bar.setAttribute('aria-valuetext', text);
  bar.setAttribute('aria-label', main1 ? main1.label : 'Erreur');
  if (chip) {
    chip.hidden = !main1;
    chip.textContent = text;
    chip.classList.toggle('cancel', !!(main1 && main1.cancel));
    chip.title = main1 && main1.cancel ? text + ' — cliquer pour annuler' : text;
    chip.onclick = main1 && main1.cancel ? (e) => { e.stopPropagation(); const c = main1.cancel; main1.cancel = null; c(); paint(); } : null;
  }
}
function hideBar(bar, chip, main) {
  shownFrac = null; shownSet = '';
  if (chip) { chip.hidden = true; chip.onclick = null; }
  if (main) main.removeAttribute('aria-busy');
  bar.removeAttribute('aria-valuenow');
  if (bar.hidden || hideTimer) return;
  bar.classList.add('fade');
  hideTimer = setTimeout(() => {
    hideTimer = null;
    if ([...tasks.values()].some((t) => t.shown)) return;
    bar.hidden = true; bar.classList.remove('on', 'fade', 'indet', 'err');
  }, FADE_MS);
}

// Test hook (window.__editor.progress): what the bar shows now and the recent task records.
export function progressInfo() {
  const { bar, chip, fill } = els();
  return {
    visible: !!(bar && !bar.hidden && !bar.classList.contains('fade')), hidden: !bar || bar.hidden,
    indeterminate: !!(bar && bar.classList.contains('indet')), err: !!(bar && bar.classList.contains('err')),
    value: bar && bar.hasAttribute('aria-valuenow') ? +bar.getAttribute('aria-valuenow') : null,
    width: fill ? fill.style.width : null, chip: chip && !chip.hidden ? chip.textContent : null,
    busy: ($('#main') || { getAttribute: () => null }).getAttribute('aria-busy'),
    running: [...tasks.values()].map((t) => ({ id: t.id, label: t.label, frac: t.frac, shown: t.shown })),
    log: log.map((t) => ({ id: t.id, label: t.label, auto: t.auto, shown: t.everShown, t0: t.t0, t1: t.t1,
      ms: t.t1 ? t.t1 - t.t0 : null, failed: t.failed, maxFrac: t.maxFrac })),
  };
}
