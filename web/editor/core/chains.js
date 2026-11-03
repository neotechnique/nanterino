/**
 * Editor core: chain keys (mirror of graph_visual.compile).
 *
 * Purpose :  computeChains() and the live / simulated chain lighting, so a journal or simulator entry (which carries only
 *            a chain key) lights its nodes.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, core/api.js, canvas/nodes.js, minimap/minimap.js, frames/nesting.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $ } from './util.js';
import { S, nidToDf } from './state.js';
import { dfData, dfNode } from './api.js';
import { nodeEl } from '../canvas/nodes.js';
import { focusChainIds } from '../minimap/minimap.js';
import { setView } from '../frames/nesting.js';

// ---------- chains: structural keys (mirror of graph_visual.compile) ----------
// The server reports a fired transition by its chain key; this walks a document the way the compiler does
// (triggers in `order`, then by (y, x); true branch before false branch; per-state counters) and returns
//   keys: Map key -> [node ids of that path], byTrigger: Map trigger id -> [keys].
// Chains the compiler would reject are skipped, which is also what it does (and then simulate answers 400).
export function computeChains(doc) {
  const nodes = {}; (doc.nodes || []).forEach((n) => { nodes[n.id] = n; });
  const adj = new Map(), stateIn = new Map(), hubOf = {};
  (doc.nodes || []).forEach((n) => { if (n.kind === 'state' && n.params && n.params.state && !hubOf[n.params.state]) hubOf[n.params.state] = n.id; });
  (doc.links || []).forEach((l) => {
    const a = nodes[l.from], b = nodes[l.to]; if (!a || !b) return;
    if (a.kind === 'start') return;                                          // Start is display only
    if (a.kind === 'state') {                                                // legacy hub -> trigger: "valid in this state"
      if (b.kind === 'trigger') { if (!stateIn.has(l.to)) stateIn.set(l.to, []); if (!stateIn.get(l.to).includes(l.from)) stateIn.get(l.to).push(l.from); }
      return;
    }
    const k = l.from + '|' + l.port; if (!adj.has(k)) adj.set(k, []); adj.get(k).push(l.to);
  });
  const trig = (doc.nodes || []).filter((n) => n.kind === 'trigger').map((n) => n.id);
  let ordered = [...new Set((doc.order || []).filter((i) => nodes[i] && nodes[i].kind === 'trigger'))];
  const seen = new Set(ordered);
  ordered = ordered.concat(trig.filter((i) => !seen.has(i)).sort((a, b) => (nodes[a].y || 0) - (nodes[b].y || 0) || (nodes[a].x || 0) - (nodes[b].x || 0)));
  const paths = (tid) => {
    const out = [];
    const rec = (nid, chain) => {
      if (chain.some((c) => c[0] === nid)) return;
      const n = nodes[nid]; if (!n) return;
      // terminals: a legacy hub / go-to, or End; an action whose output is unlinked ends the chain (implicit end)
      if (n.kind === 'goto' || n.kind === 'end' || n.kind === 'state') { out.push(chain.concat([[nid, false]])); return; }
      if (n.kind === 'condition') {
        [['true', false], ['false', true]].forEach(([port, inv]) => (adj.get(nid + '|' + port) || []).forEach((t) => rec(t, chain.concat([[nid, inv]]))));
        return;
      }
      const next = adj.get(nid + '|out') || [];
      if (!next.length && n.kind === 'action') { out.push(chain.concat([[nid, false], [null, false]])); return; }
      next.forEach((t) => rec(t, chain.concat([[nid, false]])));
    };
    rec(tid, []);
    return out;
  };
  const keys = new Map(), byTrigger = new Map(), counts = {};
  let gcount = 0;
  const next = (st) => { counts[st] = counts[st] || 0; return st + '/t' + counts[st]++; };
  ordered.forEach((tid) => {
    let p = nodes[tid].params || {};
    const mine = [];
    byTrigger.set(tid, mine);
    // Vars L2: "etat becomes X" (var_changed on etat) is the on_enter of X
    if (p.type === 'event' && p.event === 'var_changed' && p.name === 'etat') {
      if (p.value == null || p.value === '') return;
      p = Object.assign({}, p, { type: 'enter', state: p.value });
    }
    // states the trigger is linked from (legacy hubs) + the legacy `params.state`: the chain's scope
    const linked = (stateIn.get(tid) || []).map((s) => nodes[s].params && nodes[s].params.state).filter(Boolean);
    const scope = [...new Set(linked.concat((p.type === 'event' || p.type === 'after') && p.state ? [p.state] : []))];
    paths(tid).forEach((path) => {
      const ids = path.map((x) => x[0]).filter((x) => x != null);
      const hubs = (sts) => sts.map((s) => hubOf[s]).filter(Boolean);        // legacy source hubs light up with the chain
      const mid = path.slice(1, -1);
      if (p.type === 'enter') {
        if (mid.some(([nid]) => nid && nodes[nid].kind === 'condition')) return;   // refused by the compiler
        const k = p.state + '/enter'; if (!keys.has(k)) { keys.set(k, ids.concat(hubs([p.state]))); mine.push(k); } return;
      }
      const pos = [], neg = []; let force = false, dupOk = true;
      if ((p.type === 'event' || p.type === 'after') && scope.length) { pos.push(scope.slice()); force = !!p.global || scope.length > 1; dupOk = false; }
      mid.forEach(([nid, inv]) => {
        const n = nid && nodes[nid]; if (!n || n.kind !== 'condition') return;
        const q = n.params || {}, a = q.args || {};
        let isNeg = !!q.negate !== inv;
        if (q.type === 'state') { dupOk = false; (isNeg ? neg : pos).push(q.states || []); force = force || (!isNeg && !!q.global); return; }
        if (q.type === 'guard' && q.guard === 'var_compare' && a.name === 'etat') {
          const sts = ['in', 'not_in'].includes(a.op) ? [...new Set(Array.isArray(a.value) ? a.value : [a.value])] : [a.value];
          isNeg = isNeg !== ['!=', 'not_in'].includes(a.op);
          (isNeg ? neg : pos).push(sts); force = force || (!isNeg && !!q.global);
        }
      });
      let single = pos.length === 1 && pos[0].length === 1 && !neg.length && !force, places = null;
      let src = pos.length ? pos[0] : [];
      if (!single && dupOk && pos.length && !neg.length && !force) {
        places = pos[0].filter((s) => pos.slice(1).every((o) => o.includes(s)));
        if (!places.length) return;
        if (places.length === 1) { single = true; src = places; places = null; }
      }
      let ks;
      if (single) ks = [next(src[0])];
      else if (places) ks = places.map(next);          // one transition per state (duplicated chain, same fan)
      else {
        if (p.type === 'after') return;
        if (pos.length && !pos[0].filter((s) => pos.slice(1).every((o) => o.includes(s))).length) return;
        ks = ['global/t' + gcount++];
      }
      ks.forEach((key) => { keys.set(key, ids.concat(hubs(src.filter((s) => linked.includes(s))))); mine.push(key); });
    });
  });
  return { keys, byTrigger };
}
// shared state: S.liveChains (core/state.js)   // chains of the document the robot runs (last loaded / saved)

// Nodes belonging to a disabled chain (reachable from a disabled trigger and from no enabled one).
export function disabledNodes() {
  const data = dfData(), reach = (start) => {
    const seen = new Set(), st = [start];
    while (st.length) {
      const d = st.pop(); if (seen.has(d)) continue; seen.add(d);
      if (d !== start && data[d].data.model.kind === 'state') continue;   // a hub ends the chain: its outputs start OTHER chains
      for (const key in data[d].outputs) data[d].outputs[key].connections.forEach((c) => st.push(String(c.node)));
    }
    return seen;
  };
  const off = new Set(), on = new Set();
  for (const dfid in data) {
    const m = data[dfid].data.model;
    if (m.kind !== 'trigger') continue;
    reach(dfid).forEach((d) => ((m.params || {}).enabled === false ? off : on).add(d));
  }
  const out = new Set();
  off.forEach((d) => { if (!on.has(d) && data[d] && data[d].data.model.kind !== 'state') out.add(data[d].data.model.id); });
  return out;
}
// Highlight state: nodes lit by the simulator ("now" = current step, "past" = already fired) as model ids.
export const lit = { now: new Set(), past: new Set() };
export function paintChains() {
  if (!S.editor) return;
  const data = dfData(), off = disabledNodes();
  for (const dfid in data) {
    const el = nodeEl(dfid); if (!el) continue;
    const id = data[dfid].data.model.id;
    el.classList.toggle('disabled', off.has(id));
    el.classList.toggle('lit-now', lit.now.has(id));
    el.classList.toggle('lit-past', lit.past.has(id) && !lit.now.has(id));
  }
  // L7: while a simulation / journal entry is displayed, its wires glow too (now = cyan, past = blue) and
  // everything else is dimmed (container class `simdim`); cleared with the lights (Réinitialiser).
  const on = lit.now.size > 0 || lit.past.size > 0;
  if (!S.editor.container) return;
  S.editor.container.classList.toggle('simdim', on);
  S.editor.container.querySelectorAll('svg.connection').forEach((svg) => {
    const cl = svg.classList, a = data[cl[2] ? cl[2].slice(14) : ''], b = data[cl[1] ? cl[1].slice(13) : ''];
    const ia = a && a.data.model.id, ib = b && b.data.model.id;
    const now = on && lit.now.has(ia) && lit.now.has(ib);
    cl.toggle('wlit-now', now);
    cl.toggle('wlit-past', on && !now && (lit.past.has(ia) || lit.now.has(ia)) && (lit.past.has(ib) || lit.now.has(ib)));
  });
}
export function blinkChain(key) {
  const ids = S.liveChains.keys.get(key); if (!ids) return;
  if (S.curTab === 'journal') focusChainIds(ids);    // L7 fix round: the journal follows the live chain
  ids.forEach((nid) => {
    const el = nodeEl(nidToDf.get(nid)); if (!el) return;
    el.classList.remove('blink'); void el.offsetWidth; el.classList.add('blink');
    setTimeout(() => el.classList.remove('blink'), 2000);
  });
}
// Pan (keeping the zoom, at least 0.35) so that a node is in the middle of the canvas.
export function panTo(nid, minZoom) {
  const dfid = nidToDf.get(nid); if (dfid == null) return;
  const d = dfNode(dfid), st = $('#drawflow'), z = Math.max(S.editor.zoom, minZoom || 0.35);
  setView(z, st.clientWidth / 2 - (d.pos_x + 107) * z, st.clientHeight / 2 - (d.pos_y + 40) * z);
}
