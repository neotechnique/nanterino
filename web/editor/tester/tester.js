/**
 * Tester (POST /api/graph/simulate on the current, possibly unsaved, document).
 *
 * Purpose :  sim state, steps, simRun, trace rendering and selection.
 * Boundary:  network through core/api.js: POST /api/graph/simulate (on the current, possibly unsaved, document). Moved
 *            unchanged out of the former single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, variables/model.js, core/api.js, core/serialize.js, core/chains.js,
 *            diagnostics/analysis.js, canvas/view.js, minimap/minimap.js, frames/nesting.js, inspector/fields.js,
 *            variables/panel.js, panels/live.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, h, ico } from '../core/util.js';
import { S, byId, evs, nidToDf, stateIcon, stateLabel } from '../core/state.js';
import { docVars, listDef, sysVars, varDef } from '../variables/model.js';
import { dfData, postJson } from '../core/api.js';
import { serialize } from '../core/serialize.js';
import { computeChains, lit, paintChains } from '../core/chains.js';
import { analyze } from '../diagnostics/analysis.js';
import { drawBands, nodeBox } from '../canvas/view.js';
import { focusChainIds } from '../minimap/minimap.js';
import { focusNode, setView } from '../frames/nesting.js';
import { field, selectCtl } from '../inspector/fields.js';
import { liveText } from '../variables/panel.js';
import { reasonLabel } from '../panels/live.js';

// ---------- Tester (POST /api/graph/simulate on the CURRENT, possibly unsaved, document) ----------
// The whole step list is replayed on every call (the simulator is deterministic and isolated), so the
// panel never has to keep a robot-side session. The latest step's fired chains light up one by one.
export const sim = { steps: [], start: '', trace: [], final: null, chains: null, sel: -1, say: '', faces: 2, wait: 7, note: '', docErrors: [], timers: [], busy: false, again: false };
const stepText = (s) => (s.event != null ? ((byId(evs(), s.event) || {}).label || s.event) : s.say != null ? `Le visiteur dit « ${s.say} »` : s.wait_s != null ? `Attendre ${s.wait_s} s` : `${s.faces} visage(s) vu(s)`);
const stepIcon = (s) => (s.event != null ? ((byId(evs(), s.event) || {}).icon || 'bolt') : s.say != null ? 'microphone' : s.wait_s != null ? 'hourglass' : 'users');
function startStateId() {
  if (sim.start && (S.meta.states || []).some((s) => s.id === sim.start)) return sim.start;
  const st = Object.values(dfData()).map((d) => d.data.model).find((m) => m.kind === 'start');
  return (st && st.params.state) || 'veille';
}
export function clearSimLights() {
  sim.timers.forEach(clearTimeout); sim.timers = [];
  lit.now = new Set(); lit.past = new Set(); S.simState = null;
  paintChains(); drawBands();
}
export function addStep(step) { sim.note = ''; sim.steps.push(step); simRun(true); }
export async function simRun(animate) {
  if (sim.busy) { sim.again = true; return; }
  sim.busy = true;
  const doc = serialize();
  let r;
  try { r = await postJson('/api/graph/simulate', { doc, start_state: startStateId(), steps: sim.steps }); }
  catch (e) { r = { ok: false, status: 0, json: { errors: [{ message: 'Réseau : ' + e }] } }; }
  sim.busy = false;
  S.simErrors = []; sim.docErrors = [];
  if (!r.ok) {
    const errs = (r.json && r.json.errors) || [{ node: null, message: 'Erreur ' + r.status }];
    const stepErr = errs.filter((e) => e.step != null);
    if (stepErr.length) {                       // refused step(s): drop them, tell why, replay without
      const bad = new Set(stepErr.map((e) => e.step));
      sim.steps = sim.steps.filter((_, i) => !bad.has(i));
      sim.note = 'Pas refusé par le simulateur : ' + stepErr.map((e) => e.message).join(' ');
      return simRun(false);
    }
    S.simErrors = errs; sim.docErrors = errs; sim.trace = []; sim.final = null; sim.sel = -1;
    clearSimLights(); analyze(); renderTester();
    if (S.simErrors.some((e) => e.node)) $('#msgs').hidden = false;
    return r;
  }
  sim.trace = r.json.trace || []; sim.final = r.json.final || null; sim.chains = computeChains(doc);
  analyze();
  const last = sim.steps.length - 1;
  const fresh = sim.trace.map((e, i) => (e.step === last ? i : -1)).filter((i) => i >= 0);
  sim.timers.forEach(clearTimeout); sim.timers = [];
  if (animate && fresh.length > 1) {
    fresh.forEach((i, k) => sim.timers.push(setTimeout(() => selectTrace(i, k === fresh.length - 1 ? 'fit' : true), k * 400)));
    selectTrace(fresh[0], true);
  } else selectTrace(sim.trace.length - 1, 'fit');
  renderTester();
  if (sim.again) { sim.again = false; return simRun(false); }
  return r;
}
// Light the chain of trace entry i (current) and every entry before it (already fired).
export function selectTrace(i, pan) {
  sim.sel = i;
  const idsOf = (e) => (sim.chains && sim.chains.keys.get(e.chain)) || [];
  lit.now = new Set(i >= 0 && sim.trace[i] ? idsOf(sim.trace[i]) : []);
  lit.past = new Set();
  sim.trace.slice(0, Math.max(i, 0)).forEach((e) => idsOf(e).forEach((x) => lit.past.add(x)));
  S.simState = sim.trace[i] ? sim.trace[i].to : null;
  paintChains(); drawBands(); renderSimTrace();
  // L7 fix round: every displayed step brings its chain to the middle of the canvas (~0.75 zoom, or the whole
  // chain when larger); `pan === false` (tab switch) keeps the user's view
  if (pan !== false && i >= 0 && sim.trace[i]) focusChainIds(idsOf(sim.trace[i]));
}
// Frame every lit node (fired chains in blue, current one in yellow) when they fit at zoom >= 0.3;
// otherwise keep that zoom and centre on the current chain.
function fitLit() {
  const box = (set) => {
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    set.forEach((nid) => { const d = nidToDf.get(nid); if (d == null) return; const b = nodeBox(d); x0 = Math.min(x0, b.x0); y0 = Math.min(y0, b.y0); x1 = Math.max(x1, b.x1); y1 = Math.max(y1, b.y1); });
    return x0 > x1 ? null : { x0, y0, x1, y1 };
  };
  const all = box(new Set([...lit.now, ...lit.past])), now = box(lit.now), c = $('#drawflow');
  if (!all || !now) return;
  const w = all.x1 - all.x0, hh = all.y1 - all.y0;
  const z = Math.max(0.3, Math.min(1, c.clientWidth / (w * 1.1), c.clientHeight / (hh * 1.1)));
  const b = w * z <= c.clientWidth && hh * z <= c.clientHeight ? all : now;
  setView(z, c.clientWidth / 2 - ((b.x0 + b.x1) / 2) * z, c.clientHeight / 2 - ((b.y0 + b.y1) / 2) * z);
}
function renderSimTrace() {
  const box = $('#simTrace'); if (!box) return;
  box.innerHTML = ''; $('#simStatus').innerHTML = '';   // status card sits outside the scrolling trace so it never gets clipped
  if (sim.note) box.append(h('div', { class: 'simerr' }, sim.note));
  sim.docErrors.forEach((e) => box.append(h('div', { class: 'simerr', onclick: () => e.node && focusNode(e.node) }, (e.node ? e.node + ' : ' : '') + e.message)));
  if (sim.docErrors.length) box.append(h('p', { class: 'hint' }, 'Le robot refuse ce document : corrigez les nœuds en rouge, puis relancez.'));
  const f = sim.final;
  if (f) {
    const ex = f.expression ? (typeof f.expression === 'string' ? f.expression : f.expression.name) : 'aucune';
    $('#simStatus').append(h('div', { class: 'simstate' }, ico(stateIcon(f.state)), 'État simulé : ', h('b', {}, stateLabel(f.state)),
      h('span', { class: 'hint' }, `· tours ${f.turns} · expression ${ex} · regard ${f.gaze_mode}`)));
  }
  // Vars L2: simulated variables after the selected trace entry (else the final ones); changed ones highlighted
  // against the entry before it.
  const cur = sim.trace[sim.sel] ? sim.trace[sim.sel].vars : (f && f.vars);
  if (cur) {
    const prev = sim.sel > 0 && sim.trace[sim.sel - 1] ? sim.trace[sim.sel - 1].vars : null;
    const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
    const grid = h('div', { class: 'simvars', title: 'Variables simulées après ce pas (en couleur : changées par ce pas)' },
      h('span', { class: 'svlab' }, sim.trace[sim.sel] ? 'Variables après la ligne choisie :' : 'Variables à la fin :'));
    // L12: grouped by scope; conversation ones are marked: a new conversation (new visitor) puts them back
    const sysIds = new Set(sysVars().map((v) => v.id)), dn = docVars().names, dl = docVars().lists;
    const scopeOf = (k, isList) => (!isList && sysIds.has(k) ? 'system' : (((isList ? dl : dn)[k] || {}).scope || 'global'));
    const groups = { system: [], global: [], conversation: [] };
    Object.keys(cur.names || {}).forEach((k) => {
      const v = cur.names[k], chg = !!prev && !same(v, (prev.names || {})[k]), sc = scopeOf(k, false);
      const tp = (varDef(k) || {}).type;
      (groups[sc] || groups.global).push(h('span', { class: 'sv' + (chg ? ' chg' : '') + (sc === 'conversation' ? ' conv' : ''), 'data-svar': k, 'data-scope': sc,
        title: sc === 'conversation' ? 'Remise à sa valeur initiale à chaque nouvelle conversation' : null },
      h('code', {}, k), ' = ', k === 'etat' ? stateLabel(v) : liveText(v, tp), sc === 'conversation' ? h('span', { class: 'svreset' }, ' ↺') : null));
    });
    Object.keys(cur.lists || {}).forEach((k) => {
      const v = cur.lists[k], chg = !!prev && !same(v, (prev.lists || {})[k]), sc = scopeOf(k, true), ld = listDef(k) || {};
      const isDict = v && typeof v === 'object' && !Array.isArray(v);
      const tip = isDict ? Object.keys(v).map((x) => x + ' → ' + liveText(v[x], ld.type)).join(' · ') : (v || []).map((x) => liveText(x, ld.type)).join(' · ');
      const mark = isDict ? ' dict' : ld.mode === 'shuffle' ? ' sac' : ld.mode === 'history' ? ' hist.' : '';
      (groups[sc] || groups.global).push(h('span', { class: 'sv list' + (isDict ? ' dict' : '') + (chg ? ' chg' : '') + (sc === 'conversation' ? ' conv' : ''), 'data-svar': k, 'data-scope': sc,
        'data-mode': isDict ? 'dict' : (ld.mode || 'plain'), title: tip + (sc === 'conversation' ? ' (remise à zéro à chaque nouvelle conversation)' : '') },
      h('code', {}, k), ' ', liveText(v), h('small', {}, mark), sc === 'conversation' ? h('span', { class: 'svreset' }, ' ↺') : null));
    });
    const GLAB = { system: 'Système', global: 'Globales', conversation: 'Conversation ↺ (remises à zéro à chaque nouvelle conversation)' };
    ['system', 'global', 'conversation'].forEach((sc) => {
      if (!groups[sc].length) return;
      grid.append(h('div', { class: 'svgroup', 'data-group': sc }, h('span', { class: 'svglab' }, GLAB[sc] + ' :'), groups[sc]));
    });
    $('#simStatus').append(grid);
  }
  for (let st = -1; st < sim.steps.length; st++) {
    const rows = sim.trace.map((e, i) => ({ e, i })).filter((x) => x.e.step === st);
    const s = sim.steps[st];
    box.append(h('div', { class: 'sstep' }, ico(st < 0 ? 'flag' : stepIcon(s)), st < 0 ? 'Démarrage' : `${st + 1}. ${stepText(s)}`));
    if (!rows.length) box.append(h('div', { class: 'note' }, 'Rien ne se déclenche.'));
    rows.forEach(({ e, i }) => box.append(h('div', { class: 'trow' + (i === sim.sel ? ' sel' : ''), onclick: () => selectTrace(i, true) },
      h('div', {}, ico(stateIcon(e.to)), ' ', e.moved ? [stateLabel(e.from), h('span', { class: 'arrow' }, ' → '), stateLabel(e.to)] : ['Reste en ', stateLabel(e.to)],
        h('span', { class: 'hint' }, e.reason ? '  (' + reasonLabel(e.reason) + ')' : '')),
      h('div', { class: 'meta' }, `${Number(e.t).toFixed(1)} s · chaîne ${e.chain}` + ((e.effects || []).length ? ' · ' + e.effects.join(', ') : '')))));
  }
  const sel = box.querySelector('.trow.sel');
  if (sel) sel.scrollIntoView({ block: 'nearest' });
}
export function renderTester() {
  const box = $('#tester'); if (!box) return;
  box.innerHTML = '';
  box.append(h('p', { class: 'hint' }, "Essaie le graphe en cours d'édition (même non enregistré) sur un robot simulé : sans son ni micro, le vrai robot n'est jamais touché."));
  box.append(field('État de départ', selectCtl((S.meta.states || []).map((s) => ({ v: s.id, l: stateLabel(s.id) })), startStateId(), (v) => { sim.start = v; sim.note = ''; simRun(false); })));
  // Result first (state + trace, scrolls on its own), controls below.
  box.append(h('div', { id: 'simStatus' }), h('div', { id: 'simTrace' }));
  box.append(h('div', { class: 'sect' }, 'Un événement arrive'));
  const grid = h('div', { class: 'evgrid' });
  S.V.events.forEach((e) => grid.append(h('button', { type: 'button', title: e.help || e.label, onclick: () => addStep({ event: e.id }) }, ico(e.icon), h('span', { class: 't' }, e.label))));
  box.append(grid);
  box.append(h('div', { class: 'sect' }, 'Le visiteur dit…'));
  const say = h('input', { type: 'text', placeholder: 'ex. au revoir', style: 'flex:1;width:auto;min-width:0' }); say.value = sim.say;
  say.addEventListener('input', () => { sim.say = say.value; });
  const doSay = () => { const t = say.value.trim(); if (!t) return; sim.say = ''; addStep({ say: t }); };
  say.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); doSay(); } });
  box.append(h('div', { class: 'rowbtns' }, say, h('button', { type: 'button', onclick: doSay }, ico('microphone'), 'Dire')));
  box.append(h('div', { class: 'sect' }, 'Laisser passer du temps'));
  const wn = h('input', { type: 'number', min: 0.1, step: 0.5, 'aria-label': 'secondes' }); wn.value = sim.wait;
  wn.addEventListener('input', () => { sim.wait = wn.value; });
  box.append(h('div', { class: 'rowbtns' },
    h('button', { type: 'button', onclick: () => addStep({ wait_s: 5 }) }, ico('hourglass'), 'Attendre 5 s'),
    h('button', { type: 'button', onclick: () => addStep({ wait_s: 10 }) }, ico('hourglass'), 'Attendre 10 s'),
    wn, h('button', { type: 'button', onclick: () => { const n = Number(wn.value); if (n > 0 && n <= 3600) addStep({ wait_s: n }); } }, 'Attendre (s)')));
  const fn = h('input', { type: 'number', min: 0, max: 20, step: 1, 'aria-label': 'visages' }); fn.value = sim.faces;
  fn.addEventListener('input', () => { sim.faces = fn.value; });
  box.append(h('div', { class: 'sect' }, 'Visages vus par la caméra (facultatif)'),
    h('div', { class: 'rowbtns' }, fn, h('button', { type: 'button', onclick: () => { const n = Math.max(0, Math.min(20, parseInt(fn.value, 10) || 0)); addStep({ faces: n }); } }, ico('users'), 'Appliquer')));
  box.append(h('div', { class: 'rowbtns', style: 'margin-top:12px' },
    h('button', { type: 'button', class: 'danger', onclick: async () => { sim.steps = []; sim.note = ''; await simRun(false); clearSimLights(); } }, ico('refresh'), 'Réinitialiser'),   // L7: no highlight after a reset
    h('button', { type: 'button', onclick: () => { sim.steps.pop(); sim.note = ''; simRun(false); }, disabled: !sim.steps.length }, ico('x'), 'Retirer le dernier pas')));
  renderSimTrace();
}
