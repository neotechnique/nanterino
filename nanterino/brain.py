"""Dialogue orchestrator: the 6-state machine of the cahier des charges §2 + voice pipeline.

logging: robotlog via nanterino.log. Only states, transitions and latencies are logged.
Conversation history lives in RAM and is wiped at every Clôture (no memory between people).

States: veille -> accueil -> ecoute <-> reponse ; ecoute -> relance -> (ecoute | cloture) -> veille,
plus "eteint" (OFF): mic closed, no listening, no speech, until "start"/"on".
Exits from veille: UI "start" (button / face tap), the word "Nanterino" heard while in veille
(STT-based stand-in until the openWakeWord model of step 9), or `visage` events (step 6).

Cancellation (fix 2026-10-15): every speaking/answering thread carries the generation number it
was started with. stop/off/hush/barge-in bump the generation, so an old thread can never speak
again or post a late "done" event. (The previous set()+clear() of a shared Event was so fast that
running answers missed it and kept talking after "Stop".)
"""
import re
import numpy as np
import os
import collections
import queue
import threading
import time

from .audio import AudioIn, find_device
from .log import log

VEILLE, ACCUEIL, ECOUTE, REPONSE, RELANCE, CLOTURE, ETEINT = (
    "veille", "accueil", "ecoute", "reponse", "relance", "cloture", "eteint")

# Typical Whisper hallucinations on noise/silence (French YouTube-subtitle artefacts).
PHANTOMS = ("sous-titres", "sous titres", "merci d'avoir regardé", "abonnez-vous", "amara.org",
            "merci de votre attention", "♪", "[musique]", "(musique)")
MAX_TURNS = 12  # safety net: a conversation never loops forever


# Single words Whisper typically invents on breath/noise; other single words are real answers
# ("Parc ?", "Musée", "Horaires") and are now accepted (2026-10-16, user: interact better).
SINGLE_NOISE = {"merci", "bon", "ah", "oh", "euh", "hum", "hein", "voilà", "bah", "ok"}


def is_phantom(text: str, keep_words=()) -> bool:
    low = text.lower().strip(" .!?…,")
    if any(p in low for p in PHANTOMS) or not any(c.isalpha() for c in low):
        return True
    words = low.split()
    if len(words) < 2 and low not in keep_words and (len(low) < 3 or low in SINGLE_NOISE):
        return True
    return False


# Last-resort filter: a speaking robot must never claim it cannot hear/speak or is a text AI.
_DENIALS = re.compile(r"(ne (peux|puis) pas (vous |t')?(entendre|écouter|parler|voir)|ne (vous|t') ?entends pas|"
                      r"ia textuelle|modèle de langage|intelligence artificielle textuelle|assistant virtuel textuel)",
                      re.IGNORECASE)


_DEAD_END = re.compile(r"ne (peux|puis) pas (vous |t')?aider", re.IGNORECASE)


def fix_sentence(sentence: str) -> str:
    # LFM3 sometimes adds Markdown bold (**word**): strip it so the subtitles and the voice stay clean.
    sentence = sentence.replace("**", "").replace("__", "")
    if _DENIALS.search(sentence):
        log.info("answer sentence replaced reason=denial")
        return "Oui, je vous entends très bien."
    if _DEAD_END.search(sentence):  # curt refusal ends the exchange: keep the visitor talking instead
        log.info("answer sentence replaced reason=dead_end")
        return "Je n'ai pas encore cette information. Dites-moi ce que vous cherchez exactement, je vais essayer de vous orienter."
    return sentence


NO_SHEET = ("AUCUNE FICHE PERTINENTE : tu ne connais pas la réponse. Ne donne aucun lieu ni chemin ; dis que tu "
            "n'as pas encore cette information et demande ce que le visiteur cherche exactement.")


def build_messages(cfg: dict, sheets: list[dict], history: list[dict], question: str) -> list[dict]:
    """Chat messages for one answer (shared with /opt/robot/scripts/llm-bench.py).

    "sheets_last" layout keeps the system prompt and examples identical between questions, so
    llama-server can reuse that prefix from its cache, and puts the sheets just before the question.
    """
    context = "\n\n---\n\n".join(s["text"] for s in sheets) or NO_SHEET
    # No sheet found: show the model how to say "I do not know" without inventing.
    examples = list(cfg.get("few_shot", [])) + ([] if sheets else list(cfg.get("few_shot_no_sheet", [])))
    if cfg.get("prompt_layout") == "sheets_last":
        return ([{"role": "system", "content": cfg["system_prompt"]}] + examples + history
                + [{"role": "user", "content": f"Fiches :\n{context}\n\nQuestion du visiteur : {question}"}])
    return ([{"role": "system", "content": f"{cfg['system_prompt']}\n\nFiches :\n{context}"}]
            + examples + history + [{"role": "user", "content": question}])


class Brain:
    def __init__(self, cfg, out, stt, llm, tts, corpus):
        self.cfg, self.out, self.stt, self.llm, self.tts, self.corpus = cfg, out, stt, llm, tts, corpus
        self.state, self.since = VEILLE, time.monotonic()
        self.subtitle, self.last_speech = "", time.monotonic()
        self.history: list[dict] = []
        self.latencies = collections.deque(maxlen=20)  # ms, end of user speech -> first sound
        self.events: queue.Queue = queue.Queue()
        self.gen = 0        # bumped on every cancellation; threads compare with their own copy
        self._busy = False  # an utterance is being transcribed
        self.turns = 0      # exchanges in the current conversation (MAX_TURNS guard)
        self.deaf = bool(cfg.get("deaf", False))  # "Sourd": microphone forced off (tests), persisted
        self.repairs = 0           # consecutive "pardon ?" (max 2, then the normal timers act)
        self._relance_text = None  # one-shot text for the next RELANCE (used by the repair)
        self.stt.prompt = cfg.get("stt_prompt", "")
        self.mic = AudioIn(self._on_utterance, self._on_speech_start,
                           device=find_device(cfg["mic_device"], "input"),
                           silence_ms=cfg["vad_silence_ms"], max_s=cfg["max_utterance_s"],
                           source_match=cfg.get("mic_source_match", ""),
                           early_ms=cfg.get("stt_early_ms", 0), speculate=self.stt.transcribe)
        # Fixed phrases (greeting, relance, goodbye, repair) are synthesized once and replayed:
        # identical samples, no TTS wait before the robot starts talking.
        self._phrases: dict[str, np.ndarray] = {}
        threading.Thread(target=self._cache_phrases, daemon=True, name="phrase-cache").start()
        threading.Thread(target=self._loop, daemon=True, name="brain").start()

    # ------------------------------------------------------------------ public API (UI / sensors)
    def post(self, kind: str, **kw):
        self.events.put((kind, kw))

    def snapshot(self) -> dict:
        return {"state": self.state, "subtitle": self.subtitle, "mic_on": self.mic.active,
                "mic_level": round(self.mic.level, 3), "out_level": round(self.out.level, 3),
                "speaking": self.out.busy, "muted": self.out.muted, "deaf": self.deaf, "latencies_ms": list(self.latencies)}

    def set_deaf(self, deaf: bool):
        self.deaf = deaf
        if deaf:
            self.mic.stop()
        elif self.state in (VEILLE, ECOUTE) or (self.state == RELANCE and not self.out.busy):
            self.mic.start()
        log.info("deaf=%s", deaf)

    def _mic_on(self):
        """Every mic opening goes through here so the deaf mode can never be bypassed."""
        if not self.deaf:
            self.mic.start()

    # ------------------------------------------------------------------ cancellation
    def _cancel_all(self):
        """Silence now and invalidate every running speak/answer thread."""
        self.gen += 1
        self.out.stop()

    def _alive(self, gen: int) -> bool:
        return gen == self.gen

    # ------------------------------------------------------------------ audio callbacks
    def _on_speech_start(self):
        self.last_speech = time.monotonic()
        if self.state == REPONSE and self.cfg["barge_in"]:
            self.post("barge_in")

    def _on_utterance(self, pcm, t_end, text=None):
        """`text` is the early transcription of exactly `pcm` when AudioIn already made it."""
        if self._busy or self.state == ETEINT:
            return
        self._busy = True
        try:
            if text is None:
                text = self.stt.transcribe(pcm)
        except Exception:
            log.exception("stt failed")
            text = ""
        finally:
            self._busy = False
        self.last_speech = time.monotonic()
        if not text or is_phantom(text, keep_words=set(self.cfg["refusal_words"]) | {"nanterino", "oui", "non"}):
            log.info("utterance rejected reason=%s words=%d", "phantom" if text else "empty", len(text.split()))  # never the text itself
            # Loud enough to be someone talking, but nothing usable: ask to repeat instead of
            # staying silent (silence felt like "the robot does not understand").
            self.post("not_understood")
            return
        self.post("utterance", text=text, t_end=t_end)

    # ------------------------------------------------------------------ state machine
    def _go(self, state: str, reason: str):
        log.info("transition %s -> %s reason=%s", self.state, state, reason)
        self.state, self.since = state, time.monotonic()
        self._enter(state)

    def _enter(self, state: str):
        cfg = self.cfg
        if state == VEILLE:
            self.history.clear(); self.turns = 0; self.subtitle = ""; self.repairs = 0
            self._mic_on()  # listens only for the call word while idle
        elif state == ETEINT:
            self.history.clear(); self.turns = 0; self.subtitle = ""
            self.mic.stop()   # really off: nothing captured, nothing said
        elif state == ACCUEIL:
            self.mic.stop()
            self._speak_then(cfg["greeting"], "greeting_done")
        elif state == ECOUTE:
            self.subtitle = "Je vous écoute"
            self.last_speech = time.monotonic()
            self._mic_on()
        elif state == RELANCE:
            self.mic.stop()
            text, self._relance_text = self._relance_text or cfg["relance"], None
            self._speak_then(text, "relance_done")
        elif state == CLOTURE:
            self.mic.stop()
            self.history.clear()
            self._speak_then(cfg["goodbye"], "goodbye_done")

    def _speak_then(self, text: str, done_event: str):
        self.subtitle = text
        gen = self.gen

        def run():
            try:
                pcm = self._phrases.get(text)
                if pcm is None:
                    pcm = self.tts.synth(text)
                if self._alive(gen):
                    self.out.play(pcm, self.tts.rate)
                    self._wait_audio(gen)
            except Exception:
                log.exception("speak failed")
            if self._alive(gen):  # a cancelled thread never moves the state machine
                self.post(done_event, gen=gen)
        threading.Thread(target=run, daemon=True).start()

    def _cache_phrases(self):
        for key in ("greeting", "relance", "goodbye", "repair_text"):
            text = self.cfg.get(key)
            if text and text not in self._phrases:
                try:
                    self._phrases[text] = self.tts.synth(text)
                except Exception:
                    log.exception("phrase cache failed key=%s", key)
        log.info("phrase cache ready n=%d", len(self._phrases))

    def _wait_audio(self, gen: int):
        time.sleep(0.15)
        while self.out.busy and self._alive(gen):
            time.sleep(0.05)

    def _loop(self):
        # Power state survives restarts: an "off" robot stays off after a reboot (user request).
        if self.cfg.get("power") == "off":
            self.state = ETEINT
        self._enter(self.state)
        while True:
            try:
                kind, kw = self.events.get(timeout=0.25)
                if "gen" in kw and kw["gen"] != self.gen:
                    continue  # late event from a cancelled thread
                self._handle(kind, kw)
            except queue.Empty:
                pass
            except Exception:
                log.exception("event handling failed")
            self._timers()

    def _timers(self):
        now, cfg = time.monotonic(), self.cfg
        if self.state == ECOUTE and not self._busy and now - self.last_speech > cfg["silence_relance_s"]:
            self._go(RELANCE, "silence")
        elif self.state == RELANCE and self.mic.active and now - self.last_speech > cfg["silence_cloture_s"]:
            self._go(CLOTURE, "silence")

    def _handle(self, kind: str, kw: dict):
        s = self.state
        if kind == "stop":  # UI / emergency button: silence now, back to veille (still listening for its name)
            self._cancel_all()
            self._go(VEILLE, "stop")
        elif kind == "off":  # "Éteindre": silence now, mic closed, ignores everything until "on"/"start"
            self._cancel_all()
            self._go(ETEINT, "off")
        elif kind == "on" and s == ETEINT:
            self._go(VEILLE, "on")
        elif kind == "start" and s in (VEILLE, ETEINT):
            self._go(ACCUEIL, kw.get("source", "ui"))
        elif s == ETEINT:
            return  # nothing else may wake the robot while it is off
        elif kind == "visage" and s == VEILLE:
            self._go(ACCUEIL, "visage")
        elif kind == "greeting_done" and s == ACCUEIL:
            self._go(ECOUTE, "greeting_done")
        elif kind == "relance_done" and s == RELANCE:
            self.last_speech = time.monotonic()
            self._mic_on()  # 15 s window for an answer
        elif kind == "goodbye_done" and s == CLOTURE:
            # Timer instead of sleeping in the event loop: stop/off stay instant during the pause.
            gen = self.gen
            threading.Timer(self.cfg["cloture_to_veille_s"], lambda: self.post("cloture_done", gen=gen)).start()
        elif kind == "cloture_done" and s == CLOTURE:
            self._go(VEILLE, "cloture_done")
        elif kind == "answer_done" and s == REPONSE:
            self._go(ECOUTE, "answer_done")
        elif kind == "hush":  # "Tais-toi": stop the current sentence; keep the conversation going
            self._cancel_all()
            if s in (REPONSE, ACCUEIL, RELANCE):
                self._go(ECOUTE, "hush")
            elif s == CLOTURE:
                self._go(VEILLE, "hush")
        elif kind == "barge_in" and s == REPONSE:
            self._cancel_all()
            self._go(ECOUTE, "barge_in")
        elif kind == "sing":  # UI button or "chante" request: the Nanterino song
            self._cancel_all()
            self.mic.stop()  # no echo cancellation: never listen to its own song
            self._go(REPONSE, "chanson")
            threading.Thread(target=self._sing, args=(self.gen,), daemon=True).start()
        elif kind == "utterance":
            self._on_text(kw["text"], kw["t_end"])
        elif kind == "not_understood" and s in (ECOUTE, RELANCE) and not self.out.busy:
            self.repairs += 1
            if self.repairs <= 2:
                self._relance_text = self.cfg.get("repair_text") or self.cfg["relance"]
                self._go(RELANCE, "pas_compris")
        elif kind == "ask":  # typed question from the dashboard (tests without a microphone)
            if s == VEILLE:
                self.state = ECOUTE
            self._on_text(kw["text"], time.monotonic())

    def _on_text(self, text: str, t_end: float):
        low = text.lower()
        if self.state == VEILLE:
            if "nanter" in low:  # call word stand-in until openWakeWord (step 9)
                self._go(ACCUEIL, "appel")
            return
        if self.state not in (ECOUTE, RELANCE):
            return
        if any(w in low for w in self.cfg["refusal_words"]):
            self._go(CLOTURE, "refus")
            return
        # Whole words only (2026-10-28): "enchanté" used to start the song (substring match).
        if re.search(r"\b(chante[rsz]?|chantons|chanson)\b", low):  # "chante", "une chanson", "tu sais chanter ?"
            self.repairs = 0
            self._handle("sing", {})
            return
        self.repairs = 0
        self.turns += 1
        if self.turns > MAX_TURNS:
            self._go(CLOTURE, "max_turns")
            return
        self._go(REPONSE, "phrase")
        if not self.cfg["barge_in"]:
            self.mic.stop()  # without echo cancellation the robot would hear itself
        threading.Thread(target=self._answer, args=(text, t_end, self.gen), daemon=True).start()

    def _sing(self, gen: int):
        """Play the pre-built song (song/build_song.py) with line-by-line subtitles."""
        import json
        import wave
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "media", "chanson-nanterino.wav")
        try:
            with wave.open(path) as w:
                rate = w.getframerate()
                pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            lines = json.load(open(path.replace(".wav", ".json"), encoding="utf-8"))["lines"]
        except Exception:
            log.exception("song not available (build it with song/build_song.py)")
            self.subtitle = "Je n'ai pas encore appris ma chanson."
            time.sleep(2)
            if self._alive(gen):
                self.post("answer_done", gen=gen)
            return
        log.info("song start s=%.1f", len(pcm) / rate)
        self.out.play(pcm, rate)
        t0 = time.monotonic() + self.out.preroll_ms / 1000  # first sample after the wake-up pre-roll
        time.sleep(0.15)
        while self.out.busy and self._alive(gen):
            now = time.monotonic() - t0
            current = [l["text"] for l in lines if l["t"] - 0.3 <= now]
            self.subtitle = "🎵 " + current[-1] if current else "🎵"
            time.sleep(0.05)
        if self._alive(gen):  # finished normally (stop/hush bump gen and silence it)
            log.info("song end")
            self.subtitle = ""
            self.post("answer_done", gen=gen)

    def _answer(self, question: str, t_end: float, gen: int):
        cfg = self.cfg
        sheets = self.corpus.search(question, cfg.get("corpus_k", 3), cfg.get("corpus_rel_min", 0.0))
        messages = build_messages(cfg, sheets, self.history[-2 * cfg["history_turns"]:], question)
        log.info("answer start sheets=%d", len(sheets))
        full, spoken, first = [], 0, True
        try:
            for sentence in self.llm.sentences(messages):
                if not self._alive(gen):
                    return  # cancelled: no audio, no history, no event
                sentence = fix_sentence(sentence)
                full.append(sentence)
                self.subtitle = " ".join(full)  # full detail on screen, only N sentences spoken
                if spoken < cfg["spoken_sentences"]:
                    pcm = self.tts.synth(sentence)
                    if not self._alive(gen):
                        return
                    self.out.play(pcm, self.tts.rate)
                    spoken += 1
                    if first:
                        ms = int((time.monotonic() - t_end) * 1000)
                        self.latencies.append(ms)
                        # What the visitor really waits: from the end of their voice (VAD silence
                        # before t_end) to the first audible sample (after the pre-roll, if any).
                        wait = ms + self.cfg["vad_silence_ms"] + (self.out.preroll_ms if self.out.last_play_preroll else 0)
                        log.info("latency_first_sound_ms=%d wait_visitor_ms=%d", ms, wait)
                        first = False
        except Exception:
            log.exception("answer pipeline failed")
            self.subtitle = "Désolé, j'ai eu un problème."
        if not self._alive(gen):
            return
        self.history += [{"role": "user", "content": question}, {"role": "assistant", "content": " ".join(full)}]
        self._wait_audio(gen)
        if self._alive(gen):
            self.post("answer_done", gen=gen)
