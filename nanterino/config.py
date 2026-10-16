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
    # F01: a face within 3 m starts the greeting automatically (off while developing).
    "auto_greet_on_face": False,
    # Dialogue timings (seconds) from §2 and D10.
    "silence_relance_s": 8,
    "silence_cloture_s": 15,
    "cloture_to_veille_s": 2,
    "lost_face_s": 10,
    "vad_silence_ms": 800,
    "max_utterance_s": 10,
    # Microphone pinned by PipeWire description (2026-10-16: the default source had silently
    # become the Jetson's built-in input, where nothing is plugged -> the robot heard nothing).
    "mic_source_match": "Trust GXT",
    # Vocabulary hint for Whisper (names/places it otherwise mishears).
    "stt_prompt": "Nanterino, Nanterre, mairie, parc, point de collecte, déchetterie, lieu à visiter, horaires, musée, bibliothèque.",
    # Said when someone clearly spoke but nothing usable was transcribed (max 2 in a row).
    "repair_text": "Pardon, je n'ai pas bien entendu. Pouvez-vous répéter, un peu plus fort ?",
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
    # Why (2026-10-16): with the old text the model replied "je ne peux pas entendre" (it thought
    # it was a text chatbot). The robot really hears (microphone + speech recognition) and speaks;
    # the user wants it to keep the visitor engaged even when it does not know the answer.
    # Example exchanges placed before the conversation (small models copy their tone/behaviour).
    "few_shot": [
        {"role": "user", "content": "Tu m'entends ?"},
        {"role": "assistant", "content": "Oui, je vous entends très bien ! Que puis-je faire pour vous ?"},
        {"role": "user", "content": "Bonjour, ça va ?"},
        {"role": "assistant", "content": "Très bien, merci ! Vous cherchez un parc, un point de collecte ou un lieu à visiter ?"},
    ],
    "few_shot_no_sheet": [
        {"role": "user", "content": "Il y a un parc près d'ici ?"},
        {"role": "assistant", "content": "Je n'ai pas encore cette information, désolé. Quel genre de parc cherchez-vous, pour jouer ou pour vous promener ?"},
    ],
    "system_prompt": (
        "Tu es Nanterino, un petit robot d'accueil de la ville de Nanterre, physiquement présent "
        "devant le visiteur. Tu l'entends grâce à ton micro et tu lui parles avec ta voix : "
        "ne dis jamais que tu ne peux pas entendre, voir ou parler, ni que tu es une IA textuelle. "
        "Ce que dit le visiteur vient d'une reconnaissance vocale qui peut contenir des erreurs : "
        "devine le sens le plus probable ; si c'est vraiment incompréhensible, demande gentiment "
        "de reformuler. Vouvoie le visiteur. Réponds en français, de façon chaleureuse et naturelle, en deux phrases "
        "courtes maximum, sans listes ni emojis. Aux salutations ou à la conversation, réponds "
        "simplement puis propose ton aide sur les parcs, les points de collecte ou les lieux à "
        "visiter de Nanterre. Pour les faits, utilise uniquement les fiches fournies ; si la réponse "
        "n'y est pas, dis-le simplement et pose une question pour rester sur le sujet du visiteur. "
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
