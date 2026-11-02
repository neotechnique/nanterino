/**
 * Variables panel: Noms / Listes tables.
 *
 * Purpose :  renderVarNames, renderVarLists, dict items, scope / persistence fields, renderVars.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, variables/model.js, inspector/property-picker.js, inspector/fields.js,
 *            variables/panel.js, variables/values.js, core/ui.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, clone, h, ico } from '../core/util.js';
import { S, byId } from '../core/state.js';
import { docVars, itemCount, listDefs, typeLabel, varDefs } from './model.js';
import { valueIssue, varUses, vtype } from '../inspector/property-picker.js';
import { checkCtl, field, selectCtl } from '../inspector/fields.js';
import { checkNewName, deleteVarOrList, liveText, renameUses, varsChanged, varsUi } from './panel.js';
import { coerceItem, initialValue, resetVar, usesBox, valueInput } from './values.js';
import { toast } from '../core/ui.js';

const VAR_TYPE_TIP = {   // lot L5 tooltips of the variable types
  bool: 'Vrai / faux : deux valeurs, testées par « Une variable est vraie » et inversées par « Inverser une variable ».',
  number: 'Nombre (entier ou décimal) : comparable avec <, ≤, >, ≥ ; « Ajouter à une variable » le change.',
  string: 'Texte libre (300 caractères au plus) ; comparé avec = ou ≠.',
  choice: 'Choix : une valeur parmi la liste de choix déclarée.',
  duration: 'Durée en secondes (≥ 0) : comme un nombre.',
  // L12 (Variables v2)
  integer: 'Entier : nombre sans décimale, bornes min / max / pas facultatives (les actions bornent la valeur).',
  percent: 'Pourcentage de 0 à 100 (curseur).',
  datetime: 'Date et heure (AAAA-MM-JJTHH:MM) ou vide ; « Noter la date et l’heure » la remplit, « Temps écoulé depuis » la teste.',
  timer: 'Chrono : « Démarrer un chrono » le lance ; sa valeur = secondes écoulées ; « Un chrono atteint une durée » déclenche une chaîne.',
  expression: 'Expression du visage (liste du vocabulaire du robot).',
  gaze: 'Mode de regard du visage.',
  phrase: 'Phrase à dire (300 caractères au plus), voix pré-calculée comme « Dire un texte ».',
  media: 'Fichier du dossier media/ (chanson…) ou vide.',
  intent_ref: 'Nom d’une intention (ou vide).',
  list_ref: 'Nom d’une liste (ou vide).',
  state_ref: 'Nom d’un état (ou vide).',
  color: 'Couleur #rrggbb.',
  vector2: 'Deux nombres [x, y].',
  vector3: 'Trois nombres [x, y, z].',
};
// L12: store facts of GET /api/graph/vars for one variable / list: saved in state/vars.json, refused at load.
const storeOf = () => (((varsUi.live || {}).store) || {});
const savedOnRobot = (part, id) => (((storeOf().saved || {})[part]) || []).includes(id);
const ignoredOf = (part, id) => (storeOf().ignored || []).filter((g) => g.part === part && g.name === id);
const scopeLabel = (sc) => ((byId(S.V.scopes, sc || 'global') || {}).label || sc || 'Globale');
// Portée + Persistante controls shared by names and lists (persist = globals only; conversation drops it).
function scopeFields(box, rec, canPersist) {
  box.append(field('Portée', selectCtl((S.V.scopes || []).map((x) => ({ v: x.id, l: x.label })), rec.scope || 'global', (sc) => {
    if (sc === 'global') delete rec.scope; else { rec.scope = sc; delete rec.persist; }
    varsChanged(true);
  }), ((byId(S.V.scopes, rec.scope || 'global') || {}).help) || ''));
  box.lastChild.querySelector('select').setAttribute('data-opt', 'scope');
  const glob = (rec.scope || 'global') === 'global';
  const chk = checkCtl('Persistante (gardée au redémarrage du robot)', !!rec.persist, (c) => {
    if (c) rec.persist = true; else delete rec.persist;
    varsChanged(true);
  });
  const inp = chk.querySelector('input'); inp.setAttribute('data-opt', 'persist');
  if (!glob || !canPersist) inp.disabled = true;
  box.append(chk, h('div', { class: 'help' }, !canPersist ? 'Ce type ne se garde pas au redémarrage.'
    : glob ? 'Valeur enregistrée sur le robot (state/vars.json) et relue au démarrage ; « Réinitialiser » l’oublie.'
      : 'Seules les variables globales peuvent être persistantes.'));
}
// Réinitialiser + what the robot holds for it (live value, saved value, refused saved value).
function robotFields(box, part, id, type) {
  const ign = ignoredOf(part, id);
  box.append(h('div', { class: 'vrobot' }, h('span', {}, 'Sur le robot : '),
    h('b', { 'data-live': part + ':' + id, 'data-ltype': part === 'names' ? type : '' }, liveText((((varsUi.live || {})[part]) || {})[id], part === 'names' ? type : '')),
    savedOnRobot(part, id) ? h('span', { class: 'vbadge persist', 'data-tip': 'Une valeur est enregistrée dans state/vars.json.' }, 'enregistrée') : null,
    h('button', { type: 'button', 'data-act': 'reset', title: 'Remettre la valeur initiale sur le robot et oublier la valeur enregistrée',
      onclick: () => resetVar(id) }, ico('refresh'), ' Réinitialiser')));
  ign.forEach((g) => box.append(h('div', { class: 'iss warn vconf' }, `Valeur enregistrée ignorée au chargement : ${g.reason}.`)));
}
function renderVarNames(box) {
  const defs = varDefs(), names = docVars().names;
  const tbl = h('table', { class: 'vtable' }, h('thead', {}, h('tr', {}, h('th', { 'data-tip': 'Nom de la variable dans les nœuds (« $nom » dans une valeur = sa valeur).' }, 'Nom'),
    h('th', { 'data-tip': 'Type : ce que la variable peut contenir (survoler un type pour le détail).' }, 'Type'),
    h('th', { 'data-tip': 'Globale : garde sa valeur jusqu’au rechargement (ou plus si persistante). Conversation : revient à sa valeur initiale à chaque nouveau visiteur.' }, 'Portée'),
    h('th', { 'data-tip': 'Valeur au chargement du graphe (et après chaque rechargement).' }, 'Initiale'),
    h('th', { title: 'Valeur actuelle sur le robot' }, 'Live'))));
  const tb = h('tbody', {});
  defs.forEach((d) => {
    const init = d.system ? (d.id === 'etat' ? 'départ' : '—') : liveText(d.value, d.type);
    const ign = ignoredOf('names', d.id).length;
    const tr = h('tr', { class: 'vrow' + (varsUi.sel === d.id ? ' on' : '') + (d.readonly ? ' ro' : '') + (ign ? ' conf' : ''), 'data-var': d.id, title: d.description || '',
      onclick: () => { varsUi.sel = varsUi.sel === d.id ? null : d.id; varsUi.uses = null; renderVars(); } },
      h('td', {}, d.readonly ? h('span', { class: 'lock', title: 'Variable système : lecture seule' }, ico('lock')) : null, h('code', {}, d.id),
        d.persist ? h('span', { class: 'vbadge persist', 'data-tip': 'Persistante : gardée au redémarrage (state/vars.json).' }, 'P') : null,
        ign ? h('span', { class: 'vbadge conf', 'data-tip': 'La valeur enregistrée a été ignorée au chargement (voir le détail).' }, '!') : null),
      h('td', { 'data-tip': VAR_TYPE_TIP[d.type] || null }, typeLabel(d.type)),
      h('td', { class: 'vscope', 'data-scope': d.system ? 'system' : (d.scope || 'global'), 'data-tip': d.system ? 'Variable système : tenue par le robot.' : null }, d.system ? '—' : scopeLabel(d.scope)),
      h('td', {}, init), h('td', { class: 'vlive', 'data-live': 'names:' + d.id, 'data-ltype': d.type }, liveText(((varsUi.live || {}).names || {})[d.id], d.type)));
    tb.append(tr);
    if (d.description) tb.append(h('tr', { class: 'vdesc' }, h('td', { colspan: 5 }, d.description)));
  });
  tbl.append(tb);
  box.append(tbl);
  const d = varsUi.sel ? defs.find((x) => x.id === varsUi.sel) : null;
  if (d && d.readonly) {
    box.append(h('div', { class: 'vedit' }, h('div', { class: 'insttitle' }, ico('lock'), h('code', {}, d.id), h('small', { class: 'hint' }, 'système')),
      h('p', { class: 'hint' }, (d.description || '') + (d.id === 'etat' ? ' Changer : action « Changer d’état » ; tester : condition « etat = … ».' : ' Lecture seule : tenue par le robot.')),
      d.choices ? h('p', { class: 'hint' }, 'Valeurs : ' + d.choices.join(', ')) : null,
      h('p', { class: 'hint' }, 'Sur le robot : ', h('b', { 'data-live': 'names:' + d.id, 'data-ltype': d.type }, liveText(((varsUi.live || {}).names || {})[d.id], d.type)))));
  } else if (d) {
    const v = names[d.id], vt = vtype(v.type);
    const ed = h('div', { class: 'vedit' }, h('div', { class: 'insttitle' }, ico('text-caption'), h('code', {}, d.id)));
    const nm = h('input', { type: 'text', maxlength: 32, value: d.id });
    ed.append(field('Nom', h('div', { class: 'addrow' }, nm, h('button', { type: 'button', onclick: () => {
      const nu = nm.value.trim(); if (nu === d.id) return;
      const why = checkNewName(nu, d.id); if (why) { toast(why, 'err'); return; }
      const n2 = {}; Object.keys(names).forEach((k) => { n2[k === d.id ? nu : k] = names[k]; }); docVars().names = n2;
      renameUses(d.id, nu); varsUi.sel = nu; toast(`Renommée en « ${nu} » (et dans les nœuds qui l'utilisent).`, 'ok'); varsChanged(true);
    } }, 'Renommer'))));
    ed.append(field('Type', selectCtl((S.V.var_types || []).map((t) => ({ v: t.id, l: t.label })), v.type, (t) => {
      v.type = t; if (t === 'choice') v.choices = v.choices && v.choices.length ? v.choices : ['a', 'b']; else delete v.choices;
      const nt = vtype(t);
      ['min', 'max', 'step'].forEach((k) => { if (!(nt.options || []).includes(k)) delete v[k]; });
      if (nt.persist === false) delete v.persist;
      v.value = initialValue(t, v.choices); varsChanged(true);
    }), (vt.label ? vt.label + ' — ' : '') + 'Changer le type remet la valeur initiale à zéro.'));
    if (v.type === 'choice') {
      const ci = h('input', { type: 'text', value: (v.choices || []).join(', ') });
      ci.addEventListener('change', () => {
        const cs = [...new Set(ci.value.split(',').map((x) => x.trim()).filter(Boolean))];
        if (!cs.length) { toast('Un choix demande au moins une valeur.', 'err'); return; }
        v.choices = cs; if (!cs.includes(v.value)) v.value = cs[0]; varsChanged(true);
      });
      ed.append(field('Valeurs possibles (séparées par des virgules)', ci));
    }
    // the initial value control comes first among the number inputs (older tests and users type there)
    const ini = valueInput(v, v.value, (x) => { v.value = x; varsChanged(true); });
    ini.setAttribute('data-opt', 'value');
    const vi = valueIssue(v, v.value, d.id);
    ed.append(field('Valeur initiale', ini, vi ? vi.message : vt.control === 'timer' ? '' : 'Valeur au chargement du graphe (les valeurs repartent de là à chaque chargement).'));
    if ((vt.options || []).length) {
      const row = h('div', { class: 'addrow vbounds' });
      const lab = { min: 'min', max: 'max', step: 'pas' };
      (vt.options || []).forEach((k) => {
        const i = h('input', { type: 'number', step: 'any', placeholder: lab[k] || k, title: lab[k] || k, 'data-opt': k });
        i.value = v[k] == null ? '' : v[k];
        i.addEventListener('change', () => {
          const nv = i.value === '' ? null : Number(i.value);
          const lo = k === 'min' ? nv : v.min, hi = k === 'max' ? nv : v.max;
          if (lo != null && hi != null && lo > hi) { toast('Le minimum doit être inférieur ou égal au maximum.', 'err'); i.value = v[k] == null ? '' : v[k]; return; }
          if (k === 'step' && nv != null && nv <= 0) { toast('Le pas doit être positif.', 'err'); i.value = v[k] == null ? '' : v[k]; return; }
          if (nv == null) delete v[k]; else v[k] = nv;
          // an initial value outside the new bounds is a server error: bring it back inside
          if (typeof v.value === 'number') {
            const n = Math.min(v.max != null ? v.max : Infinity, Math.max(v.min != null ? v.min : -Infinity, v.value));
            if (n !== v.value) { v.value = n; toast(`Valeur initiale ramenée à ${n} (dans les bornes).`, ''); }
          }
          varsChanged(true);
        });
        row.append(h('span', { class: 'vax' }, lab[k] || k), i);
      });
      ed.append(field('Bornes (facultatives)', row, 'Les actions « Changer » / « Ajouter à » bornent la valeur ; une constante hors bornes est signalée.'));
    }
    scopeFields(ed, v, vt.persist !== false);
    robotFields(ed, 'names', d.id, v.type);
    const ta = h('textarea', { rows: 2 }); ta.value = v.description || '';
    ta.addEventListener('change', () => { if (ta.value.trim()) v.description = ta.value.trim(); else delete v.description; varsChanged(false); });
    ed.append(field('Description', ta));
    const ub = usesBox(d.id); if (ub) ed.append(ub);
    const used = varUses(d.id);
    ed.append(h('p', { class: 'hint' }, used.length ? `Utilisée par ${used.length} nœud(s) : ${used.join(', ')}.` : "Utilisée par aucun nœud."));
    ed.append(h('button', { type: 'button', class: 'danger', onclick: () => deleteVarOrList(d.id, false) }, 'Supprimer la variable'));
    box.append(ed);
  }
  // new variable
  const nn = h('input', { type: 'text', placeholder: 'nom_de_variable', maxlength: 32, style: 'flex:1;width:auto;min-width:0', 'data-new': 'var' });
  const nt = selectCtl((S.V.var_types || []).map((t) => ({ v: t.id, l: t.label })), 'number', () => {});
  nt.setAttribute('data-new', 'vartype');
  const create = () => {
    const id = nn.value.trim(), why = checkNewName(id, null);
    if (why) { toast(why, 'err'); return; }
    const t = nt.value, v = { type: t };
    if (t === 'choice') v.choices = ['a', 'b'];
    v.value = initialValue(t, v.choices);
    docVars().names[id] = v; varsUi.sel = id;
    toast(`Variable « ${id} » créée.`, 'ok'); varsChanged(true);
  };
  nn.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); create(); } });
  box.append(h('div', { class: 'sect' }, 'Nouvelle variable'), h('div', { class: 'addrow rowbtns' }, nn, nt, h('button', { type: 'button', class: 'primary', 'data-new': 'varadd', onclick: create }, 'Ajouter')));
}
// Dict items (L12): key -> value sub-table (key text, typed value, remove) + an add row.
function renderDictItems(right, r) {
  const items = r.items && typeof r.items === 'object' && !Array.isArray(r.items) ? r.items : (r.items = {});
  const tbl = h('table', { class: 'vtable vdict' }, h('thead', {}, h('tr', {}, h('th', {}, 'Clé'), h('th', {}, 'Valeur'), h('th', {}, ''))));
  const tb = h('tbody', {});
  Object.keys(items).forEach((key) => {
    const kin = h('input', { type: 'text', maxlength: 60, value: key, 'data-dkey': key });
    kin.addEventListener('change', () => {
      const nk = kin.value.trim();
      if (nk === key) return;
      if (!nk || nk.startsWith('$') || nk in items) { toast(!nk ? 'Clé vide.' : nk.startsWith('$') ? 'Une clé ne commence pas par $.' : 'Cette clé existe déjà.', 'err'); kin.value = key; return; }
      const n2 = {}; Object.keys(items).forEach((k) => { n2[k === key ? nk : k] = items[k]; }); r.items = n2; varsChanged(true);
    });
    const val = valueInput({ type: r.type }, items[key], (x) => { items[key] = x; varsChanged(true); });
    val.setAttribute('data-dval', key);
    tb.append(h('tr', { class: 'drow', 'data-dict-key': key }, h('td', {}, kin), h('td', {}, val),
      h('td', {}, h('button', { type: 'button', title: 'Retirer', onclick: () => { delete items[key]; varsChanged(true); } }, '×'))));
  });
  tbl.append(tb);
  if (!Object.keys(items).length) right.append(h('p', { class: 'hint' }, 'Dictionnaire vide.'));
  right.append(tbl);
  const nk = h('input', { type: 'text', maxlength: 60, placeholder: 'clé', 'data-new': 'dkey', style: 'flex:0 0 30%;min-width:0' });
  let nv = initialValue(r.type);
  const vin = valueInput({ type: r.type }, nv, (x) => { nv = x; });
  vin.setAttribute('data-new', 'dval');
  const add = () => {
    const k = nk.value.trim();
    if (['text', 'textarea'].includes(vtype(r.type).control)) nv = vin.value.trim();
    if (!k || k.startsWith('$')) { toast(!k ? 'Clé vide.' : 'Une clé ne commence pas par $.', 'err'); return; }
    if (k in items) { toast('Cette clé existe déjà.', 'err'); return; }
    if (nv === '' || nv == null) { toast('Valeur vide.', 'err'); return; }
    items[k] = nv; varsChanged(true);
  };
  nk.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
  right.append(h('div', { class: 'addrow' }, nk, vin, h('button', { type: 'button', 'data-new': 'dadd', onclick: add }, 'Ajouter')));
}
function renderVarLists(box) {
  const lists = listDefs(), raw = docVars().lists;
  const wrap = h('div', { class: 'vlists' });
  const left = h('div', { class: 'vlleft' });
  const modeMark = (l) => (l.kind === 'dict' ? ' {}' : l.mode === 'shuffle' ? ' sac' : l.mode === 'history' ? ' hist.' : '');
  lists.forEach((l) => left.append(h('button', { type: 'button', class: 'vlitem navok' + (varsUi.list === l.id ? ' on' : '') + (ignoredOf('lists', l.id).length ? ' conf' : ''), 'data-list': l.id, 'data-kind': l.kind, title: l.description || '',
    onclick: () => { varsUi.list = l.id; varsUi.uses = null; renderVars(); } },
    l.readonly ? h('span', { class: 'lock' }, ico('lock')) : null, h('code', {}, l.id), h('small', {}, ' ' + itemCount(l.items) + modeMark(l)))));
  if (!lists.length) left.append(h('p', { class: 'hint' }, 'Aucune liste.'));
  const right = h('div', { class: 'vlright' });
  const l = lists.find((x) => x.id === varsUi.list) || null;
  if (!l) right.append(h('p', { class: 'hint' }, 'Choisir une liste à gauche.'));
  else {
    const r = raw[l.id];
    right.append(h('div', { class: 'insttitle' }, l.readonly ? ico('lock') : ico('text-caption'), h('code', {}, l.id), h('small', { class: 'hint' }, typeLabel(l.type, true) + (l.kind === 'dict' ? ' · dictionnaire' : ''))));
    if (l.description) right.append(h('p', { class: 'hint' }, l.description));
    if (l.readonly) {
      right.append(h('div', { class: 'note' }, l.source && l.source.cfg ? `Liée à la configuration du robot (clé « ${l.source.cfg} ») : à modifier dans la configuration. Lecture seule ici.`
        : `Mots de l’intention « ${(l.source || {}).intent} » : à modifier dans le panneau Intentions. Lecture seule ici.`));
      // a bound list only accepts the shuffle mode (contract L11)
      const ms = selectCtl((S.V.list_modes || []).filter((m) => ['plain', 'shuffle'].includes(m.id)).map((m) => ({ v: m.id, l: m.label })), r.mode || 'plain', (m) => {
        if (m === 'plain') delete r.mode; else r.mode = m; varsChanged(true);
      });
      ms.setAttribute('data-opt', 'mode');
      right.append(field('Mode', ms, ((byId(S.V.list_modes, r.mode || 'plain') || {}).help) || ''));
    } else {
      right.append(field('Type des éléments', selectCtl((S.V.list_types || []).map((t) => ({ v: t.id, l: t.label })), r.type || 'string', (t) => {
        r.type = t;
        if (r.kind === 'dict') { const n2 = {}; Object.keys(r.items || {}).forEach((k) => { const x = coerceItem(t, r.items[k]); if (x !== undefined) n2[k] = x; }); r.items = n2; }
        else r.items = (r.items || []).map((x) => coerceItem(t, x)).filter((x) => x !== undefined);
        varsChanged(true);
      })));
      const ks = selectCtl((S.V.list_kinds || [{ id: 'list', label: 'Liste' }]).map((k) => ({ v: k.id, l: k.label })), l.kind, (k) => {
        if (k === 'dict') {   // list -> dict: items become cle1, cle2, ... (mode / max do not apply to a dict)
          const n2 = {}; (Array.isArray(r.items) ? r.items : []).forEach((x, i) => { n2['cle' + (i + 1)] = x; });
          r.kind = 'dict'; r.items = n2; delete r.mode; delete r.max;
        } else { r.items = Object.values(r.items || {}); delete r.kind; }
        varsChanged(true);
      });
      ks.setAttribute('data-opt', 'kind');
      right.append(field('Genre', ks, ((byId(S.V.list_kinds, l.kind) || {}).help) || ''));
      if (l.kind !== 'dict') {
        const ms = selectCtl((S.V.list_modes || []).map((m) => ({ v: m.id, l: m.label })), r.mode || 'plain', (m) => {
          if (m === 'plain') delete r.mode; else r.mode = m;
          if (m === 'history' && r.max == null) { r.max = 10; toast('Historique : taille maximale réglée à 10 (modifiable).', ''); }
          varsChanged(true);
        });
        ms.setAttribute('data-opt', 'mode');
        right.append(field('Mode', ms, ((byId(S.V.list_modes, r.mode || 'plain') || {}).help) || ''));
        const mx = h('input', { type: 'number', min: 1, max: 200, step: 1, placeholder: 'sans limite', 'data-opt': 'max' });
        mx.value = r.max == null ? '' : r.max;
        mx.addEventListener('change', () => {
          if (mx.value === '') { if (r.mode === 'history') { toast('Le mode Historique demande une taille maximale.', 'err'); mx.value = r.max; return; } delete r.max; }
          else { const n = Math.round(Number(mx.value)); if (!(n >= 1 && n <= 200)) { toast('Taille maximale : de 1 à 200.', 'err'); mx.value = r.max == null ? '' : r.max; return; } r.max = n; }
          varsChanged(true);
        });
        right.append(field('Taille maximale', mx, 'Un ajout de trop retire le plus ancien élément.'));
      }
    }
    if (l.kind === 'dict' && !l.readonly) renderDictItems(right, r);
    else {
      const ul = h('ol', { class: 'vitems' });
      (Array.isArray(l.items) ? l.items : []).forEach((it, k) => {
        const li = h('li', {}, h('span', { class: 'vit' }, liveText(it, l.type)));
        if (!l.readonly) {
          const items = raw[l.id].items;
          const mv = (d) => { const j = k + d; if (j < 0 || j >= items.length) return; [items[k], items[j]] = [items[j], items[k]]; varsChanged(true); };
          li.append(h('span', { class: 'vbtns' },
            h('button', { type: 'button', title: 'Monter', disabled: k === 0, onclick: () => mv(-1) }, '↑'),
            h('button', { type: 'button', title: 'Descendre', disabled: k === items.length - 1, onclick: () => mv(1) }, '↓'),
            h('button', { type: 'button', title: 'Retirer', onclick: () => { items.splice(k, 1); varsChanged(true); } }, '×')));
        }
        ul.append(li);
      });
      if (!itemCount(l.items)) right.append(h('p', { class: 'hint' }, 'Liste vide.'));
      right.append(ul);
    }
    right.append(h('p', { class: 'hint' }, 'Valeur live : ', h('span', { 'data-live': 'lists:' + l.id }, liveText(((varsUi.live || {}).lists || {})[l.id])), ' élément(s) sur le robot.'));
    if (!l.readonly) {
      if (l.kind !== 'dict') {
        let val = initialValue(r.type || 'string');
        const inp = valueInput({ type: r.type || 'string' }, val, (x) => { val = x; });
        inp.setAttribute('data-new', 'item');
        const add = () => {
          if (['text', 'textarea'].includes(vtype(r.type || 'string').control)) val = inp.value.trim();
          if (val === '' || val == null) { toast('Élément vide.', 'err'); return; }
          r.items = (r.items || []).concat([clone(val)]); varsChanged(true);
        };
        if (inp.tagName === 'INPUT' && inp.type === 'text') inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
        right.append(h('div', { class: 'addrow' }, inp, h('button', { type: 'button', 'data-new': 'itemadd', onclick: add }, 'Ajouter')));
      }
      scopeFields(right, r, true);
      robotFields(right, 'lists', l.id, r.type);
      const nm = h('input', { type: 'text', maxlength: 32, value: l.id });
      right.append(field('Nom', h('div', { class: 'addrow' }, nm, h('button', { type: 'button', onclick: () => {
        const nu = nm.value.trim(); if (nu === l.id) return;
        const why = checkNewName(nu, l.id); if (why) { toast(why, 'err'); return; }
        const n2 = {}; Object.keys(raw).forEach((k) => { n2[k === l.id ? nu : k] = raw[k]; }); docVars().lists = n2;
        renameUses(l.id, nu); varsUi.list = nu; varsChanged(true);
      } }, 'Renommer'))));
      const ta = h('textarea', { rows: 2 }); ta.value = r.description || '';
      ta.addEventListener('change', () => { if (ta.value.trim()) r.description = ta.value.trim(); else delete r.description; varsChanged(false); });
      right.append(field('Description', ta));
      const ub = usesBox(l.id); if (ub) right.append(ub);
      right.append(h('button', { type: 'button', class: 'danger', onclick: () => deleteVarOrList(l.id, true) }, 'Supprimer la liste'));
    } else { const ub = usesBox(l.id); if (ub) right.append(ub); }
  }
  wrap.append(left, right);
  box.append(wrap);
  const nn = h('input', { type: 'text', placeholder: 'nom_de_liste', maxlength: 32, style: 'flex:1;width:auto;min-width:0', 'data-new': 'list' });
  const nt = selectCtl((S.V.list_types || []).map((t) => ({ v: t.id, l: t.label })), 'string', () => {});
  nt.setAttribute('data-new', 'listtype');
  const nk = selectCtl((S.V.list_kinds || [{ id: 'list', label: 'Liste' }]).map((k) => ({ v: k.id, l: k.label })), 'list', () => {});
  nk.setAttribute('data-new', 'listkind');
  const create = () => {
    const id = nn.value.trim(), why = checkNewName(id, null);
    if (why) { toast(why, 'err'); return; }
    docVars().lists[id] = nk.value === 'dict' ? { type: nt.value, kind: 'dict', items: {} } : { type: nt.value, items: [] };
    varsUi.list = id;
    toast(`${nk.value === 'dict' ? 'Dictionnaire' : 'Liste'} « ${id} » créé${nk.value === 'dict' ? '' : 'e'}.`, 'ok'); varsChanged(true);
  };
  nn.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); create(); } });
  box.append(h('div', { class: 'sect' }, 'Nouvelle liste'), h('div', { class: 'addrow rowbtns' }, nn, nk, nt, h('button', { type: 'button', class: 'primary', 'data-new': 'listadd', onclick: create }, 'Ajouter')));
}
export function renderVars() {
  const box = $('#vars'); if (!box) return;
  const keep = box.scrollTop;
  box.innerHTML = '';
  box.append(h('p', { class: 'hint' }, 'Variables du graphe (comme les variables locales de Game Creator 2) : les déclencheurs « Une variable change » les écoutent, les actions les changent, les conditions les testent. Enregistrées avec le graphe ; leurs valeurs repartent de la valeur initiale à chaque chargement (portée Globale), à chaque nouvelle conversation (portée Conversation) ou sont gardées au redémarrage (Persistante).'));
  // L12: saved values the robot refused at load (type changed, invalid value): one line each, clickable
  (storeOf().ignored || []).forEach((g) => box.append(h('div', { class: 'iss warn vconf', 'data-conf': g.part + ':' + g.name,
    onclick: () => { if (g.part === 'lists') { varsUi.tab = 'lists'; varsUi.list = g.name; } else { varsUi.tab = 'names'; varsUi.sel = g.name; } renderVars(); } },
  `Valeur enregistrée ignorée : ${g.part === 'lists' ? 'liste' : 'variable'} « ${g.name} » (${g.reason}).`)));
  const nV = varDefs().length, nL = listDefs().length;
  box.append(h('div', { class: 'vtabs' },
    h('button', { type: 'button', class: 'navok' + (varsUi.tab === 'names' ? ' on' : ''), 'data-vtab': 'names', onclick: () => { varsUi.tab = 'names'; renderVars(); } }, `Noms (${nV})`),
    h('button', { type: 'button', class: 'navok' + (varsUi.tab === 'lists' ? ' on' : ''), 'data-vtab': 'lists', onclick: () => { varsUi.tab = 'lists'; renderVars(); } }, `Listes (${nL})`)));
  if (varsUi.tab === 'lists') renderVarLists(box); else renderVarNames(box);
  box.scrollTop = keep;
}
