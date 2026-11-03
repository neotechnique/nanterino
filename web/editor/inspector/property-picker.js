/**
 * Inspector: value source picker (lot M5, contract "Propriétés").
 *
 * Purpose :  SRC_* constants, srcOf / srcOutType / srcArgsFor / srcOffered / srcWords / srcUses / srcRename / srcIssues,
 *            the ▾ source button and menu (srcButton, srcPicked) and the source chip field (srcField, recursion through
 *            argFields).
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, tooltips/tooltips.js, core/state.js, variables/model.js, core/serialize.js,
 *            inspector/arg-fields.js
 * Invariant: registers ONE document click listener at evaluation (closes open .srcmenu menus), as the single file did.
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { clone, h, ico, isNum } from '../core/util.js';
import { tipi } from '../tooltips/tooltips.js';
import { S, byId } from '../core/state.js';
import { listDef, listDefs, opLabel, typeLabel, valText, varDef, varDefs } from '../variables/model.js';
import { serialize } from '../core/serialize.js';
import { ORDER_OPS, argFields } from './arg-fields.js';

// ---------- value sources (lot M5, contract "Propriétés") ----------
// A field whose vocabulary argument carries `props` takes a constant (plain control) or a value source
// `{get: <id>, ...args}` from V.properties.get; `$x` / `$utterance` ARE the Variable / Phrase entendue sources in
// shorthand. The typing rules stay on the server: V.type_compat (= graph.compatible) decides which sources a field
// may offer, the server check gives the final word (its messages land on the node like any diagnostic).
const SRC_GROUPS = [['constant', ''], ['variables', 'Variables'], ['lists', 'Listes'], ['robot', 'Robot'], ['random', 'Hasard'],
  ['time', 'Temps'], ['calc', 'Calcul'], ['other', 'Autres']];
// Menu group of each source; a new source module (drop-a-file) lands in "Autres" until it is listed here.
const SRC_GROUP_OF = { constant: 'constant', variable: 'variables', list_item: 'lists', dict_value: 'lists', utterance: 'robot',
  system: 'robot', config_value: 'robot', intent_match: 'robot', random_number: 'random', random_from_list: 'random',
  elapsed: 'time', calc: 'calc' };
export const SRC_MAX_DEPTH = 4;               // = server properties.MAX_DEPTH: a field inside 4 sources gets no ▾
const CALC_SIGN = { '+': '+', '-': '−', '*': '×', '/': '÷' };
const srcDefs = () => ((S.V.properties || {}).get) || [];
const srcDef = (id) => byId(srcDefs(), id);
export const isSrcObj = (v) => !!v && typeof v === 'object' && !Array.isArray(v) && typeof v.get === 'string';
// {id, args, short} of a value that is a source (object or `$` shorthand), null for a constant.
export function srcOf(v) {
  if (isSrcObj(v)) { const a = Object.assign({}, v); delete a.get; return { id: v.get, args: a, short: false }; }
  if (v === '$utterance') return { id: 'utterance', args: {}, short: true };
  if (typeof v === 'string' && /^\$[A-Za-z_]/.test(v)) return { id: 'variable', args: { name: v.slice(1) }, short: true };
  return null;
}
// May a value of type `s` feed a field of type `d`? Unknown types (nothing chosen yet) never hide a source.
const typeCompat = (s, d) => {
  if (!s || !d) return true;
  const tc = S.V.type_compat;
  return tc ? (tc[s] || []).includes(d) : s === d;
};
// Output type of a source with these args in a field of type ft (null = not known yet).
function srcOutType(def, args, ft) {
  const o = def && def.out;
  if (o === 'same') return ft;
  if (typeof o === 'string') return o;
  if (!o || !o.of) return null;
  const a = (def.args || []).find((x) => x.name === o.of), r = (args || {})[o.of];
  if (!a || r == null || r === '') return null;
  if (a.type === 'var') { const d = varDef(r); return d ? d.type : null; }
  if (a.type === 'list') { const l = listDef(r); return l ? l.type : null; }
  if (a.types) return a.types[r] || null;          // config_value: output type per key (vocabulary)
  const d = varDef(r); return d ? d.type : null;    // system: the system variable's own type
}
// The source's argument specs, the one named by `out.of` narrowed to the choices whose type fits the field.
function srcArgsFor(def, ft) {
  const o = def.out;
  return (def.args || []).map((a) => {
    if (!o || typeof o !== 'object' || o.of !== a.name || !ft) return a;
    const b = Object.assign({}, a);
    const all = (xs, fb) => (xs && xs.length ? xs : fb);
    if (a.type === 'var') b.var_types = all(a.var_types, S.V.var_types.map((t) => t.id)).filter((t) => typeCompat(t, ft));
    else if (a.type === 'list') b.list_types = all(a.list_types, S.V.list_types.map((t) => t.id)).filter((t) => typeCompat(t, ft));
    else if (a.type === 'enum') b.options = (a.options || []).filter((k) => typeCompat(a.types ? a.types[k] : (varDef(k) || {}).type, ft));
    return b;
  });
}
// Is the source worth offering for a field of type ft (compatible output, at least one fitting choice)?
function srcOffered(def, ft) {
  const o = def.out;
  if (o === 'same') return true;
  if (typeof o === 'string') return typeCompat(o, ft);
  const a = srcArgsFor(def, ft).find((x) => x.name === (o || {}).of);
  if (!a) return true;
  if (a.type === 'var') return varDefs().some((d) => a.var_types.includes(d.type));
  if (a.type === 'list') return listDefs().some((l) => a.list_types.includes(l.type) && (!(a.list_kinds || []).length || a.list_kinds.includes(l.kind)));
  if (a.type === 'enum') return a.options.length > 0;
  return true;
}
// A source in words, for cards, tooltips and the chip ("au hasard dans salutations", "(score + 1)").
export function srcWords(v, depth) {
  depth = depth || 0;
  const s = srcOf(v);
  if (!s || depth > 8) return valText('', v);
  const a = s.args, w = (x) => (x == null || x === '' ? '?' : srcWords(x, depth + 1));
  const def = srcDef(s.id) || {};
  const lab = (n, k) => (((def.args || []).find((x) => x.name === n) || {}).labels || {})[k] || k;
  switch (s.id) {
    case 'constant': return valText('', a.value);
    case 'variable': return a.name || '?';
    case 'utterance': return 'la phrase entendue';
    case 'list_item': {
      const L = a.list || '?', p = a.pick || 'first';
      if (p === 'last') return 'le dernier de ' + L;
      if (p === 'random') return 'au hasard dans ' + L;
      if (p === 'index') return 'l’élément ' + (a.index == null ? 1 : w(a.index)) + ' de ' + L;
      return 'le premier de ' + L;
    }
    case 'dict_value': return (a.dict || '?') + '[' + w(a.key) + ']';
    case 'system': return String(lab('name', a.name || '?')).toLowerCase() + ' (robot)';
    case 'random_number': return 'au hasard entre ' + w(a.min) + ' et ' + w(a.max);
    case 'random_from_list': return 'au hasard dans ' + (a.list || '?');
    case 'intent_match': return 'la phrase correspond à ' + (a.intent || '?');
    case 'config_value': return 'réglage ' + (a.key || '?');
    case 'elapsed': return 'temps écoulé depuis ' + (a.name || '?');
    case 'calc':
      if (a.op === 'min' || a.op === 'max') return a.op + '(' + w(a.a) + ', ' + w(a.b) + ')';
      return '(' + w(a.a) + ' ' + (CALC_SIGN[a.op] || a.op || '?') + ' ' + w(a.b) + ')';
  }
  return String(def.label || s.id).toLowerCase();
}
// Stored form of a source: `{get: variable, name: x}` -> "$x" and `{get: utterance}` -> "$utterance" wherever `$`
// was already allowed (value / text fields and every argument inside a source; NOT a plain top-level number such as
// add_var.delta, which the parser refuses as "$x"), so documents written before M5 never churn.
function srcStore(o, arg, level) {
  const keys = Object.keys(o);
  const shortOk = level > 0 || arg.type !== 'number';
  if (shortOk && o.get === 'variable' && keys.length === 2 && typeof o.name === 'string' && o.name) return '$' + o.name;
  if (shortOk && o.get === 'utterance' && keys.length === 1) return '$utterance';
  return o;
}
// Does this value (constant, `$x` or source at any depth) read the variable / list `id`?
function srcUses(v, id) {
  if (v === '$' + id) return true;
  if (!isSrcObj(v)) return false;
  return Object.entries(v).some(([k, x]) => (k !== 'get' && ['name', 'list', 'dict'].includes(k) && x === id) || srcUses(x, id));
}
// The same source with the variable / list `old` renamed `nu` at any depth.
export function srcRename(v, old, nu) {
  if (v === '$' + old) return '$' + nu;
  if (!isSrcObj(v)) return v;
  const o = {};
  for (const k in v) o[k] = k !== 'get' && ['name', 'list', 'dict'].includes(k) && v[k] === old ? nu : srcRename(v[k], old, nu);
  return o;
}
// Structural hints on the sources of a node's arguments: unknown source, required argument missing (the server
// check gives the typed verdict, e.g. "source list_item gives a string value, integer expected").
function srcIssues(v, lab, depth) {
  if (!isSrcObj(v) || (depth || 1) > SRC_MAX_DEPTH + 1) return [];
  const s = srcOf(v), def = srcDef(s.id);
  if (!def) return [`${lab} : source inconnue « ${s.id} ».`];
  const out = [];
  (def.args || []).forEach((a) => {
    const x = s.args[a.name];
    if ((x == null || x === '') && !('default' in a)) out.push(`${lab} (${def.label}) : à choisir : ${a.label || a.name}.`);
    else if (a.props) out.push(...srcIssues(x, lab, (depth || 1) + 1));
  });
  return out;
}
export function srcArgIssues(spec, args) {
  const out = [];
  ((spec && spec.args) || []).forEach((a) => { if (a.props) out.push(...srcIssues((args || {})[a.name], a.label || a.name)); });
  return out;
}
// "valeur = au hasard dans salutations" lines of a node's source fields (node tooltip).
export function srcLines(m) {
  const p = m.params || {};
  const spec = m.kind === 'action' ? byId(S.V.actions, p.action) : m.kind === 'condition' && p.type === 'guard' ? byId(S.V.guards, p.guard) : null;
  return ((spec && spec.args) || []).filter((a) => a.props && srcOf((p.args || {})[a.name]))
    .map((a) => String(a.label || a.name).toLowerCase() + ' = ' + srcWords(p.args[a.name]));
}
// The ▾ button + its grouped menu. onPick(def) receives the chosen source entry.
export function srcButton(argName, ft, curId, onPick) {
  const wrap = h('span', { class: 'srcdd' });
  const btn = h('button', { type: 'button', class: 'srcbtn', 'data-tip': 'Source de la valeur', 'aria-label': 'Source de la valeur', 'data-src-for': argName }, '▾');
  btn.addEventListener('click', (e) => {
    e.preventDefault(); e.stopPropagation();
    const open = wrap.querySelector('.srcmenu');
    document.querySelectorAll('.srcmenu').forEach((x) => x.remove());
    document.querySelectorAll('.srcbtn.on').forEach((x) => x.classList.remove('on'));
    if (open) return;
    const menu = h('div', { class: 'srcmenu', role: 'menu' }), groups = new Map();
    srcDefs().forEach((d) => {
      if (!srcOffered(d, ft)) return;
      const g = SRC_GROUP_OF[d.id] || 'other';
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(d);
    });
    SRC_GROUPS.forEach(([g, gl]) => {
      const ds = groups.get(g); if (!ds) return;
      if (gl) menu.append(h('div', { class: 'srcgrp' }, gl));
      ds.forEach((d) => menu.append(h('div', { class: 'srci' + (d.id === curId ? ' on' : ''), role: 'menuitem', 'data-src': d.id, 'data-tip': d.help || '',
        onclick: (ev) => { ev.stopPropagation(); menu.remove(); btn.classList.remove('on'); onPick(d); } }, ico(d.icon), d.label)));
    });
    btn.classList.add('on');
    wrap.append(menu);
  });
  wrap.append(btn);
  return wrap;
}
document.addEventListener('click', (e) => {
  if (e.target && e.target.closest && e.target.closest('.srcmenu')) return;
  document.querySelectorAll('.srcmenu').forEach((x) => x.remove());
  document.querySelectorAll('.srcbtn.on').forEach((x) => x.classList.remove('on'));
});
// A source was picked for field `arg` (type ft): "Valeur fixe" writes the field's plain default (dv, '' = none);
// another source starts with its enum arguments pre-filled (first fitting choice), the rest is left to choose.
export function srcPicked(d, arg, ft, set, level, dv) {
  if (d.id === 'constant') { set(arg.name, dv === undefined ? '' : clone(dv)); return; }
  const o = { get: d.id };
  srcArgsFor(d, ft).forEach((a) => {
    if (a.type === 'enum' && !('default' in a) && (a.options || []).length) o[a.name] = a.options[0];
  });
  set(arg.name, srcStore(o, arg, level));
}
// Inspector field holding a source: chip (icon, name, summary) + ▾, then its own argument fields indented (they
// may take sources in turn, up to SRC_MAX_DEPTH levels). Literals typed in sub-fields stay typed (numbers as
// numbers: the visual compiler never coerces text inside a nested source).
export function srcField(arg, lab, v, s, ft, set, level, dv) {
  const def = srcDef(s.id);
  const obj = isSrcObj(v) ? v : Object.assign({ get: s.id }, s.args);
  const out = def ? srcOutType(def, s.args, ft) : null;
  const fld = h('div', { class: 'fld srcfld', 'data-arg': arg.name, 'data-src': s.id });
  const chip = h('div', { class: 'srcchip' + (out && !typeCompat(out, ft) ? ' bad' : ''), 'data-tip': def ? def.help : 'Source inconnue' },
    ico(def ? def.icon : 'alert-triangle'), h('span', { class: 'srcname' }, def ? def.label : '? ' + s.id),
    s.id === 'variable' || s.id === 'utterance' ? null : h('span', { class: 'srcsum' }, srcWords(v)));
  fld.append(h('span', {}, lab, tipi(arg.help)), h('div', { class: 'srcrow' }, chip, srcButton(arg.name, ft, s.id, (d) => srcPicked(d, arg, ft, set, level, dv))));
  if (def && s.id !== 'constant' && (def.args || []).length) {
    const sub = h('div', { class: 'srcsub' });
    const nset = (name, x) => {
      const o = Object.assign({}, obj);
      if (x === '' || x == null) delete o[name]; else o[name] = x;
      set(arg.name, srcStore(o, arg, level));
    };
    argFields(sub, srcArgsFor(def, ft), obj, nset, { level: level + 1, ft, src: def.id });
    fld.append(sub);
  } else if (s.id === 'constant') fld.append(h('div', { class: 'help' }, 'Valeur : ' + valText('', obj.value) + ' (choisir « Valeur fixe » pour la modifier).'));
  return fld;
}
// Nodes that use a variable or list (model ids): args name/list/value "$x", var_changed trigger name.
export function varUses(id, doc) {
  const out = [];
  ((doc || serialize()).nodes || []).forEach((n) => {
    const p = n.params || {}, a = p.args || {};
    const hit = (n.kind === 'trigger' && p.name === id) || a.name === id || a.list === id || a.dict === id
      || a.key === '$' + id || [a.value, p.value].some((v) => v === '$' + id || (Array.isArray(v) && v.includes('$' + id)))
      || Object.values(a).some((x) => isSrcObj(x) && srcUses(x, id));   // lot M5: value sources
    if (hit) out.push(n.id);
  });
  return out;
}
// Display form of a guard that reads counters (vocabulary `as_vars`, e.g. "tours < max_tours").
export const asVars = (gid) => (byId(S.V.guards, gid) || {}).as_vars || '';
// A state-entry trigger: legacy `enter`, or var_changed on etat (never disabled, never ordered).
export const isEnterTrig = (m) => { const p = m.params || {}; return p.type === 'enter' || (p.type === 'event' && p.event === 'var_changed' && p.name === 'etat'); };
// Structural problems of a node's typed arguments (vocabulary `args`): unknown / wrongly typed / read-only variable
// or list, missing value. Hints only: the server compiler gives the final word.
export function argIssues(spec, args) {
  const out = [];
  ((spec && spec.args) || []).forEach((a) => {
    const v = args[a.name], lab = a.label || a.name;
    if (a.type === 'var') {
      if (v == null || v === '') { out.push('À choisir : ' + lab + '.'); return; }
      const d = varDef(v);
      if (!d) out.push(`Variable inconnue : « ${v} ».`);
      else if ((a.var_types || []).length && !a.var_types.includes(d.type)) out.push(`« ${v} » (${typeLabel(d.type)}) ne convient pas ici.`);
      else if (a.writable && d.readonly && !(v === 'etat' && spec.id === 'set_var')) out.push(`La variable système « ${v} » est en lecture seule.`);
    } else if (a.type === 'list') {
      if (v == null || v === '') { out.push('À choisir : ' + lab + '.'); return; }
      const d = listDef(v);
      if (!d) out.push(`Liste inconnue : « ${v} ».`);
      else if ((a.list_types || []).length && !a.list_types.includes(d.type)) out.push(`La liste « ${v} » (${typeLabel(d.type, true)}) ne convient pas ici.`);
      else if (a.writable && d.readonly) out.push(`La liste « ${v} » est liée à une source : lecture seule.`);
    } else if (a.type === 'value' && !a.optional && (v == null || v === '' || (Array.isArray(v) && !v.length))) out.push('À remplir : ' + lab + '.');
  });
  return out;
}

// L12: vocabulary entry of a variable type ({id, label, control, options, ops, choices?, range?, size?, default,
// nullable, persist}); an unknown type falls back to a plain text control.
export const vtype = (t) => byId(S.V.var_types, t) || { id: t, label: t, control: 'text', options: [], ops: ['=', '!='] };
// Operators allowed on a type: vocabulary op_sets first (order operators for numbers, durations, dates, chronos).
export const opsFor = (t) => ((S.V.op_sets || {})[t]) || vtype(t).ops || ['=', '!='];
const ordered = (t) => opsFor(t).includes('<');
export const numericType = (t) => ['number', 'slider', 'timer'].includes(vtype(t).control);
// Choices of a select-typed variable [{v, l}]: its own `choices` (type choice) or the vocabulary ones (expression,
// gaze, media, intent_ref, list_ref, state_ref). Long labels (intent descriptions) fall back to the id.
export const choicesOf = (def) => (def && def.type === 'choice' ? (def.choices || []).map((c) => ({ v: c, l: c }))
  : (vtype(def && def.type).choices || []).map((c) => ({ v: c.id, l: c.label && c.label.length <= 40 ? c.label : c.id })));
// Bounds of a numeric variable: its own min / max / step (number, integer) or the vocabulary range (percent).
export function boundsOf(def) {
  const r = vtype(def && def.type).range || [];
  const pick = (k, dv) => (def && def[k] != null && def[k] !== '' ? Number(def[k]) : dv == null ? null : dv);
  return { min: pick('min', r[0]), max: pick('max', r[1]), step: pick('step', def && def.type === 'integer' ? 1 : null) };
}
export const DT_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/;
// Problem of a constant against a variable definition: {level: 'err'} for a type mismatch, {level: 'warn'} for a
// number outside the bounds (the server says the same as `out_of_bounds`), null when fine. "$x" references are
// checked by the callers. Hints only: the server compiler stays the judge.
export function valueIssue(def, v, label) {
  if (!def || v == null || v === '' || isSrcObj(v) || (typeof v === 'string' && v.startsWith('$'))) return null;
  const t = vtype(def.type), c = t.control, who = label || def.id;
  const bad = (m) => ({ level: 'err', message: m });
  if (numericType(def.type)) {
    if (!(typeof v === 'number' || isNum(v))) return bad(`« ${v} » n’est pas un nombre (« ${who} » : ${typeLabel(def.type)}).`);
    const n = Number(v), b = boundsOf(def);
    if (def.type === 'integer' && !Number.isInteger(n)) return bad(`« ${v} » n’est pas un entier (« ${who} »).`);
    if ((b.min != null && n < b.min) || (b.max != null && n > b.max)) return { level: 'warn', message: `${n} est hors des bornes de « ${who} » (${b.min == null ? '…' : b.min} à ${b.max == null ? '…' : b.max}) : la valeur sera bornée.` };
    return null;
  }
  if (c === 'checkbox') return typeof v === 'boolean' || ['true', 'false'].includes(String(v)) ? null : bad(`« ${v} » n’est pas vrai / faux.`);
  if (c === 'select') {
    const cs = choicesOf(def).map((x) => x.v);
    return !cs.length || cs.includes(v) ? null : bad(`« ${v} » n’est pas un des choix de « ${who} »${def.type === 'choice' ? ' (' + cs.join(', ') + ')' : ''}.`);
  }
  if (c === 'color') return /^#[0-9a-fA-F]{6}$/.test(String(v)) ? null : bad(`« ${v} » n’est pas une couleur #rrggbb.`);
  if (c === 'vector') return Array.isArray(v) && v.length === (t.size || 2) && v.every((x) => typeof x === 'number' || isNum(x)) ? null : bad(`« ${who} » attend ${t.size || 2} nombres.`);
  if (c === 'datetime') return DT_RE.test(String(v)) ? null : bad(`« ${v} » n’est pas une date AAAA-MM-JJTHH:MM.`);
  return null;
}
// var_compare / date_compare / set_var: operator or value of the wrong type for the variable (lot L5 live check,
// generalised by L12 to every vocabulary type; the server stays the judge). `of` = the variable arg ('name').
export function compareIssues(a) {
  const out = [], d = a.name ? varDef(a.name) : null;
  if (!d || a.name === 'etat') return out;
  const op = a.op || '=', v = a.value;
  if (ORDER_OPS.includes(op) && !ordered(d.type)) out.push(`« ${opLabel(op)} » ne s’applique qu’aux nombres, durées et dates (« ${a.name} » : ${typeLabel(d.type)}).`);
  if (v == null || v === '') return out;
  if (v === '$utterance' || isSrcObj(v)) return out;   // lot M5: a source is typed by the server check
  if (typeof v === 'string' && v.startsWith('$')) {
    const r = varDef(v.slice(1));
    if (!r) out.push(`Variable inconnue : « ${v.slice(1)} ».`);
    else if (numericType(d.type) !== numericType(r.type) || (!numericType(d.type) && r.type !== d.type && !(vtype(d.type).control === 'text' && vtype(r.type).control !== 'select' && ['text', 'textarea'].includes(vtype(r.type).control))))
      out.push(`Types différents : « ${a.name} » (${typeLabel(d.type)}) comparée à « ${r.id} » (${typeLabel(r.type)}).`);
    return out;
  }
  const iss = valueIssue(d, v, a.name);
  if (iss && iss.level === 'err') out.push(iss.message);
  return out;
}
// L12: a constant item / dict value of the wrong type for the list or dict it goes into (list_add, dict_set,
// dict_value_compare). Type mismatch only; the server gives the final word.
export function dictValueIssues(a) {
  const ref = a.dict || a.list, l = ref ? listDef(ref) : null;
  if (!l || a.value === undefined || l.readonly) return [];
  const iss = valueIssue({ id: ref, type: l.type }, a.value, ref);
  return iss && iss.level === 'err' ? [iss.message] : [];
}
