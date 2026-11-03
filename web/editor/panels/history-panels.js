/**
 * Panels: Versions and Journal.
 *
 * Purpose :  GET /api/graph/versions + restore; GET /api/graph/trace then live last_transition entries.
 * Boundary:  network through core/api.js: GET /api/graph/versions, POST /api/graph/versions/<id>/restore, GET
 *            /api/graph/trace. Moved unchanged out of the former single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, core/api.js, core/chains.js, frames/nesting.js, core/ui.js, core/actions.js,
 *            panels/live.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, h, ico } from '../core/util.js';
import { S, byId, evs, stateLabel } from '../core/state.js';
import { api, postJson } from '../core/api.js';
import { blinkChain } from '../core/chains.js';
import { focusNode } from '../frames/nesting.js';
import { modal, toast } from '../core/ui.js';
import { loadAll } from '../core/actions.js';
import { fmtTime, reasonLabel } from './live.js';

// ---------- Versions (GET /api/graph/versions, POST .../restore) ----------
export async function loadVersions() {
  const box = $('#versions'); if (!box) return;
  box.innerHTML = ''; box.append(h('p', { class: 'hint' }, 'Chargement…'));
  const r = await api('/api/graph/versions');
  box.innerHTML = '';
  if (!r.ok || !r.json) { box.append(h('p', { class: 'hint' }, 'Liste indisponible (' + r.status + ').')); return; }
  box.append(h('p', { class: 'hint' }, `Une copie datée est gardée à chaque enregistrement (les ${r.json.max || 30} dernières).`));
  if (!r.json.versions.length) box.append(h('p', { class: 'hint' }, "Aucune sauvegarde pour l'instant."));
  r.json.versions.forEach((v) => {
    const s = v.summary || {};
    const sum = s.error ? 'Illisible : ' + s.error : `${s.states} états · ${s.chains} chaînes` + (s.disabled ? ` · ${s.disabled} désactivée(s)` : '');
    const when = new Date(v.date).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'medium' });
    box.append(h('div', { class: 'row' }, ico('clock'),
      h('div', { class: 'grow' }, h('div', {}, when), h('div', { class: 'sub' }, sum + ' · ' + Math.round((v.size || 0) / 1024 * 10) / 10 + ' Ko')),
      h('button', { type: 'button', disabled: !!s.error, onclick: () => confirmRestore(v, when) }, 'Restaurer')));
  });
}
function confirmRestore(v, when) {
  modal('Restaurer cette version ?',
    h('div', {}, h('p', {}, 'Version du ' + when + '.'),
      h('p', {}, "Le graphe actuel est sauvegardé d'abord : rien n'est perdu. Les modifications non enregistrées dans l'éditeur sont abandonnées.")),
    [{ label: 'Annuler' }, { label: 'Restaurer', cls: 'primary', fn: async () => {
      const r = await postJson('/api/graph/versions/' + encodeURIComponent(v.id) + '/restore', {});
      if (r.ok) {
        toast((r.json && r.json.message) || 'Version restaurée.', r.json && r.json.applied ? 'ok' : '');
        await loadAll();
        if (S.curTab === 'versions') loadVersions();
      } else {
        const why = r.json && (r.json.message || (r.json.errors || []).map((e) => e.message).join(' ') || r.json.detail) || '';
        toast('Restauration refusée (' + r.status + ') ' + why, 'err');
      }
    } }]);
}

// ---------- Journal (GET /api/graph/trace at open, then WS / live `last_transition`) ----------
// shared state: S.journal, S.liveSeen, S.seenT (core/state.js)
export async function loadJournal() {
  const r = await api('/api/graph/trace');
  if (r.ok && r.json) S.journal = (r.json.trace || []).slice(-50);
  renderJournal();
}
function focusChain(key) {
  const ids = S.liveChains.keys.get(key);
  if (!ids) { toast("Cette chaîne n'existe pas dans le graphe affiché (" + key + ').', ''); return; }
  focusNode(ids[0]); blinkChain(key);
}
function renderJournal() {
  const box = $('#journal'); if (!box || box.hidden) return;
  box.innerHTML = '';
  box.append(h('p', { class: 'hint' }, 'Les 50 dernières chaînes déclenchées sur le vrai robot, en direct. Cliquer une ligne pour voir sa chaîne.'));
  if (!S.journal.length) box.append(h('p', { class: 'hint' }, "Rien pour l'instant."));
  S.journal.slice().reverse().forEach((e) => {
    const ev = byId(evs(), e.event);
    box.append(h('div', { class: 'trow', onclick: () => focusChain(e.chain) },
      h('div', {}, ico(ev ? ev.icon : 'clock'), ' ', e.moved ? [stateLabel(e.from), h('span', { class: 'arrow' }, ' → '), stateLabel(e.to)] : ['Reste en ', stateLabel(e.to)]),
      h('div', { class: 'meta' }, `${fmtTime(e.t)} · ${ev ? ev.label : e.event || 'délai'}` + (e.reason && reasonLabel(e.reason) !== (ev && ev.label) ? ' · ' + reasonLabel(e.reason) : '') + ' · chaîne ' + e.chain)));
  });
}
export function onLastTransition(lt) {
  if (!S.liveSeen) { S.liveSeen = true; S.seenT = lt ? lt.t : 0; return; }   // first snapshot: history, not news
  if (!lt || lt.t === S.seenT) return;
  S.seenT = lt.t;
  if (!S.journal.length || S.journal[S.journal.length - 1].t !== lt.t) S.journal.push(lt);
  S.journal = S.journal.slice(-50);
  renderJournal();
  blinkChain(lt.chain);
}
