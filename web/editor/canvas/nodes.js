/**
 * Canvas: node rendering.
 *
 * Purpose :  node card HTML (summary, delay text, kind icon, disabled / legacy cards) and refreshNode.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, variables/model.js, inspector/property-picker.js, core/api.js,
 *            diagnostics/check.js, menu/node-menu.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { esc, icoHtml } from '../core/util.js';
import {
  S, CATS, KINDS, KIND_TIP, PORT_TIP, byId, evs, iconOf, nidToDf, stateColor, stateIcon, stateLabel
} from '../core/state.js';
import { opLabel, valText } from '../variables/model.js';
import { asVars, isSrcObj, srcLines, srcWords } from '../inspector/property-picker.js';
import { model } from '../core/api.js';
import { ISSUE_PREFIX, markNode } from '../diagnostics/check.js';
import { slotTheme, themeById } from '../menu/node-menu.js';

// ---------- node rendering ----------
function delayText(d) {
  const k = S.V.delays.find((x) => x.key === d);
  return k ? `${k.label} (${k.value} s)` : (d === '' || d == null ? '?' : `${d} s`);
}
export function summary(m) {
  const p = m.params || {};
  switch (m.kind) {
    case 'start': return 'État de départ : ' + stateLabel(p.state);
    case 'trigger':
      if (p.type === 'event' && p.event === 'var_changed') {
        if (p.name === 'etat') return 'Quand etat devient ' + valText('etat', p.value) + " (entrée dans l'état)";
        return 'Quand ' + (p.name || '?') + ' change' + (p.value != null && p.value !== '' ? ' (devient ' + valText(p.name, p.value) + ')' : '');
      }
      if (p.type === 'event') { const e = byId(evs(), p.event); return e ? e.label : '? ' + (p.event || ''); }
      if (p.type === 'after') {
        const s = byId(S.V.since, p.since || 'state');
        return 'Après ' + delayText(p.delay) + ' ' + (s ? s.label : '');
      }
      if (p.type === 'enter') return "À l'entrée dans " + stateLabel(p.state);
      return '?';
    case 'condition':
      if (p.type === 'state') return (p.negate ? 'Pas dans : ' : 'Dans : ') + (p.states || []).map(stateLabel).join(', ');
      {
        const g = byId(S.V.guards, p.guard), a = p.args || {}, no = p.negate ? 'Non : ' : '';
        if (p.guard === 'var_compare') return no + (a.name || '?') + ' ' + opLabel(a.op || '=') + ' ' + valText(a.name, a.value);
        if (p.guard === 'var_true') return no + (a.name || '?') + ' est vrai';
        if (p.guard === 'list_contains') return no + (a.list || '?') + ' contient ' + valText(a.list, a.value);
        if (p.guard === 'list_empty') return no + (a.list || '?') + ' est vide';
        return no + (g ? g.label : '? ' + (p.guard || '')) + (asVars(p.guard) ? ' (' + asVars(p.guard) + ')' : '');
      }
    case 'action': {
      if (p.action === 'set_var' && (p.args || {}).name === 'etat') return "Changer d'état → " + valText('etat', p.args.value) + (p.reason ? ' (' + p.reason + ')' : '');
      const a = byId(S.V.actions, p.action);
      const args = Object.entries(p.args || {}).map(([k, v]) => `${k}=${isSrcObj(v) ? srcWords(v) : v}`).join(', ');
      return (a ? a.label : '? ' + (p.action || '')) + (args ? ' (' + args + ')' : '') + (p.phase === 'then' ? ' [après]' : '');
    }
    case 'goto': return '→ ' + stateLabel(p.state) + (p.reason ? ' (' + p.reason + ')' : '');
    case 'end': return 'Fin de chaîne';
    case 'state': return stateLabel(p.state);
  }
  return '';
}
export function stateDesc(id) {
  const d = (S.meta.states || []).find((x) => x.id === id), s = byId(S.V.states, id);
  return (d && d.description) || (s && s.description) || '';
}
function nodeHtml(m) {
  const k = KINDS[m.kind];
  if (m.kind === 'state') {   // hub card: fixed height (the server's auto layout assumes 84 px)
    const sid = (m.params || {}).state, col = stateColor(sid);
    return `<div class="nhead">${icoHtml(stateIcon(sid), col)}<span class="ntitle">État</span></div><div class="nstate" style="color:${esc(col)}">${esc(stateLabel(sid))}</div><div class="nsum ndesc">${esc(stateDesc(sid))}</div><div class="nmsg"></div>`;
  }
  const tag = m.group === 'global' ? `<span class="ntag" data-tip="Règle globale : valable dans tous les états, évaluée avant les règles de l’état courant." style="background:${esc(stateColor(m.group))}">${esc(m.group === 'global' ? 'global' : stateLabel(m.group))}</span>` : '';
  const off = m.kind === 'trigger' && (m.params || {}).enabled === false ? '<span class="ntag off" data-tip="Chaîne désactivée : elle reste dans le fichier mais le robot l’ignore (clic droit → Activer la chaîne).">désactivée</span>' : '';
  const scope = m.kind === 'trigger' && (m.params || {}).state && (m.params || {}).type !== 'enter'
    ? `<div class="nsum nscope">${icoHtml(stateIcon(m.params.state), stateColor(m.params.state))} dans : ${esc(stateLabel(m.params.state))}</div>` : '';
  const desc = m.description ? `<div class="nsum" style="color:var(--mut)">${esc(m.description)}</div>` : '';
  return `<div class="nhead">${icoHtml(iconOf(m), k.color)}<span class="ntitle">${esc(k.label)}</span>${off}${tag}</div><div class="nsum">${esc(summary(m))}</div>${scope}${desc}<div class="nmsg"></div>`;
}
// Header tooltip (lot L5): what the kind does, then the help of the vocabulary entry the node uses.
function headTip(m) {
  const p = m.params || {};
  let help = '';
  if (m.kind === 'trigger' && p.type === 'event') help = (byId(evs(), p.event) || {}).help || '';
  if (m.kind === 'condition' && p.type === 'guard') help = (byId(S.V.guards, p.guard) || {}).help || '';
  if (m.kind === 'action') help = (byId(S.V.actions, p.action) || {}).help || '';
  return (KIND_TIP[m.kind] || '') + (help ? '\n' + help : '');
}
// Lot L8: bubble of a whole node: what it does (kind + vocabulary help), its settings, Category › Theme (same theme
// as the node menu), its description and its problems. Built at hover time from the live model and `issues`.
export function nodeTipOf(el) {
  const dfid = el && el.id && el.id.startsWith('node-') ? el.id.slice(5) : null, m = dfid != null ? model(dfid) : null;
  if (!m) return '';
  const lines = [headTip(m) || (KINDS[m.kind] || {}).label];
  const s = summary(m); if (s) lines.push('Réglages : ' + s);
  srcLines(m).forEach((l) => lines.push('Source : ' + l));          // lot M5: "valeur = au hasard dans salutations"
  const p = nodePath(m); if (p) lines.push(p);
  if (m.description) lines.push('Note : ' + m.description);
  (S.issues.get(m.id) || []).filter((i) => i.level !== 'todo').forEach((i) => lines.push((ISSUE_PREFIX[i.level] || '') + i.message));
  return lines.filter(Boolean).join('\n');
}
// Theme of a node = the theme its node-menu entry uses (menuItems): vocabulary entry theme or a theme slot.
export function nodeTheme(m) {
  const p = m.params || {}, a = p.args || {};
  if (m.kind === 'trigger') {
    if (p.type === 'after') return slotTheme('after');
    if (p.event === 'var_changed' && p.name === 'etat') return slotTheme('state_enter');
    if (String(p.event || '').startsWith('intent.')) return slotTheme('intent');
    const e = byId(evs(), p.event); return e ? e.theme : null;
  }
  if (m.kind === 'condition') {
    if (p.type === 'state' || (p.guard === 'var_compare' && a.name === 'etat')) return slotTheme('state_test');
    const g = byId(S.V.guards, p.guard); return g ? g.theme : null;
  }
  if (m.kind === 'action') {
    if (p.action === 'set_var' && a.name === 'etat') return slotTheme('state_move');
    const x = byId(S.V.actions, p.action); return x ? x.theme : null;
  }
  return null;
}
export function nodePath(m) {
  const c = CATS.find((x) => x.id === m.kind);
  return c ? c.label + ' › ' + themeById(nodeTheme(m)).label : '';
}
function portTips(dfid) {
  const el = nodeEl(dfid), m = model(dfid); if (!el || !m) return;
  el.querySelectorAll('.inputs .input').forEach((e) => e.setAttribute('data-tip', PORT_TIP.in));
  el.querySelectorAll('.outputs .output').forEach((e) => e.setAttribute('data-tip', m.kind === 'condition'
    ? (e.classList.contains('output_2') ? PORT_TIP.false : PORT_TIP.true) : m.kind === 'trigger' ? PORT_TIP.trigger : PORT_TIP.action));
}
export function nodeEl(dfid) { return document.getElementById('node-' + dfid); }
export function refreshNode(dfid) {
  const el = nodeEl(dfid), m = model(dfid);
  if (!el || !m) return;
  const c = el.querySelector('.drawflow_content_node');
  if (c) c.innerHTML = nodeHtml(m);
  markNode(dfid);
}

export function addNodeFromModel(m, x, y) {
  const k = KINDS[m.kind];
  const dfid = S.editor.addNode(m.kind, k.ins, k.outs, x, y, 'node-' + k.cls, { model: m }, nodeHtml(m), false);
  nidToDf.set(m.id, dfid);
  portTips(dfid);
  return dfid;
}
