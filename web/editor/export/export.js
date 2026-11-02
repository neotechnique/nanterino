/**
 * Export (lot L14): "Exporter l'image".
 *
 * Purpose :  export popover, POST /api/graph/snapshot, status polling, PNG download (read-only).
 * Boundary:  network: POST /api/graph/snapshot, GET /api/graph/snapshot/status and /api/graph/snapshot.png (read-only
 *            export). Moved unchanged out of the former single-file editor.js (lot M6).
 * Depends :  core/util.js, core/state.js, core/api.js, core/ui.js, core/debug.js
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
import { $, h } from '../core/util.js';
import { S } from '../core/state.js';
import { api, postJson } from '../core/api.js';
import { toast } from '../core/ui.js';
import { sleep } from '../core/debug.js';

// ---------- lot L14: "Exporter l'image" (full-resolution PNG of the whole graph) ----------
// The capture runs on the robot (POST /api/graph/snapshot -> tools/graph_snapshot.py in its own headless Firefox);
// this page only starts it, shows its progress in one toast and downloads the PNG. Options never touch the document.
// shared state: S.exportPop, S.exportRun, S.exportInfo (core/state.js)
export const exportOpts = { scale: 1, theme: 'dark', doc: 'saved' };
function exportPopover() {
  if (S.exportPop) return S.exportPop;
  const group = (name, label, choices) => h('fieldset', { class: 'exgrp' }, h('legend', null, label),
    choices.map(([v, l]) => h('label', { class: 'exopt' },
      h('input', { type: 'radio', name: 'ex-' + name, value: String(v), checked: String(exportOpts[name]) === String(v),
        onchange: () => { exportOpts[name] = name === 'scale' ? +v : v; } }), ' ' + l)));
  S.exportPop = h('div', { id: 'exportPop', class: 'exportpop', role: 'dialog', 'aria-label': "Exporter l'image du graphe", hidden: true,
    onclick: (e) => e.stopPropagation() },
    h('div', { class: 'extitle' }, "Exporter l'image du graphe"),
    group('scale', 'Zoom', [[1, '100 % (pleine résolution)'], [0.5, '50 %']]),
    group('theme', 'Thème', [['dark', 'Sombre'], ['light', 'Clair']]),
    group('doc', 'Graphe', [['saved', 'Graphe enregistré (celui du robot)'], ['default', 'Graphe par défaut']]),
    h('div', { class: 'exhint' }, "Tout le graphe en une seule image PNG, calculée sur le robot (30 s à 2 min ; immédiat si rien n'a changé). Les modifications non enregistrées n'y figurent pas."),
    h('div', { class: 'exbtns' },
      h('button', { onclick: () => { S.exportPop.hidden = true; } }, 'Fermer'),
      h('button', { id: 'btnExportGo', class: 'primary', onclick: () => { S.exportPop.hidden = true; startExport(); } }, 'Exporter')));
  document.body.append(S.exportPop);
  document.addEventListener('click', () => { S.exportPop.hidden = true; });
  return S.exportPop;
}
export function toggleExport(e) {
  if (e) e.stopPropagation();
  const pop = exportPopover(), r = $('#btnExport').getBoundingClientRect();
  pop.hidden = !pop.hidden;
  if (!pop.hidden) {
    pop.style.top = Math.round(r.bottom + 6) + 'px';
    pop.style.left = Math.round(Math.max(8, Math.min(r.left, innerWidth - pop.offsetWidth - 8))) + 'px';
  }
}
export async function startExport(opts) {
  if (S.exportRun) { toast("Un export d'image est déjà en cours.", ''); return; }
  opts = { ...exportOpts, ...(opts || {}) };
  const btn = $('#btnExport'), box = $('#toasts'), t = h('div', { class: 'toast exprog', role: 'status' }, "Export de l'image : démarrage…");
  const say = (m) => { t.textContent = m; if (!t.isConnected) box.append(t); };
  box.append(t); if (btn) btn.disabled = true;
  S.exportRun = { opts, t0: Date.now() }; S.exportInfo = { state: 'running', opts };
  try {
    let job = null;
    const deadline = Date.now() + 420000;
    // single-flight on the robot: if ANOTHER capture was running, wait for it, then ask again for ours
    for (let round = 0; round < 3; round++) {
      const r = await postJson('/api/graph/snapshot', opts);
      if (!r.ok || !r.json || !r.json.job) throw new Error((r.json && r.json.error) || ('HTTP ' + r.status));
      job = r.json.job;
      const other = !!job.already_running;
      if (other) say("Une autre capture est en cours sur le robot : attente…");
      while (job.state === 'running') {
        if (Date.now() > deadline) throw new Error('délai dépassé');
        if (!other) say("Export de l'image : " + Math.round((job.progress || 0) * 100) + ' % (' + Math.round(job.seconds || 0) + ' s)…');
        await sleep(1000);
        const s = await api('/api/graph/snapshot/status');
        if (!s.ok || !s.json || !s.json.job) throw new Error('statut indisponible (' + s.status + ')');
        job = s.json.job;
      }
      if (!other) break;
    }
    if (!job || job.state !== 'done' || !job.url) throw new Error((job && job.error) || 'capture inachevée');
    say("Export de l'image : téléchargement…");
    const resp = await fetch(job.url);
    if (!resp.ok) throw new Error('téléchargement refusé (' + resp.status + ')');
    const buf = new Uint8Array(await resp.arrayBuffer());
    const sig = [137, 80, 78, 71, 13, 10, 26, 10].every((v, i) => buf[i] === v);
    if (!sig || buf.length < 24) throw new Error("le fichier reçu n'est pas une image PNG");
    const dv = new DataView(buf.buffer), w = dv.getUint32(16), hgt = dv.getUint32(20);
    const cd = resp.headers.get('Content-Disposition') || '', name = (/filename="([^"]+)"/.exec(cd) || [])[1] || job.filename || 'nanterino-graph.png';
    S.exportInfo = { state: 'done', name, bytes: buf.length, width: w, height: hgt, png: sig, cache_hit: !!job.cache_hit, job, opts,
      disposition: cd, seconds: Math.round((Date.now() - S.exportRun.t0) / 100) / 10 };
    if (!window.__exportNoSave) {      // headless checks set this flag: the download stays in memory only
      const url = URL.createObjectURL(new Blob([buf], { type: 'image/png' })), a = h('a', { href: url, download: name });
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    }
    say('Image exportée : ' + name + ' (' + w + ' × ' + hgt + ' px, ' + (buf.length / 1048576).toFixed(1) + ' Mo)' + (job.cache_hit ? ' — graphe inchangé, image déjà prête.' : '.'));
    t.classList.add('ok');
    setTimeout(() => t.remove(), 9000);
  } catch (e) {
    S.exportInfo = { state: 'failed', error: String(e && e.message || e), opts };
    say("Export de l'image impossible : " + S.exportInfo.error);
    t.classList.add('err');
    setTimeout(() => t.remove(), 12000);
  } finally {
    S.exportRun = null; if (btn) btn.disabled = false;
  }
}
