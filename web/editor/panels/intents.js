/**
 * Panels: intents (editable words, regex, only_in, description, new intents).
 *
 * Purpose :  renderIntents and intent cards.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, variables/model.js, core/history.js, hierarchy/tree.js, inspector/fields.js,
 *            inspector/inspector.js, variables/panel.js, core/ui.js, panels/live.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, h, ico } from '../core/util.js';
import { S, INTENT_NAME, byId, stateIcon } from '../core/state.js';
import { listDefs } from '../variables/model.js';
import { commitSoon } from '../core/history.js';
import { scheduleTree } from '../hierarchy/tree.js';
import { checkCtl, field, selectCtl } from '../inspector/fields.js';
import { renderInspector } from '../inspector/inspector.js';
import { varsUi } from '../variables/panel.js';
import { toast } from '../core/ui.js';
import { activateTab } from './live.js';

// ---------- intents panel (editable: words, regex, only_in, description, new intents) ----------
// The document (meta.intents) is the working copy; the server validates names, regexes and states at save /
// simulate time and answers with {intent: name, message}. A shared list (`words_from`) is shown read-only.
function intentChanged(rerender) {
  commitSoon();
  scheduleTree();
  if (rerender) renderIntents();
  if (S.selDf != null) renderInspector();
}
export function intentCard(name) {
  const it = S.meta.intents[name] || (S.meta.intents[name] = {});
  const sv = byId(S.V.intents, name) || {};
  const card = h('div', { class: 'intent' });
  card.append(h('div', { class: 'ihead' }, ico(it.icon || sv.icon || 'message', 'var(--cond)'), h('code', {}, 'intent.' + name)));
  if (S.intentErrs[name]) card.append(h('div', { class: 'ierr' }, S.intentErrs[name]));
  // Vars L2: lists bound to this intent's words (or to its shared config key) are visible in the Variables panel
  listDefs().filter((l) => l.source && (l.source.intent === name || (it.words_from && l.source.cfg === it.words_from))).forEach((l) => card.append(
    h('div', { class: 'note' }, 'Aussi visible comme liste ', h('a', { href: '#', class: 'navok', onclick: (e) => { e.preventDefault(); varsUi.tab = 'lists'; varsUi.list = l.id; activateTab('vars'); } }, '« ' + l.id + ' »'), ' dans le panneau Variables.')));
  if (it.words_from) {
    card.append(h('div', { class: 'note' }, `Liste partagée avec la config (clé « ${it.words_from} ») : à modifier dans la configuration du robot.`));
  } else {
    const mode = it.regex != null ? 'regex' : 'words';
    card.append(field('Reconnaissance', selectCtl([{ v: 'words', l: 'Liste de mots' }, { v: 'regex', l: 'Expression régulière' }], mode, (v) => {
      if (v === 'regex') { delete it.words; it.regex = it.regex || ''; } else { delete it.regex; it.words = it.words || []; }
      intentChanged(true);
    })));
    if (mode === 'regex') {
      const rx = h('input', { type: 'text', class: 'rx', spellcheck: 'false' }); rx.value = it.regex || '';
      rx.addEventListener('change', () => { it.regex = rx.value; intentChanged(false); });
      card.append(field('Expression (validée par le robot)', rx));
    } else {
      const wrap = h('div', { class: 'fld' }, h('span', {}, 'Mots reconnus'));
      (it.words || []).forEach((w, idx) => wrap.append(h('span', { class: 'chip' }, w,
        h('button', { type: 'button', title: 'Retirer', onclick: () => { it.words.splice(idx, 1); intentChanged(true); } }, '×'))));
      if (!(it.words || []).length) wrap.append(h('div', { class: 'note' }, 'Aucun mot pour l’instant.'));
      const inp = h('input', { type: 'text', placeholder: 'Ajouter un mot ou une phrase' });
      const add = () => {
        const ws = inp.value.split(',').map((x) => x.trim()).filter(Boolean);
        if (!ws.length) return;
        it.words = (it.words || []).concat(ws.filter((x) => !(it.words || []).includes(x)));
        intentChanged(true);
      };
      inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
      wrap.append(h('div', { class: 'addrow' }, inp, h('button', { type: 'button', onclick: add }, 'Ajouter')));
      card.append(wrap);
    }
  }
  const only = h('div', { class: 'fld' }, h('span', {}, 'Seulement dans les états (aucun coché : partout)'));
  S.V.states.forEach((s) => only.append(checkCtl(s.label, (it.only_in || []).includes(s.id), (c) => {
    const set = new Set(it.only_in || []); c ? set.add(s.id) : set.delete(s.id);
    if (set.size) it.only_in = S.V.states.map((x) => x.id).filter((x) => set.has(x)); else delete it.only_in;
    intentChanged(false);
  }, stateIcon(s.id))));
  card.append(only);
  const ta = h('textarea', {}); ta.value = it.description || '';
  ta.addEventListener('change', () => { it.description = ta.value; intentChanged(false); });
  card.append(field('Description', ta));
  return card;
}
export function renderIntents() {
  const box = $('#intents'); box.innerHTML = '';
  box.append(h('p', { class: 'hint' }, 'Phrases que le robot reconnaît et transforme en événement « intent.… », utilisable comme déclencheur. La première intention qui correspond gagne.'));
  Object.keys(S.meta.intents || {}).forEach((n) => box.append(intentCard(n)));
  S.V.intents.filter((i) => i.fixed).forEach((i) => box.append(h('div', { class: 'intent' },
    h('div', { class: 'ihead' }, ico(i.icon || 'question-mark', 'var(--cond)'), h('code', {}, 'intent.' + i.id)),
    h('div', { class: 'note' }, 'Intention implicite : toute phrase qui ne correspond à aucune autre. Non modifiable.'))));
  const nm = h('input', { type: 'text', placeholder: 'nom_de_l_intention', maxlength: 32, style: 'flex:1;width:auto;min-width:0' });
  const create = () => {
    const n = nm.value.trim();
    if (!INTENT_NAME.test(n)) { toast('Nom invalide : minuscules, chiffres et _, commence par une lettre, 32 caractères au plus.', 'err'); return; }
    if (n === 'question' || (S.meta.intents || {})[n]) { toast('Ce nom est déjà pris.', 'err'); return; }
    S.meta.intents = S.meta.intents || {};
    S.meta.intents[n] = { words: [], description: '' };
    toast(`Intention « ${n} » créée : ajoutez au moins un mot. Elle est utilisable comme déclencheur « intent.${n} ».`, 'ok');
    intentChanged(true);
  };
  nm.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); create(); } });
  box.append(h('div', { class: 'sect' }, 'Nouvelle intention'), h('div', { class: 'addrow rowbtns' }, nm, h('button', { type: 'button', class: 'primary', onclick: create }, 'Créer')));
}
