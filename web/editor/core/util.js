/**
 * Editor core: tiny DOM helpers.
 *
 * Purpose :  h() element factory, $ query, clone / isNum / esc, Tabler icon helpers (ico, icoHtml), the console / window
 *            error capture feeding errLog (read by the verification scenarios) and the #debug overlay (dbg).
 * Boundary:  DOM of the editor page and the shared state S only, no network call. Moved unchanged out of the former
 *            single-file editor.js (lot M6).
 * Depends :  nothing (leaf module)
 * Invariant: evaluated first (no imports): the error capture is installed before any other module runs.
 * Test    :  l7 editor scenarios (scripts/l7_scenarios.sh) through the window.__editor hooks.
 */
// ---------- tiny helpers ----------
export const $ = (s, r) => (r || document).querySelector(s);
export const clone = (o) => JSON.parse(JSON.stringify(o));
export const isNum = (s) => /^-?\d+(\.\d+)?$/.test(String(s).trim());
export function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const k in attrs || {}) {
    const v = attrs[k];
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat()) {
    if (c == null || c === false) continue;
    e.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return e;
}
export const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
// Icons: CSS mask over the vendored Tabler SVG, coloured by currentColor. Names come from the vocabulary
// (validated again here because they end up in a style attribute).
const ICON_OK = /^[a-z0-9-]{1,40}$/;
export const icoUrl = (n) => "url('/web/vendor/tabler/" + (ICON_OK.test(n || '') ? n : 'circle-dot') + ".svg')";
export const icoHtml = (n, color) => `<span class="ico" style="--ic:${icoUrl(n)}${color ? ';color:' + color : ''}"></span>`;
export function ico(n, color) {
  const e = h('span', { class: 'ico' });
  e.style.setProperty('--ic', icoUrl(n));
  if (color) e.style.color = color;
  return e;
}
export const errLog = [];
['error', 'warn'].forEach((lv) => {          // console errors count for the verification scenarios
  const orig = console[lv];
  console[lv] = function () { if (lv === 'error') errLog.push('console.error ' + Array.from(arguments).join(' ')); return orig.apply(console, arguments); };
});
window.addEventListener('error', (e) => { errLog.push(String(e.message)); dbg('ERR ' + e.message); });
window.addEventListener('unhandledrejection', (e) => { errLog.push(String(e.reason)); dbg('REJ ' + e.reason); });
export function dbg(msg) {
  if (!location.hash.includes('debug') || location.hash.includes('quiet')) return;
  let d = $('#dbg');
  if (!d) { d = h('div', { id: 'dbg' }); document.body.append(d); }
  d.textContent += msg + '\n';
}
