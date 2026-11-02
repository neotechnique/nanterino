/**
 * Inspector: the right-hand Inspecteur tab.
 *
 * Purpose :  renderInspector(): node, wire, group, column, post-it or chain inspector.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, inspector/property-picker.js, core/api.js, canvas/nodes.js,
 *            diagnostics/check.js, frames/groups.js, frames/nesting.js, frames/notes.js, hierarchy/tree.js,
 *            inspector/fields.js, inspector/arg-fields.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, h, ico } from '../core/util.js';
import { S, KINDS, byId, evs, iconOf, stateIcon, stateLabel } from '../core/state.js';
import { asVars } from './property-picker.js';
import { dfNode, model } from '../core/api.js';
import { stateDesc } from '../canvas/nodes.js';
import { ISSUE_PREFIX } from '../diagnostics/check.js';
import { frameById } from '../frames/groups.js';
import { renderFrameInspector } from '../frames/nesting.js';
import { noteById, renderNoteInspector } from '../frames/notes.js';
import { renderChainInspector, syncTreeSel } from '../hierarchy/tree.js';
import { checkCtl, edit, field, iconSelect, numOrKey, renderWireInspector, selectCtl, textCtl } from './fields.js';
import { REQUIRED_ARGS, argFields } from './arg-fields.js';

export function renderInspector() {
  const box = $('#inspector'); box.innerHTML = '';
  syncTreeSel();                       // L10: every selection change passes here: the hierarchy row follows
  const fr = S.selFrame && frameById(S.selFrame);
  if (fr) { renderFrameInspector(box, fr); return; }
  const nt = S.selNote && noteById(S.selNote);
  if (nt) { renderNoteInspector(box, nt); return; }
  if (S.selChain && S.selDf == null) { renderChainInspector(box); return; }
  if (S.selConn && S.selDf == null && renderWireInspector(box)) return;
  const m = S.selDf != null ? model(S.selDf) : null;
  if (!m) { box.append(h('p', { class: 'hint' }, 'Sélectionnez un élément dans la hiérarchie ou le graphe ; clic droit sur le graphe pour ajouter un nœud.')); return; }
  const p = m.params;
  box.append(h('div', { class: 'insttitle' }, ico(iconOf(m), KINDS[m.kind].color),
    KINDS[m.kind].label, h('small', { class: 'hint' }, m.id + (m.group ? ' · ' + (m.group === 'global' ? 'global' : stateLabel(m.group)) : ''))));
  const helpOf = (list, id) => (byId(list, id) || {}).help || '';
  const stateOpts = S.V.states.map((s) => ({ v: s.id, l: s.label, icon: stateIcon(s.id) }));
  const myIssues = S.issues.get(m.id) || [];      // lot L5: the node's errors / warnings first (badge click lands here)
  if (myIssues.length) box.append(h('div', { class: 'isslist' }, myIssues.map((i) => h('div', { class: 'iss ' + i.level }, (ISSUE_PREFIX[i.level] || '') + i.message))));

  if (m.kind === 'start') {
    box.append(field('État de départ (fixé par le code)', h('input', { type: 'text', disabled: true, value: stateLabel(p.state) })));
  }
  if (m.kind === 'trigger') {
    const types = [{ v: 'event', l: 'Un événement arrive' }, { v: 'after', l: 'Après un délai' }].concat(p.type === 'enter' ? [{ v: 'enter', l: "À l'entrée dans un état (ancien)" }] : []);
    box.append(field('Type', selectCtl(types, p.type, (v) => edit((mm) => {
      const wasOff = mm.params.enabled === false;
      mm.params = { type: v };
      if (v === 'event') mm.params.event = (S.V.events[0] || {}).id;
      if (v === 'after') { mm.params.delay = (S.V.delays[0] || {}).key || 5; mm.params.since = 'state'; }
      if (wasOff) mm.params.enabled = false;
    }, true))));
    const isEnter = p.type === 'enter' || (p.type === 'event' && p.event === 'var_changed' && p.name === 'etat');
    if (p.type === 'event') box.append(field('Événement', iconSelect(evs().map((e) => ({ v: e.id, l: e.label, icon: e.icon })), p.event, (v) => edit((mm) => {
      mm.params.event = v; delete mm.params.name; delete mm.params.value;
    }, true)), helpOf(evs(), p.event)));
    if (p.type === 'event' && p.event === 'var_changed') {
      // the trigger's own params carry name / value (not `args`): same typed controls
      argFields(box, (byId(S.V.events, 'var_changed') || {}).args || [], p, (k, v) => edit((mm) => {
        if (v === '' || v == null) delete mm.params[k]; else mm.params[k] = v;
        if (k === 'name') delete mm.params.value;
      }, true), { id: 'var_changed' });
      if (p.name === 'etat') box.append(h('p', { class: 'hint' }, "« Quand etat devient X » = entrée dans l'état X : seulement des actions, ni condition ni changement d'état ; jamais désactivée."));
    } else if (p.type === 'event' && ((byId(S.V.events, p.event) || {}).args || []).length) {
      // L12: any other event with vocabulary args (timer_reached: name = chrono, value = seconds) keeps them in params
      argFields(box, byId(S.V.events, p.event).args, p, (k, v) => edit((mm) => {
        if (v === '' || v == null) delete mm.params[k]; else mm.params[k] = v;
      }, true), { id: p.event });
    }
    if (!isEnter) {
      box.append(h('p', { class: 'hint' }, "Un déclencheur n'a pas d'entrée. Pour le limiter à un état, ajoutez juste après lui une condition « etat = … » (clic droit → Insérer après → Comparer une variable)."));
      box.append(h('p', { class: 'hint fannote' }, "Plusieurs branches : toutes celles qui ne changent pas d'état s'exécutent (dans l'ordre des numéros), puis une seule branche change d'état : la première qui correspond."));
      const fb = (S.fanInfo.fans || {})[m.id];
      if (fb && fb.length > 1) box.append(h('p', { class: 'hint' }, 'Ordre actuel : ' + fb.slice().sort((a, b) => a.rank - b.rank).map((b) => b.rank + ' → ' + b.target + (b.moves ? ' (change l\'état)' : '') + (b.ignored ? ' [ignorée]' : '')).join(' ; ')));
      box.append(checkCtl('Chaîne activée', p.enabled !== false, (c) => edit((mm) => { mm.params.enabled = c; }, true), 'power'));
      if (p.enabled === false) box.append(h('p', { class: 'hint' }, "Désactivée : la chaîne reste dans le fichier mais le robot l'ignore (grisée sur le canvas)."));
    }
    if (p.type === 'after') {
      box.append(field('Délai (secondes, ou clé de réglage)', textCtl(p.delay, (v) => edit((mm) => { mm.params.delay = numOrKey(v); }, true), 'text', 'dl-delays'),
        'Clés : ' + S.V.delays.map((d) => `${d.key} = ${d.value} s`).join(' ; ')));
      box.append(h('datalist', { id: 'dl-delays' }, S.V.delays.map((d) => h('option', { value: d.key }))));
      box.append(field('Compté', selectCtl(S.V.since.map((s) => ({ v: s.id, l: s.label })), p.since || 'state', (v) => edit((mm) => { mm.params.since = v; }))));
      box.append(h('p', { class: 'hint' }, 'Un délai doit être rattaché à un état : condition « etat = … » (ou « etat parmi … ») juste après.'));
    }
    if (p.type === 'enter') box.append(field('État', iconSelect(stateOpts, p.state, (v) => edit((mm) => { mm.params.state = v; }, true)), 'Ancienne forme : préférez « Une variable change » sur etat.'));
  }
  if (m.kind === 'condition') {
    const types = [{ v: 'guard', l: 'Une condition (garde ou variable)' }].concat(p.type === 'state' ? [{ v: 'state', l: "L'état courant (ancien)" }] : []);
    box.append(field('Type', selectCtl(types, p.type, (v) => edit((mm) => {
      mm.params = { type: v, negate: !!mm.params.negate };
      if (v === 'guard') mm.params.guard = (S.V.guards[0] || {}).id; else mm.params.states = [];
    }, true))));
    if (p.type === 'guard') {
      box.append(field('Condition', iconSelect(S.V.guards.map((g) => ({ v: g.id, l: g.label + (g.as_vars ? ' (' + g.as_vars + ')' : ''), icon: g.icon })), p.guard, (v) => edit((mm) => {
        mm.params.guard = v; delete mm.params.global;
        const g = byId(S.V.guards, v);
        if (g && (g.args || []).length) { mm.params.args = {}; if (v === 'var_compare') mm.params.args.op = '='; } else delete mm.params.args;
      }, true)), helpOf(S.V.guards, p.guard)));
      if (asVars(p.guard)) box.append(h('p', { class: 'hint' }, ico('text-caption'), ' En variables : ', h('code', {}, asVars(p.guard))));
      const g = byId(S.V.guards, p.guard);
      if (g && (g.args || []).length) argFields(box, g.args, p.args || {}, (k, v) => edit((mm) => {
        mm.params.args = mm.params.args || {};
        if (v === '' || v == null) delete mm.params.args[k]; else mm.params.args[k] = v;
        if (k === 'name' || k === 'list') { delete mm.params.args.value; if (k === 'name' && mm.params.guard === 'var_compare') mm.params.args.op = '='; delete mm.params.global; }
        if (k === 'op' && (['in', 'not_in'].includes(v) !== Array.isArray(mm.params.args.value))) delete mm.params.args.value;
      }, true), { id: p.guard });
      const a = p.args || {};
      if (p.guard === 'var_compare' && a.name === 'etat' && ['=', 'in'].includes(a.op || '=')) {
        box.append(checkCtl('Règle globale (évaluée avec les règles globales, limitée à ces états)', p.global, (c) => edit((mm) => { if (c) mm.params.global = true; else delete mm.params.global; })));
      }
      if (p.guard === 'var_compare' && a.name === 'etat') box.append(h('p', { class: 'hint' }, "La condition sur etat range la chaîne dans la colonne de l'état (plusieurs états : une copie par état). Sans condition sur etat, la règle est globale."));
    }
    if (p.type === 'state') {
      const wrap = h('div', { class: 'fld' }, h('span', {}, 'États'));
      S.V.states.forEach((s) => wrap.append(checkCtl(s.label, (p.states || []).includes(s.id), (c) => edit((mm) => {
        const set = new Set(mm.params.states || []); c ? set.add(s.id) : set.delete(s.id); mm.params.states = [...set];
      }), stateIcon(s.id))));
      box.append(wrap);
      box.append(checkCtl('Règle globale (limitée à ces états)', p.global, (c) => edit((mm) => { if (c) mm.params.global = true; else delete mm.params.global; })));
    }
    box.append(checkCtl('Inverser (non)', p.negate, (c) => edit((mm) => { mm.params.negate = c; })));
    box.append(h('p', { class: 'hint' }, 'Sorties : « Vrai » continue la chaîne ; « Faux » démarre la branche suivante.'));
  }
  if (m.kind === 'action') {
    box.append(field('Action', iconSelect(S.V.actions.map((a) => ({ v: a.id, l: a.label, icon: a.icon })), p.action, (v) => edit((mm) => { mm.params.action = v; mm.params.args = {}; delete mm.params.reason; }, true)), helpOf(S.V.actions, p.action)));
    const a = byId(S.V.actions, p.action);
    argFields(box, (a && a.args) || [], p.args || {}, (k, v) => edit((mm) => {
      mm.params.args = mm.params.args || {};
      if (v === '' || v == null) delete mm.params.args[k]; else mm.params.args[k] = v;
      if (k === 'name' || k === 'list') delete mm.params.args.value;
      if (!(mm.params.action === 'set_var' && mm.params.args.name === 'etat')) delete mm.params.reason;
    }, true), { id: p.action, required: REQUIRED_ARGS[p.action] || [] });
    const move = p.action === 'set_var' && (p.args || {}).name === 'etat';
    if (move) {
      box.append(field('Raison (journal)', textCtl(p.reason || '', (v) => edit((mm) => { v = v.trim().slice(0, 100); if (v) mm.params.reason = v; else delete mm.params.reason; }, true)),
        'Texte libre affiché dans le journal quand cette chaîne change l’état ; par défaut, l’événement déclencheur.'));
      box.append(h('p', { class: 'hint' }, "Changer d'état : les actions avant ce nœud s'exécutent avant le changement, celles après lui juste après (dans le nouvel état). Un seul changement d'état par chaîne."));
    } else {
      box.append(field('Quand', selectCtl([{ v: 'do', l: "Avant le changement d'état" }, { v: 'then', l: "Après le changement d'état" }], p.phase || 'do', (v) => edit((mm) => { mm.params.phase = v; })),
        "Utile seulement sans action « Changer d'état » dans la chaîne (sinon la position décide : avant / après elle)."));
    }
  }
  if (m.kind === 'state') {
    const nIn = ((dfNode(S.selDf).inputs.input_1 || {}).connections || []).length, nOut = ((dfNode(S.selDf).outputs.output_1 || {}).connections || []).length;
    box.append(field('État', h('input', { type: 'text', disabled: true, value: stateLabel(p.state) }), stateDesc(p.state)));
    box.append(h('p', { class: 'hint' }, `Il y a un seul nœud par état. Entrée : ${nIn} chaîne(s) qui y arrivent. Sortie : ${nOut} déclencheur(s) valables dans cet état.`));
    box.append(h('p', { class: 'hint' }, "Pour changer l'état du robot, reliez le dernier nœud d'une chaîne à l'entrée (à gauche) de ce nœud. Cliquez sur le fil pour noter la raison qui apparaît dans le journal."));
  }
  if (m.kind === 'goto') {
    box.append(field("État d'arrivée", iconSelect(stateOpts, p.state, (v) => edit((mm) => { mm.params.state = v; }, true)), (byId(S.V.states, p.state) || {}).description || ''));
    box.append(field('Raison (journal)', textCtl(p.reason, (v) => edit((mm) => { if (v) mm.params.reason = v; else delete mm.params.reason; }))));
  }
  if (m.kind === 'end') box.append(h('p', { class: 'hint' }, "Fin de chaîne : aucun changement d'état."));

  const ta = h('textarea', {}); ta.value = m.description || '';
  ta.addEventListener('change', () => edit((mm) => { mm.description = ta.value; }));
  if (m.kind !== 'state') box.append(field('Description', ta));
  box.append(h('button', { class: 'danger', onclick: () => { S.editor.removeNodeId('node-' + S.selDf); } }, 'Supprimer ce nœud'));
}
