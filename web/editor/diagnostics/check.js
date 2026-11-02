/**
 * Diagnostics: branch order, server dry run and badges.
 *
 * Purpose :  fan-out order (GC2-like), POST /api/graph/check (runCheck / freshCheck), node badges, the toolbar counter
 *            #btnDiag (diagNodes / diagCycle) and the message list.
 * Boundary:  network through core/api.js: POST /api/graph/check (dry run, never writes). Moved unchanged out of the
 *            former single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, core/api.js, canvas/nodes.js, core/serialize.js, diagnostics/analysis.js,
 *            canvas/view.js, frames/nesting.js, menu/node-menu.js, hierarchy/tree.js, panels/live.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, h } from '../core/util.js';
import { S, KINDS, nidToDf } from '../core/state.js';
import { dfNode, model, postJson } from '../core/api.js';
import { nodeEl } from '../canvas/nodes.js';
import { serialize } from '../core/serialize.js';
import { analyze } from './analysis.js';
import { drawBands } from '../canvas/view.js';
import { focusNode } from '../frames/nesting.js';
import { selectDf } from '../menu/node-menu.js';
import { scheduleTree } from '../hierarchy/tree.js';
import { activateTab } from '../panels/live.js';

// ---------- branch order (GC2-like: every branch without state change runs, one branch changes the state) ----------
export function scheduleCheck() {
  clearTimeout(S.checkTimer);
  S.checkTimer = setTimeout(runCheck, 500);
}
// Resolves true when checkErrors / fanInfo describe the document as it is now (fresh or already current), false when
// the dry run could not answer (network / 5xx). A run already in flight for the same document is shared, and an answer
// for an older document never overwrites a newer one (L6: save awaits this instead of trusting stale badges).
// shared state: S.checkInflight, S.checkOkKey (core/state.js)
export async function runCheck() {
  if (!S.editor || S.loading) return false;
  let doc;
  try { doc = serialize(); } catch (e) { return false; }
  const key = JSON.stringify(doc);
  if (S.checkInflight && S.checkInflight.key === key) return S.checkInflight.promise;
  if (key === S.lastCheckKey) return key === S.checkOkKey;   // nothing changed since the last dry run: no loop through analyze()
  S.lastCheckKey = key;
  const promise = (async () => {
    let r;
    try { r = await postJson('/api/graph/check', doc); } catch (e) { r = {}; }
    if (S.checkInflight && S.checkInflight.key === key) S.checkInflight = null;
    if (!r.json || r.status >= 500) { if (S.lastCheckKey === key) S.lastCheckKey = ''; return false; }   // retry next time
    if (S.lastCheckKey !== key) return false;      // the document changed meanwhile: a newer run owns the badges
    S.fanInfo = { warnings: r.json.warnings || [], fans: r.json.fans || {} };
    S.checkErrors = r.json.errors || [];           // lot L5: the dry-run compile errors become node badges too
    S.checkOkKey = key;
    analyze();
    return true;
  })();
  S.checkInflight = { key, promise };
  return promise;
}
// L6: run the debounced dry run now (cancel the pending timer) and wait for the answer about the current document.
export async function freshCheck() {
  clearTimeout(S.checkTimer); S.checkTimer = null;
  return runCheck();
}
// A small numbered badge on each target of a node with several outgoing links = execution order.
export function paintOrderBadges() {
  document.querySelectorAll('.ordbadge').forEach((e) => e.remove());
  const fans = S.fanInfo.fans || {};
  for (const tid in fans) {
    const groups = new Map();                    // path prefix -> Map(next node id -> {rank, ignored})
    fans[tid].forEach((b) => {
      for (let i = 0; i < b.nodes.length - 1; i++) {
        const key = b.nodes.slice(0, i + 1).join('>');
        if (!groups.has(key)) groups.set(key, new Map());
        const g = groups.get(key), nx = b.nodes[i + 1], cur = g.get(nx);
        g.set(nx, { rank: cur ? Math.min(cur.rank, b.rank) : b.rank, ignored: cur ? cur.ignored && b.ignored : b.ignored, moves: (cur && cur.moves) || b.moves });
      }
    });
    groups.forEach((g) => {
      if (g.size < 2) return;
      g.forEach((v, nid) => {
        const df = nidToDf.get(nid), el = df != null ? nodeEl(df) : null;
        if (!el) return;
        el.append(h('span', { class: 'ordbadge' + (v.ignored ? ' ign' : ''), title: v.ignored ? "Ordre " + v.rank + " : ignorée, une autre branche change déjà l'état." : 'Ordre d\'exécution ' + v.rank + (v.moves ? ' (change l\'état)' : '') }, String(v.rank)));
      });
    });
  }
}
// Lot L5: each node with an error / a warning (/ an info) carries a badge (✖ red, ⚠ amber, i grey) whose tooltip lists
// the messages; a click selects the node and shows them at the top of the inspector. 'todo' (fresh node) has no badge.
export const ISSUE_PREFIX = { err: 'Erreur : ', warn: 'Attention : ', todo: 'À faire : ', info: 'Info : ' };
export function markNode(dfid) {
  const el = nodeEl(dfid), m = model(dfid);
  if (!el || !m) return;
  const list = S.issues.get(m.id) || [];
  const hasErr = list.some((i) => i.level === 'err'), hasWarn = !hasErr && list.some((i) => i.level === 'warn');
  el.classList.toggle('err', hasErr);
  el.classList.toggle('warn', hasWarn);
  const msg = el.querySelector('.nmsg');
  if (msg) msg.textContent = list.filter((i) => i.level !== 'info').map((i) => i.message).join(' ');
  el.removeAttribute('title');                  // the badge carries the messages now (one tooltip system)
  const lvl = hasErr ? 'err' : hasWarn ? 'warn' : list.some((i) => i.level === 'info') ? 'info' : null;
  let b = el.querySelector(':scope > .dbadge');
  if (!lvl) { if (b) b.remove(); return; }
  if (!b) {
    b = h('span', { class: 'dbadge', role: 'button', tabindex: '-1' });
    ['mousedown', 'pointerdown', 'touchstart', 'dblclick'].forEach((t) => b.addEventListener(t, (e) => e.stopPropagation(), { passive: true }));
    b.addEventListener('click', (e) => { e.stopPropagation(); const mm = model(dfid); if (mm) showIssuesOf(mm.id, false); });
    el.append(b);
  }
  b.className = 'dbadge ' + lvl;
  b.textContent = lvl === 'err' ? '✖' : lvl === 'warn' ? '⚠' : 'i';
  b.setAttribute('aria-label', lvl === 'err' ? 'Erreur' : lvl === 'warn' ? 'Avertissement' : 'Information');
  b.setAttribute('data-tip', list.filter((i) => i.level !== 'todo').map((i) => (ISSUE_PREFIX[i.level] || '') + i.message).join('\n'));
}
// Select a node and show its messages in the inspector (pan = bring it into view first: toolbar counter).
function showIssuesOf(nid, pan) {
  const df = nidToDf.get(nid); if (df == null) return;
  if (S.curTab !== 'node') activateTab('node');
  if (pan) focusNode(nid); else selectDf(df);
  if (innerWidth <= 900) document.body.classList.remove('hide-right');
  const l = document.querySelector('#inspector .isslist'); if (l) l.scrollIntoView({ block: 'nearest' });
}
// Nodes with an error, then with a warning, in reading order (column / x, then y): the toolbar counter cycles them.
// shared state: S.diagIdx (core/state.js)
export function diagNodes() {
  const rank = (nid) => { const l = S.issues.get(nid) || []; return l.some((i) => i.level === 'err') ? 0 : l.some((i) => i.level === 'warn') ? 1 : 2; };
  return [...S.issues.keys()].filter((nid) => nidToDf.has(nid) && rank(nid) < 2).sort((a, b) => {
    const da = dfNode(nidToDf.get(a)), db = dfNode(nidToDf.get(b));
    return rank(a) - rank(b) || (da.pos_x - db.pos_x) || (da.pos_y - db.pos_y);
  });
}
export function diagCycle() {
  const list = diagNodes();
  if (!list.length) { if (S.globalIssues.length) $('#msgs').hidden = false; return null; }
  S.diagIdx = (S.diagIdx + 1) % list.length;
  showIssuesOf(list[S.diagIdx], true);
  return list[S.diagIdx];
}
export function paintDiagWires() {   // wires into / out of a node with an error get a subtle red glow
  const bad = new Set();
  S.issues.forEach((l, nid) => { if (l.some((i) => i.level === 'err') && nidToDf.has(nid)) bad.add(String(nidToDf.get(nid))); });
  document.querySelectorAll('#drawflow svg.connection').forEach((svg) => {
    const cl = svg.classList;
    svg.classList.toggle('derr', !!(cl[1] && cl[2] && (bad.has(cl[1].slice(13)) || bad.has(cl[2].slice(14)))));
  });
}
export function markLive() { drawBands(); }

// Toolbar counter (lot L5): errors / warnings of the whole graph; a click cycles through the affected nodes.
function paintDiagCount(ne, nw) {
  const b = $('#btnDiag'); if (!b) return;
  b.className = 'diag' + (ne ? ' err' : nw ? ' warn' : ' ok');
  b.innerHTML = '';
  if (!ne && !nw) b.append(h('span', { class: 'dok' }, '✔'), ' 0');
  else b.append(h('span', { class: 'dne' }, '✖ ' + ne), h('span', { class: 'dnw' }, '⚠ ' + nw));
  b.setAttribute('data-tip', !ne && !nw ? 'Aucune erreur ni avertissement détecté.'
    : `${ne} erreur(s), ${nw} avertissement(s). Cliquer : aller au nœud suivant concerné (ses messages s’affichent dans l’inspecteur).`);
  b.setAttribute('aria-label', `${ne} erreur(s), ${nw} avertissement(s)`);
}
export function renderMsgs() {
  scheduleTree();                      // L10: hierarchy badges follow every diagnostics pass (debounced)
  const box = $('#msgs'), tg = $('#btnMsgs');
  const all = [];
  S.issues.forEach((list, nid) => list.forEach((i) => all.push({ ...i, nid })));
  S.globalIssues.forEach((i) => all.push({ ...i, nid: null }));
  for (let k = all.length - 1; k >= 0; k--) if (all[k].level === 'info') all.splice(k, 1);   // infos: badge only
  const ne = all.filter((i) => i.level === 'err').length, nw = all.length - ne;
  paintDiagCount(ne, all.filter((i) => i.level === 'warn').length);
  tg.hidden = !all.length;
  tg.textContent = `${ne} erreur(s), ${nw} avertissement(s)`;
  box.innerHTML = '';
  all.sort((a, b) => (a.level === b.level ? 0 : a.level === 'err' ? -1 : 1)).forEach((i) => {
    const m = i.nid ? model(nidToDf.get(i.nid)) : null;
    const where = m ? KINDS[m.kind].label + ' ' + m.id + ' : ' : '';
    box.append(h('div', { class: 'm ' + i.level, onclick: () => i.nid && focusNode(i.nid) }, where + i.message));
  });
  if (!all.length) box.hidden = true;
}
