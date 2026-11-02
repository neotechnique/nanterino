/**
 * Variables panel: typed value controls.
 *
 * Purpose :  initialValue / coerceItem / valueInput (one typed control per vocabulary `control`), resetVar, usesBox.
 * Boundary:  network through core/api.js: POST /api/graph/vars/reset (Réinitialiser). Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, inspector/property-picker.js, core/api.js, frames/nesting.js, inspector/fields.js,
 *            inspector/arg-fields.js, variables/panel.js, core/ui.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { clone, h, ico, isNum } from '../core/util.js';
import { DT_RE, boundsOf, choicesOf, numericType, vtype } from '../inspector/property-picker.js';
import { postJson } from '../core/api.js';
import { focusNode } from '../frames/nesting.js';
import { selectCtl } from '../inspector/fields.js';
import { defaultValueFor } from '../inspector/arg-fields.js';
import { refreshVarStore, varsUi } from './panel.js';
import { toast } from '../core/ui.js';

// Initial value of a new variable / list item of type `t`: the vocabulary default (first choice for a select that
// cannot be empty, '' for text), never invented here.
export function initialValue(t, choices) {
  if (t === 'choice') return (choices || [])[0];
  const vt = vtype(t);
  if (vt.control === 'select' && !vt.nullable) {
    const cs = (vt.choices || []).map((c) => c.id);
    return cs.includes(vt.default) || !cs.length ? vt.default : cs[0];
  }
  if (vt.default !== undefined) return clone(vt.default);
  return t === 'string' ? '' : defaultValueFor(t, choices);
}
// A value converted to type `t` when a list changes its item type (undefined = dropped).
export function coerceItem(t, x) {
  const vt = vtype(t), c = vt.control;
  if (numericType(t)) { if (!isNum(x)) return 0; let n = Number(x); if (t === 'integer') n = Math.round(n); if (vt.range) n = Math.min(vt.range[1], Math.max(vt.range[0], n)); return n; }
  if (c === 'checkbox') return x === true || x === 'true' || x === 'vrai';
  if (c === 'vector') return Array.isArray(x) && x.length === (vt.size || 2) ? x.map(Number) : clone(vt.default);
  if (c === 'color') return /^#[0-9a-fA-F]{6}$/.test(String(x)) ? x : (vt.default || '#ffffff');
  if (c === 'datetime') return DT_RE.test(String(x)) ? x : undefined;
  if (c === 'select') return (vt.choices || []).some((o) => o.id === x) ? x : initialValue(t);
  return x == null ? '' : typeof x === 'object' ? JSON.stringify(x) : String(x);
}
// Typed input of a variable's initial value, a list item or a dict value, chosen by the vocabulary `control`
// (L12): checkbox, number (bounded = number + slider), slider (percent), text, textarea, select (own choices or the
// vocabulary ones; nullable = "(aucun)"), datetime (+ Maintenant / Vider), timer (no value: read-only hint), color,
// vector (2 / 3 numbers). `def` = {type, choices?, min?, max?, step?}. The element carries data-ctl = control; a
// text control is the <input> itself (callers read its value on Enter / Ajouter).
export function valueInput(def, value, onchange) {
  const t = vtype(def.type), c = t.control, nullable = !!t.nullable;
  const tag = (e) => { e.setAttribute('data-ctl', c); return e; };
  if (c === 'checkbox') {
    const x = h('input', { type: 'checkbox' }); x.checked = value === true;
    x.addEventListener('change', () => onchange(x.checked)); return tag(x);
  }
  if (c === 'number' || c === 'slider') {
    const b = boundsOf(def);
    const fix = (x) => { let n = Number(x); if (def.type === 'integer') n = Math.round(n); return n; };
    const num = h('input', { type: 'number', step: b.step != null ? b.step : 'any', min: b.min != null ? b.min : def.type === 'duration' ? 0 : null, max: b.max });
    num.value = value == null ? '' : value;
    if (b.min == null || b.max == null) { num.addEventListener('change', () => onchange(num.value === '' ? 0 : fix(num.value))); return tag(num); }
    // bounded number / percent: the number field and a slider kept in sync
    const rng = h('input', { type: 'range', min: b.min, max: b.max, step: b.step != null ? b.step : def.type === 'number' ? 'any' : 1 });
    rng.value = value == null ? b.min : value;
    num.addEventListener('change', () => { const n = num.value === '' ? 0 : fix(num.value); rng.value = n; onchange(n); });
    rng.addEventListener('input', () => { num.value = rng.value; });
    rng.addEventListener('change', () => onchange(fix(rng.value)));
    return tag(h('div', { class: 'vslider' }, num, rng));
  }
  if (c === 'select') {
    const opts = choicesOf(def);
    return tag(selectCtl((nullable || !opts.length ? [{ v: '', l: '(aucun)' }] : []).concat(opts), value == null ? '' : value, (x) => onchange(x === '' ? null : x)));
  }
  if (c === 'datetime') {
    const i = h('input', { type: 'datetime-local' }); i.value = value ? String(value).slice(0, 16) : '';
    i.addEventListener('change', () => onchange(i.value === '' ? null : i.value));
    const now = h('button', { type: 'button', 'data-act': 'now', title: 'Date et heure de ce navigateur' }, 'Maintenant');
    now.addEventListener('click', () => {
      const d = new Date(), p2 = (n) => String(n).padStart(2, '0');
      i.value = `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}T${p2(d.getHours())}:${p2(d.getMinutes())}`;
      onchange(i.value);
    });
    const kids = [i, now];
    if (nullable) kids.push(h('button', { type: 'button', 'data-act': 'clear', title: 'Aucune date', onclick: () => { i.value = ''; onchange(null); } }, 'Vider'));
    return tag(h('div', { class: 'addrow vdt' }, kids));
  }
  if (c === 'timer') return tag(h('div', { class: 'hint' }, ico('clock'), ' Chrono : arrêté au chargement ; l’action « Démarrer un chrono » le lance, la valeur lue = secondes écoulées.'));
  if (c === 'color') {
    const i = h('input', { type: 'color' }); i.value = /^#[0-9a-fA-F]{6}$/.test(String(value)) ? value : '#ffffff';
    i.addEventListener('change', () => onchange(i.value)); return tag(i);
  }
  if (c === 'vector') {
    const n = t.size || 2, cur = Array.isArray(value) && value.length === n ? value.slice() : new Array(n).fill(0);
    const box = h('div', { class: 'vvec' });
    ['x', 'y', 'z'].slice(0, n).forEach((ax, k) => {
      const i = h('input', { type: 'number', step: 'any', title: ax, 'data-axis': ax }); i.value = cur[k];
      i.addEventListener('change', () => { cur[k] = i.value === '' ? 0 : Number(i.value); onchange(cur.slice()); });
      box.append(h('span', { class: 'vax' }, ax), i);
    });
    return tag(box);
  }
  if (c === 'textarea') {
    const t2 = h('textarea', { rows: 2, maxlength: 300 }); t2.value = value == null ? '' : value;
    t2.addEventListener('change', () => onchange(t2.value)); return tag(t2);
  }
  const i = h('input', { type: 'text' }); i.value = value == null ? '' : value;
  i.addEventListener('change', () => onchange(i.value)); return tag(i);
}
// Réinitialiser (L12): POST /api/graph/vars/reset {name}: the robot puts the variable / list back to its initial
// value and forgets its saved one. 404 = unknown to the running graph (not saved yet), system or source-bound.
export async function resetVar(id) {
  let r;
  try { r = await postJson('/api/graph/vars/reset', { name: id }); } catch (e) { r = { status: 0, json: null }; }
  if (r.ok) {
    if (r.json && r.json.vars && r.json.vars.names) varsUi.live = r.json.vars;
    toast(`« ${id} » remise à sa valeur initiale sur le robot (valeur enregistrée oubliée).`, 'ok');
    await refreshVarStore();
    return true;
  }
  const why = (r.json && (r.json.error || r.json.message)) || ('erreur ' + r.status);
  toast(r.status === 404 ? `Réinitialisation impossible pour « ${id} » : le robot ne la connaît pas (graphe pas encore enregistré, variable système ou liste liée). ${why}`
    : `Réinitialisation refusée : ${why}`, 'err');
  return false;
}
export function usesBox(id) {
  if (!varsUi.uses || varsUi.uses.id !== id) return null;
  return h('div', { class: 'iss err vuses' }, `Suppression refusée : « ${id} » est utilisée par `,
    varsUi.uses.nodes.map((nid, k) => [k ? ', ' : '', h('a', { href: '#', class: 'navok', onclick: (e) => { e.preventDefault(); focusNode(nid); } }, nid)]).flat(), '.');
}
