"""Nanterino core service: engines + brain + web UI (face for the HDMI screen, dashboard for the PC).

logging: robotlog via nanterino.log. Run: python -m nanterino.server (systemd user service).
Access control: only localhost, Tailscale (100.64/10) and the USB-C link may connect; the robot
is not exposed to the venue Wi-Fi.
"""
import asyncio
import ipaddress
import os
import subprocess

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

from . import config
from .audio import AudioOut, SpeakerProfiles, find_device, list_devices
from .brain import Brain
from .corpus import Corpus
from .engines import LLM, STT, TTS
from .log import log
from .metrics import Metrics

cfg = config.load()
WEB = os.path.join(config.ROOT, "web")
NETS = [ipaddress.ip_network(n) for n in cfg["allowed_nets"]]

tts = TTS(cfg["tts_voice"])
out = AudioOut(find_device(cfg["out_device"], "output"), rate=tts.rate, volume=cfg["volume"],
               keepalive_noise_db=cfg["keepalive_noise_db"])
out.start()
speakers = SpeakerProfiles(cfg, out, config.save_overrides)
stt, llm, corpus, metrics = STT(cfg["stt_url"]), LLM(cfg["llm_url"]), Corpus(cfg["fiches_dir"]), Metrics()
brain = Brain(cfg, out, stt, llm, tts, corpus)
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


@app.get("/api/live")
def live():
    """Cheap 10 Hz snapshot for the native UI (no engine health probes)."""
    return brain.snapshot()


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
    if action in ("start", "stop"):
        brain.post(action, source="ui")
    elif action == "ask" and body.get("text"):
        brain.post("ask", text=body["text"])
    elif action == "say" and body.get("text"):
        out.play(tts.synth(body["text"]), tts.rate)
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
