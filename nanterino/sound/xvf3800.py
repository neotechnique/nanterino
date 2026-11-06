"""Seeed reSpeaker XVF3800 4-Mic Array backend (lot L44): the on-chip direction of arrival (DOA) read over USB.

logging: robotlog via nanterino.log.

Purpose
    The XVF3800 (XMOS) beamforms and tracks the speaker itself. `Xvf3800Source` does NOT capture audio: it polls the
    chip's vendor control interface (pyusb control transfers, no kernel driver detach, the ALSA audio streams stay
    free for the speech microphone) at ~15 Hz on its own thread and turns the answer into the SoundSource `Reading`
    model (raw azimuth in degrees, + = counter-clockwise seen from above, same sign as the head pan; the front offset
    is applied later by tracker.SoundTracker, the dashboard button « Définir comme avant »).
    Protocol (vendor IN request, verified against Seeed's reference script xvf_host.py / respeaker_get_doa.py):
        bmRequestType 0xC0 (device-to-host | vendor | device), bRequest 0, wValue = 0x80 | cmdid, wIndex = resid,
        wLength = payload + 1; byte 0 of the answer is a status (0 = ok, 64 = retry: ask again after ~10 ms).
        DOA_VALUE            resid 20 cmdid 18  2 x uint16 LE : (doa degrees 0..359, speech_detected 0/1)
        AEC_AZIMUTH_VALUES   resid 33 cmdid 75  4 x float32 LE: beam1, beam2, free-running, auto-select (radians)
        AEC_SPENERGY_VALUES  resid 33 cmdid 80  4 x float32 LE: speech energy per beam (> 0 = speech)
    Mapping (INFERRED where marked): azimuth = sign * DOA_VALUE (sign +1 = counter-clockwise, XMOS math convention,
    inferred, not stated in the sources; cfg sound_xvf_sign = -1 mirrors it); the chip's own zero is board dependent
    and is removed by the persisted front offset. Confidence: 1.0 when the chip flags speech, 0.6 when only the speech
    energy is > 0 (claps), otherwise 0 with NO azimuth. level_db is a NOMINAL proxy (-25 speech, -40 energy only, -90
    nothing) because the energy values have no documented dB scale; the real figure is in info()["energy_max"].
Boundary
    Only start() touches USB, and only server.py calls it. `usb.core` is imported lazily (pyusb may be missing). The
    device object is injectable (`device_factory`) so tests run with a fake that returns raw bytes. Every failure is a
    NotConfiguredError with a French reason (create() then falls back to mono); after start(), read errors never
    raise: info()["available"] turns False with a reason and poll() returns an empty Reading.
Invariants
    - never a made-up angle: no speech flag and no energy -> azimuth None, confidence 0 (after the HOLD_S hold of
      the last voiced azimuth, lot L45, which bridges the chip's speech-flag gaps inside a sentence);
    - poll() never blocks (the reader thread owns all USB traffic; a lock-free copy of the latest Reading is returned);
    - the status byte is always checked; a retry status is re-asked at most RETRY_MAX times.
How to test
    .venv/bin/python -m tests.test_sound   (fake device, no hardware);  .venv/bin/python scripts/xvf3800_probe.py
"""
import math
import struct
import threading
import time

from ..log import log
from .angles import wrap180
from .sources import NotConfiguredError, Reading, SoundSource

VID, PID = 0x2886, 0x001A
REQ_IN_VENDOR_DEVICE = 0xC0           # CTRL_IN | CTRL_TYPE_VENDOR | CTRL_RECIPIENT_DEVICE
STATUS_OK, STATUS_RETRY = 0, 64
RETRY_MAX, RETRY_SLEEP_S, TIMEOUT_MS = 20, 0.01, 200
# name -> (resid, cmdid, struct format of the payload after the status byte)
PARAMS = {
    "DOA_VALUE": (20, 18, "<HH"),
    "AEC_AZIMUTH_VALUES": (33, 75, "<ffff"),
    "AEC_SPENERGY_VALUES": (33, 80, "<ffff"),
}
UDEV_HINT = "Lancer une fois « sudo bash /opt/robot/scripts/install-respeaker-udev.sh » puis rebrancher le micro."
LEVEL_SPEECH_DB, LEVEL_ENERGY_DB, LEVEL_NONE_DB = -25.0, -40.0, -90.0
# Lot L45: the chip drops its speech flag between syllables / words; the last voiced azimuth is held for HOLD_S with a
# confidence decaying linearly to 0 (direction() needs >= 0.5, so nodes see at most HOLD_S / 2 of hold), level_db
# LEVEL_ENERGY_DB, raw["held"] True. After HOLD_S of silence: azimuth None again (no angle invented in silence).
HOLD_S = 0.5


class ControlError(RuntimeError):
    """A control transfer was refused or answered with an error status."""


def decode_response(raw, fmt: str):
    """Status byte + payload -> tuple. Raises ControlError on a bad status or a short answer."""
    raw = bytes(raw)
    size = struct.calcsize(fmt)
    if not raw:
        raise ControlError("réponse vide")
    if raw[0] != STATUS_OK:
        raise ControlError("statut %d" % raw[0])
    if len(raw) < 1 + size:
        raise ControlError("réponse trop courte (%d octets au lieu de %d)" % (len(raw), 1 + size))
    return struct.unpack(fmt, raw[1:1 + size])


def read_param(dev, name: str):
    """One parameter read, re-asking while the chip answers « retry ». Returns the decoded tuple."""
    resid, cmdid, fmt = PARAMS[name]
    length = 1 + struct.calcsize(fmt)
    for _ in range(RETRY_MAX):
        raw = bytes(dev.ctrl_transfer(REQ_IN_VENDOR_DEVICE, 0, 0x80 | cmdid, resid, length, TIMEOUT_MS))
        if raw and raw[0] == STATUS_RETRY:
            time.sleep(RETRY_SLEEP_S)
            continue
        return decode_response(raw, fmt)
    raise ControlError("le micro répond toujours « réessayer »")


def to_azimuth(doa_deg: float, sign: float = 1.0) -> float:
    """Chip degrees (0..359) -> raw azimuth in (-180, 180]; sign -1 mirrors the rotation sense."""
    return wrap180(sign * float(doa_deg))


def interpret(doa, speech_flag, energies, sign=1.0, beam_auto_rad=None):
    """(azimuth_deg or None, confidence, voice_prob, level_db, energy_max) from one set of raw values."""
    emax = max([e for e in energies if isinstance(e, float) and math.isfinite(e)] or [0.0])
    if speech_flag:
        conf, voice, level = 1.0, 1.0, LEVEL_SPEECH_DB
    elif emax > 0:
        conf, voice, level = 0.6, 0.0, LEVEL_ENERGY_DB
    else:
        return None, 0.0, 0.0, LEVEL_NONE_DB, emax
    az = None
    if beam_auto_rad is not None and math.isfinite(beam_auto_rad) and not speech_flag:
        az = to_azimuth(math.degrees(beam_auto_rad), sign)      # energy only: the auto-select beam is the best guess
    if az is None:
        az = to_azimuth(doa, sign)
    return az, conf, voice, level, emax


def find_device(find=None):
    """The XVF3800 usb device or None. `find` is usb.core.find-like (tests inject it)."""
    if find is None:
        try:
            import usb.core
        except ImportError:
            return None
        find = usb.core.find
    try:
        return find(idVendor=VID, idProduct=PID)
    except Exception:   # noqa: BLE001 - libusb backend missing etc.: treat as absent
        return None


def detect(find=None) -> bool:
    return find_device(find) is not None


class Xvf3800Source(SoundSource):
    name = "xvf3800"
    gives_direction = True

    def __init__(self, sign=1.0, hz=15.0, device_factory=None):
        self.sign = -1.0 if float(sign) < 0 else 1.0
        self.period = 1.0 / max(1.0, min(30.0, float(hz)))
        self._factory = device_factory
        self._dev = None
        self._lock = threading.Lock()
        self._latest = None
        self._thread, self._stop = None, threading.Event()
        self.available, self.reason, self.version = False, "Pas encore démarré.", None
        self.raw = {}
        self._fails = 0
        self._voiced = None          # (t, azimuth, confidence) of the last voiced reading (HOLD_S hold)

    # ------------------------------------------------------------------ lifecycle
    def _open(self):
        if self._factory is not None:
            return self._factory()
        try:
            import usb.core
        except ImportError:
            raise NotConfiguredError("Backend « xvf3800 » : pyusb n'est pas installé.")
        dev = usb.core.find(idVendor=VID, idProduct=PID)
        if dev is None:
            raise NotConfiguredError("Backend « xvf3800 » : reSpeaker XVF3800 (2886:001a) introuvable sur l'USB.")
        return dev

    @staticmethod
    def _explain(e) -> str:
        if getattr(e, "errno", None) == 13 or "Access denied" in str(e) or "ermission" in str(e):
            return "Accès USB refusé (droits). " + UDEV_HINT
        return "%s: %s" % (type(e).__name__, e)

    def start(self):
        dev = self._open()
        try:
            self.raw["doa"] = read_param(dev, "DOA_VALUE")        # first read = the permission / presence probe
        except NotConfiguredError:
            raise
        except Exception as e:   # noqa: BLE001 - usb.core.USBError, ControlError, OSError
            raise NotConfiguredError("Backend « xvf3800 » : %s" % self._explain(e))
        self._dev, self.available, self.reason = dev, True, ""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="xvf3800", daemon=True)
        self._thread.start()
        log.info("xvf3800 DOA reader started (%.0f Hz, sign %+d)", 1.0 / self.period, self.sign)

    def stop(self):
        self._stop.set()
        t, self._thread = self._thread, None
        if t is not None:
            t.join(timeout=1.0)
        dev, self._dev = self._dev, None
        try:
            import usb.util
            if dev is not None and self._factory is None:
                usb.util.dispose_resources(dev)
        except Exception:   # noqa: BLE001
            pass
        self.available = False

    # ------------------------------------------------------------------ reading
    def read_once(self, now=None) -> Reading:
        """One full read of the three parameters -> Reading (also the unit-test entry point)."""
        now = time.monotonic() if now is None else now
        dev = self._dev
        doa, flag = read_param(dev, "DOA_VALUE")
        beams = read_param(dev, "AEC_AZIMUTH_VALUES")
        energies = read_param(dev, "AEC_SPENERGY_VALUES")
        az, conf, voice, level, emax = interpret(doa, flag, energies, self.sign, beams[3])
        held = False
        if az is not None:
            self._voiced = (now, az, conf)
        elif self._voiced is not None and 0 <= now - self._voiced[0] < HOLD_S:
            t_v, az_v, conf_v = self._voiced          # short gap inside speech: keep the angle, fade the confidence
            az, conf, level, held = az_v, round(conf_v * (1.0 - (now - t_v) / HOLD_S), 3), LEVEL_ENERGY_DB, True
        self.raw = {"doa_deg": doa, "speech": flag, "beams_rad": [round(b, 3) for b in beams],
                    "energy_max": emax, "held": held}
        return Reading(t=now, azimuth_deg=az, level_db=level, confidence=conf, voice_prob=voice)

    def _run(self):
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                r = self.read_once(t0)
                with self._lock:
                    self._latest, self._fails = r, 0
                    self.available, self.reason = True, ""
            except Exception as e:   # noqa: BLE001 - unplugged, transient USB error ...
                self._fails += 1
                if self._fails == 3:          # tolerate single glitches, then say so
                    log.error("xvf3800 read failing: %s", e)
                if self._fails >= 3:
                    with self._lock:          # availability and the empty reading flip together
                        self.available, self.reason = False, "Lecture USB en échec : %s" % self._explain(e)
                        self._latest = Reading(t=t0, level_db=LEVEL_NONE_DB)
            self._stop.wait(max(0.0, self.period - (time.monotonic() - t0)))

    def poll(self, now):
        with self._lock:
            r = self._latest
        return r

    def info(self):
        return {"name": self.name, "gives_direction": True, "available": self.available, "reason": self.reason,
                "detail": "reSpeaker XVF3800 : direction calculée par la puce (USB), niveau approximatif.",
                "sign": int(self.sign), "raw": dict(self.raw)}
