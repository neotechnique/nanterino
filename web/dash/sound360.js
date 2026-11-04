/* « Son 360° » screen of the Nanterino dashboard (lot C2): where the sound comes from, around the robot seen from above.
 *
 * Purpose  : a top view of the robot with its FRONT clearly marked (arrow + « AVANT »), a live beam toward the sound
 *            source (length = level, opacity = confidence), a fading trail of the last seconds, the numbers (azimuth,
 *            level, confidence, front offset), the « Définir comme avant » button (clap in front of the robot, then
 *            press it), the backend name and an honest message when the microphone gives no direction (today's mono
 *            mic), the head pan from /api/body/state drawn over it (head vs sound), and, when the backend is the
 *            simulation, a virtual source the user drags around the robot.
 * Boundary : talks only to /api/sound/* (contract in nanterino/sound/api.py), the /api/sound/stream WebSocket (falls
 *            back to polling GET /api/sound/state) and GET /api/body/state (head pan overlay, read only).
 * Invariants: azimuths are in the calibrated robot frame (0 = front = up on screen, + = robot's left = screen left,
 *            counter-clockwise); the array marker turns with the front offset; a direction is drawn only when the
 *            backend gives one (never a made-up angle); sim drags are throttled to one POST per 80 ms.
 * Test     : .venv/bin/python -m tests.web.run sound360   (window.__snd exposes state(), beam(), lastReply, errors)
 */
const $ = (id) => document.getElementById(id);
const NS = 'http://www.w3.org/2000/svg';
const C = 150;                                     // SVG centre (viewBox 0 0 300 300)
const R0 = 36, R1 = 140;                           // beam length for -60 dB .. 0 dB
const TRAIL_S = 8;
const SIDES = { avant: 'devant', gauche: 'à gauche', arriere: 'derrière', droite: 'à droite' };

let state = null, ws = null, pollTimer = null, headPan = null, lastSimAt = 0, simPending = null, dragging = false;
const trail = [];                                  // {t, az, lvl, conf}
const snd = { state: () => state, lastReply: null, errors: [], trail: () => trail.length };
window.__snd = snd;

const fmt = (v, d = 1) => (v == null || !isFinite(v) ? '–' : Number(v).toFixed(d));
const norm = (db) => Math.max(0, Math.min(1, ((db == null ? -90 : db) + 60) / 60));
const pt = (az, r) => { const a = az * Math.PI / 180; return [C - r * Math.sin(a), C - r * Math.cos(a)]; };
const sideOf = (az) => {
  const d = ((az + 45) % 360 + 360) % 360;        // same sectors as nanterino/sound/angles.py
  return d < 90 ? 'avant' : d < 180 ? 'gauche' : d < 270 ? 'arriere' : 'droite';
};

function guard(fn) {
  return (...a) => { try { return fn(...a); } catch (e) { snd.errors.push(String(e && e.stack || e)); } };
}

async function api(method, path, body) {
  const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body) });
  let j = null;
  try { j = await r.json(); } catch (e) { j = { ok: false, error: 'réponse illisible' }; }
  snd.lastReply = { status: r.status, body: j };
  return { status: r.status, body: j };
}

function say(text, bad) {
  const m = $('snd-feedback');
  m.textContent = text || '';
  m.className = 'mech-msg' + (text ? (bad ? ' bad' : ' ok') : '');
}

// ---- drawing
function beam(az, lvl, conf) {
  const b = $('snd-beam'), dot = $('snd-src');
  if (az == null) { b.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); return; }
  const r = R0 + norm(lvl) * (R1 - R0);
  const [x, y] = pt(az, r);
  const op = (0.15 + 0.85 * Math.max(0, Math.min(1, conf))).toFixed(3);
  for (const [k, v] of [['x2', x.toFixed(1)], ['y2', y.toFixed(1)], ['opacity', op], ['visibility', 'visible']]) b.setAttribute(k, v);
  for (const [k, v] of [['cx', x.toFixed(1)], ['cy', y.toFixed(1)], ['opacity', op], ['visibility', 'visible']]) dot.setAttribute(k, v);
}

function drawTrail(now) {
  const g = $('snd-trail');
  while (trail.length && now - trail[0].t > TRAIL_S) trail.shift();
  g.replaceChildren(...trail.map((p) => {
    const c = document.createElementNS(NS, 'circle');
    const [x, y] = pt(p.az, R0 + norm(p.lvl) * (R1 - R0));
    c.setAttribute('cx', x.toFixed(1)); c.setAttribute('cy', y.toFixed(1)); c.setAttribute('r', '3.2');
    c.setAttribute('opacity', (0.6 * (1 - (now - p.t) / TRAIL_S) * Math.max(0.2, p.conf)).toFixed(3));
    return c;
  }));
}

function drawHead() {
  const h = $('snd-head');
  if (headPan == null) { h.setAttribute('visibility', 'hidden'); $('snd-headval').textContent = '–'; return; }
  const [x, y] = pt(headPan, 95);                // drawn over the robot, under the beam's source dot
  h.setAttribute('x2', x.toFixed(1)); h.setAttribute('y2', y.toFixed(1)); h.setAttribute('visibility', 'visible');
  $('snd-headval').textContent = fmt(headPan) + '°';
}

const render = guard(() => {
  if (!state) return;
  const last = state.last || {};
  const dir = state.direction;
  const now = Date.now() / 1000;
  $('snd-backend').textContent = 'Backend : ' + state.backend + (state.configured && state.configured !== state.backend
    ? ' (configuré : ' + state.configured + ')' : '') + (state.available === false ? ' – indisponible' : '');
  // L44: a backend that stopped working after start (USB unplugged) has no backend_error: show its reason too
  const msg = state.message || (state.available === false && state.reason ? state.reason : '');
  $('snd-msg').textContent = msg;
  $('snd-msg').hidden = !msg;
  $('snd-sim').hidden = state.backend !== 'sim';
  $('snd-front').disabled = !state.gives_direction;
  $('snd-offset').textContent = fmt(state.front_offset_deg) + '°';
  $('snd-array').setAttribute('transform', 'rotate(' + fmt(state.front_offset_deg, 2) + ' ' + C + ' ' + C + ')');
  const az = last.azimuth_deg;
  $('snd-az').textContent = az == null ? '–' : fmt(az) + '° (' + SIDES[sideOf(az)] + ')';
  $('snd-level').textContent = last.level_db == null ? '–' : fmt(last.level_db) + ' dB';
  $('snd-conf').textContent = last.confidence == null ? '–' : Math.round(last.confidence * 100) + ' %';
  $('snd-raw').textContent = last.raw_azimuth_deg == null ? '–' : fmt(last.raw_azimuth_deg) + '°';
  $('snd-net').textContent = dir ? 'oui' : 'non';
  beam(az == null ? null : az, last.level_db, last.confidence || 0);
  if (az != null) {
    const t = last.wall || now;
    if (!trail.length || t > trail[trail.length - 1].t + 0.04) trail.push({ t, az, lvl: last.level_db, conf: last.confidence || 0 });
  }
  drawTrail(now);
  drawHead();
});

// ---- data
function onState(s) { state = s; render(); }

function connect() {
  try {
    ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/api/sound/stream?hz=15');
  } catch (e) { startPolling(); return; }
  ws.onmessage = (ev) => { try { onState(JSON.parse(ev.data)); } catch (e) { snd.errors.push(String(e)); } };
  ws.onclose = () => { ws = null; startPolling(); setTimeout(() => { if (!ws) { stopPolling(); connect(); } }, 5000); };
  ws.onerror = () => { try { ws.close(); } catch (e) { /* closed */ } };
}

function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(async () => {
    try { onState(await (await fetch('/api/sound/state')).json()); } catch (e) { /* server restarting */ }
  }, 200);
}
function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

async function pollHead() {
  try {
    const b = await (await fetch('/api/body/state')).json();
    const j = (b.joints || []).find((x) => x.id === 'head_pan');
    headPan = j ? j.position : null;
  } catch (e) { headPan = null; }
  drawHead();
}

// ---- actions
async function setFront() {
  const r = await api('POST', '/api/sound/front', { set_current: true });
  if (r.status === 200) {
    trail.length = 0;
    say('Nouvel avant enregistré : décalage ' + fmt(r.body.front_offset_deg) + '°.', false);
  } else say(r.body && r.body.error || ('erreur ' + r.status), true);
  onState((await api('GET', '/api/sound/state')).body);
}

async function sendSim(body) {
  const r = await api('POST', '/api/sound/sim', body);
  if (r.status !== 200) say(r.body && r.body.error || ('erreur ' + r.status), true);
  return r;
}

function simAt(ev) {
  const svg = $('snd-svg');
  const box = svg.getBoundingClientRect();
  const x = (ev.clientX - box.left) * 300 / box.width - C, y = (ev.clientY - box.top) * 300 / box.height - C;
  const az = Math.atan2(-x, -y) * 180 / Math.PI;   // inverse of pt(): up = 0, screen-left = +90
  const r = Math.hypot(x, y);
  const lvl = r > R0 ? Math.min(0, -60 + 60 * (r - R0) / (R1 - R0)) : Number($('snd-sim-level').value);
  $('snd-sim-level').value = String(Math.round(lvl));
  const body = { azimuth: Math.round(az * 10) / 10, level: Math.round(lvl * 10) / 10 };
  const now = performance.now();
  if (now - lastSimAt >= 80) { lastSimAt = now; sendSim(body); } else simPending = body;
}

function wire() {
  $('snd-front').addEventListener('click', guard(setFront));
  const svg = $('snd-svg');
  svg.addEventListener('pointerdown', guard((ev) => {
    if (!state || state.backend !== 'sim') return;
    dragging = true;
    try { svg.setPointerCapture(ev.pointerId); } catch (e) { /* synthetic events */ }
    simAt(ev);
  }));
  svg.addEventListener('pointermove', guard((ev) => { if (dragging) simAt(ev); }));
  const end = guard(() => { dragging = false; if (simPending) { sendSim(simPending); simPending = null; } });
  svg.addEventListener('pointerup', end);
  svg.addEventListener('pointercancel', end);
  $('snd-sim-clear').addEventListener('click', guard(() => sendSim({ clear: true })));
  $('snd-sim-random').addEventListener('click', guard(() => sendSim({ random: true })));
  setInterval(() => { if (simPending && performance.now() - lastSimAt >= 80) { lastSimAt = performance.now(); sendSim(simPending); simPending = null; } }, 100);
}

snd.beam = () => {
  const b = $('snd-beam');
  return { visible: b.getAttribute('visibility') !== 'hidden', x2: +b.getAttribute('x2'), y2: +b.getAttribute('y2'),
    opacity: +b.getAttribute('opacity') };
};
snd.screenAngle = () => {                            // azimuth the beam is drawn at (inverse of pt())
  const b = snd.beam();
  return b.visible ? Math.atan2(-(b.x2 - C), -(b.y2 - C)) * 180 / Math.PI : null;
};

if ($('snd')) {
  wire();
  connect();
  pollHead();
  setInterval(pollHead, 1000);
  setInterval(() => drawTrail(Date.now() / 1000), 500);
}
