/**
 * Inspector: basic form controls and the wire inspector.
 *
 * Purpose :  field / selectCtl / textCtl / areaCtl / checkCtl / iconSelect, edit() commit helper, numOrKey,
 *            renderWireInspector.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, tooltips/tooltips.js, core/state.js, core/api.js, canvas/nodes.js, core/history.js,
 *            canvas/wires.js, inspector/inspector.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { h, ico, isNum } from '../core/util.js';
import { tipi } from '../tooltips/tooltips.js';
import { S, linkKey, stateLabel } from '../core/state.js';
import { model } from '../core/api.js';
import { refreshNode } from '../canvas/nodes.js';
import { commitSoon } from '../core/history.js';
import { KIND_HEX, paintWires } from '../canvas/wires.js';
import { renderInspector } from './inspector.js';

// ---------- inspector ----------
export function field(label, control, help, tip) {
  // A custom dropdown holds clickable rows: a <label> around it would re-click its button, so use a <div>.
  // `tip` (lot L5): help of the argument, behind an "i" icon next to the label (hover or tap).
  const tag = control && control.classList && control.classList.contains('dd') ? 'div' : 'label';
  return h(tag, { class: 'fld' }, h('span', {}, label, tipi(tip)), control, help ? h('div', { class: 'help' }, help) : null);
}
// Dropdown that can show an icon per entry (a native <select> cannot). options: [{v, l, icon}].
export function iconSelect(options, value, onchange) {
  const opts = options.slice();
  if (value != null && value !== '' && !opts.some((o) => String(o.v) === String(value))) opts.unshift({ v: value, l: '(inconnu) ' + value, icon: 'circle-dot' });
  const root = h('div', { class: 'dd' }), btn = h('button', { type: 'button', class: 'ddb' }), list = h('div', { class: 'ddl', hidden: true });
  const cur = () => opts.find((o) => String(o.v) === String(value));
  const paint = () => {
    btn.innerHTML = ''; const c = cur();
    btn.append(ico(c && c.icon), h('span', { class: 'ddt' }, c ? c.l : '(choisir)'), h('span', { class: 'ddc' }, '▾'));
  };
  opts.forEach((o) => list.append(h('div', { class: 'ddi' + (String(o.v) === String(value) ? ' on' : ''), title: o.l,
    onclick: (e) => { e.stopPropagation(); value = o.v; list.hidden = true; paint(); onchange(o.v); } }, ico(o.icon), o.l)));
  btn.addEventListener('click', (e) => { e.stopPropagation(); const was = list.hidden; document.querySelectorAll('.ddl').forEach((l) => { l.hidden = true; }); list.hidden = !was; });
  paint(); root.append(btn, list);
  return root;
}
export function areaCtl(value, onchange, maxlen) {
  const t = h('textarea', { maxlength: maxlen || null, rows: 3 });
  t.value = value == null ? '' : value;
  t.addEventListener('change', () => onchange(t.value));
  return t;
}
export function selectCtl(options, value, onchange) {
  const s = h('select', {});
  const opts = options.slice();
  if (value != null && value !== '' && !opts.some((o) => String(o.v) === String(value))) opts.unshift({ v: value, l: '(inconnu) ' + value });
  opts.forEach((o) => s.append(h('option', { value: o.v }, o.l)));
  s.value = value == null ? '' : value;
  s.addEventListener('change', () => onchange(s.value));
  return s;
}
export function textCtl(value, onchange, type, list) {
  const i = h('input', { type: type || 'text', list: list || null });
  i.value = value == null ? '' : value;
  i.addEventListener('change', () => onchange(i.value));
  return i;
}
export function checkCtl(label, value, onchange, icon) {
  const c = h('input', { type: 'checkbox' }); c.checked = !!value;
  c.addEventListener('change', () => onchange(c.checked));
  return h('label', { class: 'chk' }, c, icon ? ico(icon) : null, label);
}
export function edit(fn, rerender) {
  const m = model(S.selDf); if (!m) return;
  fn(m);
  refreshNode(S.selDf);
  if (rerender) renderInspector();
  commitSoon();
}
export const numOrKey = (v) => { v = String(v).trim(); return isNum(v) ? Number(v) : v; };

// Inspector of the selected wire: the hop into a state node carries the journal reason (and a description when the
// chain has no node of its own to hold it).
export function renderWireInspector(box) {
  const w = S.selConn, a = model(w.out), b = model(w.in);
  if (!a || !b) { S.selConn = null; return false; }
  const idx = +w.outCls.split('_')[1], port = a.kind === 'condition' ? (idx === 1 ? 'true' : 'false') : 'out', key = linkKey(a.id, port, b.id);
  box.append(h('div', { class: 'insttitle' }, ico('arrow-right', KIND_HEX[a.kind]), 'Fil', h('small', { class: 'hint' }, `${a.id} → ${b.id}`)));
  if (b.kind === 'state') {
    const mt = S.linkMeta.get(key) || {};
    const setMeta = (k, v) => { const cur = Object.assign({}, S.linkMeta.get(key) || {}); if (v) cur[k] = v; else delete cur[k]; if (Object.keys(cur).length) S.linkMeta.set(key, cur); else S.linkMeta.delete(key); paintWires(); commitSoon(); };
    box.append(field("Vers l'état", h('input', { type: 'text', disabled: true, value: stateLabel(b.params.state) })));
    box.append(field('Raison (journal)', textCtl(mt.reason || '', (v) => setMeta('reason', v.trim().slice(0, 100))), 'Texte libre affiché dans le journal quand cette chaîne change l’état ; par défaut, l’événement déclencheur.'));
    box.append(field('Description de la chaîne', areaCtl(mt.description || '', (v) => setMeta('description', v.trim().slice(0, 500)), 500), 'Utile seulement si aucun nœud de la chaîne ne peut porter la description.'));
  } else box.append(h('p', { class: 'hint' }, 'Ce fil relie deux nœuds de la même chaîne.'));
  box.append(h('button', { type: 'button', class: 'danger', onclick: () => { S.editor.removeSingleConnection(w.out, w.in, w.outCls, 'input_1'); S.selConn = null; renderInspector(); } }, 'Supprimer le fil'));
  return true;
}
