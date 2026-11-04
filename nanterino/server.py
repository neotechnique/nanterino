"""Nanterino core service: engines + brain + web UI (face for the HDMI screen, dashboard for the PC).

logging: robotlog via nanterino.log. Run: python -m nanterino.server (systemd user service).
Access control: only localhost, Tailscale (100.64/10) and the USB-C link may connect; the robot
is not exposed to the venue Wi-Fi.
Graph editor routes follow Notes/graph-visual-format.md; lot L1 (2026-10-31) adds GET /api/graph/vars (live values
of the graph variables, read from Brain.var_snapshot()). Lot L11 (2026-11-01): the live Brain gets the persistent variable
store (state/vars.json, flushed at exit), GET /api/graph/vars adds `store` (Brain.var_store_info) and
POST /api/graph/vars/reset {"name"} puts a variable / list back to its initial value and forgets its saved value.
Lot L14 (2026-11-01): full-resolution PNG export of the graph: POST /api/graph/snapshot starts ONE capture job
(nanterino/snapshot_jobs.py runs tools/graph_snapshot.py with /usr/bin/python3 under `nice`, in its own thread and
process group: neither the event loop nor the robot loop waits for it), GET /api/graph/snapshot/status reports it,
GET /api/graph/snapshot.png serves the PNG as an attachment. GET /api/graph/visual?source=default serves the packaged
graph with its automatic layout (read-only; the capture of `--doc default` loads it into its own headless page).
Lot N1 (2026-11-02): the dashboard's mute / volume controls go through Brain.set_muted / Brain.set_volume (deaf already
used Brain.set_deaf) so the graph triggers mute_changed / volume_changed / deaf_changed fire for them too; the brain's
`volume_hook` / `flag_hook` give the graph actions the same effect (speaker profile, persisted flags). Dashboard
notifications (graph action notify_dashboard): GET /api/notifications lists the pending ones (also `notifications`
in GET /api/status), POST /api/notifications/click {"id"} clicks one (posts notification_clicked). Additive only.
Lot C3 (2026-11-04): the robot body (nanterino/body) is built here with the persistent calibration store
(state/body-calibration.json) and handed to the Brain (heartbeat tick). /api/body/* routes are thin wrappers of
nanterino/body/api.py (contract in its header): state, WebSocket stream, command, stop, estop / reset, sweep,
calibration get / put / set_min|set_max|set_zero / export / import, trace. Limits are enforced by Body.clamp for every
source. The dashboard's « Mécanique » screen script is served from web/dash/ (whitelist). Additive only.
Lot C2 (2026-11-04): the 360-degree sound tracker (nanterino/sound, cfg["sound_backend"], default mono = level only) is
built here on the brain's microphone with state/sound-calibration.json (front offset) and replaces brain.sound.
/api/sound/* routes are thin wrappers of nanterino/sound/api.py (contract in its header): state, WebSocket stream,
front offset, history, sim control (backend sim only), runtime backend switch (mono | sim only: they open no device).
The « Son 360° » screen script is web/dash/sound360.js. Additive only.
"""
import asyncio
import atexit
import ipaddress
import os
import re
import subprocess
import threading
import time

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response

from . import config
from .audio import AudioOut, SpeakerProfiles, find_device, list_devices
from .brain import JOURNAL_MAX, Brain, build_messages
from .corpus import Corpus
from . import graph as graph_mod
from . import graph_visual
from . import sim
from .engines import LLM, STT, TTS
from .log import log
from .metrics import Metrics
from .snapshot_jobs import SnapshotJobs, files_signature, snapshot_key
from .var_store import DEFAULT_PATH as VARS_STATE_PATH, VarStore
from . import body as body_mod
from .body import api as body_api
from .body.calibration import DEFAULT_PATH as BODY_CAL_PATH
from . import sound as sound_mod
from .sound import api as sound_api
from . import web_assets
from .vision import Vision

cfg = config.load()
WEB = os.path.join(config.ROOT, "web")
NETS = [ipaddress.ip_network(n) for n in cfg["allowed_nets"]]

tts = TTS(cfg["tts_voice"])
out = AudioOut(find_device(cfg["out_device"], "output"), rate=tts.rate, volume=cfg["volume"],
               keepalive_noise_db=cfg["keepalive_noise_db"])
out.start()
speakers = SpeakerProfiles(cfg, out, config.save_overrides)
out.muted = bool(cfg.get("muted", False))  # mute state is persisted like power
stt, llm, corpus, metrics = STT(cfg["stt_url"]), LLM(cfg["llm_url"], cfg.get("llm_options")), Corpus(cfg["fiches_dir"]), Metrics()
var_store = VarStore(VARS_STATE_PATH)   # lot L11: `persist: true` graph variables (written <= 1x / 2 s)
atexit.register(var_store.flush)        # a service stop keeps the last values
# lot C3: the live body (backend from cfg["body_backend"], sim by default) with the persisted calibration
body = body_mod.create(cfg, calibration_path=BODY_CAL_PATH)
brain = Brain(cfg, out, stt, llm, tts, corpus, var_store=var_store, body=body)
# lot N1: graph actions set_volume / set_mute / set_deaf act like the dashboard (speaker profile, persisted flags)
brain.volume_hook = lambda v: speakers.update(volume=v)
brain.flag_hook = lambda key, value: config.save_overrides({key: value})
# lot C2: the live 360-degree sound tracker on the brain's mic (mono by default: nothing is opened besides that mic)
sound = sound_mod.create(cfg, mic=brain.mic, calibration_path=sound_mod.DEFAULT_CAL_PATH, start=True)
brain.sound = sound
atexit.register(lambda: sound.source.stop())


def _llm_warmer():
    """Keep the LLM prompt prefix cached: warm at startup and again whenever llama-server comes
    back after a restart (its cache is empty then). Answers are unchanged; only latency drops."""
    was_ready = False
    while True:
        ready = llm.ready()
        if ready and not was_ready:
            try:
                ms = llm.warm(build_messages(cfg, [], [], "Bonjour"))
                log.info("llm warm done took_ms=%d", ms)
            except Exception as e:
                log.warning("llm warm failed (%s)", e)
                ready = False  # retry on the next check
        was_ready = ready
        time.sleep(30)


threading.Thread(target=_llm_warmer, name="llm-warmer", daemon=True).start()
vision = Vision(lost_face_s=cfg["lost_face_s"])
# F01 auto-greeting: a new face within 3 m wakes the robot (only from veille; ignored when off).
# The flag is read at each event so it can be toggled without restarting.
vision.on_face = lambda dist: cfg.get("auto_greet_on_face") and brain.post("visage")
# `visage_perdu` (no face for lost_face_s) is posted for graph authors; the default graph ignores it.
vision.on_face_lost = lambda: brain.post("visage_perdu")
vision.on_faces = brain.set_faces   # face count for the events personnes_multiples / inactivite_longue
app = FastAPI(title="Nanterino")


def _allowed(host: str | None) -> bool:
    try:
        return any(ipaddress.ip_address(host) in n for n in NETS)
    except (TypeError, ValueError):
        return False


@app.middleware("http")
async def guard(request: Request, call_next):
    if not _allowed(request.client.host if request.client else None):
        return PlainTextResponse("forbidden", status_code=403)
    return await call_next(request)


@app.get("/")
@app.get("/face")
def face():
    return FileResponse(os.path.join(WEB, "face.html"))


@app.get("/dash")
def dash():
    return FileResponse(os.path.join(WEB, "dash.html"))


@app.get("/api/status")
def status():
    return {**brain.snapshot(), "metrics": metrics.data, "engines": engines(),
            "volume": out.volume, "sheets": len(corpus.sheets), "notifications": brain.notifications_view(),
            "speaker": {"sink": speakers.current, **speakers.profile()}, "config": {
                k: cfg[k] for k in ("mic_device", "out_device", "barge_in", "spoken_sentences")}}


def engines() -> dict:
    return {"stt": stt.ready(), "llm": llm.ready(), "tts": True}


@app.get("/api/graph")
def graph():
    """The dialogue graph the robot runs (states, transitions, descriptions) + validation error if the
    override file was rejected."""
    return {**brain.engine.graph.to_dict(), "error": brain.graph_error}


@app.post("/api/graph/reload")
def graph_reload():
    """Re-read graph.yaml; refused (409) unless the robot is idle (veille/eteint)."""
    ok, err = brain.reload_graph()
    if not ok:
        return JSONResponse({"ok": False, "error": "robot busy: reload only in veille/eteint"}, status_code=409)
    return {"ok": err is None, "source": brain.engine.graph.source, "error": err}


# ---- visual graph editor (contract: Notes/graph-visual-format.md)
def _graph_paths() -> tuple[str, str]:
    gp = cfg["graph_file"]
    return gp, graph_visual.layout_path_for(gp)


_NO_CACHE = {"Cache-Control": "no-cache"}
_EDITOR_ASSETS = {"editor.css": "text/css"}   # M6: the editor script is the module tree below (/web/editor/...)
_VENDOR_ASSETS = {"drawflow.min.js": "text/javascript", "drawflow.min.css": "text/css", "LICENSE": "text/plain"}


_MODULES = web_assets.ModuleCache()


@app.get("/web/editor/{path:path}")
async def web_editor_module(path: str, request: Request):
    """Lot M6: the editor's native ES modules (web/editor/**/*.js|css), read-only. web_assets.editor_module refuses
    anything but lowercase module paths under web/editor/ (no `..`, no other extension, no symlink escape).
    async + in-memory bytes (re-read when size / mtime change): ~40 small files per page load, the threadpool hop of
    FileResponse made the split editor load slower than the single file."""
    hit = web_assets.editor_module(WEB, path)
    if hit is None:
        return PlainTextResponse("not found", status_code=404)
    body, etag = _MODULES.get(hit[0])
    # same no-cache policy as editor.css (a redeployed module is revalidated, never served stale); unchanged = 304
    headers = {**_NO_CACHE, "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(body, media_type=hit[1], headers=headers)


@app.get("/web/{name}")
def web_asset(name: str):
    """Editor page assets (whitelist: no directory listing, no other web file is exposed here)."""
    if name not in _EDITOR_ASSETS:
        return PlainTextResponse("not found", status_code=404)
    # no-cache: browsers must revalidate, otherwise an edited asset stays stale after a deploy.
    return FileResponse(os.path.join(WEB, name), media_type=_EDITOR_ASSETS[name], headers=_NO_CACHE)


@app.get("/web/vendor/drawflow/{name}")
def web_vendor(name: str):
    """Vendored Drawflow (MIT) files, served from disk so the editor works offline."""
    if name not in _VENDOR_ASSETS:
        return PlainTextResponse("not found", status_code=404)
    return FileResponse(os.path.join(WEB, "vendor", "drawflow", name), media_type=_VENDOR_ASSETS[name])


_ICON_NAME = re.compile(r"^[a-z0-9-]{1,40}\.svg$")


@app.get("/web/vendor/tabler/{name}")
def web_tabler(name: str):
    """Vendored Tabler icons (MIT): only `<lowercase-name>.svg` and LICENSE, read from web/vendor/tabler/."""
    if not (_ICON_NAME.match(name) or name == "LICENSE"):
        return PlainTextResponse("not found", status_code=404)
    path = os.path.join(WEB, "vendor", "tabler", name)
    if not os.path.isfile(path):
        return PlainTextResponse("not found", status_code=404)
    return FileResponse(path, media_type="text/plain" if name == "LICENSE" else "image/svg+xml")


@app.get("/editor")
def editor():
    path = os.path.join(WEB, "editor.html")
    if not os.path.exists(path):
        return PlainTextResponse("editor.html is not installed yet", status_code=404)
    with open(path, encoding="utf-8") as f:
        html = f.read()
    # lot M6: one modulepreload per module so the browser fetches the whole tree in one wave (no import waterfall)
    html = re.sub(r"<!-- m6-modulepreload:[^>]*-->", lambda _m: web_assets.modulepreload_links(WEB), html, count=1)
    return HTMLResponse(html, headers=_NO_CACHE)


@app.get("/api/graph/vocab")
def graph_vocab():
    """Palette of the visual editor: events, actions (with argument schema), guards, delays, states, intents."""
    return graph_mod.vocabulary(brain.cfg, brain.engine.graph)


@app.get("/api/graph/vars")
def graph_vars():
    """Live values of the graph variables (system ones included) and lists, for the editor and its Tester; `store`
    (lot L11) = persistence facts: enabled, persisted / saved names, ignored saved values, scope of each variable."""
    return {**brain.var_snapshot(), "store": brain.var_store_info()}


@app.post("/api/graph/vars/reset")
async def graph_vars_reset(body: dict):
    """Variable manager "Réinitialiser" (lot L11): initial value back + saved value forgotten. 404 = unknown or read-only."""
    name = body.get("name") if isinstance(body, dict) else None
    if not (isinstance(name, str) and name):
        return JSONResponse({"ok": False, "error": "`name` manquant."}, status_code=400)
    ok = await run_in_threadpool(brain.reset_var, name)
    if not ok:
        return JSONResponse({"ok": False, "error": "Variable inconnue ou en lecture seule : %s." % name}, status_code=404)
    return {"ok": True, "name": name, "vars": brain.var_snapshot()}


def _visual_doc(source: str = "saved") -> dict:
    """Node document as GET /api/graph/visual serves it. `saved` = the active graph (positions from graph.layout.json,
    else automatic); `default` (L14) = the packaged graph (graph_mod.DEFAULT_PATH) with its shipped / automatic layout,
    whatever override is active. Pure read: nothing is written or applied."""
    start = "eteint" if cfg.get("power") == "off" else "veille"
    if source == "default":
        raw = graph_visual.load_raw(graph_mod.DEFAULT_PATH)
        layout = graph_visual.load_layout(graph_visual.layout_path_for(graph_mod.DEFAULT_PATH))
        return {**graph_visual.to_visual(raw, layout, start), "error": None, "pending": False}
    raw = graph_visual.load_raw(brain.engine.graph.source)
    layout = graph_visual.load_layout(_graph_paths()[1])
    doc = graph_visual.to_visual(raw, layout, start)
    return {**doc, "error": brain.graph_error, "pending": brain.graph_pending}


@app.get("/api/graph/visual")
def graph_visual_get(source: str = "saved"):
    """Node document of the active graph (positions from graph.layout.json, else automatic);
    `?source=default` = the packaged default graph (L14, read-only)."""
    if source not in ("saved", "default"):
        return JSONResponse({"ok": False, "error": "source: saved | default"}, status_code=400)
    return _visual_doc(source)


@app.post("/api/graph/visual")
async def graph_visual_post(request: Request):
    """Compile + validate + back up + write the node document; apply now (idle) or at the next veille."""
    try:
        doc = await request.json()
    except ValueError:
        return JSONResponse({"ok": False, "errors": [{"node": None, "message": "JSON invalide."}]}, status_code=400)
    gp, lp = _graph_paths()
    report: dict = {}
    ok, errors = await run_in_threadpool(graph_visual.save, doc, brain.cfg, gp, lp, report)
    if not ok:
        return JSONResponse({"ok": False, "errors": errors, "warnings": report.get("warnings", [])}, status_code=400)
    applied = await run_in_threadpool(brain.request_graph_reload)
    return {"ok": True, "applied": applied, "warnings": report.get("warnings", []), "fans": report.get("fans", {}), "message": (
        "Graphe enregistré et appliqué." if applied else "Graphe enregistré : il sera appliqué à la prochaine veille.")}


@app.post("/api/graph/reset")
async def graph_reset():
    """Back up the override, delete it and run the packaged default graph again."""
    gp, lp = _graph_paths()
    await run_in_threadpool(graph_visual.reset, gp, lp)
    applied = await run_in_threadpool(brain.request_graph_reload)
    return {"ok": True, "applied": applied, "message": (
        "Graphe par défaut rétabli." if applied else "Graphe par défaut rétabli : appliqué à la prochaine veille.")}


@app.post("/api/graph/simulate")
async def graph_simulate(request: Request):
    """Editor "Tester" mode: compile the posted document (nothing written) and run it in an isolated simulated
    robot (nanterino/sim.py): no sound, no microphone, manual clock. The live brain is never touched."""
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "errors": [{"node": None, "message": "JSON invalide."}]}, status_code=400)
    report: dict = {}
    raw, _layout, errors = graph_visual.from_visual(body.get("doc"), brain.cfg, report)
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)
    ov = body.get("cfg") or {}
    if not isinstance(ov, dict):
        return JSONResponse({"ok": False, "errors": [{"node": None, "message": "`cfg` doit être un objet."}]}, status_code=400)
    try:
        result = await run_in_threadpool(sim.simulate, raw, brain.cfg, body.get("start_state") or "veille",
                                         body.get("steps") or [], body.get("start_time"), ov)
    except sim.SimError as e:
        return JSONResponse({"ok": False, "errors": e.errors}, status_code=400)
    except graph_mod.GraphError as e:
        return JSONResponse({"ok": False, "errors": [{"node": None, "message": str(e)}]}, status_code=400)
    return {"ok": True, **result, "warnings": report.get("warnings", [])}


@app.post("/api/graph/check")
async def graph_check(request: Request):
    """Dry-run compile of an editor document (nothing written, nothing applied): errors, warnings (e.g. several
    branches of one trigger that change the state) and, per trigger with several outgoing branches, the
    execution order the engine will use. The editor calls it while the user edits (lot L5: node badges). An error
    found by the YAML validator keeps `node` = its trigger and adds `at` = the faulty condition / action node."""
    try:
        doc = await request.json()
    except ValueError:
        return JSONResponse({"ok": False, "errors": [{"node": None, "message": "JSON invalide."}]}, status_code=400)
    report: dict = {}
    _raw, _layout, errors = await run_in_threadpool(graph_visual.from_visual, doc, brain.cfg, report)
    return {"ok": not errors, "errors": errors, "warnings": report.get("warnings", []), "fans": report.get("fans", {})}


@app.get("/api/graph/versions")
def graph_versions():
    """Backups of the active graph file (newest first) with a short summary each."""
    return {"versions": graph_visual.list_versions(_graph_paths()[0]), "max": graph_visual.KEEP_BACKUPS}


@app.post("/api/graph/versions/{vid}/restore")
async def graph_version_restore(vid: str):
    """Back up the current graph, then make backup `vid` active (now when idle, else at the next veille)."""
    gp, lp = _graph_paths()
    ok, status, msg = await run_in_threadpool(graph_visual.restore_version, vid, brain.cfg, gp, lp)
    if not ok:
        return JSONResponse({"ok": False, "errors": [{"node": None, "message": msg}]}, status_code=status)
    applied = await run_in_threadpool(brain.request_graph_reload)
    return {"ok": True, "applied": applied, "message": (
        "Version restaurée et appliquée." if applied else "Version restaurée : elle sera appliquée à la prochaine veille.")}


@app.get("/api/notifications")
def notifications():
    """Lot N1: pending dashboard notifications of the graph action notify_dashboard (oldest first)."""
    return {"notifications": brain.notifications_view()}


@app.post("/api/notifications/click")
async def notification_click(body: dict):
    """Lot N1: {"id": n} clicks a pending notification (it leaves the list, the graph gets notification_clicked)."""
    nid = body.get("id")
    if isinstance(nid, bool) or not isinstance(nid, int):
        return JSONResponse({"ok": False, "error": "id (entier) attendu"}, status_code=400)
    ok = brain.click_notification(nid)
    return JSONResponse({"ok": ok, "notifications": brain.notifications_view()}, status_code=200 if ok else 404)


@app.get("/api/graph/trace")
def graph_trace():
    """Live journal: the last chains that fired (oldest first)."""
    return {"trace": brain.trace(), "max": JOURNAL_MAX}


# ---- lot L14: full-resolution PNG export of the graph (editor button "Exporter l'image", tools/Get-GraphSnapshot.ps1)
SNAPSHOT_TOOL = os.path.join(config.ROOT, "tools", "graph_snapshot.py")
SNAPSHOT_DIR = os.path.join(config.ROOT, "exports", "graph-snapshots")   # gitignored cache (<key>.png + <key>.json)
SNAPSHOT_PYTHON = "/usr/bin/python3"       # system Python: the venv has no PIL
def _snapshot_code() -> list:
    """Files whose change invalidates cached snapshots: the editor page, its stylesheet, every module of the M6 tree
    (listed at call time, so an added module counts) and the capture tool."""
    return [os.path.join(WEB, n) for n in ("editor.html", "editor.css")] + web_assets.editor_module_files(WEB) + [SNAPSHOT_TOOL]
_SNAP_CROP = re.compile(r"^column=[A-Za-z0-9_-]{1,60}$")


def _snapshot_cmd(opts: dict, out_path: str) -> list:
    """Low priority (nice 19) capture of the local server; the tool drives its own geckodriver (port 4466)."""
    cmd = ["nice", "-n", "19", SNAPSHOT_PYTHON, SNAPSHOT_TOOL, "--out", out_path, "--scale", str(opts["scale"]),
           "--theme", opts["theme"], "--doc", opts["doc"], "--base", "http://127.0.0.1:%s" % cfg["http_port"]]
    if opts.get("crop"):
        cmd += ["--crop", opts["crop"]]
    return cmd


snapshots = SnapshotJobs(SNAPSHOT_DIR, _snapshot_cmd, timeout_s=360, keep=12)


def _snapshot_options(body) -> tuple[dict | None, str | None]:
    body = body if isinstance(body, dict) else {}
    try:
        scale = float(body.get("scale", 1.0))
    except (TypeError, ValueError):
        return None, "scale: nombre attendu."
    if not 0.1 <= scale <= 2.0:
        return None, "scale: entre 0.1 et 2."
    theme, doc, crop = body.get("theme", "dark"), body.get("doc", "saved"), body.get("crop") or None
    if theme not in ("dark", "light"):
        return None, "theme: dark | light."
    if doc not in ("saved", "default"):
        return None, "doc: saved | default."
    if crop is not None and not (isinstance(crop, str) and _SNAP_CROP.match(crop)):
        return None, "crop: column=<id>."
    return {"scale": round(scale, 3), "theme": theme, "doc": doc, "crop": crop}, None


def _snapshot_view(job: dict | None) -> dict:
    if not job:
        return {"ok": True, "job": None}
    j = dict(job)
    if job["state"] == "done":
        j["url"] = "/api/graph/snapshot.png?key=" + job["key"]
        j["filename"] = "nanterino-graph-%s.png" % (job.get("created") or time.strftime("%Y%m%d-%H%M"))
    return {"ok": True, "job": j}


@app.post("/api/graph/snapshot")
async def graph_snapshot_start(request: Request):
    """Start the PNG capture (single-flight: while one runs, its job is returned). Same document + options + code
    as a cached PNG = `done` at once with `cache_hit`. Body (all optional): {scale: 1 | 0.5, theme: dark | light,
    doc: saved | default, crop: "column=<state>"}. Never touches the robot (read-only capture of /editor)."""
    try:
        body = await request.json()
    except ValueError:
        body = {}
    opts, err = _snapshot_options(body)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)

    def start():
        key = snapshot_key(_visual_doc(opts["doc"]), opts, files_signature(_snapshot_code()))
        return snapshots.start(key, opts)
    return _snapshot_view(await run_in_threadpool(start))


@app.get("/api/graph/snapshot/status")
def graph_snapshot_status():
    """Current / last capture job: state running | done | failed, progress 0-1, seconds, size, url when done."""
    return _snapshot_view(snapshots.status())


@app.get("/api/graph/snapshot.png")
def graph_snapshot_png(key: str = ""):
    """The PNG of `key` (default: the last finished job) as an attachment nanterino-graph-YYYYMMDD-HHMM.png."""
    if not key:
        job = snapshots.status()
        key = job["key"] if job and job["state"] == "done" else ""
    if not re.fullmatch(r"[0-9a-f]{24}", key or ""):
        return JSONResponse({"ok": False, "error": "Aucune image prête."}, status_code=404)
    meta = snapshots.cached(key)
    if meta is None:
        return JSONResponse({"ok": False, "error": "Image inconnue ou effacée."}, status_code=404)
    name = "nanterino-graph-%s.png" % (meta.get("created") or "export")
    return FileResponse(snapshots.png_path(key), media_type="image/png", filename=name,
                        headers={"Cache-Control": "no-cache", "Content-Disposition": 'attachment; filename="%s"' % name})


# ---- lot C3: robot body (handlers in nanterino/body/api.py; Body.clamp enforces the limits for every source)
_DASH_ASSETS = {"mechanics.js": "text/javascript", "sound360.js": "text/javascript"}   # sound360: lot C2


@app.get("/web/dash/{name}")
def web_dash(name: str):
    """Dashboard scripts (whitelist): web/dash/mechanics.js is the « Mécanique » screen, sound360.js « Son 360° »."""
    if name not in _DASH_ASSETS:
        return PlainTextResponse("not found", status_code=404)
    return FileResponse(os.path.join(WEB, "dash", name), media_type=_DASH_ASSETS[name], headers=_NO_CACHE)


def _body_reply(result):
    status, payload = result
    return JSONResponse(payload, status_code=status)


async def _json_or_none(request: Request):
    try:
        return await request.json()
    except ValueError:
        return None


@app.get("/api/body/state")
def body_state():
    return _body_reply(body_api.state(body))


@app.post("/api/body/command")
async def body_command(request: Request):
    return _body_reply(body_api.command(body, await _json_or_none(request)))


@app.post("/api/body/stop")
def body_stop():
    return _body_reply(body_api.stop(body))


@app.post("/api/body/estop")
async def body_estop(request: Request):
    return _body_reply(body_api.estop(body, await _json_or_none(request)))


@app.post("/api/body/estop/reset")
def body_estop_reset():
    return _body_reply(body_api.estop_reset(body))


@app.post("/api/body/sweep")
async def body_sweep(request: Request):
    return _body_reply(body_api.sweep(body, await _json_or_none(request)))


@app.get("/api/body/calibration")
def body_calibration():
    return _body_reply(body_api.calibration_get(body))


@app.put("/api/body/calibration")
async def body_calibration_put(request: Request):
    payload = await _json_or_none(request)
    return _body_reply(await run_in_threadpool(body_api.calibration_put, body, payload))   # file write off the loop


@app.get("/api/body/calibration/export")
def body_calibration_export():
    status, doc = body_api.calibration_export(body)
    name = "nanterino-calibration-%s.json" % time.strftime("%Y%m%d-%H%M")
    return JSONResponse(doc, status_code=status, headers={"Content-Disposition": 'attachment; filename="%s"' % name})


@app.post("/api/body/calibration/import")
async def body_calibration_import(request: Request):
    payload = await _json_or_none(request)
    return _body_reply(await run_in_threadpool(body_api.calibration_import, body, payload))


@app.post("/api/body/calibration/{joint}/{action}")
async def body_calibration_set(joint: str, action: str):
    return _body_reply(await run_in_threadpool(body_api.calibration_set, body, joint, action))


@app.get("/api/body/trace")
def body_trace(seconds: str = "10"):
    return _body_reply(body_api.trace(body, seconds))


@app.websocket("/api/body/stream")
async def body_stream(socket: WebSocket):
    """Body.state() pushed at ?hz= (1..20, default 15) for the « Mécanique » screen."""
    if not _allowed(socket.client.host if socket.client else None):
        await socket.close(code=1008)
        return
    await socket.accept()
    period = 1.0 / body_api.stream_hz(socket.query_params.get("hz"))
    try:
        while True:
            await socket.send_json(body.state())
            await asyncio.sleep(period)
    except Exception:
        pass


# ---- lot C2: 360-degree sound (handlers in nanterino/sound/api.py)
@app.get("/api/sound/state")
def sound_state():
    return _body_reply(sound_api.state(sound))


@app.post("/api/sound/front")
async def sound_front(request: Request):
    payload = await _json_or_none(request)
    return _body_reply(await run_in_threadpool(sound_api.front, sound, payload))   # file write off the loop


@app.get("/api/sound/history")
def sound_history(seconds: str = "10"):
    return _body_reply(sound_api.history(sound, seconds))


@app.post("/api/sound/sim")
async def sound_sim(request: Request):
    return _body_reply(sound_api.sim(sound, await _json_or_none(request)))


@app.post("/api/sound/backend")
async def sound_backend(request: Request):
    payload = await _json_or_none(request)
    return _body_reply(sound_api.backend(sound, payload, lambda n: sound_mod.make_source(n, cfg, brain.mic),
                                         sound_mod.RUNTIME_BACKENDS))


@app.websocket("/api/sound/stream")
async def sound_stream(socket: WebSocket):
    """sound_api.stream_frame() pushed at ?hz= (1..20, default 15) for the « Son 360° » screen."""
    if not _allowed(socket.client.host if socket.client else None):
        await socket.close(code=1008)
        return
    await socket.accept()
    period = 1.0 / sound_api.stream_hz(socket.query_params.get("hz"))
    try:
        while True:
            await socket.send_json(sound_api.stream_frame(sound))
            await asyncio.sleep(period)
    except Exception:
        pass


@app.get("/api/live")
def live():
    """Cheap 10 Hz snapshot for the native UI (no engine health probes)."""
    return {**brain.snapshot(), "face": vision.state, "gaze": cfg["gaze"], "face_scale": cfg["face_scale"]}


@app.get("/api/devices")
def devices():
    return list_devices()


@app.get("/api/errors")
def errors(lines: int = 30):
    r = subprocess.run(["tail", "-n", str(lines), "/var/log/robot/errors.log"], capture_output=True, text=True)
    return PlainTextResponse(r.stdout)


@app.get("/api/monitor")
def monitor(after: int = 0):
    """Ids of clips spoken after `after` (the dashboard polls this when PC listening is on)."""
    return [cid for cid, _ in list(out.monitor) if cid > after]


@app.get("/api/monitor/{cid}.wav")
def monitor_clip(cid: int):
    for i, wav in list(out.monitor):
        if i == cid:
            return Response(wav, media_type="audio/wav")
    return PlainTextResponse("gone", status_code=404)


@app.post("/api/control")
async def control(body: dict):
    action = body.get("action")
    log.info("ui action=%s", action)  # the action name only, never typed text
    if action in ("start", "stop", "hush", "off", "on"):
        brain.post(action, source="ui")
        if action in ("off", "on", "start"):
            config.save_overrides({"power": "off" if action == "off" else "on"})
    elif action == "mute":  # value true/false; default toggles
        v = body.get("value")
        brain.set_muted((not out.muted) if v is None else bool(v), external=True)   # lot N1: posts mute_changed
        config.save_overrides({"muted": out.muted})  # survives restarts (user: "laisse en muet")
        if out.muted:
            out.stop()
    elif action == "ask" and body.get("text"):
        brain.post("ask", text=body["text"])
    elif action == "say" and body.get("text"):
        # TTS synthesis takes hundreds of ms: run it off the event loop so /api/live (10 Hz) and the
        # websocket keep answering. TTS.synth() holds its own lock, so concurrent calls stay safe.
        wav = await run_in_threadpool(tts.synth, body["text"])
        out.play(wav, tts.rate)
    elif action == "volume":  # stored in the current speaker's profile
        brain.set_volume(max(0.0, min(1.0, float(body.get("value", 0.8)))), external=True)   # lot N1: volume_hook + volume_changed
    elif action == "keepalive_db":  # "off" = pure digital silence
        v = body.get("value")
        speakers.update(keepalive_noise_db=None if v in (None, "", "off") else float(v))
    elif action == "test_tone":  # used by speaker-calibrate; same path as speech
        import numpy as np
        t = np.arange(int(tts.rate * 0.4)) / tts.rate
        tone = (0.5 * np.sin(2 * np.pi * 1000 * t) * 32767).astype(np.int16)
        tone[:110] = (tone[:110] * np.linspace(0, 1, 110)).astype(np.int16)
        out.play(tone, tts.rate)
    elif action == "preroll":  # {"ms": 300, "db": -45}
        speakers.update(preroll_ms=int(body.get("ms", 300)), preroll_db=float(body.get("db", -45)))
    elif action == "deaf":  # value true/false; default toggles. Persisted like mute.
        v = body.get("value")
        brain.set_deaf((not brain.deaf) if v is None else bool(v))
        config.save_overrides({"deaf": brain.deaf})
    elif action == "auto_greet":  # value true/false
        cfg["auto_greet_on_face"] = bool(body.get("value", True))
        config.save_overrides({"auto_greet_on_face": cfg["auto_greet_on_face"]})
    elif action == "gaze":  # {"offset_x":..,"offset_y":..,"gain_x":..,"gain_y":..}, any subset
        g = dict(cfg["gaze"])
        for k in ("offset_x", "offset_y", "gain_x", "gain_y"):
            if k in body:
                lo, hi = (-1.0, 1.0) if k.startswith("offset") else (0.0, 3.0)
                g[k] = max(lo, min(hi, float(body[k])))
        cfg["gaze"] = g
        if body.get("save", True):  # the UI sends save=false while a slider is dragged (live preview)
            config.save_overrides({"gaze": g})
    elif action == "face_scale":  # {"value": 0.5..1.6}
        cfg["face_scale"] = max(0.5, min(1.6, float(body.get("value", 1.0))))
        if body.get("save", True):
            config.save_overrides({"face_scale": cfg["face_scale"]})
    elif action == "sing":  # the Nanterino song (media/chanson-nanterino.wav)
        brain.post("sing")
    elif action == "reload_corpus":
        corpus.reload()
    elif action in ("mic_device", "out_device"):
        config.save_overrides({action: body.get("value") or None})
        return JSONResponse({"ok": True, "note": "redémarrage du service requis"})
    else:
        return JSONResponse({"ok": False, "error": "unknown action"}, status_code=400)
    return {"ok": True}


@app.websocket("/ws")
async def ws(socket: WebSocket):
    if not _allowed(socket.client.host if socket.client else None):
        await socket.close(code=1008)
        return
    await socket.accept()
    try:
        while True:  # 10 Hz is enough for the mouth animation and meters
            await socket.send_json(brain.snapshot())
            await asyncio.sleep(0.1)
    except Exception:
        pass


if __name__ == "__main__":
    log.info("nanterino core starting port=%s", cfg["http_port"])
    uvicorn.run(app, host="0.0.0.0", port=cfg["http_port"], log_level="warning")
