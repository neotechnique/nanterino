/* « Mécanique » screen of the Nanterino dashboard (lot C3): live joints, bounded set-points, calibration, e-stop.
 *
 * Purpose  : one row per joint grouped Tête / Bras gauche / Bras droit / Base (live position, speed, current,
 *            temperature; a slider bounded by the calibration min..max; « Définir mini / maxi / zéro »; « Balayage
 *            lent »; enable toggle), the global ARRÊT D'URGENCE + réarmement in the sticky header, calibration
 *            export / import, and a live side / top schematic of the robot (SVG).
 * Boundary : talks only to /api/body/* (contract in nanterino/body/api.py) and the /api/body/stream WebSocket (falls
 *            back to polling GET /api/body/state). The server enforces every limit (Body.clamp): the slider bounds are
 *            a convenience, never the safety. No other dashboard code is touched (dash.html loads this module).
 * Invariants: rows are built once per layout / calibration signature, live values update in place; a slider the
 *            user is dragging is never overwritten by the stream; commands are throttled to one per 100 ms per joint.
 * Test     : .venv/bin/python -m tests.web.run mechanics   (window.__mech exposes state() and lastReply for checks)
 */
const $ = (id) => document.getElementById(id);
const el = (tag, attrs = {}, kids = []) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'text') e.textContent = v; else if (k === 'class') e.className = v; else e.setAttribute(k, v);
  }
  for (const c of kids) e.append(c);
  return e;
};
const fmt = (v, d = 1) => (v == null || !isFinite(v) ? '–' : Number(v).toFixed(d));

let state = null, sig = '', ws = null, pollTimer = null;
const dragging = new Set();        // joint ids whose slider is being moved by the user
const lastSent = {};               // joint id -> time of the last command (throttle)
const pendingVal = {};             // joint id -> value waiting for the throttle window
const mech = { state: () => state, lastReply: null, errors: [] };
window.__mech = mech;

async function api(method, path, body) {
  const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body) });
  let j = null;
  try { j = await r.json(); } catch (e) { j = { ok: false, error: 'réponse illisible' }; }
  mech.lastReply = { status: r.status, body: j };
  if (!r.ok) notify((j && (j.error || (j.errors || []).join(' '))) || ('erreur ' + r.status), true);
  return { status: r.status, body: j };
}

function notify(text, bad = false) {
  const n = $('mech-msg');
  if (!n) return;
  n.textContent = text;
  n.className = 'mech-msg ' + (bad ? 'bad' : 'ok');
  clearTimeout(notify._t);
  notify._t = setTimeout(() => { n.textContent = ''; n.className = 'mech-msg'; }, 6000);
}

// ---- commands
function sendTarget(id, value) {
  const now = performance.now();
  pendingVal[id] = value;
  if (now - (lastSent[id] || 0) < 100) {
    clearTimeout(sendTarget['_t' + id]);
    sendTarget['_t' + id] = setTimeout(() => sendTarget(id, pendingVal[id]), 110);
    return;
  }
  lastSent[id] = now;
  api('POST', '/api/body/command', { targets: { [id]: Number(value) } });
}

async function setFromPos(id, action) {
  const r = await api('POST', `/api/body/calibration/${id}/${action}`);
  if (r.status === 200) notify({ set_min: 'Mini', set_max: 'Maxi', set_zero: 'Zéro' }[action] + ' enregistré pour ' + id);
  refresh();
}

async function setEnabled(id, on) {
  await api('PUT', '/api/body/calibration', { joints: { [id]: { enabled: on } } });
  refresh();
}

async function estop() { await api('POST', '/api/body/estop', { reason: 'bouton du tableau de bord' }); refresh(); }
async function estopReset() { await api('POST', '/api/body/estop/reset'); notify('Arrêt d\'urgence réarmé'); refresh(); }

async function exportCal() {
  const r = await fetch('/api/body/calibration/export');
  const txt = await r.text();
  mech.lastExport = txt;
  const a = el('a', { href: URL.createObjectURL(new Blob([txt], { type: 'application/json' })),
    download: 'nanterino-calibration.json' });
  document.body.append(a); a.click(); a.remove();
  notify('Calibration exportée');
}

async function importCal(file) {
  let doc;
  try { doc = JSON.parse(await file.text()); } catch (e) { notify('Fichier JSON invalide', true); return; }
  const r = await api('POST', '/api/body/calibration/import', doc);
  if (r.status === 200) notify('Calibration importée'); 
  refresh();
}

// ---- rendering
function layoutSig(s) {
  return JSON.stringify(s.joints.map((j) => [j.id, j.calibration]));
}

function buildRows(s) {
  const host = $('mech-joints');
  host.textContent = '';
  for (const g of s.groups) {
    const js = s.joints.filter((j) => j.group === g.id);
    if (!js.length) continue;
    const box = el('div', { class: 'mech-group', id: 'mech-group-' + g.id }, [el('h3', { text: g.label })]);
    for (const j of js) box.append(buildRow(j));
    host.append(box);
  }
}

function buildRow(j) {
  const c = j.calibration, wheel = j.mode === 'velocity';
  const step = wheel ? 0.01 : (j.unit === 'rad' ? 0.01 : 0.5);
  const slider = el('input', { type: 'range', class: 'mech-slider', 'data-joint': j.id, min: c.min, max: c.max,
    step, 'aria-label': 'Consigne ' + j.label });
  slider.value = j.target;
  slider.addEventListener('pointerdown', () => dragging.add(j.id));
  slider.addEventListener('pointerup', () => setTimeout(() => dragging.delete(j.id), 300));
  slider.addEventListener('input', () => { $('mech-tg-' + j.id).textContent = fmt(slider.value, wheel ? 2 : 1); sendTarget(j.id, slider.value); });
  slider.addEventListener('change', () => { dragging.delete(j.id); sendTarget(j.id, slider.value); });
  const btn = (txt, act, title) => {
    const b = el('button', { type: 'button', 'data-act': act, 'data-joint': j.id, title, text: txt });
    if (wheel) { b.disabled = true; b.title = 'Sans objet pour une roue (commande en vitesse)'; }
    b.addEventListener('click', () => (act === 'sweep'
      ? api('POST', '/api/body/sweep', { joint: j.id }).then((r) => r.status === 200 && notify('Balayage lent : ' + j.label))
      : setFromPos(j.id, act)));
    return b;
  };
  const en = el('input', { type: 'checkbox', 'data-joint': j.id, class: 'mech-enable' });
  en.checked = j.enabled;
  en.addEventListener('change', () => setEnabled(j.id, en.checked));
  const u = j.unit, vu = wheel ? 'm/s²' : u + '/s²';   // acceleration unit
  return el('div', { class: 'mech-row', id: 'mech-row-' + j.id }, [
    el('div', { class: 'mech-head' }, [
      el('strong', { text: j.label }), el('code', { text: j.id }),
      el('label', { class: 'mech-en' }, [en, document.createTextNode(' activé')])]),
    el('div', { class: 'mech-live' }, [
      el('span', {}, [document.createTextNode(wheel ? 'Vitesse ' : 'Position '), el('b', { id: 'mech-pos-' + j.id }), document.createTextNode(' ' + (wheel ? 'm/s' : u))]),
      el('span', {}, [document.createTextNode(wheel ? 'Distance ' : 'Vitesse '), el('b', { id: 'mech-vel-' + j.id }), document.createTextNode(' ' + (wheel ? 'm' : u + '/s'))]),
      el('span', {}, [document.createTextNode('Courant '), el('b', { id: 'mech-cur-' + j.id }), document.createTextNode(' A')]),
      el('span', {}, [document.createTextNode('Temp. '), el('b', { id: 'mech-tmp-' + j.id }), document.createTextNode(' °C')]),
      el('span', { class: 'mech-flag', id: 'mech-flag-' + j.id })]),
    el('div', { class: 'mech-ctl' }, [
      el('span', { class: 'mech-lim', id: 'mech-min-' + j.id, text: fmt(c.min, wheel ? 2 : 1) }), slider,
      el('span', { class: 'mech-lim', id: 'mech-max-' + j.id, text: fmt(c.max, wheel ? 2 : 1) }),
      el('span', { class: 'mech-tg' }, [document.createTextNode('consigne '), el('b', { id: 'mech-tg-' + j.id, text: fmt(j.target, wheel ? 2 : 1) })])]),
    el('div', { class: 'btns mech-btns' }, [
      btn('Définir mini', 'set_min', 'La position actuelle devient la butée basse'),
      btn('Définir maxi', 'set_max', 'La position actuelle devient la butée haute'),
      btn('Définir zéro', 'set_zero', 'La position actuelle devient le zéro (les butées physiques ne bougent pas)'),
      btn('Balayage lent', 'sweep', 'Va lentement au mini, au maxi, puis revient')]),
    el('div', { class: 'mech-sub', text: `vitesse maxi ${c.max_speed} ${wheel ? 'm/s' : u + '/s'} · accél. maxi ${c.max_accel} ${vu} · courant maxi ${c.max_current} A · zone morte ${c.deadband} · sens ${c.direction > 0 ? '+' : '−'} · zéro ${fmt(c.zero, 2)}` })]);
}

function update(s) {
  state = s;
  const sg = layoutSig(s);
  if (sg !== sig) { sig = sg; buildRows(s); }
  for (const j of s.joints) {
    const wheel = j.mode === 'velocity';
    $('mech-pos-' + j.id).textContent = fmt(wheel ? j.velocity : j.position, wheel ? 2 : 1);
    $('mech-vel-' + j.id).textContent = fmt(wheel ? j.position : j.velocity, wheel ? 2 : 1);
    $('mech-cur-' + j.id).textContent = fmt(j.current, 2);
    $('mech-tmp-' + j.id).textContent = fmt(j.temperature, 1);
    const flag = !j.enabled ? 'désactivé' : j.overcurrent ? 'surintensité' : j.sweeping ? 'balayage' : j.moving ? 'en mouvement' : '';
    const f = $('mech-flag-' + j.id);
    f.textContent = flag; f.className = 'mech-flag' + (flag === 'surintensité' || flag === 'désactivé' ? ' bad' : '');
    const sl = document.querySelector(`.mech-slider[data-joint="${j.id}"]`);
    if (sl && !dragging.has(j.id) && document.activeElement !== sl) {
      sl.value = j.target;
      $('mech-tg-' + j.id).textContent = fmt(j.target, wheel ? 2 : 1);
    }
    const en = document.querySelector(`.mech-enable[data-joint="${j.id}"]`);
    if (en && document.activeElement !== en) en.checked = j.enabled;
  }
  const on = s.estop && s.estop.active;
  document.body.classList.toggle('estop-on', !!on);
  $('estop-state').textContent = on ? 'ARRÊT D\'URGENCE ACTIF' : '';
  $('estop-reset').hidden = !on;
  $('mech-backend').textContent = 'backend : ' + s.backend + (s.backend === 'sim' ? ' (simulation, aucun moteur réel)' : '');
  $('mech-banner').textContent = s.backend_error ? 'Backend configuré indisponible : ' + s.backend_error : '';
  const st = s.calibration_store;
  $('mech-store').textContent = st ? `calibration rév. ${st.revision}${st.updated_at ? ' · ' + st.updated_at : ' · valeurs par défaut'}${st.error ? ' · ' + st.error : ''}` : 'calibration en mémoire';
  $('mech-events').textContent = (s.events || []).slice(-6).reverse().map((e) =>
    new Date(e.t * 1000).toLocaleTimeString('fr-FR') + '  ' + (e.joint ? e.joint + ' : ' : '') + e.message).join('\n');
  drawSchematic(s);
}

// ---- schematic: side view (head tilt, arms) + top view (head pan, wheel speeds)
function drawSchematic(s) {
  const J = Object.fromEntries(s.joints.map((j) => [j.id, j]));
  const v = (id, k = 'position') => (J[id] ? J[id][k] : 0);
  const rad = (d) => d * Math.PI / 180;
  const set = (id, attrs) => { const e = $(id); if (e) for (const [k, val] of Object.entries(attrs)) e.setAttribute(k, val); };
  // side view: torso centre (100, 110); head pivot (100, 62); shoulders at (100, 80); 0 deg = arm down, + = forward/up
  const tilt = rad(v('head_tilt'));
  set('sch-head', { transform: `rotate(${(-v('head_tilt')).toFixed(1)} 100 62)` });
  set('sch-gaze', { x2: (100 + 34 * Math.cos(-tilt)).toFixed(1), y2: (48 + 34 * Math.sin(-tilt)).toFixed(1) });
  for (const [side, dx] of [['l', -4], ['r', 4]]) {
    const sh = rad(v(`arm_${side}_shoulder`)), el2 = rad(v(`arm_${side}_elbow`));
    const x0 = 100 + dx, y0 = 82, L1 = 30, L2 = 26;
    const x1 = x0 + L1 * Math.sin(sh), y1 = y0 + L1 * Math.cos(sh);
    const x2 = x1 + L2 * Math.sin(sh + el2), y2 = y1 + L2 * Math.cos(sh + el2);
    set(`sch-arm-${side}`, { points: `${x0},${y0} ${x1.toFixed(1)},${y1.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}` });
  }
  // top view: robot centre (100, 100); head pan 0 = forward (up), + = to the robot's left (counter-clockwise)
  const pan = rad(v('head_pan'));
  set('sch-pan', { x2: (100 - 40 * Math.sin(pan)).toFixed(1), y2: (100 - 40 * Math.cos(pan)).toFixed(1) });
  for (const [id, x] of [['base_left_wheel', 62], ['base_right_wheel', 138]]) {
    const sp = J[id] ? J[id].velocity : 0, len = Math.max(-1, Math.min(1, sp / 0.5)) * 34;
    set('sch-' + id, { x1: x, x2: x, y1: 100, y2: (100 - len).toFixed(1) });
  }
  $('sch-caption').textContent = `pan ${fmt(v('head_pan'))}° · tilt ${fmt(v('head_tilt'))}° · épaules ${fmt(v('arm_l_shoulder'))}° / ${fmt(v('arm_r_shoulder'))}° · roues ${fmt(J.base_left_wheel ? J.base_left_wheel.velocity : 0, 2)} / ${fmt(J.base_right_wheel ? J.base_right_wheel.velocity : 0, 2)} m/s`;
}

// ---- live feed
async function refresh() {
  try { const r = await fetch('/api/body/state'); if (r.ok) update(await r.json()); } catch (e) { mech.errors.push(String(e)); }
}

function connect() {
  try { ws = new WebSocket(`ws://${location.host}/api/body/stream?hz=15`); } catch (e) { ws = null; }
  if (!ws) { pollTimer = pollTimer || setInterval(refresh, 300); return; }
  ws.onmessage = (m) => { try { update(JSON.parse(m.data)); } catch (e) { mech.errors.push(String(e)); } };
  ws.onopen = () => { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } };
  ws.onclose = () => { pollTimer = pollTimer || setInterval(refresh, 300); setTimeout(connect, 2000); };
}

function init() {
  $('estop').addEventListener('click', estop);
  $('estop-reset').addEventListener('click', estopReset);
  $('mech-stop').addEventListener('click', () => api('POST', '/api/body/stop').then(refresh));
  $('mech-export').addEventListener('click', exportCal);
  $('mech-import').addEventListener('change', (ev) => { const f = ev.target.files[0]; if (f) importCal(f); ev.target.value = ''; });
  mech.refresh = refresh;
  mech.importDoc = (doc) => api('POST', '/api/body/calibration/import', doc).then((r) => { refresh(); return r; });
  refresh().then(connect);
}

init();
