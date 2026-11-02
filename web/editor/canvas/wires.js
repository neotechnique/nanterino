/**
 * Canvas: wires.
 *
 * Purpose :  kind-colour gradients on every wire (paintWires, paintDragWire) and the faded returning wires with their
 *            proxy badges (L7).
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, core/api.js, canvas/nodes.js, core/serialize.js, core/chains.js, canvas/view.js
 * Invariant: Drawflow 0.0.60 writes the wire path into svg.children[0]: the gradient <defs> is appended AFTER the path.
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, h, ico } from '../core/util.js';
import { S, linkKey, nidToDf, stateColor, stateIcon, stateLabel } from '../core/state.js';
import { dfData, model, nidOf } from '../core/api.js';
import { nodeEl } from './nodes.js';
import { serialize } from '../core/serialize.js';
import { computeChains, panTo } from '../core/chains.js';
import { nodeBox } from './view.js';

// ---------- wires: colour gradient from the source kind colour to the target kind colour ----------
// Drawflow draws every connection as <svg class="connection node_in_node-X node_out_node-Y output_k input_k"><path
// class="main-path" d="M x1 y1 C ... x2 y2">, in canvas coordinates. A userSpaceOnUse linearGradient from the path's
// first to its last point (the same space as `d`) follows the wire whatever its shape; it is refreshed whenever
// Drawflow redraws a node's wires (updateConnectionNodes is wrapped in boot()).
// INVARIANT (lot L4 fix "wires don't follow a dragged node"): Drawflow 0.0.60 updates a wire by writing `d` into
// `svg.children[0]` (updateConnectionNodes, updateConnection, reroute code) instead of looking up `.main-path`. The
// gradient <defs> is therefore APPENDED after the path; inserted first (as in L3) it received every new `d` and the
// visible path froze at its first shape while its node moved.
export const KIND_HEX = { start: '#2ea043', end: '#e5534b', trigger: '#e3b341', action: '#4f8ef7', condition: '#56d364', state: '#a371f7', goto: '#a371f7' };
// shared state: S.gradSeq (core/state.js)
export function paintWires(only) {
  if (!S.editor || !S.editor.container) return;
  const data = dfData();
  const sel = only ? `svg.connection.node_in_${only}, svg.connection.node_out_${only}` : 'svg.connection';
  S.editor.container.querySelectorAll(sel).forEach((svg) => {
    const cl = svg.classList;
    if (cl.length < 5) return;
    const inId = cl[1].slice(13), outId = cl[2].slice(14), path = svg.querySelector('.main-path');
    const a = data[outId], b = data[inId];
    if (!path || !a || !b) return;
    const nums = (path.getAttribute('d') || '').match(/-?\d+(?:\.\d+)?(?:e-?\d+)?/g);
    if (!nums || nums.length < 4) return;
    let x1 = +nums[0], y1 = +nums[1], x2 = +nums[nums.length - 2], y2 = +nums[nums.length - 1];
    if (x1 === x2 && y1 === y2) x2 += 1;
    let g = svg.querySelector('linearGradient');
    if (!g) {
      const NS = 'http://www.w3.org/2000/svg';
      const defs = document.createElementNS(NS, 'defs');
      g = document.createElementNS(NS, 'linearGradient');
      g.id = 'wg' + (++S.gradSeq);
      g.setAttribute('gradientUnits', 'userSpaceOnUse');
      g.append(document.createElementNS(NS, 'stop'), document.createElementNS(NS, 'stop'));
      defs.append(g); svg.append(defs);   // L4: AFTER the path, Drawflow writes `d` into svg.children[0]
    }
    g.setAttribute('x1', x1); g.setAttribute('y1', y1); g.setAttribute('x2', x2); g.setAttribute('y2', y2);
    const stops = g.querySelectorAll('stop');
    stops[0].setAttribute('offset', '0'); stops[0].setAttribute('stop-color', KIND_HEX[a.data.model.kind] || '#8b949e');
    stops[1].setAttribute('offset', '1'); stops[1].setAttribute('stop-color', KIND_HEX[b.data.model.kind] || '#8b949e');
    path.style.stroke = `url(#${g.id})`;
    // L7: "returning" wires (into a state hub, or from a hub to another column) are drawn faded by default
    const am = a.data.model, bm = b.data.model;
    cl.toggle('ret', (bm.kind === 'state' && am.kind !== 'start') || (am.kind === 'state' && am.group !== bm.group));
    svg.dataset.src = am.id; svg.dataset.dst = bm.id;
    const idx = +cl[3].split('_')[1], port = a.data.model.kind === 'condition' ? (idx === 1 ? 'true' : 'false') : 'out';
    const mt = S.linkMeta.get(linkKey(a.data.model.id, port, b.data.model.id));
    let t = path.querySelector('title');
    if (mt && mt.reason) { if (!t) { t = document.createElementNS('http://www.w3.org/2000/svg', 'title'); path.append(t); } t.textContent = 'Raison : ' + mt.reason; }
    else if (t) t.remove();
  });
  scheduleBadges();
  applyRetFocus();
}

// Lot L3: the wire being dragged out of a port (Drawflow's `connection_ele`, classes "connection" only until it is
// dropped) gets the same gradient: it STARTS with the source node's kind colour (green for a condition, whatever
// its port: the red / green pastille of Vrai / Faux is only a port marker) and ends with the colour of the node
// under the pointer, or the source colour while it hangs in the void. Called on connectionStart and on every
// Drawflow updateConnection (pointer move); paintWires() takes over once the wire is linked.
// shared state: S.dragSrcKind (core/state.js)
export function paintDragWire(clientX, clientY) {
  const svg = S.editor && S.editor.connection_ele;
  if (!svg || !S.dragSrcKind) return;
  const path = svg.querySelector('.main-path');
  const nums = path && (path.getAttribute('d') || '').match(/-?\d+(?:\.\d+)?(?:e-?\d+)?/g);
  const NS = 'http://www.w3.org/2000/svg';
  let g = svg.querySelector('linearGradient');
  if (!g) {
    const defs = document.createElementNS(NS, 'defs');
    g = document.createElementNS(NS, 'linearGradient');
    g.id = 'wg' + (++S.gradSeq);
    g.setAttribute('gradientUnits', 'userSpaceOnUse');
    g.append(document.createElementNS(NS, 'stop'), document.createElementNS(NS, 'stop'));
    defs.append(g); svg.append(defs);     // L4: after the path (Drawflow's updateConnection writes children[0])
  }
  if (nums && nums.length >= 4) {
    let x2 = +nums[nums.length - 2];
    if (+nums[0] === x2 && +nums[1] === +nums[nums.length - 1]) x2 += 1;
    g.setAttribute('x1', nums[0]); g.setAttribute('y1', nums[1]); g.setAttribute('x2', x2); g.setAttribute('y2', nums[nums.length - 1]);
  }
  let dst = S.dragSrcKind;
  if (clientX != null) {
    const el = document.elementFromPoint(clientX, clientY);
    const ne = el && el.closest && el.closest('.drawflow-node');
    const m = ne ? model(ne.id.replace('node-', '')) : null;
    if (m) dst = m.kind;
  }
  const stops = g.querySelectorAll('stop');
  stops[0].setAttribute('offset', '0'); stops[0].setAttribute('stop-color', KIND_HEX[S.dragSrcKind] || '#8b949e');
  stops[1].setAttribute('offset', '1'); stops[1].setAttribute('stop-color', KIND_HEX[dst] || '#8b949e');
  if (path) path.style.stroke = `url(#${g.id})`;
}

// ---------- returning wires: faded by default, "→ État" proxy badges, focus on hover / selection (L7) ----------
// LEGACY (L6/L7 hub drawing; Vars L2 draws no hub, so nothing below fires on a current document): a wire that ends
// in a state hub was drawn at ~12 % opacity (CSS `svg.connection.ret`); each chain end got a small badge "→ <État>"
// right of its last node instead (click = pan to the hub). Hovering or selecting a node, hub,
// wire or badge lights the related returning wires (class `rel`, full gradient) and fades the others
// (container class `retfocus`). Pure drawing: nothing here is saved.
// shared state: S.badgesEl, S.badgeRaf, S.retHover (core/state.js)
const RET_KEY = 'nanterino.editor.retWires';
export function retVisible() { try { return localStorage.getItem(RET_KEY) === 'visible'; } catch (e) { return false; } }
export function setRetVisible(on) {
  try { localStorage.setItem(RET_KEY, on ? 'visible' : 'discret'); } catch (e) { /* private window: per page only */ }
  document.body.classList.toggle('ret-visible', on);
  const b = $('#btnRet'); if (b) b.textContent = 'Fils de retour : ' + (on ? 'visibles' : 'discrets');
}
function scheduleBadges() { if (!S.badgeRaf) S.badgeRaf = requestAnimationFrame(() => { S.badgeRaf = 0; drawBadges(); }); }
function drawBadges() {
  if (!S.editor || !S.editor.precanvas) return;
  if (!S.badgesEl || !S.badgesEl.isConnected) { S.badgesEl = h('div', { id: 'rbadges' }); S.editor.precanvas.append(S.badgesEl); }
  S.badgesEl.innerHTML = '';
  const stack = new Map();
  S.editor.container.querySelectorAll('svg.connection.ret').forEach((svg) => {
    const src = svg.dataset.src, dst = svg.dataset.dst, sd = nidToDf.get(src), dd = nidToDf.get(dst);
    if (sd == null || dd == null) return;
    const dm = model(dd), sm = model(sd);
    if (!dm || dm.kind !== 'state' || !sm || sm.kind === 'state' || sm.kind === 'start') return;   // badge only for a chain end -> hub
    const b = nodeBox(sd), k = stack.get(src) || 0; stack.set(src, k + 1);
    const st = dm.params.state;
    const el = h('div', { class: 'rbadge', 'data-src': src, 'data-dst': dst, title: 'Retour vers l’état « ' + stateLabel(st) + ' » (clic : y aller)',
      style: `left:${b.x1 + 14}px;top:${(b.y0 + b.y1) / 2 - 12 + k * 28}px;--c:${stateColor(st)}` }, ico(stateIcon(st), stateColor(st)), h('span', {}, '→ ' + stateLabel(st)));
    el.addEventListener('mousedown', (e) => e.stopPropagation());   // no canvas pan from a badge
    el.addEventListener('click', (e) => { e.stopPropagation(); panTo(dst, 0.5); const he = nodeEl(dd); if (he) { he.classList.remove('blink'); void he.offsetWidth; he.classList.add('blink'); setTimeout(() => he.classList.remove('blink'), 2000); } });
    S.badgesEl.append(el);
  });
}
// Model ids of the chains that contain `nid` (from the analysed document), plus nid itself.
function chainIdsOf(nid) {
  const out = new Set([nid]);
  try { const ch = computeChains(serialize()); ch.keys.forEach((ids) => { if (ids.includes(nid)) ids.forEach((x) => out.add(x)); }); } catch (e) { /* half-built doc */ }
  return out;
}
// Focus source: hovered thing first, else the selected node / wire. Returns a predicate on (src, dst) or null.
function retFocusPred() {
  let f = S.retHover;
  if (!f && S.selDf != null && model(S.selDf)) f = { node: model(S.selDf).id };
  if (!f && S.editor && S.editor.connection_selected) { const svg = S.editor.connection_selected.closest && S.editor.connection_selected.closest('svg.connection'); if (svg && svg.dataset.src) f = { wire: [svg.dataset.src, svg.dataset.dst] }; }
  if (!f) return null;
  const kindOf = (id) => { const d = nidToDf.get(id); const m = d == null ? null : model(d); return m ? m.kind : null; };
  if (f.node && kindOf(f.node) === 'state') { const s = f.node; return (a, b) => a === s || b === s; }
  const seed = f.node || (kindOf(f.wire[0]) === 'state' ? f.wire[1] : f.wire[0]);
  const R = chainIdsOf(seed);
  return (a, b) => (f.wire && a === f.wire[0] && b === f.wire[1]) || (R.has(a) && kindOf(a) !== 'state') || (R.has(b) && kindOf(b) !== 'state');
}
function applyRetFocus() {
  if (!S.editor || !S.editor.container) return;
  const pred = retFocusPred();
  S.editor.container.classList.toggle('retfocus', !!pred);
  S.editor.container.querySelectorAll('svg.connection').forEach((svg) => svg.classList.toggle('rel', !!pred && svg.classList.contains('ret') && pred(svg.dataset.src, svg.dataset.dst)));
  if (S.badgesEl) S.badgesEl.querySelectorAll('.rbadge').forEach((el) => el.classList.toggle('rel', !!pred && pred(el.dataset.src, el.dataset.dst)));
}
export function installRetHover() {
  const root = S.editor.container;
  root.addEventListener('mouseover', (e) => {
    const t = e.target, bd = t.closest && t.closest('.rbadge'), nd = !bd && t.closest && t.closest('.drawflow-node'), w = !bd && !nd && t.closest && t.closest('svg.connection');
    const next = bd ? { wire: [bd.dataset.src, bd.dataset.dst] } : nd ? { node: nidOf(nd.id.replace('node-', '')) } : w && w.dataset.src ? { wire: [w.dataset.src, w.dataset.dst] } : null;
    if (JSON.stringify(next) !== JSON.stringify(S.retHover)) { S.retHover = next; applyRetFocus(); }
  });
  root.addEventListener('mouseleave', () => { if (S.retHover) { S.retHover = null; applyRetFocus(); } });
  // selection changes arrive through Drawflow's own click handling: re-evaluate just after it
  S.editor.container.addEventListener('mouseup', () => setTimeout(applyRetFocus, 0));
}
