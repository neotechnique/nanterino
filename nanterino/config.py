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
    # Extra fields of every LLM request. LFM3-1.7B (Liquid AI, 2026-10-29): vendor sampling
    # temp 0.1 / top_k 50 / repeat 1.1, reasoning off. Qwen2.5 used {"temperature": 0.3}.
    # Prompt shape, measured 2026-10-29 on the 20-question bench (scripts/llm-bench.py, LFM3):
    # sheets after the cached system prompt + examples, and sheets scoring < 50 % of the best match
    # dropped (2.55 -> 2.05 sheets): first sentence 1.77 s -> 1.39 s, answers unchanged or better.
    "prompt_layout": "sheets_last",
    "corpus_k": 3,
    "corpus_rel_min": 0.5,
    "llm_options": {"temperature": 0.1, "top_k": 50, "repeat_penalty": 1.1,
                    "chat_template_kwargs": {"enable_thinking": False}},
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
    # Pupil = clamp(-x * gain_x + offset_x, y * gain_y + offset_y), x/y = face position in the
    # camera image (-1..1). Offsets compensate the camera mounted above the eye screen.
    # Face size multiplier (0.5-1.6), set from the dashboard slider "Taille du visage".
    "face_scale": 1.0,
    "gaze": {"offset_x": 0.0, "offset_y": 0.0, "gain_x": 1.6, "gain_y": 1.4},
    # Dialogue timings (seconds) from §2 and D10.
    "silence_relance_s": 8,
    "silence_cloture_s": 15,
    "cloture_to_veille_s": 2,
    "lost_face_s": 10,  # no face for this long -> vision posts `visage_perdu` (only a disabled example chain uses it)
    # Opening hours for the guard `dans_les_horaires` and the events ouverture/fermeture, e.g.
    # {"lun-ven": "09:00-18:00", "sam": ["10:00-12:00", "14:00-17:00"]}. Empty = always open, no events.
    "opening_hours": {},
    # No face and no speech for this long -> the event `inactivite_longue` is posted once (until activity).
    "idle_long_s": 300,
    # Heartbeat: the brain loop ticks at this rate (delays are accurate to one tick); the watchdog
    # trips when no tick was processed for watchdog_s seconds (stuck handler). See nanterino/graph.py.
    "heartbeat_hz": 10,
    "watchdog_s": 5,
    # Robot body backend (lot C3): sim (kinematic simulator, default until the hardware is chosen) | mujoco (lot B3)
    # | real (servos, plan B4). An unavailable backend falls back to sim with a dashboard banner (nanterino/body).
    "body_backend": "sim",
    # 360-degree sound (lot C2, nanterino/sound): mono (default: today's single USB mic, level only, NO direction) | sim
    # (virtual sources) | array (N-mic array, geometry in sound_array_geometry) | vendor (array that reports its own
    # direction, sound_vendor_model; not written yet). An unavailable backend falls back to mono (dashboard message).
    "sound_backend": "mono",
    "sound_array_geometry": f"{ROOT}/nanterino/sound/array.yaml",
    "sound_vendor_model": None,
    "sound_min_level_db": -50,
    # Optional dialogue graph override (YAML, French); invalid -> logged, default graph.yaml used.
    "graph_file": f"{ROOT}/graph.yaml",
    "vad_silence_ms": 800,
    # Early transcription after this much silence (0 = off); the utterance still ends at
    # vad_silence_ms, the text is just ready sooner (AudioIn.early_ms).
    "stt_early_ms": 390,
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
    "greeting": "Bonjour, je suis Nanterino. Je connais les lieux de Nanterre et les bons gestes pour la planète. Que cherchez-vous ?",
    "relance": "Voulez-vous un parc, un lieu à visiter, ou un conseil pour trier vos déchets ?",
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
        "simplement puis propose ton aide sur les parcs, les lieux remarquables de Nanterre ou "
        "les bons gestes écologiques (tri, compost, économies d'eau et d'énergie). Pour les faits, utilise uniquement les fiches fournies ; si la réponse "
        "n'y est pas, dis-le simplement et pose une question pour rester sur le sujet du visiteur. "
        "N'invente jamais de lieu, d'adresse, d'horaire ni de ligne de bus."
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
