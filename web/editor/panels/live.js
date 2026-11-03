/**
 * Panels: live view and right-hand tabs.
 *
 * Purpose :  WS /ws + polling fallback (onLive, connectWs, heartbeat) and activateTab.
 * Boundary:  WS /ws (live state, heartbeat, last_transition) with GET /api/live polling as fallback; never /api/control.
 *            Moved unchanged out of the former single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, core/api.js, canvas/nodes.js, diagnostics/check.js, inspector/inspector.js,
 *            panels/intents.js, variables/panel.js, variables/tables.js, tester/tester.js, panels/history-panels.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, dbg } from '../core/util.js';
import { S, byId, evs, nidToDf, stateLabel } from '../core/state.js';
import { api } from '../core/api.js';
import { nodeEl } from '../canvas/nodes.js';
import { markLive } from '../diagnostics/check.js';
import { renderInspector } from '../inspector/inspector.js';
import { renderIntents } from './intents.js';
import { startVarsPoll, stopVarsPoll } from '../variables/panel.js';
import { renderVars } from '../variables/tables.js';
import { clearSimLights, renderTester, selectTrace, sim, simRun } from '../tester/tester.js';
import { loadJournal, loadVersions, onLastTransition } from './history-panels.js';

// ---------- live view ----------
// Live snapshot: WS /ws when the server has a WebSocket library, otherwise GET /api/live polling
// (same snapshot, 2 Hz). Polling only runs while no WS message arrived recently.
function onLive(s) {
  if (!S.lastWs) dbg('live first snapshot state=' + s.state);
  S.lastWs = Date.now();
  onLastTransition(s.last_transition || null);
  S.lastAge = s.heartbeat ? s.heartbeat.age_ms : null;
  if (s.state !== S.liveState) { S.liveState = s.state; $('#liveState').textContent = 'État : ' + stateLabel(s.state); markLive(); }
  paintHeart();
}
// After two failed handshakes (server without a WebSocket library) stop retrying for the session:
// each attempt would log a console error. Polling /api/live keeps the live view working.
// shared state: S.wsFails, S.wsOpened (core/state.js)
export function connectWs() {
  let ws;
  try { ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws'); } catch (e) { return; }
  ws.onopen = () => { S.wsOpened = true; S.wsFails = 0; };
  ws.onmessage = (m) => { try { onLive(JSON.parse(m.data)); } catch (e) { /* ignore bad frame */ } };
  ws.onclose = () => { if (!S.wsOpened && ++S.wsFails >= 2) return; setTimeout(connectWs, S.wsOpened ? 3000 : 1500); };
}
export async function pollLive() {
  if (Date.now() - S.lastWs < 1500) return;
  try { const r = await api('/api/live', { progress: false }); if (r.ok && r.json) onLive(r.json); } catch (e) { /* offline: heart turns red */ }
}

export function paintHeart() {
  const el = $('#heart');
  const stale = Date.now() - S.lastWs > 2000;
  const age = stale || S.lastAge == null ? 1e9 : S.lastAge;
  el.className = 'heart ' + (age < 500 ? 'ok' : age < 2000 ? 'slow' : 'dead');
  el.title = stale ? 'Pas de nouvelles du robot' : `Dernier battement : ${S.lastAge} ms`;
}

// ---------- right-hand panels (tabs) ----------
// shared state: S.curTab (core/state.js)
export function activateTab(name) {
  const leaving = S.curTab;
  S.curTab = name;
  document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === name));
  document.querySelectorAll('#right .panel').forEach((p) => { p.hidden = p.dataset.panel !== name; });
  if (leaving === 'tester' && name !== 'tester') clearSimLights();   // simulator lights never linger over the live view
  if (name === 'node') renderInspector();
  if (name === 'intents') renderIntents();
  if (name === 'vars') { renderVars(); startVarsPoll(); } else stopVarsPoll();
  if (name === 'tester') { renderTester(); if (sim.trace.length) selectTrace(sim.sel < 0 ? sim.trace.length - 1 : sim.sel, false); else simRun(false); }
  if (name === 'versions') loadVersions();
  if (name === 'journal') loadJournal();
  if (innerWidth <= 900) document.body.classList.remove('hide-right');
}
// Transition reasons are free text set by the graph (goto "reason"), else the triggering event id.
const REASONS = { appel: 'Nom du robot entendu', ask: 'Question tapée', chanson: 'Demande de chanson', max_turns: "Trop d'échanges",
  pas_compris: 'Parole non comprise', phrase: 'Phrase dite', refus: 'Le visiteur veut partir', silence: 'Silence prolongé',
  visage_perdu: 'Le visage disparaît', source: 'Bouton Démarrer', start: 'Démarrage', hush: '« Tais-toi »', stop: 'Bouton Stop',
  off: 'Bouton Éteindre', on: 'Bouton Allumer' };
export const reasonLabel = (r) => REASONS[r] || (byId(evs(), r) || {}).label || String(r);
export const fmtTime = (t) => new Date(t * 1000).toLocaleTimeString('fr-FR');
export const isVisible = (nid) => {
  const el = nodeEl(nidToDf.get(nid)); if (!el) return false;
  const a = el.getBoundingClientRect(), b = $('#drawflow').getBoundingClientRect();
  return a.left >= b.left && a.right <= b.right && a.top >= b.top && a.bottom <= b.bottom;
};
