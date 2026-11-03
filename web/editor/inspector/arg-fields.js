/**
 * Inspector: typed argument controls (Vars L2, L12, M5).
 *
 * Purpose :  argFields(): one control per vocabulary argument, chosen by the ARG_CONTROLS registry (keyed by arg type /
 *            control), plus the value source hooks of lot M5.
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, variables/model.js, inspector/property-picker.js, inspector/fields.js,
 *            variables/values.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { clone, h } from '../core/util.js';
import { S, byId, evs, stateIcon } from '../core/state.js';
import { itemCount, listDef, listDefs, opLabel, typeLabel, varDef, varDefs } from '../variables/model.js';
import {
  SRC_MAX_DEPTH, boundsOf, choicesOf, opsFor, srcButton, srcField, srcOf, srcPicked, valueIssue, vtype
} from './property-picker.js';
import { areaCtl, checkCtl, field, numOrKey, selectCtl, textCtl } from './fields.js';
import { valueInput } from '../variables/values.js';

// ---------- typed argument controls (Vars L2) ----------
// Required plain args per action (var / list / value args are described by the vocabulary itself).
export const REQUIRED_ARGS = { say_text: ['text'], set_expression: ['name', 'seconds'], wait: ['seconds'], gaze: ['mode'] };
export const ORDER_OPS = ['<', '<=', '>', '>='];
// Default value written when a variable / list is picked for a required `value` (so a checkbox or a select never
// shows a value the document does not hold). Text has no default.
// L12: read from the vocabulary (var_types[].default / choices); text, dates and chronos have no default here.
export function defaultValueFor(type, choices) {
  if (type === 'choice') return (choices || [])[0];
  const vt = byId(S.V.var_types, type);
  if (!vt) return type === 'bool' ? false : (type === 'number' || type === 'duration') ? 0 : undefined;
  if (['text', 'textarea', 'timer', 'datetime'].includes(vt.control)) return undefined;
  if (vt.control === 'select') {
    if (vt.nullable) return undefined;
    const cs = (vt.choices || []).map((c) => c.id);
    return cs.includes(vt.default) || !cs.length ? vt.default : cs[0];
  }
  return vt.default == null ? undefined : clone(vt.default);
}
// Argument control registry (lot M6): the former if / else chain of argFields, one entry per control, keyed by the
// vocabulary argument type (or the argument flag that picks the control). Entries are tried IN ORDER and the first
// whose when(arg) is true renders (same precedence as the chain: `number` with `min` before plain `number`, text keys
// before intents, long texts, then the plain text field). render(c) appends to c.box; returning true skips the M5 ▾
// post-step exactly like the chain's early `return` did. c = the per-argument context built in argFields.
export const ARG_CONTROLS = [
  {
    key: 'var',
    when: (arg) => arg.type === 'var',
    render({ box, arg, v, lab, ctx, F, pick }) {
      const opts = varDefs().filter((d) => (!(arg.var_types || []).length || arg.var_types.includes(d.type))
        && (!arg.writable || !d.readonly || (d.id === 'etat' && ctx.id === 'set_var')));
      const sel = selectCtl([{ v: '', l: '(choisir une variable)' }].concat(opts.map((d) => ({ v: d.id, l: d.id + ' — ' + typeLabel(d.type) + (d.system ? ' (système)' : '') }))),
        v == null ? '' : v, (x) => pick(x, varDef(x)));
      sel.classList.add('varsel');
      const d = v ? varDef(v) : null;
      box.append(F(lab, sel, d ? (d.description || d.label || '') : (opts.length ? '' : 'Aucune variable de ce type : créez-en une dans le panneau Variables.')));
    },
  },
  {
    key: 'list',
    when: (arg) => arg.type === 'list',
    render({ box, arg, v, lab, F, pick }) {
      const opts = listDefs().filter((l) => (!(arg.list_types || []).length || arg.list_types.includes(l.type))
        && (!(arg.list_kinds || []).length || arg.list_kinds.includes(l.kind)) && (!arg.writable || !l.readonly));
      const dict = (arg.list_kinds || []).length === 1 && arg.list_kinds[0] === 'dict';
      const sel = selectCtl([{ v: '', l: dict ? '(choisir un dictionnaire)' : '(choisir une liste)' }].concat(opts.map((l) => ({ v: l.id, l: l.id + ' — ' + typeLabel(l.type, true) + ' (' + itemCount(l.items) + ')' }))),
        v == null ? '' : v, (x) => pick(x, null));
      sel.classList.add('varsel');
      box.append(F(lab, sel, opts.length ? '' : dict ? 'Aucun dictionnaire de ce type : créez-en un dans le panneau Variables (Listes, genre Dictionnaire).' : 'Aucune liste de ce type : créez-en une dans le panneau Variables.'));
    },
  },
  {
    key: 'value',
    when: (arg) => arg.type === 'value',
    render({ box, arg, v, lab, cur, set, F, stateOpts, kindOf, refDef }) {
      const d = refDef(arg), isList = kindOf(arg.of) === 'list';
      if (!d) { box.append(F(lab, h('div', { class: 'hint' }, isList ? "Choisir d'abord la liste." : "Choisir d'abord la variable."))); return true; }
      const opt = !!arg.optional, none = opt ? '(toute valeur)' : '(choisir)';
      const ctlType = vtype(d.type).control;
      let ctl, hint = opt ? 'Facultatif.' : '';
      if (!isList && d.id === 'etat') {
        if (['in', 'not_in'].includes(cur.op)) {
          const chosen = Array.isArray(v) ? v : (v ? [v] : []);
          ctl = h('div', { class: 'statechk' });
          S.V.states.forEach((s) => ctl.append(checkCtl(s.label, chosen.includes(s.id), (c) => {
            const st = new Set(chosen); c ? st.add(s.id) : st.delete(s.id);
            set(arg.name, S.V.states.map((x) => x.id).filter((x) => st.has(x)));
          }, stateIcon(s.id))));
        } else ctl = selectCtl([{ v: '', l: none }].concat(stateOpts), v == null ? '' : v, (x) => set(arg.name, x));
      } else if (d.type === 'choice' || ctlType === 'select') {
        ctl = selectCtl([{ v: '', l: none }].concat(choicesOf(d)), v == null ? '' : v, (x) => set(arg.name, x));
      } else if (d.type === 'bool') {
        if (opt) ctl = selectCtl([{ v: '', l: none }, { v: 'true', l: 'vrai' }, { v: 'false', l: 'faux' }], v == null ? '' : String(v), (x) => set(arg.name, x === '' ? '' : x === 'true'));
        else ctl = checkCtl('vrai', v === true || v === 'true', (c) => set(arg.name, c));
      } else if (ctlType === 'number' || ctlType === 'slider' || ctlType === 'timer') {
        // a chrono compares as elapsed seconds; bounded numbers show their bounds (a constant outside = warning)
        const b = ctlType === 'timer' ? { min: 0, max: null, step: null } : boundsOf(d);
        ctl = h('input', { type: 'number', step: 'any', min: d.type === 'duration' || ctlType === 'timer' ? 0 : null });
        ctl.value = v == null ? '' : v;
        ctl.addEventListener('change', () => set(arg.name, ctl.value === '' ? '' : Number(ctl.value)));
        if (b.min != null || b.max != null) hint = [hint, `Bornes : ${b.min == null ? '…' : b.min} à ${b.max == null ? '…' : b.max}.`].filter(Boolean).join(' ');
        if (ctlType === 'timer') hint = [hint, 'En secondes écoulées depuis le départ du chrono.'].filter(Boolean).join(' ');
        const vi = valueIssue(d, v, d.id);
        if (vi && vi.level === 'warn') hint = vi.message;
      } else if (ctlType === 'datetime') {
        // date_compare: a fixed date, or "$heure" (now) / another date variable
        const now = v === '$heure';
        ctl = h('div', {});
        if (!now) ctl.append(valueInput(d, v, (x) => set(arg.name, x == null ? '' : x)));
        ctl.append(checkCtl('maintenant ($heure)', now, (c) => set(arg.name, c ? '$heure' : '')));
      } else if (['color', 'vector'].includes(ctlType)) {
        ctl = valueInput(d, v, (x) => set(arg.name, x));
      } else {
        const utt = arg.utterance && v === '$utterance';
        ctl = h('div', {});
        if (!utt) ctl.append(ctlType === 'textarea' ? areaCtl(v, (x) => set(arg.name, x), 300) : textCtl(v, (x) => set(arg.name, x)));
        if (arg.utterance) ctl.append(checkCtl('la phrase entendue ($utterance)', utt, (c) => set(arg.name, c ? '$utterance' : '')));
      }
      box.append(F(lab + (isList ? ' (' + typeLabel(d.type, true) + ')' : ' (' + typeLabel(d.type) + ')'), ctl, hint));
    },
  },
  {
    key: 'enum',
    when: (arg) => arg.type === 'enum',
    render({ box, arg, v, lab, cur, set, ctx, F, opType }) {
      let options = (arg.options || []).slice();
      const labels = Object.assign({ in: 'parmi', not_in: 'hors de' }, arg.labels || {});
      if (arg.name === 'op') {
        const ot = opType();
        if (cur.name === 'etat') options = ['=', '!=', 'in', 'not_in'];
        else if (ot) { const allowed = opsFor(ot); options = options.filter((o) => allowed.includes(o)); }
      }
      const optLabel = (o) => (arg.name === 'op' ? opLabel(o) + '  ' : '') + (labels[o] || (byId(evs(), o) || {}).label || String(o));
      const required = (ctx.required || []).includes(arg.name) || arg.name === 'op';
      box.append(F(lab, selectCtl((arg.name === 'op' ? [] : [{ v: '', l: required ? '(à choisir)' : '(aucun)' }]).concat(options.map((o) => ({ v: o, l: optLabel(o) }))), v == null ? (arg.name === 'op' ? '=' : '') : v, (x) => set(arg.name, x)),
        arg.name === 'op' ? '' : required ? 'Obligatoire : choisir une valeur.' : 'Facultatif.'));
    },
  },
  {
    key: 'time',
    when: (arg) => arg.type === 'time',
    render({ box, arg, v, lab, set, F }) {
      // L12: hh:mm (time_between); the browser's time field gives "HH:MM"
      const t = h('input', { type: 'time', step: 60, 'data-arg': arg.name });
      t.value = typeof v === 'string' && /^\d{1,2}:\d{2}$/.test(v) ? v.padStart(5, '0') : '';
      t.addEventListener('change', () => set(arg.name, t.value ? t.value.slice(0, 5) : ''));
      box.append(F(lab, t, typeof v === 'string' && v && !/^\d{1,2}:\d{2}$/.test(v) ? `« ${v} » n’est pas une heure hh:mm.` : ''));
    },
  },
  {
    key: 'multi',
    when: (arg) => arg.type === 'multi',
    render({ box, arg, v, lab, set, F }) {
      // L12: several options (weekday_in): one checkbox each, kept in the vocabulary order
      const chosen = Array.isArray(v) ? v : (v ? [v] : []);
      const wrap = h('div', { class: 'statechk multichk', 'data-arg': arg.name });
      (arg.options || []).forEach((o) => {
        const c = checkCtl((arg.labels || {})[o] || o, chosen.includes(o), (on) => {
          const st = new Set(chosen); on ? st.add(o) : st.delete(o);
          const out = (arg.options || []).filter((x) => st.has(x));
          set(arg.name, out.length ? out : '');
        });
        c.querySelector('input').setAttribute('data-opt', o);
        wrap.append(c);
      });
      box.append(F(lab, wrap, chosen.length ? '' : 'Au moins un choix.'));
    },
  },
  {
    key: 'number-min',
    when: (arg) => arg.type === 'number' && arg.min != null && !(arg.options || []).length,
    render({ box, arg, v, lab, set, F }) {
      // L12: plain number with a lower bound (seconds of elapsed_since / timer_reached)
      const n = h('input', { type: 'number', step: 'any', min: arg.min, 'data-arg': arg.name });
      n.value = v == null ? '' : v;
      n.addEventListener('change', () => set(arg.name, n.value === '' ? '' : Number(n.value)));
      box.append(F(lab, n, v != null && v !== '' && Number(v) < arg.min ? `${arg.min} au minimum.` : ''));
    },
  },
  {
    key: 'number',
    when: (arg) => arg.type === 'number',
    render({ box, arg, i, v, lab, set, F }) {
      const lid = 'dl-arg' + i;
      const dl = (arg.options || []).length ? h('datalist', { id: lid }, (arg.options || []).map((o) => h('option', { value: o }))) : null;
      box.append(F(lab + ((arg.options || []).length && !/clé/.test(lab) ? ' (nombre, ou clé de réglage)' : ''), textCtl(v, (x) => set(arg.name, x === '' ? '' : numOrKey(x)), 'text', dl ? lid : null)));
      if (dl) box.append(dl);
    },
  },
  {
    key: 'text-keys',
    when: (arg) => arg.utterance || arg.vars,
    render({ box, arg, i, v, lab, set, F }) {
      // L12: dict keys: a fixed key, "$utterance" (a key heard in the sentence) or "$variable" (a text variable)
      const utt = arg.utterance && v === '$utterance';
      const lid = 'dl-vars' + i;
      const wrap = h('div', {});
      if (!utt) wrap.append(textCtl(v, (x) => set(arg.name, x.trim()), 'text', arg.vars ? lid : null));
      if (arg.vars) wrap.append(h('datalist', { id: lid }, varDefs().filter((d) => ['text', 'textarea', 'select'].includes(vtype(d.type).control)).map((d) => h('option', { value: '$' + d.id }))));
      if (arg.utterance) wrap.append(checkCtl('une clé de la phrase entendue ($utterance)', utt, (c) => set(arg.name, c ? '$utterance' : '')));
      const ref = typeof v === 'string' && v.startsWith('$') && v !== '$utterance' ? v.slice(1) : null;
      box.append(F(lab, wrap, ref && !varDef(ref) ? `Variable inconnue : « ${ref} ».` : arg.vars ? '« $nom » = la valeur de la variable texte nom.' : ''));
    },
  },
  {
    key: 'intent',
    when: (arg) => arg.type === 'intent',
    render({ box, arg, v, lab, set, F }) {
      // lot M5: an intent of the vocabulary (source intent_match; never the implicit `question`)
      const opts = (S.V.intents || []).filter((it) => it.id !== 'question').map((it) => ({ v: it.id, l: it.label && it.label.length <= 40 ? it.label : it.id }));
      box.append(F(lab, selectCtl([{ v: '', l: '(choisir un motif)' }].concat(opts), v == null ? '' : v, (x) => set(arg.name, x)), opts.length ? '' : 'Aucun motif.'));
    },
  },
  {
    key: 'textarea',
    when: (arg) => arg.max_len > 100,
    render({ box, arg, v, lab, set, F }) {
      box.append(F(lab, areaCtl(v, (x) => set(arg.name, x), arg.max_len), `${arg.max_len} caractères au plus.` + (arg.optional ? ' Facultatif.' : '')));
    },
  },
  {
    key: 'text',
    when: () => true,
    render({ box, arg, v, lab, set, F }) {
      box.append(F(lab, textCtl(v, (x) => set(arg.name, x)), arg.optional ? 'Facultatif.' : ''));
    },
  },
];

// Controls for a vocabulary argument list. `cur` = current values, `set(name, value)` writes one ('' / null = remove).
//   var   -> variables filtered by var_types; `writable` hides read-only ones (etat stays offered to set_var: it is
//            the state change)
//   list  -> lists filtered by list_types; `writable` hides source-bound lists
//   value -> control by the type of the variable / list items named by `of`: checkbox (bool), number (number,
//            duration), select (choice; etat = the states, a set of states with in / not_in), text (string, with a
//            "$utterance" switch when the vocabulary offers it)
//   enum  -> select with the vocabulary labels (op: = != in not_in on etat; order operators only for numbers)
// L12 additions: list args also filter by list_kinds (list / dict); `value` of a dict = the dict's value type; any
// vocabulary type gets its typed control (valueInput), numbers show their bounds; `time` = hh:mm field; `multi` =
// one checkbox per option (week days); `text` with `utterance` / `vars` = "$utterance" switch + "$variable" hints;
// `number` with `min` = number field; operators follow op_sets of the type of the variable (or dict) they compare.
export function argFields(box, specArgs, cur, set, ctx) {
  ctx = ctx || {};
  const stateOpts = S.V.states.map((s) => ({ v: s.id, l: s.label }));
  const kindOf = (name) => ((specArgs || []).find((x) => x.name === name) || {}).type;
  const refDef = (arg) => {
    const ref = cur[arg.of];
    if (ref == null || ref === '') return null;
    return kindOf(arg.of) === 'list' ? listDef(ref) : varDef(ref);
  };
  // type compared by an `op`: the variable (name) or the dict / list values
  const opType = () => {
    if (cur.name) { const d = varDef(cur.name); return d ? d.type : null; }
    const lref = cur.dict || cur.list; if (lref) { const l = listDef(lref); return l ? l.type : null; }
    return null;
  };
  // lot M5: type a value source must give for this field (`props`: "of" = the variable / list / dict named by
  // `of`, "same" = the enclosing field's type, else a type id); null = not known yet (nothing chosen)
  const propType = (arg) => {
    if (arg.props === 'of') { const d = refDef(arg); return d ? d.type : null; }
    if (arg.props === 'same') return ctx.ft || null;
    return arg.props || null;
  };
  (specArgs || []).forEach((arg, i) => {
    const v = cur[arg.name], lab = arg.label || arg.name;
    const F = (l, c, hp) => field(l, c, hp, arg.help);   // lot L5: argument help as a tooltip
    const dependent = (specArgs || []).find((x) => x.type === 'value' && x.of === arg.name && !x.optional);
    const pick = (x, def) => {
      set(arg.name, x);
      if (dependent && def) { const dv = def.id === 'etat' ? (S.V.states[0] || {}).id : defaultValueFor(def.type, def.choices); if (dv !== undefined) set(dependent.name, dv); }
    };
    // lot M5: the field takes a value source (vocabulary `props`): a source (or `$x` / `$utterance`) shows as its chip
    // + sub-fields; a constant keeps the plain control below, with the ▾ added next to its label (post-step)
    const ft = arg.props ? propType(arg) : null, level = ctx.level || 0;
    const srcOk = !!ft && level < SRC_MAX_DEPTH && !(arg.type === 'value' && ['in', 'not_in'].includes(cur.op));
    let dv;                                // plain default written by « Valeur fixe »
    if (srcOk && arg.type === 'value') {
      const rd = refDef(arg);
      dv = rd && rd.id === 'etat' && kindOf(arg.of) !== 'list' ? (S.V.states[0] || {}).id : defaultValueFor(ft, (rd || {}).choices);
    }
    const n0 = box.children.length;
    if (srcOk) {
      const s = srcOf(v);
      if (s) { box.append(srcField(arg, lab, v, s, ft, set, level, dv)); return; }
    }
    const c = { box, specArgs, arg, i, v, lab, cur, set, ctx, F, pick, dependent, stateOpts, kindOf, refDef, opType, ft, level, srcOk, dv, n0 };
    if (ARG_CONTROLS.find((e) => e.when(arg)).render(c) === true) return;   // true = the chain's former early return
    if (srcOk) {   // lot M5: ▾ next to the plain control's label (outside the <label>: a button inside would take its clicks)
      const f = Array.from(box.children).slice(n0).find((e) => e.classList.contains('fld'));
      if (f) {
        const w = h('div', { class: 'srcwrap' });
        f.replaceWith(w);
        w.append(f, srcButton(arg.name, ft, 'constant', (d) => srcPicked(d, arg, ft, set, level, dv)));
      }
    }
  });
}
