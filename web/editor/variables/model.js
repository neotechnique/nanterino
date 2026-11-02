/**
 * Variables (Vars L2): definitions of the document variables and lists.
 *
 * Purpose :  docVars / sysVars / varDefs / listDefs, type labels and the valText formatter shared by cards, inspector and
 *            panels.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/state.js, inspector/property-picker.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { S, byId, stateLabel } from '../core/state.js';
import { isSrcObj, srcWords } from '../inspector/property-picker.js';

// ---------- variables (Vars L2) ----------
// Two sources: system variables come from the vocabulary (V.variables, `system`/`readonly`, never in the document);
// user variables and lists are the document's own `variables` block ({names: {id: {type, value, choices?, description}},
// lists: {id: {type, items? | from? | intent?, description}}}), edited by the Variables panel and saved with the doc.
// A list bound to a source (`from` = config key, `intent` = intent words) is read-only here; its items are shown
// from the vocabulary snapshot. The server stays the validator (types, names, deleting a used variable = 400).
export const VAR_NAME = /^[a-z][a-z0-9_]{0,31}$/;
export const docVars = () => {
  S.meta.variables = S.meta.variables && typeof S.meta.variables === 'object' ? S.meta.variables : {};
  if (!S.meta.variables.names || typeof S.meta.variables.names !== 'object') S.meta.variables.names = {};
  if (!S.meta.variables.lists || typeof S.meta.variables.lists !== 'object') S.meta.variables.lists = {};
  return S.meta.variables;
};
export const sysVars = () => (((S.V.variables || {}).names) || []).filter((v) => v.system);
// Every name variable: [{id, type, label?, description, choices?, value?, system, readonly}], system ones first.
export function varDefs() {
  const out = sysVars().map((v) => Object.assign({}, v, { system: true, readonly: true }));
  const seen = new Set(out.map((v) => v.id));
  const names = docVars().names;
  Object.keys(names).forEach((id) => { if (!seen.has(id)) out.push(Object.assign({ id, system: false, readonly: false }, names[id])); });
  return out;
}
// Every list: [{id, type, items, description, readonly, source}] (source = {cfg} | {intent} for a bound list).
export function listDefs() {
  const snap = {}; (((S.V.variables || {}).lists) || []).forEach((l) => { snap[l.id] = l; });
  const lists = docVars().lists;
  return Object.keys(lists).map((id) => {
    const l = lists[id] || {}, bound = !!(l.from || l.intent), kind = l.kind === 'dict' ? 'dict' : 'list';
    // L12: a dict keeps its items as a {key: value} object; every other list is an array
    const own = kind === 'dict' ? (l.items && typeof l.items === 'object' && !Array.isArray(l.items) ? l.items : {}) : (Array.isArray(l.items) ? l.items : []);
    return { id, type: l.type || 'string', description: l.description || '', readonly: bound,
      source: l.from ? { cfg: l.from } : l.intent ? { intent: l.intent } : null,
      kind, mode: l.mode || 'plain', max: l.max == null ? null : l.max, scope: l.scope || 'global', persist: !!l.persist,
      items: bound ? (((snap[id] || {}).items) || []) : own };
  });
}
// L12: number of entries of a list or a dict (dict items are an object).
export const itemCount = (items) => (Array.isArray(items) ? items.length : items && typeof items === 'object' ? Object.keys(items).length : 0);
export const varDef = (id) => varDefs().find((v) => v.id === id) || null;
export const listDef = (id) => listDefs().find((l) => l.id === id) || null;
export const typeLabel = (t, lists) => ((byId(lists ? S.V.list_types : S.V.var_types, t) || {}).label || t);
export const opLabel = (o) => ({ '=': '=', '!=': '≠', '<': '<', '<=': '≤', '>': '>', '>=': '≥', in: 'parmi', not_in: 'hors de' }[o] || o);
// A value as shown on a card: the etat value by its state label, `$x` as "x", lists joined.
export const valText = (name, v) => {
  if (isSrcObj(v)) return srcWords(v);            // lot M5: a value source in words
  if (Array.isArray(v)) return v.map((x) => valText(name, x)).join(', ');
  if (name === 'etat') return stateLabel(v);
  if (typeof v === 'string' && v.startsWith('$')) return v === '$utterance' ? 'la phrase entendue' : v.slice(1);
  if (v === true) return 'vrai';
  if (v === false) return 'faux';
  return v == null || v === '' ? '?' : String(v);
};
