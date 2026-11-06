"""Direction of arrival for a generic microphone array (lot C2): geometry file, GCC-PHAT pairs, SRP-PHAT on a grid.

logging: robotlog via nanterino.log (geometry errors are raised, not logged).

Purpose
    `load_geometry(path)` reads the array description (array.yaml: channel -> mic position in mm, sample rate, frame,
    voice band, gate); `DoaEstimator(geometry).analyse(frame)` turns one multi-channel frame into (azimuth, confidence,
    level, voice probability):
      1. Hann window, real FFT per channel, keep only the voice band bins (band_hz, default 300-3400 Hz: this
         frequency mask IS the voice-band filter, no separate IIR stage);
      2. PHAT-weighted cross spectra of every mic pair (GCC-PHAT);
      3. SRP-PHAT: the sum over pairs and bins of the cross spectra steered to each candidate azimuth of a 360-degree
         grid (far-field plane wave, horizontal plane), one matrix-vector product with a precomputed steering
         matrix, only the strongest ENERGY_SHARE bins voting; parabolic refinement of the peak;
      4. confidence = the normalised peak coherence mapped to 0..1 (CONF_FLOOR .. CONF_FULL), level = voice-band
         power in dBFS, voice_prob = share of 30 ms sub-frames webrtcvad calls speech (None if webrtcvad is missing);
      5. gate: below min_level_db (or, with gate: voice, below vad_threshold) the frame has NO direction.
    `CircularSmoother` smooths successive azimuths on the unit circle (no jump at +-180).
Boundary
    Pure numpy (plus optional webrtcvad); no device access (array_source.py captures). Units: positions in metres
    inside, millimetres in the file; robot frame x forward, y left, z up; azimuth 0 = front, + = left (angles.py).
Invariants
    - physics convention, shared with the synthetic test signals: a plane wave from unit direction u reaches mic m at
      position p_m EARLIER by (p_m . u) / c, i.e. X_m(f) = S(f) exp(+j 2 pi f (p_m . u) / c);
    - a planar array cannot tell up from down: elevation is always None here (a 3-D geometry would need an
      elevation grid; not done until such an array exists);
    - analyse() never raises on a silent or constant frame (level -inf is reported as -120 dB, no direction).
CPU budget
    measured by tests.test_sound on the Jetson (4 mics, 1024-sample frames at 16 kHz, 1-degree grid): see the
    `doa cpu` line it prints; ArraySoundSource.stats() reports the live figure.
How to test
    .venv/bin/python -m tests.test_sound   (synthetic plane waves from known angles, noise, wrap-around)
"""
import itertools
import math
from dataclasses import dataclass, field

import numpy as np

from .angles import wrap180

SPEED_OF_SOUND = 343.0          # m/s at about 20 degrees C
CONF_FLOOR, CONF_FULL = 0.25, 0.75   # normalised SRP peak -> confidence 0 .. 1 (synthetic set: independent noise
                                     # peaks <= 0.16, a voice at 10 dB SNR >= 0.8)
ENERGY_SHARE = 0.3                   # share of the voice-band bins (the strongest) that vote in the SRP
RATES = (8000, 16000, 32000, 48000)  # webrtcvad rates; any array driver can resample to one of them
GATES = ("level", "voice")


@dataclass
class Geometry:
    name: str
    rate: int
    channels: int                       # channels captured from the device
    mic_channels: list                  # device channel index of each mic, in `positions` order
    positions: np.ndarray               # (M, 3) metres, robot frame
    device: str | None = None           # PortAudio name substring (sounddevice); None = default input
    frame: int = 1024
    hop: int = 1024
    band_hz: tuple = (300.0, 3400.0)
    gate: str = "level"
    min_level_db: float = -50.0
    vad_threshold: float = 0.5
    smoothing: float = 0.5              # CircularSmoother alpha (1 = no smoothing)
    grid_deg: float = 1.0
    source: str = field(default="", repr=False)


def _err(where, msg):
    return ValueError("%s : %s" % (where, msg))


def geometry_from_dict(d: dict, where: str = "géométrie") -> Geometry:
    """Validated Geometry from a parsed array.yaml (French ValueError naming the problem)."""
    if not isinstance(d, dict):
        raise _err(where, "objet YAML attendu")
    rate = d.get("rate", 16000)
    if rate not in RATES:
        raise _err(where, "rate doit valoir %s" % ", ".join(map(str, RATES)))
    mics = d.get("mics")
    if not isinstance(mics, list) or len(mics) < 2:
        raise _err(where, "au moins 2 micros dans `mics`")
    channels = d.get("channels", len(mics))
    if not isinstance(channels, int) or channels < len(mics):
        raise _err(where, "channels (%r) doit être un entier >= nombre de micros" % (channels,))
    pos, chans = [], []
    for i, m in enumerate(mics):
        if not isinstance(m, dict) or not all(isinstance(m.get(k, 0), (int, float)) for k in ("x", "y", "z")):
            raise _err(where, "micro %d : {channel, x, y, z} en mm attendu" % i)
        ch = m.get("channel", i)
        if not isinstance(ch, int) or not 0 <= ch < channels:
            raise _err(where, "micro %d : channel %r hors de 0..%d" % (i, ch, channels - 1))
        chans.append(ch)
        pos.append([float(m.get("x", 0)) / 1000.0, float(m.get("y", 0)) / 1000.0, float(m.get("z", 0)) / 1000.0])
    if len(set(chans)) != len(chans):
        raise _err(where, "deux micros sur la même voie")
    P = np.array(pos, dtype=float)
    if min(np.linalg.norm(P[i] - P[j]) for i, j in itertools.combinations(range(len(P)), 2)) < 1e-3:
        raise _err(where, "deux micros à la même position")
    if np.ptp(P[:, 0]) < 1e-3 and np.ptp(P[:, 1]) < 1e-3:
        raise _err(where, "micros alignés verticalement : aucune direction horizontale mesurable")
    frame = d.get("frame", 1024)
    if not isinstance(frame, int) or frame < 256 or frame & (frame - 1):
        raise _err(where, "frame doit être une puissance de 2 >= 256")
    hop = d.get("hop", frame)
    if not isinstance(hop, int) or not 0 < hop <= frame:
        raise _err(where, "hop doit être un entier dans 1..frame")
    band = d.get("band_hz", [300, 3400])
    if not (isinstance(band, (list, tuple)) and len(band) == 2 and 0 < band[0] < band[1] <= rate / 2):
        raise _err(where, "band_hz = [bas, haut] dans 0..%d Hz" % (rate // 2))
    gate = d.get("gate", "level")
    if gate not in GATES:
        raise _err(where, "gate doit valoir level ou voice")
    smoothing = float(d.get("smoothing", 0.5))
    grid = float(d.get("grid_deg", 1.0))
    if not 0 < smoothing <= 1 or not 0.25 <= grid <= 10:
        raise _err(where, "smoothing dans ]0, 1] et grid_deg dans [0.25, 10]")
    return Geometry(name=str(d.get("name", "barrette")), rate=int(rate), channels=channels, mic_channels=chans,
                    positions=P, device=d.get("device"), frame=frame, hop=hop,
                    band_hz=(float(band[0]), float(band[1])), gate=gate,
                    min_level_db=float(d.get("min_level_db", -50.0)),
                    vad_threshold=float(d.get("vad_threshold", 0.5)), smoothing=smoothing, grid_deg=grid,
                    source=where)


def load_geometry(path: str) -> Geometry:
    import yaml
    with open(path, encoding="utf-8") as f:
        return geometry_from_dict(yaml.safe_load(f), path)


def circular_geometry(n=4, radius_mm=32.0, rate=16000, **kw) -> Geometry:
    """Helper (tests, docs): n mics on a horizontal circle, mic 0 straight ahead, counter-clockwise."""
    mics = [{"channel": i, "x": radius_mm * math.cos(2 * math.pi * i / n),
             "y": radius_mm * math.sin(2 * math.pi * i / n), "z": 0.0} for i in range(n)]
    return geometry_from_dict(dict({"name": "cercle %d micros r=%g mm" % (n, radius_mm), "rate": rate,
                                    "channels": n, "mics": mics}, **kw), "cercle")


def gcc_phat(x, y, rate, max_tau=None, interp=16):
    """Classic pairwise GCC-PHAT: delay (seconds) of y relative to x (positive = y arrives later)."""
    n = len(x) + len(y)
    X, Y = np.fft.rfft(x, n=n), np.fft.rfft(y, n=n)
    R = X * np.conj(Y)
    cc = np.fft.irfft(R / (np.abs(R) + 1e-12), n=interp * n)
    max_shift = interp * n // 2
    if max_tau is not None:
        max_shift = min(int(interp * rate * max_tau), max_shift)
    cc = np.concatenate((cc[-max_shift:], cc[:max_shift + 1]))
    shift = int(np.argmax(np.abs(cc))) - max_shift
    return -shift / float(interp * rate)


def _vad():
    try:
        import webrtcvad
        return webrtcvad.Vad(2)
    except Exception:   # noqa: BLE001 - optional dependency
        return None


class DoaEstimator:
    def __init__(self, geom: Geometry):
        self.geom = geom
        n, rate = geom.frame, geom.rate
        self.win = np.hanning(n)
        self.win_power = float(np.sum(self.win ** 2))
        freqs = np.fft.rfftfreq(n, 1.0 / rate)
        self.bins = np.nonzero((freqs >= geom.band_hz[0]) & (freqs <= geom.band_hz[1]))[0]
        f = freqs[self.bins]
        self.pairs = list(itertools.combinations(range(len(geom.positions)), 2))
        self.thetas = np.arange(-180.0, 180.0, geom.grid_deg)
        th = np.radians(self.thetas)
        u = np.stack([np.cos(th), np.sin(th), np.zeros_like(th)], axis=1)          # (T, 3)
        P = geom.positions
        dpos = np.array([P[i] - P[j] for i, j in self.pairs])                       # (Q, 3)
        tau = dpos @ u.T / SPEED_OF_SOUND                                           # (Q, T) seconds
        # steering: conj of the expected cross-spectrum phase exp(+j 2 pi f tau); (Q*F, T) for one matvec per frame
        steer = np.exp(-2j * np.pi * f[None, :, None] * tau[:, None, :])           # (Q, F, T)
        self.steer = steer.reshape(len(self.pairs) * len(f), len(self.thetas)).astype(np.complex64)
        self.ii = np.array([i for i, _ in self.pairs])
        self.jj = np.array([j for _, j in self.pairs])
        self.vad = _vad()

    def level_db(self, X) -> float:
        """Voice-band mean power of the windowed frame, averaged over mics, in dBFS (full scale sine ~ -3 dB)."""
        p = 2.0 * float(np.mean(np.sum(np.abs(X) ** 2, axis=0))) / (self.geom.frame * self.win_power)
        return 10.0 * math.log10(p) if p > 1e-12 else -120.0

    def voice_prob(self, x0) -> float | None:
        if self.vad is None:
            return None
        rate = self.geom.rate
        sub = int(rate * 0.03)
        pcm = (np.clip(x0, -1.0, 1.0) * 32767).astype(np.int16)
        chunks = [pcm[k:k + sub] for k in range(0, len(pcm) - sub + 1, sub)]
        if not chunks:
            return None
        try:
            return sum(self.vad.is_speech(c.tobytes(), rate) for c in chunks) / len(chunks)
        except Exception:   # noqa: BLE001
            return None

    def srp(self, frame) -> tuple:
        """(SRP curve over self.thetas, X band spectra (F, M)) of one (n, channels) frame."""
        x = np.asarray(frame, dtype=float)[:, self.geom.mic_channels]
        x = x - x.mean(axis=0, keepdims=True)
        X = np.fft.rfft(x * self.win[:, None], axis=0)[self.bins]                  # (F, M)
        cross = X[:, self.ii] * np.conj(X[:, self.jj])                              # (F, Q)
        phat = cross / (np.abs(cross) + 1e-12)
        # energy mask: PHAT whitens every bin to weight 1, so the empty bins between the harmonics of a voice would
        # weigh as much as the harmonics; only the ENERGY_SHARE strongest bins vote (measured: voice at 10 dB SNR,
        # max error 9 -> 4 degrees on the 4-mic 32 mm circle)
        k = max(1, int(round(ENERGY_SHARE * len(X))))
        keep = np.argpartition(np.mean(np.abs(X) ** 2, axis=1), len(X) - k)[len(X) - k:]
        w = np.zeros(len(X))
        w[keep] = 1.0
        vec = (phat * w[:, None]).T.reshape(-1).astype(np.complex64)                 # (Q*F,)
        return np.real(vec @ self.steer) / (len(self.pairs) * k), X

    def analyse(self, frame) -> dict:
        """{azimuth_deg (raw, None when gated), confidence, level_db, voice_prob, peak} for one frame."""
        g = self.geom
        curve, X = self.srp(frame)
        level = self.level_db(X)
        vp = self.voice_prob(np.asarray(frame, dtype=float)[:, g.mic_channels[0]]) if g.gate == "voice" else None
        k = int(np.argmax(curve))
        peak = float(curve[k])
        a, b = curve[k - 1], curve[(k + 1) % len(curve)]                           # circular neighbours
        den = a - 2 * peak + b
        off = 0.5 * (a - b) / den if den < -1e-12 else 0.0
        az = wrap180(self.thetas[k] + max(-0.5, min(0.5, off)) * g.grid_deg)
        conf = max(0.0, min(1.0, (peak - CONF_FLOOR) / (CONF_FULL - CONF_FLOOR)))
        gated = level < g.min_level_db or (g.gate == "voice" and (vp is None or vp < g.vad_threshold))
        return {"azimuth_deg": None if gated or conf <= 0 else az, "confidence": 0.0 if gated else conf,
                "level_db": level, "voice_prob": vp, "peak": peak}


class CircularSmoother:
    """Exponential smoothing of azimuths on the unit circle, weighted by confidence; restarts after a silence."""

    def __init__(self, alpha=0.5, reset_s=0.6):
        self.alpha, self.reset_s = float(alpha), float(reset_s)
        self._v, self._t = None, None

    def update(self, az, conf, t):
        if az is None or conf <= 0:
            return None
        v = np.array([math.cos(math.radians(az)), math.sin(math.radians(az))])
        if self._v is None or self._t is None or t - self._t > self.reset_s:
            self._v = v
        else:
            a = self.alpha * max(0.2, min(1.0, conf))
            self._v = (1 - a) * self._v + a * v
        self._t = t
        return wrap180(math.degrees(math.atan2(self._v[1], self._v[0])))
