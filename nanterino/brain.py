"""Dialogue orchestrator: the 6-state machine of the cahier des charges §2 + voice pipeline.

logging: robotlog via nanterino.log. Only states, transitions and latencies are logged.
Conversation history lives in RAM and is wiped at every Clôture (no memory between people).

States: veille -> accueil -> ecoute <-> reponse ; ecoute -> relance -> (ecoute | cloture) -> veille,
plus "eteint" (OFF): mic closed, no listening, no speech, until "start"/"on".
Exits from veille: UI "start" (button / face tap), the word "Nanterino" heard while in veille
(STT-based stand-in until the openWakeWord model of step 9), or `visage` events (step 6).

Graph + heartbeat (2026-10-30): the transitions are no longer coded here. They live in
nanterino/graph.yaml (French, editable; override file /opt/robot/nanterino/graph.yaml) and are run by
nanterino.graph.GraphEngine. This module keeps the *capabilities*: the closed registry of actions and
guards (`_build_engine`) and the audio/LLM/TTS threads. A heartbeat thread posts a `tick` at
cfg["heartbeat_hz"] (10 Hz); the single "brain" loop blocks on the event queue and every tick evaluates
the graph's `after:` delays and the scheduled events. A watchdog thread trips when no tick was processed
for cfg["watchdog_s"] seconds (a handler is stuck): it logs to errors.log, cancels speech, queues a
priority `stop` and restarts a dead loop thread.

Cancellation (fix 2026-10-15): every speaking/answering thread carries the generation number it
was started with. stop/off/hush/barge-in bump the generation, so an old thread can never speak
again or post a late "done" event. (The previous set()+clear() of a shared Event was so fast that
running answers missed it and kept talking after "Stop".)
"""
import itertools
import re
import numpy as np
import os
import collections
import queue
import threading
import time

from . import graph as graph_mod
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
        # PriorityQueue: the watchdog's `stop` (priority -1) must pass ahead of anything queued.
        # The sequence number keeps FIFO order inside one priority and avoids comparing payload dicts.
        self.events: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = itertools.count()
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
        # Heartbeat / watchdog bookkeeping (read by snapshot() from other threads: plain floats/ints only).
        self.hb_hz = max(0.5, float(cfg.get("heartbeat_hz", 10)))
        self.watchdog_s = float(cfg.get("watchdog_s", 5))
        self._closing = threading.Event()
        self._tick_pending = False   # at most one tick in the queue: a stuck loop must not pile them up
        self._last_beat = time.monotonic()
        self._lag_ms, self._hz, self._trips, self._wd_tripped = 0.0, 0.0, 0, False
        self._beats: collections.deque = collections.deque(maxlen=30)
        self._tick_err_at = 0.0
        self._scheduled: list = []   # (due monotonic, event, gen): replaces the old threading.Timer
        self._sched_lock = threading.Lock()
        self.graph_error = None
        self.engine = self._build_engine()
        threading.Thread(target=self._cache_phrases, daemon=True, name="phrase-cache").start()
        self._start_threads()

    # ------------------------------------------------------------------ public API (UI / sensors)
    def post(self, kind: str, **kw):
        self.events.put((0, next(self._seq), kind, kw))

    def post_priority(self, kind: str, **kw):
        """Handled before every queued event (used by the watchdog)."""
        self.events.put((-1, next(self._seq), kind, kw))

    def snapshot(self) -> dict:
        now = time.monotonic()
        return {"state": self.state, "subtitle": self.subtitle, "mic_on": self.mic.active,
                "mic_level": round(self.mic.level, 3), "out_level": round(self.out.level, 3),
                "speaking": self.out.busy, "muted": self.out.muted, "deaf": self.deaf, "latencies_ms": list(self.latencies),
                "state_age_s": round(now - self.since, 1), "turns": self.turns,
                "heartbeat": {"hz": round(self._hz, 1), "lag_ms": round(self._lag_ms, 1),
                              "age_ms": int((now - self._last_beat) * 1000), "trips": self._trips}}

    def reload_graph(self) -> tuple[bool, str | None]:
        """Re-read the graph file; only while idle (veille/eteint) so no conversation is cut mid-state.

        Returns (applied, error): error is the validation message when the file was invalid and the
        default graph is running instead.
        """
        if self.state not in (VEILLE, ETEINT):
            return False, "busy"
        self.engine = self._build_engine()
        return True, self.graph_error

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
        self.engine.enter(state)  # the graph's `on_enter` actions

    def _build_engine(self) -> "graph_mod.GraphEngine":
        """Load the active graph (override file or default) and bind it to this brain's capabilities.

        The dicts below are the CLOSED vocabulary implemented here; graph.ACTION_SPECS / GUARDS list the
        names a graph file may use and GraphEngine refuses to start if one is missing.
        """
        cfg = self.cfg
        graph, self.graph_error = graph_mod.load_active(cfg)

        def clear_conversation(kw):
            self.history.clear(); self.turns = 0; self.subtitle = ""

        def reset_silence(kw):
            self.last_speech = time.monotonic()

        def speak_relance(kw):
            text, self._relance_text = self._relance_text or cfg["relance"], None  # one-shot repair text
            self._speak_then(text, "relance_done")

        def schedule(kw, event, delay):
            d = float(delay if isinstance(delay, (int, float)) else cfg[delay])
            with self._sched_lock:  # gen captured now: stop/off before the due time drops the event
                self._scheduled.append((time.monotonic() + d, event, self.gen))

        def count_turn(kw):
            self.turns += 1

        def count_repair(kw):
            self.repairs += 1

        def set_relance_text(kw):
            self._relance_text = cfg.get("repair_text") or cfg["relance"]

        def start_answer(kw):
            threading.Thread(target=self._answer, args=(kw["text"], kw["t_end"], self.gen), daemon=True).start()

        def start_sing(kw):
            threading.Thread(target=self._sing, args=(self.gen,), daemon=True).start()

        def as_utterance(kw):  # typed text (dashboard "ask") handled exactly like a spoken one
            self.engine.dispatch("utterance", {"text": kw["text"], "t_end": kw.get("t_end") or time.monotonic()})

        actions = {
            "cancel_all": lambda kw: self._cancel_all(),
            "mic_on": lambda kw: self._mic_on(),
            "mic_off": lambda kw: self.mic.stop(),
            # Without echo cancellation the robot would hear itself, unless barge-in is wanted.
            "mic_off_no_barge_in": lambda kw: None if cfg["barge_in"] else self.mic.stop(),
            "clear_conversation": clear_conversation,
            "clear_history": lambda kw: self.history.clear(),
            "reset_repairs": lambda kw: setattr(self, "repairs", 0),
            "reset_silence": reset_silence,
            "subtitle_listening": lambda kw: setattr(self, "subtitle", "Je vous écoute"),
            "count_turn": count_turn, "count_repair": count_repair, "set_relance_text": set_relance_text,
            "speak_phrase": lambda kw, text, done: self._speak_then(cfg[text], done),
            "speak_relance": speak_relance,
            "schedule": schedule,
            "emit": lambda kw, event: self.engine.dispatch(event, {}),
            "start_answer": start_answer, "start_sing": start_sing, "as_utterance": as_utterance,
        }
        guards = {
            "auto_greet_on_face": lambda kw: bool(cfg.get("auto_greet_on_face")),
            "barge_in": lambda kw: bool(cfg.get("barge_in")),
            "not_busy": lambda kw: not self._busy,
            "mic_active": lambda kw: bool(self.mic.active),
            "not_speaking": lambda kw: not self.out.busy,
            "repairs_left": lambda kw: self.repairs < 2,          # "pardon ?" at most twice in a row
            "turns_left": lambda kw: self.turns < MAX_TURNS,       # looked up at call time (tests patch it)
        }
        return graph_mod.GraphEngine(graph, self, actions, guards, cfg)

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

    # ------------------------------------------------------------------ threads: loop, heartbeat, watchdog
    def _start_threads(self):
        self._hb_thread = threading.Thread(target=self._heartbeat, daemon=True, name="heartbeat")
        self._hb_thread.start()
        self._start_loop(boot=True)
        threading.Thread(target=self._watchdog, daemon=True, name="watchdog").start()

    def _start_loop(self, boot: bool):
        self._loop_thread = threading.Thread(target=self._loop, args=(boot,), daemon=True, name="brain")
        self._loop_thread.start()

    def shutdown(self):
        """Stop the three threads (tests; the service itself never calls it)."""
        self._closing.set()
        self.post_priority("_quit")

    def _loop(self, boot: bool = True):
        if boot:
            # Power state survives restarts: an "off" robot stays off after a reboot (user request).
            if self.cfg.get("power") == "off":
                self.state = ETEINT
            try:
                self.engine.enter(self.state)
            except Exception:
                log.exception("boot entry failed")
        while not self._closing.is_set():
            try:
                _, _, kind, kw = self.events.get()  # blocks: the heartbeat wakes it 10x/s
                if kind == "_quit":
                    return
                if kind == "tick":
                    self._on_tick(kw)
                    continue
                if "gen" in kw and kw["gen"] != self.gen:
                    continue  # late event from a cancelled thread
                self.engine.dispatch(kind, kw)
            except Exception:
                log.exception("event handling failed")

    def _on_tick(self, kw: dict):
        now = time.monotonic()
        # Beat accounting comes first: "a beat was processed" is what the watchdog measures.
        self._tick_pending, self._wd_tripped, self._last_beat = False, False, now
        self._lag_ms = (now - kw["t"]) * 1000.0
        self._beats.append(now)
        if len(self._beats) > 2 and now > self._beats[0]:
            self._hz = (len(self._beats) - 1) / (now - self._beats[0])
        try:
            self._release_scheduled(now)
            self.engine.tick(now)
        except Exception:
            if now - self._tick_err_at > 5:  # a systematic bug must not flood the log at 10 Hz
                self._tick_err_at = now
                log.exception("tick handling failed")

    def _release_scheduled(self, now: float):
        with self._sched_lock:
            due = [x for x in self._scheduled if x[0] <= now]
            self._scheduled = [x for x in self._scheduled if x[0] > now]
        for _, event, gen in due:
            self.post(event, gen=gen)  # dropped by the loop if a stop/off bumped gen meanwhile

    def _heartbeat(self):
        period = 1.0 / self.hb_hz
        nxt = time.monotonic() + period
        while not self._closing.wait(max(0.0, nxt - time.monotonic())):
            now = time.monotonic()
            nxt += period
            if nxt < now:  # we overslept (suspend, heavy load): do not fire a burst to catch up
                nxt = now + period
            if not self._tick_pending:
                self._tick_pending = True
                self.events.put((0, next(self._seq), "tick", {"t": now}))

    def _watchdog(self):
        check = max(0.05, min(1.0, self.watchdog_s / 4))
        while not self._closing.wait(check):
            if not self._hb_thread.is_alive():
                log.error("watchdog: heartbeat thread died, restarting it")
                self._hb_thread = threading.Thread(target=self._heartbeat, daemon=True, name="heartbeat")
                self._hb_thread.start()
            if not self._loop_thread.is_alive():
                log.error("watchdog: brain loop thread died, restarting it")
                self._start_loop(boot=False)
            age = time.monotonic() - self._last_beat
            if age > self.watchdog_s and not self._wd_tripped:
                self._wd_tripped = True  # one trip per stall; cleared by the next processed beat
                self._trips += 1
                log.error("watchdog: no heartbeat processed for %.1fs in state=%s, forcing stop (trip %d)",
                          age, self.state, self._trips)
                self._cancel_all()
                self.post_priority("stop", source="watchdog")

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
