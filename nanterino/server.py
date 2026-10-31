"""Nanterino core service: engines + brain + web UI (face for the HDMI screen, dashboard for the PC).

logging: robotlog via nanterino.log. Run: python -m nanterino.server (systemd user service).
Access control: only localhost, Tailscale (100.64/10) and the USB-C link may connect; the robot
is not exposed to the venue Wi-Fi.
"""
import asyncio
import ipaddress
import os
import re
import subprocess
import threading
import time

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

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
brain = Brain(cfg, out, stt, llm, tts, corpus)


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
            "volume": out.volume, "sheets": len(corpus.sheets),
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
_EDITOR_ASSETS = {"editor.js": "text/javascript", "editor.css": "text/css"}
_VENDOR_ASSETS = {"drawflow.min.js": "text/javascript", "drawflow.min.css": "text/css", "LICENSE": "text/plain"}


@app.get("/web/{name}")
def web_asset(name: str):
    """Editor page assets (whitelist: no directory listing, no other web file is exposed here)."""
    if name not in _EDITOR_ASSETS:
        return PlainTextResponse("not found", status_code=404)
    # no-cache: browsers must revalidate, otherwise an edited editor.js stays stale after a deploy.
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
    return FileResponse(path, headers=_NO_CACHE)


@app.get("/api/graph/vocab")
def graph_vocab():
    """Palette of the visual editor: events, actions (with argument schema), guards, delays, states, intents."""
    return graph_mod.vocabulary(brain.cfg, brain.engine.graph)


@app.get("/api/graph/visual")
def graph_visual_get():
    """Node document of the active graph (positions from graph.layout.json, else automatic)."""
    raw = graph_visual.load_raw(brain.engine.graph.source)
    layout = graph_visual.load_layout(_graph_paths()[1])
    doc = graph_visual.to_visual(raw, layout, "eteint" if cfg.get("power") == "off" else "veille")
    return {**doc, "error": brain.graph_error, "pending": brain.graph_pending}


@app.post("/api/graph/visual")
async def graph_visual_post(request: Request):
    """Compile + validate + back up + write the node document; apply now (idle) or at the next veille."""
    try:
        doc = await request.json()
    except ValueError:
        return JSONResponse({"ok": False, "errors": [{"node": None, "message": "JSON invalide."}]}, status_code=400)
    gp, lp = _graph_paths()
    ok, errors = await run_in_threadpool(graph_visual.save, doc, brain.cfg, gp, lp)
    if not ok:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)
    applied = await run_in_threadpool(brain.request_graph_reload)
    return {"ok": True, "applied": applied, "message": (
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
    raw, _layout, errors = graph_visual.from_visual(body.get("doc"), brain.cfg)
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
    return {"ok": True, **result}


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


@app.get("/api/graph/trace")
def graph_trace():
    """Live journal: the last chains that fired (oldest first)."""
    return {"trace": brain.trace(), "max": JOURNAL_MAX}


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
        out.muted = (not out.muted) if v is None else bool(v)
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
        speakers.update(volume=max(0.0, min(1.0, float(body.get("value", 0.8)))))
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
