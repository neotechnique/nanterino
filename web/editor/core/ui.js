/**
 * Editor core: toast, modal and YAML preview.
 *
 * Purpose :  toast(), modal(), toYaml().
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, h } from './util.js';

// ---------- toast / modal ----------
// Toasts stack top-right of the canvas (never over the drawer or the nodes' ports area).
export function toast(msg, kind) {
  const box = $('#toasts'), t = h('div', { class: 'toast ' + (kind || '') }, msg);
  box.append(t);
  while (box.children.length > 4) box.firstChild.remove();
  setTimeout(() => t.remove(), 6000);
}
export function modal(title, body, buttons) {
  $('#mTitle').textContent = title;
  const b = $('#mBody'); b.innerHTML = ''; b.append(body);
  const bt = $('#mBtns'); bt.innerHTML = '';
  buttons.forEach((x) => bt.append(h('button', { class: x.cls || '', onclick: () => { $('#modal').hidden = true; x.fn && x.fn(); } }, x.label)));
  $('#modal').hidden = false;
}
export function toYaml(o, ind) {
  ind = ind || '';
  const scalar = (v) => (typeof v === 'string' ? (/^[\w .\-/éèêàùçîôÉ']+$/.test(v) && v !== '' && !/^(true|false|null|\d+)$/i.test(v) ? v : JSON.stringify(v)) : v === null ? 'null' : String(v));
  if (Array.isArray(o)) {
    if (!o.length) return '[]';
    return o.map((v) => (v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length
      ? ind + '- ' + toYaml(v, ind + '  ').replace(/^\s+/, '') : ind + '- ' + (v && typeof v === 'object' ? toYaml(v, ind + '  ') : scalar(v)))).join('\n');
  }
  if (o && typeof o === 'object') {
    const ks = Object.keys(o);
    if (!ks.length) return '{}';
    return ks.map((k) => {
      const v = o[k];
      if (v && typeof v === 'object' && (Array.isArray(v) ? v.length : Object.keys(v).length)) return ind + k + ':\n' + toYaml(v, ind + '  ');
      return ind + k + ': ' + (v && typeof v === 'object' ? toYaml(v) : scalar(v));
    }).join('\n');
  }
  return ind + scalar(o);
}
