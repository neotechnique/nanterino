/**
 * Editor core: debug scenarios (#debug=...).
 *
 * Purpose :  sleep() and runDebug(): the in-page screenshot / round-trip scenarios started by boot() when the URL hash
 *            asks for them (harmless in normal use).
 * Boundary:  runs only with a #debug=... hash; network: GET /api/graph, /api/graph/visual, POST /api/graph/visual +
 *            /api/graph/reset (round-trip check). Moved unchanged out of the former single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, core/api.js, core/serialize.js, frames/nesting.js, hierarchy/tree.js,
 *            panels/intents.js, core/actions.js, panels/live.js, tester/tester.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { clone, dbg, errLog } from './util.js';
import { S, byId, evs } from './state.js';
import { api, dfData, model, postJson } from './api.js';
import { serialize } from './serialize.js';
import { fit, focusBand, focusNode } from '../frames/nesting.js';
import { scheduleTree } from '../hierarchy/tree.js';
import { renderIntents } from '../panels/intents.js';
import { postDoc } from './actions.js';
import { activateTab } from '../panels/live.js';
import { sim, simRun } from '../tester/tester.js';

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function runDebug() {
  const mode = (location.hash.match(/debug=(\w+)/) || [])[1];
  if (!mode) return;
  await new Promise((r) => setTimeout(r, 800));
  if (mode === 'band') { focusBand('veille'); dbg('band'); }
  else if (mode === 'icons') { focusBand('ecoute', 0.7); dbg('icons errors=' + errLog.length); }
  else if (mode === 'tester') {
    // "visage -> dit au revoir": visage in veille, let the greeting end, then the visitor says goodbye.
    activateTab('tester');
    await sleep(300);
    sim.steps = [{ event: 'visage' }, { wait_s: 4 }, { say: 'au revoir' }];
    await simRun(false);
    await sleep(300);
    const r = sim.final;
    dbg('sim final=' + JSON.stringify(r) + ' trace=' + sim.trace.map((e) => e.chain).join(','));
  } else if (mode === 'versions') { activateTab('versions'); }
  else if (mode === 'journal') { activateTab('journal'); await sleep(500); }
  else if (mode === 'intents') {
    activateTab('intents');
    S.meta.intents = S.meta.intents || {};
    S.meta.intents.au_secours = { words: ['au secours', 'aidez-moi'], only_in: ['ecoute', 'relance'], description: 'Le visiteur appelle à l’aide.' };
    renderIntents(); scheduleTree();
    document.querySelector('#intents').scrollTop = 99999;
    dbg('intent trigger offered: ' + !!byId(evs(), 'intent.au_secours'));
  }
  else if (mode === 'fit') { fit(); }
  else if (mode === 'select') {
    const first = Object.keys(dfData()).find((i) => model(i).kind === 'action');
    focusNode(model(first).id);
    dbg('select done; errors=' + errLog.length);
  } else if (mode === 'error') {
    const doc = serialize();
    const g = doc.nodes.find((n) => n.kind === 'action' && n.params.action === 'set_var' && (n.params.args || {}).name === 'etat');
    g.params.args.value = 'etat_inexistant';
    const r = await postDoc(doc);       // 400 expected: nothing written
    focusNode(g.id);
    dbg('POST status=' + r.status + ' errors=' + JSON.stringify(r.json));
  } else if (mode === 'roundtrip') {
    const before = (await api('/api/graph')).json;
    const vis = (await api('/api/graph/visual')).json;
    const doc = serialize();
    const norm = (d) => JSON.stringify({ n: d.nodes.length, l: d.links.length,
      nodes: d.nodes.map((n) => [n.id, n.kind, JSON.stringify(n.params), n.group || '', n.description || '']).sort(),
      links: d.links.map((l) => l.from + l.port + l.to).sort() });
    dbg('visual==serialized (ids,kind,params,group,links): ' + (norm(vis) === norm(doc)) + ' nodes=' + doc.nodes.length + ' links=' + doc.links.length);
    const r = await postJson('/api/graph/visual', doc);
    dbg('POST status=' + r.status + ' ' + JSON.stringify(r.json));
    const after = (await api('/api/graph')).json;
    const strip = (g) => { const c = clone(g); delete c.source; return JSON.stringify(c); };
    dbg('GET /api/graph identical except source: ' + (strip(before) === strip(after)) + ' (source ' + before.source + ' -> ' + after.source + ')');
    const rs = await postJson('/api/graph/reset', {});
    dbg('reset status=' + rs.status + ' ' + JSON.stringify(rs.json));
    const fin = (await api('/api/graph')).json;
    dbg('after reset identical except source: ' + (strip(before) === strip(fin)) + ' source=' + fin.source);
    dbg('console errors: ' + errLog.length);
  }
}
