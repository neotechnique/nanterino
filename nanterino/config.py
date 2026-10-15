"""Runtime configuration: defaults below, overridden by /opt/robot/nanterino/config.json.

logging: robotlog via nanterino.log. Timings come from the cahier des charges §2 / D10.
"""
import json
import os

ROOT = "/opt/robot/nanterino"

DEFAULTS = {
    # Engine endpoints (local services, never Internet).
    "stt_url": "http://127.0.0.1:8178/inference",
    "llm_url": "http://127.0.0.1:8179/v1/chat/completions",
    "tts_voice": f"{ROOT}/models/piper/fr_FR-siwis-medium.onnx",
    "fiches_dir": f"{ROOT}/fiches",
    # Audio devices, matched as substrings of PortAudio names. "pipewire" routes through PipeWire,
    # whose default sink/source are chosen with wpctl (PortAudio's own default is the first raw ALSA
    # card, which bypasses PipeWire and grabbed the Trust mic's headphone jack on 2026-10-15).
    "mic_device": "pipewire",
    "out_device": "pipewire",
    "volume": 0.8,
    # Default keep-alive for an uncalibrated speaker: inaudible noise. Many USB amps (e.g. Jieli
    # UACDemo, 2026-10-15) mute on digital silence and clip the first syllable. None = pure silence.
    "keepalive_noise_db": -70,
    # Wake-up pre-roll before speech after silence (ms of rising noise, peak level in dBFS).
    "preroll_ms": 300,
    "preroll_db": -45,
    # Per-speaker overrides keyed by PipeWire node.name (written by the dashboard / calibration).
    "speaker_profiles": {},
    # "off" = Éteint (mic closed, silent) and kept off across restarts; set from the UI.
    "power": "on",
    # Dialogue timings (seconds) from §2 and D10.
    "silence_relance_s": 8,
    "silence_cloture_s": 15,
    "cloture_to_veille_s": 2,
    "lost_face_s": 10,
    "vad_silence_ms": 800,
    "max_utterance_s": 10,
    "spoken_sentences": 2,
    "history_turns": 6,
    # Barge-in needs echo cancellation (speakerphone); off with a plain speaker.
    "barge_in": False,
    # HTTP UI: only these client networks may connect (localhost, Tailscale, USB-C link).
    "http_port": 8080,
    "allowed_nets": ["127.0.0.0/8", "100.64.0.0/10", "192.168.55.0/24"],
    "greeting": "Bonjour, je suis Nanterino. Je connais les parcs et les lieux écologiques de Nanterre. Que cherchez-vous ?",
    "relance": "Voulez-vous un parc, un point de collecte ou un lieu à visiter ?",
    "goodbye": "Bonne journée !",
    "refusal_words": ["non merci", "stop", "au revoir", "arrête", "arrete"],
    "system_prompt": (
        "Tu es Nanterino, robot d'accueil de la ville de Nanterre. Tu réponds en français, "
        "en deux phrases maximum, uniquement à partir des fiches fournies. Si la réponse "
        "n'y est pas, dis que tu ne sais pas et propose un lieu proche du sujet. "
        "N'invente jamais de lieu, d'adresse ni d'horaire."
    ),
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    path = os.path.join(ROOT, "config.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def save_overrides(changes: dict) -> None:
    """Persist UI changes (devices, volume) without rewriting defaults."""
    path = os.path.join(ROOT, "config.json")
    current = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            current = json.load(f)
    current.update(changes)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
