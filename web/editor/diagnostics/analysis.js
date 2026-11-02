/**
 * Diagnostics: structural client hints (not the validator).
 *
 * Purpose :  analyze(): per node issues (issues map), global issues, type mismatch hints; the server stays the only judge
 *            of validity.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/state.js, variables/model.js, inspector/property-picker.js, core/api.js, core/chains.js,
 *            diagnostics/check.js, canvas/view.js, canvas/wires.js, minimap/overview.js, inspector/arg-fields.js,
 *            variables/panel.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { S, INTENT_NAME, NO_TRIGGER_INPUT, byId, evs, freshIds, nidToDf } from '../core/state.js';
import { varDef } from '../variables/model.js';
import { argIssues, compareIssues, dictValueIssues, srcArgIssues } from '../inspector/property-picker.js';
import { dfData, model } from '../core/api.js';
import { disabledNodes, paintChains } from '../core/chains.js';
import { markNode, paintDiagWires, paintOrderBadges, renderMsgs, scheduleCheck } from './check.js';
import { drawBands } from '../canvas/view.js';
import { paintWires } from '../canvas/wires.js';
import { scheduleMinimap } from '../minimap/overview.js';
import { REQUIRED_ARGS } from '../inspector/arg-fields.js';
import { varsUi } from '../variables/panel.js';

// ---------- analysis (structural hints, not the validator) ----------
export function analyze() {
  const data = dfData();
  const out = new Map();
  // A node the user just dropped from the palette gets mild "todo" hints (no coloured outline) until the
  // first validate / save, instead of errors for the fields it has not had time to receive yet.
  const add = (nid, level, message) => {
    if (freshIds.has(nid)) { if (level === 'warn' || level === 'info') return; level = 'todo'; }   // structural warnings wait until validate
    if (!out.has(nid)) out.set(nid, []);
    if (out.get(nid).some((i) => i.message === message)) return;     // same message from the client and the server
    out.get(nid).push({ level, message });
  };
  const incoming = {}, outgoing = {};
  for (const dfid in data) { incoming[dfid] = 0; outgoing[dfid] = 0; }
  for (const dfid in data) {
    for (const key in data[dfid].outputs) for (const c of data[dfid].outputs[key].connections) {
      outgoing[dfid]++; incoming[c.node] = (incoming[c.node] || 0) + 1;
    }
  }
  const stateIds = new Set(S.V.states.map((s) => s.id));
  for (const dfid in data) {
    const m = data[dfid].data.model, p = m.params || {}, id = m.id;
    if (m.kind === 'trigger') {
      if (p.type === 'event' && !byId(evs(), p.event)) add(id, 'err', String(p.event || '').startsWith('intent.')
        ? `Intention inconnue : « ${p.event.slice(7)} » (à créer dans le panneau Intentions).` : 'Événement inconnu ou manquant.');
      if (p.type === 'event' && p.event === 'var_changed') {
        if (!p.name) add(id, 'err', '« Une variable change » : choisir la variable.');
        else if (!varDef(p.name)) add(id, 'err', `Variable inconnue : « ${p.name} ».`);
        else if (p.name === 'etat' && (p.value == null || p.value === '')) add(id, 'err', "« Quand etat change » : choisir l'état (la valeur) qui déclenche la chaîne.");
      }
      if (data[dfid].inputs && (data[dfid].inputs.input_1 || { connections: [] }).connections.length) add(id, 'err', NO_TRIGGER_INPUT);
      if (p.type === 'after' && (p.delay === '' || p.delay == null)) add(id, 'err', 'Délai manquant.');
      if (p.type === 'enter' && !stateIds.has(p.state)) add(id, 'err', 'État inconnu.');
      if (!['event', 'after', 'enter'].includes(p.type)) add(id, 'err', 'Type de déclencheur inconnu.');
      if (!outgoing[dfid]) add(id, 'warn', "Ce déclencheur n'a pas de chaîne.");
    } else if (m.kind === 'condition') {
      if (p.type === 'state' && !(p.states || []).length) add(id, 'err', 'Aucun état choisi.');
      if (p.type === 'guard' && !byId(S.V.guards, p.guard)) add(id, 'err', 'Garde inconnue ou manquante.');
      else if (p.type === 'guard') {
        argIssues(byId(S.V.guards, p.guard), p.args || {}).forEach((msg) => add(id, 'err', msg));
        srcArgIssues(byId(S.V.guards, p.guard), p.args || {}).forEach((msg) => add(id, 'err', msg));   // lot M5
        if (['var_compare', 'date_compare'].includes(p.guard)) compareIssues(p.args || {}).forEach((msg) => add(id, 'err', msg));
        dictValueIssues(p.args || {}).forEach((msg) => add(id, 'err', msg));
      }
    } else if (m.kind === 'action') {
      if (!byId(S.V.actions, p.action)) add(id, 'err', 'Action inconnue ou manquante.');
      else {
        argIssues(byId(S.V.actions, p.action), p.args || {}).forEach((msg) => add(id, 'err', msg));
        srcArgIssues(byId(S.V.actions, p.action), p.args || {}).forEach((msg) => add(id, 'err', msg));   // lot M5
        // L12: a constant of the wrong type for the variable / dict (bounds are the server's out_of_bounds warning)
        if (p.action === 'set_var' && (p.args || {}).name !== 'etat') compareIssues(Object.assign({}, p.args, { op: '=' })).forEach((msg) => add(id, 'err', msg));
        dictValueIssues(p.args || {}).forEach((msg) => add(id, 'err', msg));
        const need = REQUIRED_ARGS[p.action] || [];
        need.forEach((k) => { const v = (p.args || {})[k]; if (v == null || v === '') add(id, 'err', 'À remplir : ' + ((((byId(S.V.actions, p.action) || {}).args || []).find((x) => x.name === k)) || {}).label + '.'); });
      }
    } else if (m.kind === 'goto') {
      if (!stateIds.has(p.state)) add(id, 'err', "État d'arrivée inconnu.");
    } else if (m.kind === 'state') {
      add(id, 'warn', "Ancien nœud État : il n'est plus utilisé (supprimez-le ; l'état se teste avec « etat = … » et se change avec l'action « Changer d'état »).");
    }
    if (!['start', 'trigger', 'state'].includes(m.kind) && !incoming[dfid]) add(id, 'warn', "Nœud non relié : il serait perdu à l'enregistrement.");
    if (m.kind === 'condition') {
      // Vars L2: an action with an unlinked output ends its chain; a condition needs at least one linked output
      const o1 = data[dfid].outputs.output_1, o2 = data[dfid].outputs.output_2;
      if (!(o1 && o1.connections.length) && !(o2 && o2.connections.length)) add(id, 'warn', 'La condition n’a aucune suite : relier au moins une de ses sorties.');
      else if (!(o1 && o1.connections.length)) add(id, 'info', 'Sortie Vrai libre : quand la condition est vraie, la chaîne s’arrête ici (seule la branche Faux agit).');
    }
    if (m.kind === 'action' && p.action === 'set_var' && (p.args || {}).name === 'etat' && p.args.value && !stateIds.has(p.args.value)) add(id, 'err', 'État de destination inconnu.');
    if (m.kind === 'condition') {
      for (const c of (data[dfid].inputs.input_1 || { connections: [] }).connections) {
        const src = data[c.node];
        if (src && src.data.model.kind === 'action') add(id, 'err', 'Une condition ne peut pas suivre une action.');
      }
    }
  }
  // lot L5: reachability from the triggers (unreachable node, chain without action, only disabled triggers upstream)
  const reachFrom = (start) => {
    const seen = new Set(), st = [start];
    while (st.length) {
      const d = st.pop(); if (seen.has(d) || !data[d]) continue; seen.add(d);
      if (d !== start && data[d].data.model.kind === 'state') continue;
      for (const key in data[d].outputs) data[d].outputs[key].connections.forEach((c) => st.push(String(c.node)));
    }
    return seen;
  };
  const reached = new Set();
  for (const dfid in data) {
    const m = data[dfid].data.model;
    if (m.kind !== 'trigger') continue;
    const r = reachFrom(dfid);
    r.forEach((d) => reached.add(d));
    if (outgoing[dfid] && ![...r].some((d) => data[d].data.model.kind === 'action')) add(m.id, 'warn', 'Cette chaîne ne contient aucune action : elle ne fait rien.');
  }
  for (const dfid in data) {
    const m = data[dfid].data.model;
    if (!['trigger', 'start', 'state'].includes(m.kind) && incoming[dfid] && !reached.has(dfid)) add(m.id, 'warn', 'Aucun déclencheur en amont : ce nœud ne s’exécute jamais.');
  }
  disabledNodes().forEach((nid) => {
    const df = nidToDf.get(nid), m = df != null ? model(df) : null;
    if (m && m.kind !== 'trigger') add(nid, 'info', 'Chaîne désactivée en amont : ce nœud ne s’exécute pas tant qu’elle reste désactivée.');
  });
  S.globalIssues = [];
  Object.keys(S.meta.intents || {}).forEach((n) => {
    const it = S.meta.intents[n] || {};
    if (!INTENT_NAME.test(n)) S.globalIssues.push({ level: 'err', message: `Intention « ${n} » : nom invalide.` });
    if (!it.words_from && !it.regex && !(it.words || []).length) S.globalIssues.push({ level: 'warn', message: `Intention « ${n} » : aucun mot (ajoutez au moins un mot ou une expression).` });
  });
  S.intentErrs = {};
  const seenG = new Set();
  S.serverErrors.concat(S.simErrors, S.checkErrors).forEach((e) => {
    const gkey = (e.intent || e.variable || '') + '|' + e.message;
    if (e.intent) { S.intentErrs[e.intent] = e.message; if (!seenG.has(gkey)) S.globalIssues.push({ level: 'err', message: `Intention « ${e.intent} » : ${e.message}` }); }
    else if (e.variable && !(e.node && nidToDf.has(e.node))) { if (!seenG.has(gkey)) S.globalIssues.push({ level: 'err', message: `Variable « ${e.variable} » : ${e.message}` }); }
    else if ((e.at && nidToDf.has(e.at)) || (e.node && nidToDf.has(e.node))) {
      // lot L5: the faulty node itself (`at`) AND the trigger of its chain (`node`, the contract location)
      [e.at, e.node].forEach((x) => { if (x && nidToDf.has(x)) add(x, 'err', e.message); });
    }
    else if (!e.note && !seenG.has(gkey)) S.globalIssues.push({ level: 'err', message: e.message });
    else if (e.note && !seenG.has(gkey)) S.globalIssues.push({ level: 'err', message: 'Post-it : ' + e.message });
    seenG.add(gkey);
  });
  // L12: persisted values the robot refused at load (type changed / invalid): GET /api/graph/vars `store.ignored`
  ((((varsUi.live || {}).store) || {}).ignored || []).forEach((g) => {
    S.globalIssues.push({ level: 'warn', message: `Valeur enregistrée ignorée (${g.part === 'lists' ? 'liste' : 'variable'} « ${g.name} ») : ${g.reason}. Réinitialisez-la dans le panneau Variables.` });
  });
  (S.fanInfo.warnings || []).forEach((w) => {
    // L12: a constant outside the variable's min / max; L27: say_random / say_list_item on a list that is empty and
    // never filled (`empty_list`): both on the faulty node (`at`), else its trigger, else the global messages
    if (w.kind === 'out_of_bounds' || w.kind === 'empty_list') {
      const at = [w.at, w.node].find((x) => x && nidToDf.has(x));
      if (at) add(at, 'warn', w.message); else S.globalIssues.push({ level: 'warn', message: w.message });
      return;
    }
    (new Set([w.node].concat(w.nodes || []))).forEach((id) => {
      if (nidToDf.has(id)) add(id, 'warn', id === w.node ? w.message : "Cette destination est en concurrence avec une autre branche du même déclencheur : une seule changera l'état.");
    });
  });
  S.issues = out;
  for (const dfid in data) markNode(dfid);
  paintDiagWires();
  paintOrderBadges();
  scheduleCheck();
  paintChains();
  drawBands();
  paintWires();
  renderMsgs();
  scheduleMinimap();       // L6: minimap diagnostic dots follow the badges
}
