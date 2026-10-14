"""Dialogue orchestrator: the 6-state machine of the cahier des charges §2 + voice pipeline.

logging: robotlog via nanterino.log. Only states, transitions and latencies are logged.
Conversation history lives in RAM and is wiped at every Clôture (no memory between people).

States: veille -> accueil -> ecoute <-> reponse ; ecoute -> relance -> (ecoute | cloture) -> veille.
Exits from veille: UI "start" (button / face tap), the word "Nanterino" heard while in veille
(STT-based stand-in until the openWakeWord model of step 9), or `visage` events (step 6).
"""
import collections
import queue
import threading
import time

from .audio import AudioIn, find_device
from .log import log

VEILLE, ACCUEIL, ECOUTE, REPONSE, RELANCE, CLOTURE = "veille", "accueil", "ecoute", "reponse", "relance", "cloture"


class Brain:
    def __init__(self, cfg, out, stt, llm, tts, corpus):
        self.cfg, self.out, self.stt, self.llm, self.tts, self.corpus = cfg, out, stt, llm, tts, corpus
        self.state, self.since = VEILLE, time.monotonic()
        self.subtitle, self.last_speech = "", time.monotonic()
        self.history: list[dict] = []
        self.latencies = collections.deque(maxlen=20)  # ms, end of user speech -> first sound
        self.events: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        self._busy = False  # an utterance is being processed
        self.mic = AudioIn(self._on_utterance, self._on_speech_start,
                           device=find_device(cfg["mic_device"], "input"),
                           silence_ms=cfg["vad_silence_ms"], max_s=cfg["max_utterance_s"])
        threading.Thread(target=self._loop, daemon=True, name="brain").start()

    # ------------------------------------------------------------------ public API (UI / sensors)
    def post(self, kind: str, **kw):
        self.events.put((kind, kw))

    def snapshot(self) -> dict:
        return {"state": self.state, "subtitle": self.subtitle, "mic_on": self.mic.active,
                "mic_level": round(self.mic.level, 3), "out_level": round(self.out.level, 3),
                "speaking": self.out.busy, "latencies_ms": list(self.latencies)}

    # ------------------------------------------------------------------ audio callbacks
    def _on_speech_start(self):
        self.last_speech = time.monotonic()
        if self.state == REPONSE and self.cfg["barge_in"]:
            self.post("barge_in")

    def _on_utterance(self, pcm, t_end):
        if self._busy:
            return
        self._busy = True
        try:
            text = self.stt.transcribe(pcm)
        except Exception:
            log.exception("stt failed")
            text = ""
        finally:
            self._busy = False
        self.last_speech = time.monotonic()
        if text:
            self.post("utterance", text=text, t_end=t_end)

    # ------------------------------------------------------------------ state machine
    def _go(self, state: str, reason: str):
        log.info("transition %s -> %s reason=%s", self.state, state, reason)
        self.state, self.since = state, time.monotonic()
        self._enter(state)

    def _enter(self, state: str):
        cfg = self.cfg
        if state == VEILLE:
            self.history.clear()
            self.subtitle = ""
            self.mic.start()  # listens only for the call word while idle
        elif state == ACCUEIL:
            self.mic.stop()
            self._speak_then(cfg["greeting"], "greeting_done")
        elif state == ECOUTE:
            self.subtitle = "Je vous écoute"
            self.last_speech = time.monotonic()
            self.mic.start()
        elif state == RELANCE:
            self.mic.stop()
            self._speak_then(cfg["relance"], "relance_done")
        elif state == CLOTURE:
            self.mic.stop()
            self.history.clear()
            self._speak_then(cfg["goodbye"], "goodbye_done")

    def _speak_then(self, text: str, done_event: str):
        self.subtitle = text

        def run():
            try:
                self.out.play(self.tts.synth(text), self.tts.rate)
                self._wait_audio()
            except Exception:
                log.exception("speak failed")
            self.post(done_event)
        threading.Thread(target=run, daemon=True).start()

    def _wait_audio(self):
        time.sleep(0.15)
        while self.out.busy and not self._cancel.is_set():
            time.sleep(0.05)

    def _loop(self):
        self._enter(VEILLE)
        while True:
            try:
                kind, kw = self.events.get(timeout=0.25)
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
        if kind == "stop":  # UI / emergency button: silence now, back to veille
            self._cancel.set(); self.out.stop(); self._cancel.clear()
            self._go(VEILLE, "stop")
        elif kind == "start" and s == VEILLE:
            self._go(ACCUEIL, kw.get("source", "ui"))
        elif kind == "visage" and s == VEILLE:
            self._go(ACCUEIL, "visage")
        elif kind == "greeting_done" and s == ACCUEIL:
            self._go(ECOUTE, "greeting_done")
        elif kind == "relance_done" and s == RELANCE:
            self.last_speech = time.monotonic()
            self.mic.start()  # 15 s window for an answer
        elif kind == "goodbye_done" and s == CLOTURE:
            time.sleep(self.cfg["cloture_to_veille_s"])
            self._go(VEILLE, "cloture_done")
        elif kind == "answer_done" and s == REPONSE:
            self._go(ECOUTE, "answer_done")
        elif kind == "barge_in" and s == REPONSE:
            self._cancel.set(); self.out.stop()
            self._go(ECOUTE, "barge_in")
        elif kind == "utterance":
            self._on_text(kw["text"], kw["t_end"])
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
        self._go(REPONSE, "phrase")
        if not self.cfg["barge_in"]:
            self.mic.stop()  # without echo cancellation the robot would hear itself
        self._cancel.clear()
        threading.Thread(target=self._answer, args=(text, t_end), daemon=True).start()

    def _answer(self, question: str, t_end: float):
        cfg = self.cfg
        sheets = self.corpus.search(question)
        context = "\n\n---\n\n".join(s["text"] for s in sheets) or "AUCUNE FICHE PERTINENTE."
        messages = ([{"role": "system", "content": f"{cfg['system_prompt']}\n\nFiches :\n{context}"}]
                    + self.history[-2 * cfg["history_turns"]:]
                    + [{"role": "user", "content": question}])
        log.info("answer start sheets=%d", len(sheets))
        full, spoken, first = [], 0, True
        try:
            for sentence in self.llm.sentences(messages):
                if self._cancel.is_set():
                    break
                full.append(sentence)
                self.subtitle = " ".join(full)  # full detail on screen, only N sentences spoken
                if spoken < cfg["spoken_sentences"]:
                    self.out.play(self.tts.synth(sentence), self.tts.rate)
                    spoken += 1
                    if first:
                        ms = int((time.monotonic() - t_end) * 1000)
                        self.latencies.append(ms)
                        log.info("latency_first_sound_ms=%d", ms)
                        first = False
        except Exception:
            log.exception("answer pipeline failed")
            self.subtitle = "Désolé, j'ai eu un problème."
        self.history += [{"role": "user", "content": question}, {"role": "assistant", "content": " ".join(full)}]
        self._wait_audio()
        self.post("answer_done")
