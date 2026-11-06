"""Tests of the 360-degree sound layer (lot C2, 2026-11-04): nanterino/sound, the Brain hook, the micro sound triad.

logging: robotlog via tests.test_brain_graph (imported through tests.test_nodes_n1 for the shared helpers).

Purpose
    angles (wrap-around sectors), sources (sim, honest mono, vendor placeholder, fallbacks, the reSpeaker XVF3800
    backend of lot L44 on a FAKE usb device: protocol decode, units, front offset, permission denied, unplug), DOA (GCC-PHAT pairs and
    SRP-PHAT on SYNTHETIC multi-channel plane waves from known angles, with noise: error <= 10 degrees on a 4-mic
    circle of radius 32 mm, CPU time per frame printed), the array source path without a device, the tracker (front
    offset applied once and persisted atomically, history ring, freshness / confidence / level gates), the Brain hook
    (sound_from_direction posted only when listened to, anti-burst throttling, never by mono, never when deaf), the
    three nodes (trigger sectors, condition between two angles across 180, action turn_toward_sound on a simulated
    body: bounded, saturated, wheels untouched), the API handlers, the vocabulary goldens changing only additively
    (pre-C2 copies), the server routes and the dashboard module (static checks).
Boundary
    The live microphone is NEVER opened (no ArraySoundSource.start(), mono reads a fake mic); nanterino.server is never
    imported. Temporary files under /tmp/test_sound.
How to run (repo root)
    .venv/bin/python -m tests.test_sound            # ~10 s; --only name1,name2
    prints PASS / FAIL lines, `doa accuracy` / `doa cpu` lines and `sound tests: n/n passed`
"""
import datetime
import json
import math
import os
import shutil
import sys
import time

sys.path.insert(0, "/opt/robot/lib")
import numpy as np  # noqa: E402

from nanterino import graph as G, graph_visual as V, nodes, sim  # noqa: E402
from nanterino import sound as S  # noqa: E402
from nanterino.brain import Brain  # noqa: E402
from nanterino.sound import api as A, doa as D  # noqa: E402
from nanterino.sound.angles import SECTORS, angle_diff, circular_mean, in_sector, sector_of, wrap180  # noqa: E402
from nanterino.sound.array_source import ArraySoundSource  # noqa: E402
from nanterino.sound.sources import (MonoLevelSource, NotConfiguredError, SimSoundSource,  # noqa: E402
                                     VendorDoaSource)
from nanterino.sound.tracker import SCHEMA, CalibrationStore, SoundTracker  # noqa: E402
from nanterino.sound.turn import turn_head_toward  # noqa: E402
from tests.test_nodes_n1 import GOLDEN, MONDAY, act, counter, guard, ints, strip_ids  # noqa: E402
from tests.test_graph_vars import CFG, mini, parse, refused  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = "/tmp/test_sound"
# The lot C2 node ids (strip them and the vocabulary is the pre-C2 golden byte for byte).
C2 = {"triggers": ["sound_from_direction"], "actions": ["turn_toward_sound"], "conditions": ["sound_direction_between"]}
REPORT = {}


def strip_c2(v: dict) -> dict:
    """The vocabulary without the lot C2 entries (used first by tests.test_nodes_n3.strip_n3). The entries of the later
    lot B1 (Mouvement theme) leave first (tests.test_nodes_motion.strip_b1), so every older additive check keeps working."""
    from tests.test_nodes_motion import strip_b1   # lazy: tests.test_nodes_motion imports the N1 helpers
    return strip_ids(strip_b1(v), C2)


def fresh_tmp():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    return TMP


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


# ---------------------------------------------------------------- synthetic array signals
def plane_wave(geom, az_deg, rng, snr_db=20.0, kind="noise", n=None, amp=0.1):
    """(n, M) far-field plane wave from azimuth az_deg (robot frame, + = left): mic m hears s(t + p_m.u / c), exact
    fractional delays in the frequency domain; independent white noise per mic at `snr_db`. kind = noise (white
    noise source) | voice (vibrato harmonic series 140 Hz with an amplitude envelope)."""
    n = n or geom.frame
    rate, L = geom.rate, 4 * n
    if kind == "noise":
        s = rng.standard_normal(L)
    else:
        t = np.arange(L) / rate
        ph = 2 * np.pi * np.cumsum(140 + 20 * np.sin(2 * np.pi * 3 * t)) / rate
        s = sum(np.sin(k * ph) / k for k in range(1, 20)) * (1 + 0.5 * np.sin(2 * np.pi * 4 * t))
    Sf, f = np.fft.rfft(s), np.fft.rfftfreq(L, 1 / rate)
    u = np.array([math.cos(math.radians(az_deg)), math.sin(math.radians(az_deg)), 0.0])
    x = np.stack([np.fft.irfft(Sf * np.exp(2j * np.pi * f * (p @ u) / D.SPEED_OF_SOUND), n=L) for p in geom.positions],
                 axis=1)[n:2 * n]
    x = x / np.max(np.abs(x)) * amp
    sig = np.sqrt(np.mean(x ** 2))
    return x + rng.standard_normal(x.shape) * sig / (10 ** (snr_db / 20))


ANGLES = (-179, -150, -120, -90, -60, -30, -10, 0, 15, 45, 75, 90, 120, 150, 179, 180)


# ---------------------------------------------------------------- angles
def test_wrap_and_sectors():
    assert [wrap180(a) for a in (0, 180, -180, 190, -190, 360, 540, -540, 721)] == [0, 180, 180, -170, 170, 0, 180, 180, 1]
    assert sector_of(0) == "avant" and sector_of(44.9) == "avant" and sector_of(45) == "gauche"
    assert sector_of(-45) == "avant" and sector_of(-45.1) == "droite" and sector_of(180) == "arriere"
    assert sector_of(-135) == "droite" and sector_of(135) == "arriere" and sector_of(-179) == "arriere"
    for az in range(-180, 181, 5):   # the named sectors tile the circle: exactly one each
        assert sum(in_sector(az, a, b, include_end=False) for a, b in SECTORS.values()) == 1, az
    assert abs(circular_mean([170, -170]) - 180) < 1e-6 and circular_mean([0, 180]) is None
    assert angle_diff(-179, 179) == 2 and angle_diff(10, 350) == 20


def test_in_sector_wrap_around():
    assert in_sector(180, 135, -135) and in_sector(-170, 135, -135) and in_sector(140, 135, -135)
    assert not in_sector(0, 135, -135) and not in_sector(90, 135, -135) and not in_sector(-90, 135, -135)
    assert in_sector(0, -45, 45) and not in_sector(90, -45, 45) and not in_sector(180, -45, 45)
    assert in_sector(-5, 350, 20) and in_sector(15, 350, 20) and not in_sector(30, 350, 20)
    assert in_sector(123, 10, 10) and in_sector(-77, 0, 360)          # a == b (mod 360): the whole circle
    assert in_sector(45, -45, 45) and not in_sector(45, -45, 45, include_end=False)


# ---------------------------------------------------------------- sources
def test_sim_source():
    src = SimSoundSource()
    assert src.poll(0).azimuth_deg is None and src.poll(0).level_db == -90.0
    src.set(270, -15, 0.8, now=0)
    r = src.poll(1)
    assert (r.azimuth_deg, r.level_db, r.confidence) == (-90.0, -15.0, 0.8)
    src.set(30, hold_s=1.0, now=10)
    assert src.poll(10.5).azimuth_deg == 30 and src.poll(11.1).azimuth_deg is None
    src.script([(1.0, 10, -20), (0.5, None, -90), (1.0, -100, -30)], now=20)
    assert [src.poll(t).azimuth_deg for t in (20.2, 21.2, 21.7, 23.0)] == [10, None, -100, None]
    src.random(now=0)
    seen = {src.poll(t).azimuth_deg is not None for t in np.arange(0, 60, 0.5)}
    assert seen == {True, False}
    src.clear()
    assert src.poll(100).azimuth_deg is None
    noisy = SimSoundSource(seed=3, noise_deg=4.0)
    noisy.set(0, now=0)
    vals = [noisy.poll(t).azimuth_deg for t in range(50)]
    assert 0 < np.std(vals) < 8 and abs(np.mean(vals)) < 3


def test_mono_is_honest():
    rec = sim.Rec()
    mic = sim.FakeIn(rec)
    src = MonoLevelSource(mic)
    r = src.poll(1.0)
    assert r.azimuth_deg is None and r.level_db is None and r.confidence == 0, r      # closed mic: no level at all
    mic.start()
    mic.level = 0.5
    r = src.poll(2.0)
    assert r.azimuth_deg is None and r.confidence == 0 and abs(r.level_db - 20 * math.log10(0.5)) < 1e-6, r
    clock = Clock(2.0)
    tr = SoundTracker(src, clock=clock)
    tr.poll()
    assert tr.direction() is None and tr.level() is not None
    ok, err = tr.set_front_current()
    assert not ok and "ne mesure pas de direction" in err, err
    st = tr.state()
    assert st["backend"] == "mono" and not st["gives_direction"] and "mono" in st["message"] and st["direction"] is None
    assert MonoLevelSource(None).poll(0).level_db is None


def test_vendor_placeholder_and_fallbacks():
    for model in (None, "respeaker_usb_v2"):
        try:
            VendorDoaSource(model)
        except NotConfiguredError as e:
            assert "HOWTO-sound360" in str(e), e
        else:
            raise AssertionError("vendor source constructed without a driver")
    tr = S.create({"sound_backend": "vendor"})
    assert tr.source.name == "mono" and tr.configured == "vendor" and "sound_vendor_model" in tr.backend_error
    assert "indisponible" in tr.state()["message"]
    for cfg, exc in (({"sound_backend": "vendor"}, NotConfiguredError), ({"sound_backend": "laser"}, ValueError),
                     ({"sound_backend": "array", "sound_array_geometry": "/nonexistent.yaml"}, NotConfiguredError)):
        try:
            S.create(cfg, strict=True)
        except exc:
            pass
        else:
            raise AssertionError("strict create accepted %r" % cfg)
    assert S.create({}).source.name == "mono"                          # default = today's behaviour
    assert S.create({"sound_backend": "array"}).source.name == "array"  # placeholder geometry loads, nothing opened
    assert S.create({"sound_backend": "sim"}).source.name == "sim"


# ---------------------------------------------------------------- DOA
def test_geometry_file_and_validation():
    g = D.load_geometry(S.DEFAULT_GEOMETRY)
    assert g.positions.shape == (4, 3) and g.rate == 16000 and g.gate == "level"
    assert abs(np.linalg.norm(g.positions[1]) - 0.032) < 1e-9 and g.positions[1][1] > 0     # mic 1 on the LEFT (+y)
    base = {"rate": 16000, "mics": [{"x": 30, "y": 0}, {"x": -30, "y": 0}]}
    D.geometry_from_dict(base)
    for bad, frag in (({"rate": 11025}, "rate"), ({"mics": [{"x": 1}]}, "au moins 2"),
                      ({"mics": [{"x": 0, "y": 0, "z": 0}, {"x": 0, "y": 0, "z": 50}]}, "verticalement"),
                      ({"mics": [{"x": 1, "y": 0}, {"x": 1, "y": 0}]}, "même position"),
                      ({"frame": 1000}, "puissance de 2"), ({"band_hz": [300, 9000]}, "band_hz"),
                      ({"gate": "always"}, "gate"), ({"channels": 1}, "channels"),
                      ({"mics": [{"channel": 0, "x": 30}, {"channel": 0, "x": -30}]}, "même voie")):
        try:
            D.geometry_from_dict(dict(base, **bad))
        except ValueError as e:
            assert frag in str(e), (frag, str(e))
        else:
            raise AssertionError("geometry accepted: %r" % bad)


def test_gcc_phat_pairs():
    rng = np.random.default_rng(7)
    rate, n = 16000, 4096
    s = rng.standard_normal(n + 64)
    for delay in (0.0, 1.0, 2.5, -3.25):
        Sf, f = np.fft.rfft(s), np.fft.rfftfreq(len(s), 1 / rate)
        y = np.fft.irfft(Sf * np.exp(-2j * np.pi * f * delay / rate), n=len(s))   # y = x delayed by `delay` samples
        tau = D.gcc_phat(s[:n], y[:n], rate, max_tau=0.001)
        assert abs(tau * rate - delay) < 0.1, (delay, tau * rate)


def test_doa_synthetic_accuracy():
    g = D.circular_geometry(4, 32.0)
    est = D.DoaEstimator(g)
    rng = np.random.default_rng(1)
    worst = {}
    for kind, snrs in (("noise", (20, 10, 5, 0)), ("voice", (20, 10))):
        for snr in snrs:
            errs = []
            for az in ANGLES:
                r = est.analyse(plane_wave(g, az, rng, snr, kind))
                assert r["azimuth_deg"] is not None, (kind, snr, az, r)
                errs.append(abs(angle_diff(r["azimuth_deg"], az)))
            worst["%s@%ddB" % (kind, snr)] = (round(max(errs), 2), round(float(np.mean(errs)), 2))
            assert max(errs) <= 10.0, (kind, snr, errs)
    REPORT["doa accuracy (4 mics, r=32 mm, 16 kHz, 16 angles; max / mean error deg)"] = worst
    x = plane_wave(g, 30, rng, 20)
    est.analyse(x)
    t0, N = time.thread_time(), 100
    for _ in range(N):
        est.analyse(x)
    ms = 1000 * (time.thread_time() - t0) / N
    REPORT["doa cpu"] = "%.2f ms per 64 ms frame (%.1f %% of one core at 15.6 frames/s)" % (ms, ms * 15.6 / 10)
    assert ms < 20, ms   # budget: well under the 64 ms hop on one Orin core


def test_doa_confidence_and_gates():
    g = D.circular_geometry(4, 32.0)
    est = D.DoaEstimator(g)
    rng = np.random.default_rng(2)
    high = est.analyse(plane_wave(g, 60, rng, 20))
    assert high["confidence"] > 0.9 and abs(angle_diff(high["azimuth_deg"], 60)) < 3, high
    diffuse = [est.analyse(rng.standard_normal((g.frame, 4)) * 0.05) for _ in range(20)]
    assert all(d["confidence"] < 0.1 for d in diffuse), [d["confidence"] for d in diffuse]   # no direction in noise
    silent = est.analyse(np.zeros((g.frame, 4)))
    assert silent["azimuth_deg"] is None and silent["confidence"] == 0 and silent["level_db"] == -120.0
    quiet = est.analyse(plane_wave(g, 60, rng, 20, amp=1e-4))            # coherent but below min_level_db (-50)
    assert quiet["level_db"] < -50 and quiet["azimuth_deg"] is None and quiet["confidence"] == 0, quiet
    vg = D.DoaEstimator(D.circular_geometry(4, 32.0, gate="voice"))
    assert vg.analyse(np.zeros((g.frame, 4)))["azimuth_deg"] is None
    six = D.DoaEstimator(D.circular_geometry(6, 46.0))                   # any N: a 6-mic circle works the same
    r = six.analyse(plane_wave(six.geom, -120, rng, 10))
    assert abs(angle_diff(r["azimuth_deg"], -120)) <= 5, r


def test_array_source_without_device():
    g = D.circular_geometry(4, 32.0)
    src = ArraySoundSource(g)
    assert src.poll(0) is None and src._stream is None                   # nothing captured, nothing opened
    rng = np.random.default_rng(3)
    for k in range(5):
        r = src.process_block(plane_wave(g, 60, rng, 10), t=k * 0.064)
    assert abs(angle_diff(src.poll(1).azimuth_deg, 60)) < 4 and src.stats()["frames"] == 5
    assert src.stats()["cpu_ms_mean"] is not None and src.info()["stats"]["frame_ms"] == 64.0
    # smoothing across +-180: 179 then -179 stays near 180, never jumps through 0
    for k, az in enumerate((179, -179, 179, -179)):
        r = src.process_block(plane_wave(g, az, rng, 20), t=10 + k * 0.064)
    assert abs(angle_diff(r.azimuth_deg, 180)) < 5, r
    r = src.process_block(np.zeros((g.frame, 4)), t=20)
    assert r.azimuth_deg is None and r.confidence == 0


# ---------------------------------------------------------------- tracker
def test_front_offset_persistence():
    path = os.path.join(fresh_tmp(), "state", "sound-calibration.json")
    clock = Clock()
    src = SimSoundSource()
    tr = SoundTracker(src, CalibrationStore(path), clock=clock)
    assert tr.front_offset == 0 and not os.path.exists(path)
    src.set(60, -20, now=clock.t)
    for _ in range(10):
        clock.t += 0.1
        tr.poll()
    assert tr.direction()["azimuth_deg"] == 60
    ok, err = tr.set_front_current()
    assert ok, err
    assert tr.front_offset == 60 and tr.direction()["azimuth_deg"] == 0 and tr.direction()["raw_azimuth_deg"] == 60
    doc = json.load(open(path, encoding="utf-8"))
    assert doc["schema"] == SCHEMA and doc["front_offset_deg"] == 60 and doc["version"] == 1
    assert [f for f in os.listdir(os.path.dirname(path)) if f.endswith(".tmp")] == []   # atomic: no temp left
    clock.t += 0.1
    assert tr.poll()["azimuth_deg"] == 0
    tr2 = SoundTracker(SimSoundSource(), CalibrationStore(path), clock=clock)        # a restart keeps the front
    assert tr2.front_offset == 60
    src.set(-170, now=clock.t)
    clock.t += 0.1
    assert tr.poll()["azimuth_deg"] == 130                                             # wrap180(-170 - 60)
    assert tr.set_front_offset(-90) == (True, None) and tr.direction()["azimuth_deg"] == -80
    assert tr.set_front_offset("x")[0] is False and tr.set_front_offset(float("nan"))[0] is False
    open(path, "w").write("{broken")
    st = CalibrationStore(path)
    assert st.load() == 0.0 and "illisible" in st.last_error
    json.dump({"schema": "other", "front_offset_deg": 5}, open(path, "w"))
    assert CalibrationStore(path).load() == 0.0


def test_tracker_history_and_gates():
    clock = Clock()
    src = SimSoundSource()
    tr = SoundTracker(src, clock=clock)
    src.set(100, -25, 0.9, now=clock.t)
    for _ in range(40):                       # 4 s at 10 Hz (the brain heartbeat)
        clock.t += 0.1
        tr.poll()
    h = tr.history(1.0)
    assert 10 <= len(h) <= 11 and all(x["azimuth_deg"] == 100 for x in h) and "mono_t" not in h[0], len(h)
    assert len(tr.history(1000)) == 40 and tr.history(0)[-1]["azimuth_deg"] == 100
    clock.t += 1.5                            # stale
    assert tr.direction() is None and tr.level() is None
    src.set(100, -25, 0.4, now=clock.t)       # not confident enough
    tr.poll()
    assert tr.direction() is None
    src.set(100, -70, 1.0, now=clock.t)       # below the level gate
    tr.poll()
    assert tr.direction() is None
    src.set(100, -30, 1.0, now=clock.t)
    tr.poll()
    assert tr.direction()["azimuth_deg"] == 100


# ---------------------------------------------------------------- brain + nodes
def sbrain(raw, source=None, body=None, **cfg):
    """Non-threaded Brain of the fake world (tests.test_nodes_n1.brain) with an injected sound tracker."""
    clock = sim.SimClock()
    t0, wall0 = clock.t, datetime.datetime.fromisoformat(MONDAY).timestamp()
    rec, tts = sim.Rec(), sim.FakeTTS()
    out = sim.FakeOut(rec, tts, clock)
    wall = lambda: wall0 + (clock.t - t0)   # noqa: E731
    mic = sim.FakeIn(rec)
    tracker = None if source is None else SoundTracker(source, clock=clock, wall=wall)
    b = Brain(dict(CFG, power="on", **cfg), out, sim.FakeSTT(), sim.FakeLLM(rec), tts, sim.FakeCorpus(), clock=clock,
              wall=wall, mic=mic, graph=parse(raw), threaded=False, start_state="veille", sound=tracker, body=body)
    b.rng.seed(0)
    b.pump()
    return b, clock, rec


def run(b, clock, seconds):
    for _ in range(int(round(seconds / 0.1))):
        clock.t += 0.1
        b._on_tick({"t": clock.t})
        b.pump()


def counters():
    return mini(glob=[counter("sound_from_direction", "n"), counter("sound_from_direction", "g", value="gauche"),
                      counter("sound_from_direction", "d", value="arriere")], variables=ints("n", "g", "d"))


def test_trigger_posted_and_throttled():
    src = SimSoundSource()
    b, clock, _ = sbrain(counters(), src)
    v = lambda: (b.var_value("n"), b.var_value("g"), b.var_value("d"))   # noqa: E731
    src.set(90, -20, now=clock.t)
    run(b, clock, 3.0)                          # one continuous sound on the left: ONE event
    assert v() == (1, 1, 0), v()
    src.clear()
    run(b, clock, 1.0)                          # silence re-arms
    src.set(170, -20, now=clock.t)
    run(b, clock, 1.0)
    assert v() == (2, 1, 1), v()
    for k in range(10):                         # a burst of side changes every 0.2 s for 2 s
        src.set(90 if k % 2 else 0, -20, now=clock.t)
        run(b, clock, 0.2)
    n = b.var_value("n")
    assert 3 <= n <= 5, n                       # at most one post per SOUND_EVENT_GAP_S (2 s -> 2 more, +1 boundary)
    src.set(10, -20, 0.3, now=clock.t)          # not confident: nothing
    run(b, clock, 2.0)
    src.clear()
    run(b, clock, 1.0)
    before = b.var_value("n")
    src.set(10, -20, 0.3, now=clock.t)
    run(b, clock, 2.0)
    assert b.var_value("n") == before


def test_trigger_never_from_mono_unlistened_or_deaf():
    b, clock, _ = sbrain(counters())            # default tracker = mono on the fake mic
    assert b.sound.source.name == "mono"
    b.mic.start()
    b.mic.level = 0.9
    run(b, clock, 2.0)
    assert b.var_value("n") == 0
    src = SimSoundSource()
    b, clock, _ = sbrain(mini(glob=[{"on": "start", "do": [], "to": "a"}]), src)
    posts = []
    b.post = lambda kind, **kw: posts.append(kind)
    src.set(90, now=clock.t)
    for _ in range(20):
        clock.t += 0.1
        b._on_tick({"t": clock.t})
    assert "sound_from_direction" not in posts  # nobody listens: never posted
    del b.post
    b, clock, _ = sbrain(counters(), src, deaf=True)
    src.set(90, now=clock.t)
    run(b, clock, 2.0)
    assert b.var_value("n") == 0                # a deaf robot does not react to sounds


def test_trigger_parser_and_visual():
    raw = counters()
    want = parse(raw).to_dict()
    back, _layout, errs = V.from_visual(V.to_visual(json.loads(json.dumps(raw))), CFG)
    assert not errs and parse(back).to_dict() == want, errs
    refused(mini(glob=[counter("sound_from_direction", "n", value="haut")], variables=ints("n")), "must be one of")
    refused(mini(glob=[counter("sound_from_direction", "n", var="n")], variables=ints("n")), "takes no `var:`")
    v = G.vocabulary(CFG)
    ev = next(e for e in v["events"] if e["id"] == "sound_from_direction")
    assert ev["theme"] == "micro" and ev["args"][0]["type"] == "enum" and ev["args"][0]["options"] == list(SECTORS)
    gd = next(g for g in v["guards"] if g["id"] == "sound_direction_between")
    assert [a["name"] for a in gd["args"]] == ["start", "end"] and gd["theme"] == "micro"
    ac = next(a for a in v["actions"] if a["id"] == "turn_toward_sound")
    assert ac["theme"] == "micro" and ac["args"] == []
    assert "sound_from_direction" in G.WATCH_EVENTS


def test_condition_sound_direction_between():
    src = SimSoundSource()
    b, clock, _ = sbrain(mini(), src)
    assert not guard(b, "sound_direction_between", start=-180, end=180)   # nothing heard yet
    src.set(170, -20, now=clock.t)
    run(b, clock, 0.3)
    assert guard(b, "sound_direction_between", start=135, end=-135)       # behind, across 180
    assert not guard(b, "sound_direction_between", start=-45, end=45)
    assert not guard(b, "sound_direction_between", start=-135, end=135)   # the front 270 degrees, not the back
    src.set(-20, -20, now=clock.t)
    run(b, clock, 0.3)
    assert guard(b, "sound_direction_between", start=-45, end=45) and guard(b, "sound_direction_between", start=340, end=0)
    src.clear()
    run(b, clock, 1.5)
    assert not guard(b, "sound_direction_between", start=-45, end=45)    # stale -> false


def test_action_turn_toward_sound():
    src = SimSoundSource()
    b, clock, _ = sbrain(mini(), src)
    events = []
    b.body.add_event_hook(events.append)
    src.set(40, -20, now=clock.t)
    run(b, clock, 0.2)
    act(b, "turn_toward_sound")
    run(b, clock, 3.0)
    js = {j["id"]: j for j in b.body.state()["joints"]}
    assert abs(js["head_pan"]["position"] - 40) < 0.06, js["head_pan"]
    for w in ("base_left_wheel", "base_right_wheel"):
        assert js[w]["target"] == 0 and js[w]["position"] == 0 and js[w]["velocity"] == 0, js[w]
    assert any(e["kind"] == "arrived" for e in events) and not any(e["kind"] in ("clamp", "refused") for e in events)
    src.set(150, -20, now=clock.t)               # beyond the head range [-90, 90]: saturated, never the wheels
    run(b, clock, 0.2)
    res = turn_head_toward(b.body, b.sound.direction()["azimuth_deg"])
    assert res["saturated"] and res["pan"] == 90 and res["requested"] == 150 and res["ok"], res
    run(b, clock, 3.0)
    js = {j["id"]: j for j in b.body.state()["joints"]}
    assert abs(js["head_pan"]["position"] - 90) < 0.06 and js["base_left_wheel"]["position"] == 0
    src.set(-120, -20, now=clock.t)
    run(b, clock, 0.2)
    act(b, "turn_toward_sound")
    run(b, clock, 4.0)
    assert abs(b.body.state()["joints"][0]["position"] + 90) < 0.06
    src.clear()                                  # no direction: nothing moves
    run(b, clock, 1.5)
    n = len(events)
    act(b, "turn_toward_sound")
    run(b, clock, 1.0)
    assert len(events) == n and abs(b.body.state()["joints"][0]["position"] + 90) < 0.06
    b.body.stop_all("test")                      # latched e-stop: refused, reported
    src.set(0, now=clock.t)
    run(b, clock, 0.2)
    res = turn_head_toward(b.body, 0)
    assert not res["ok"] and "urgence" in res["error"], res
    b.body.reset_estop()
    # the head limits are the calibrated ones (Body), not a constant
    b.body.set_calibration({"head_pan": {"max": 30}})
    assert turn_head_toward(b.body, 60)["pan"] == 30


# ---------------------------------------------------------------- API
def test_api_handlers():
    clock = Clock()
    tr = SoundTracker(SimSoundSource(), clock=clock)
    st, s = A.state(tr)
    # L45: the handler polls the source itself, so `last` is the silent sim reading (no azimuth), not None
    assert st == 200 and s["backend"] == "sim" and s["last"]["azimuth_deg"] is None and s["direction"] is None
    assert A.front(tr, None)[0] == 400 and A.front(tr, {})[0] == 400
    assert A.front(tr, {"set_current": True})[0] == 409                    # silence: no dominant direction
    assert A.sim(tr, {"azimuth": "x"})[0] == 400 and A.sim(tr, {"azimuth": 10, "level": 5})[0] == 400
    assert A.sim(tr, None)[0] == 400
    assert A.sim(tr, {"azimuth": 30, "level": -25}) == (200, {"ok": True})
    for _ in range(5):
        clock.t += 0.1
        tr.poll()
    assert tr.direction()["azimuth_deg"] == 30
    st, r = A.front(tr, {"set_current": True})
    assert st == 200 and r["front_offset_deg"] == 30
    assert A.sim(tr, {"azimuth": 90})[0] == 200 and tr.direction()["azimuth_deg"] == 90   # calibrated frame in and out
    assert tr.direction()["raw_azimuth_deg"] == 120
    assert A.front(tr, {"offset_deg": "a"})[0] == 400 and A.front(tr, {"offset_deg": 0})[1]["front_offset_deg"] == 0
    st, h = A.history(tr, "2")
    assert st == 200 and h["seconds"] == 2 and h["samples"]
    assert A.history(tr, "x")[0] == 400 and A.history(tr, "-1")[0] == 400 and A.history(tr, "999")[1]["seconds"] == 60
    assert A.sim(tr, {"clear": True})[0] == 200 and A.sim(tr, {"random": True})[0] == 200
    mk = lambda n: S.make_source(n, {}, None)   # noqa: E731
    assert A.backend(tr, {"backend": "array"}, mk)[0] == 400 and A.backend(tr, None, mk)[0] == 400
    assert A.backend(tr, {"backend": "mono"}, mk) == (200, {"ok": True, "backend": "mono"})
    assert A.sim(tr, {"azimuth": 10})[0] == 409                              # sim control only on the sim backend
    assert A.front(tr, {"set_current": True})[0] == 409
    assert A.backend(tr, {"backend": "sim"}, mk)[1]["backend"] == "sim" and tr.configured == "sim"
    assert [A.stream_hz(x) for x in (None, "x", "0", "100", "10", "nan")] == [15.0, 15.0, 1.0, 20.0, 10.0, 15.0]
    assert set(A.stream_frame(tr)) == {"backend", "configured", "error", "message", "gives_direction", "last",
                                       "direction", "front_offset_deg", "min_confidence", "t"}
    json.dumps(tr.state())


# ---------------------------------------------------------------- reSpeaker XVF3800 (lot L44, fake USB device)
class FakeXvf:
    """Answers vendor control transfers like the XVF3800 (status byte + little-endian payload)."""

    def __init__(self, doa=90, speech=1, beams=(1.0, 2.0, 3.0, 1.5708), energies=(0, 0, 0, 0), retry_first=0, exc=None):
        self.doa, self.speech, self.beams, self.energies = doa, speech, beams, energies
        self.retry, self.exc, self.calls = retry_first, exc, []

    def ctrl_transfer(self, rt, req, value, index, length, timeout=None):
        import struct
        self.calls.append((rt, req, value, index, length))
        if self.exc is not None:
            raise self.exc
        if self.retry > 0:
            self.retry -= 1
            return bytes([64]) + bytes(length - 1)
        if (index, value) == (20, 0x92):
            return bytes([0]) + struct.pack("<HH", self.doa, self.speech)
        if (index, value) == (33, 0xCB):
            return bytes([0]) + struct.pack("<ffff", *self.beams)
        if (index, value) == (33, 0xD0):
            return bytes([0]) + struct.pack("<ffff", *self.energies)
        return bytes([1]) + bytes(length - 1)


class FakeUsbError(OSError):
    """Stands for usb.core.USBError (errno 13 = access denied)."""


def test_xvf3800_protocol_decode():
    from nanterino.sound import xvf3800 as X
    dev = FakeXvf(doa=218, speech=1, retry_first=2)
    assert X.read_param(dev, "DOA_VALUE") == (218, 1)
    assert dev.calls[-1] == (0xC0, 0, 0x92, 20, 5)                       # vendor IN, 0x80|18, resid 20, 1+4 bytes
    assert len(dev.calls) == 3                                           # two « retry » statuses re-asked
    b = X.read_param(FakeXvf(beams=(3.804, 5.017, 3.155, 3.155)), "AEC_AZIMUTH_VALUES")
    assert abs(b[0] - 3.804) < 1e-5 and len(b) == 4
    assert X.read_param(dev, "AEC_SPENERGY_VALUES") == (0.0, 0.0, 0.0, 0.0) and dev.calls[-1][:4] == (0xC0, 0, 0xD0, 33)
    for raw in (b"", bytes([1, 0, 0, 0, 0]), bytes([0, 1, 2])):
        try:
            X.decode_response(raw, "<HH")
        except X.ControlError:
            pass
        else:
            raise AssertionError("bad answer accepted: %r" % (raw,))
    try:
        X.read_param(FakeXvf(retry_first=10 ** 6), "DOA_VALUE")
    except X.ControlError as e:
        assert "réessayer" in str(e)
    else:
        raise AssertionError("endless retry accepted")


def test_xvf3800_units_and_front_offset():
    from nanterino.sound import xvf3800 as X
    assert X.to_azimuth(90) == 90 and X.to_azimuth(270) == -90 and X.to_azimuth(359) == -1 and X.to_azimuth(180) == 180
    assert X.to_azimuth(90, -1) == -90
    az, conf, voice, lvl, e = X.interpret(100, 1, (0.0,) * 4)
    assert (az, conf, voice) == (100, 1.0, 1.0) and lvl == X.LEVEL_SPEECH_DB
    az, conf, _v, lvl, e = X.interpret(100, 0, (0.0, 0.5, 0.0, 0.0), beam_auto_rad=math.pi / 2)
    assert abs(az - 90) < 1e-6 and conf == 0.6 and lvl == X.LEVEL_ENERGY_DB and e == 0.5   # clap: auto beam, radians
    assert X.interpret(100, 0, (0.0,) * 4) == (None, 0.0, 0.0, X.LEVEL_NONE_DB, 0.0)        # never a made-up angle
    # through the tracker: raw 100 deg, front offset 100 -> straight ahead
    src = X.Xvf3800Source(device_factory=lambda: FakeXvf(doa=100))
    src._dev = src._factory()
    r = src.read_once(now=5.0)
    assert r.azimuth_deg == 100 and r.confidence == 1.0 and src.raw["doa_deg"] == 100
    clock = Clock(5.0)
    tr = SoundTracker(src, clock=clock)
    src.poll = lambda now: r
    tr.poll()
    assert tr.set_front_current()[0] and tr.front_offset == 100
    tr.poll()
    assert tr.direction()["azimuth_deg"] == 0


def test_xvf3800_gate_and_hold():
    """Lot L45: a speech-flag gap shorter than HOLD_S keeps the last voiced angle with a fading confidence; silence
    longer than HOLD_S gives NO angle; the stream / state handlers poll the source themselves."""
    from nanterino.sound import xvf3800 as X
    dev = FakeXvf(doa=40, speech=1)
    src = X.Xvf3800Source(device_factory=lambda: dev)
    src._dev = src._factory()
    r = src.read_once(now=10.0)
    assert r.azimuth_deg == 40 and r.confidence == 1.0 and src.raw["held"] is False
    dev.speech, dev.doa = 0, 300                     # flag drops between two words (chip doa drifts meanwhile)
    r = src.read_once(now=10.1)
    assert r.azimuth_deg == 40 and src.raw["held"] is True, r          # held angle, not the drifting raw doa
    assert abs(r.confidence - 0.8) < 1e-6 and r.level_db == X.LEVEL_ENERGY_DB
    r = src.read_once(now=10.2)
    assert abs(r.confidence - 0.6) < 1e-6
    # through the tracker: direction() (conf >= 0.5) during the first half of the hold only
    clock = Clock(10.2)
    tr = SoundTracker(src, clock=clock)
    src.poll = lambda now, r=r: r
    tr.poll()
    assert tr.direction() is not None and tr.direction()["azimuth_deg"] == 40
    late = src.read_once(now=10.4)                    # 0.4 s after the voice: still drawn, too weak for the nodes
    assert late.azimuth_deg == 40 and 0 < late.confidence < 0.5, late
    gone = src.read_once(now=10.0 + X.HOLD_S + 0.01)  # silence longer than the hold: no invented angle
    assert gone.azimuth_deg is None and gone.confidence == 0.0 and src.raw["held"] is False
    assert src.read_once(now=20.0).azimuth_deg is None
    dev.speech = 1                                   # voice again: a fresh angle, no stale hold
    assert src.read_once(now=20.1).azimuth_deg == -60
    dev.speech, dev.energies = 0, (0.0, 2.5e4, 0.0, 0.0)    # clap: energy only -> auto-select beam, confidence 0.6
    r = src.read_once(now=20.2)
    assert r.confidence == 0.6 and src.raw["held"] is False and abs(r.azimuth_deg - 90) < 1e-3
    # handlers poll: a reading appears in GET state / the stream without any heartbeat poll
    sim = SimSoundSource()
    tr2 = SoundTracker(sim, clock=Clock(1.0))
    sim.set(25.0, -20.0, 1.0, now=1.0)
    assert tr2.state()["last"] is None
    assert A.stream_frame(tr2)["last"]["azimuth_deg"] == 25.0
    polls = tr2.polls
    assert A.state(tr2)[1]["last"]["azimuth_deg"] == 25.0 and tr2.polls == polls + 1


def test_xvf3800_reasons_and_fallback():
    from nanterino.sound import xvf3800 as X
    denied = FakeUsbError(13, "Access denied (insufficient permissions)")
    try:
        X.Xvf3800Source(device_factory=lambda: FakeXvf(exc=denied)).start()
    except NotConfiguredError as e:
        assert "Accès USB refusé" in str(e) and "install-respeaker-udev.sh" in str(e), e
    else:
        raise AssertionError("permission denied accepted")
    assert X.find_device(lambda **kw: None) is None and not X.detect(lambda **kw: None)
    assert X.detect(lambda **kw: object())
    orig = S.make_source
    try:
        S.make_source = lambda name, cfg=None, mic=None: X.Xvf3800Source(device_factory=lambda: FakeXvf(exc=denied))
        tr = S.create({"sound_backend": "xvf3800"}, start=True)           # real create(): falls back to mono + reason
        st = tr.state()
        assert tr.source.name == "mono" and "Accès USB refusé" in tr.backend_error
        assert st["available"] is False and "Accès USB refusé" in st["reason"] and "indisponible" in st["message"]
        try:
            S.create({"sound_backend": "xvf3800"}, strict=True, start=True)
        except NotConfiguredError:
            pass
        else:
            raise AssertionError("strict create swallowed the error")
    finally:
        S.make_source = orig
    # auto: device absent -> plain mono without any error; present -> the reSpeaker backend (not started here)
    orig_detect = X.detect
    try:
        X.detect = lambda find=None: False
        tr = S.create({"sound_backend": "auto"})
        assert tr.source.name == "mono" and tr.backend_error is None and tr.state()["available"] is True
        X.detect = lambda find=None: True
        tr = S.create({"sound_backend": "auto"})
        assert tr.source.name == "xvf3800" and tr.configured == "auto"
        assert S.create({"sound_backend": "mono"}).source.name == "mono"      # an explicit name always wins
        assert S.make_source("vendor", {"sound_vendor_model": "xvf3800"}).name == "xvf3800"
    finally:
        X.detect = orig_detect


def test_xvf3800_thread_and_unplug():
    from nanterino.sound import xvf3800 as X
    dev = FakeXvf(doa=200, speech=1)
    src = X.Xvf3800Source(hz=30, device_factory=lambda: dev)
    src.start()
    try:
        t0 = time.time()
        r = None
        while time.time() - t0 < 3 and r is None:
            r = src.poll(0)
            time.sleep(0.02)
        assert r is not None and r.azimuth_deg == -160 and r.confidence == 1.0, r
        assert src.info()["available"] is True and src.info()["gives_direction"] is True
        dev.exc = FakeUsbError(19, "No such device (it may have been disconnected)")      # unplugged
        t0 = time.time()
        while time.time() - t0 < 3 and src.info()["available"]:
            time.sleep(0.02)
        info = src.info()
        assert info["available"] is False and "Lecture USB en échec" in info["reason"], info
        assert src.poll(0).azimuth_deg is None and src.poll(0).confidence == 0
    finally:
        src.stop()
    assert src.info()["available"] is False


# ---------------------------------------------------------------- goldens, server, dashboard
def test_goldens_c2_only_gained_entries():
    from tests.test_nodes_registry import golden_diff, vocab_dumps
    dumps = vocab_dumps(G)
    assert not golden_diff(dumps), "the C2 goldens differ: %s" % golden_diff(dumps)
    for name, text in dumps.items():
        with open(os.path.join(GOLDEN, name.replace(".json", ".pre-c2.json")), "rb") as f:
            old = f.read()
        stripped = json.dumps(strip_c2(json.loads(text)), ensure_ascii=False, indent=1) + "\n"
        assert stripped.encode("utf-8") == old, "%s minus the C2 entries is not the pre-C2 golden" % name


def test_shipped_graph_unchanged():
    text = open(G.DEFAULT_PATH, encoding="utf-8").read()
    assert not [i for ids in C2.values() for i in ids if i in text]
    assert nodes.TRIGGERS["sound_from_direction"].theme == "micro"


def test_server_routes_and_dashboard():
    src = open(os.path.join(ROOT, "nanterino", "server.py"), encoding="utf-8").read()
    for needle in ('@app.get("/api/sound/state")', '@app.websocket("/api/sound/stream")', '@app.post("/api/sound/front")',
                   '@app.get("/api/sound/history")', '@app.post("/api/sound/sim")', '@app.post("/api/sound/backend")',
                   "brain.sound = sound", '"sound360.js": "text/javascript"', "sound_mod.RUNTIME_BACKENDS"):
        assert needle in src, needle
    import ast
    ast.parse(src)
    from nanterino import config
    assert config.DEFAULTS["sound_backend"] == "auto"   # L44: reSpeaker when plugged in, else mono
    dash = open(os.path.join(ROOT, "web", "dash.html"), encoding="utf-8").read()
    for needle in ('id="snd"', '/web/dash/sound360.js', '>AVANT<', 'id="snd-front"', 'id="snd-beam"', 'id="snd-msg"',
                   'id="snd-sim"', 'id="snd-head"', 'id="snd-array"'):
        assert needle in dash, needle
    # the module parses as an ES module and touches only allowed browser globals (editor scanner and allow-list)
    from tests import test_web_modules as WM
    d = os.path.join(fresh_tmp(), "dash")
    os.makedirs(d)
    shutil.copy(os.path.join(ROOT, "web", "dash", "sound360.js"), os.path.join(d, "main.js"))
    _paths, probs = WM.analyse(d)
    assert not probs["parse"] and not probs["unused"] and not probs["size"], probs
    assert not probs["free"], probs["free"]


TESTS = [test_wrap_and_sectors, test_in_sector_wrap_around, test_sim_source, test_mono_is_honest,
         test_vendor_placeholder_and_fallbacks, test_geometry_file_and_validation, test_gcc_phat_pairs,
         test_doa_synthetic_accuracy, test_doa_confidence_and_gates, test_array_source_without_device,
         test_front_offset_persistence, test_tracker_history_and_gates, test_trigger_posted_and_throttled,
         test_trigger_never_from_mono_unlistened_or_deaf, test_trigger_parser_and_visual,
         test_condition_sound_direction_between, test_action_turn_toward_sound, test_api_handlers,
         test_xvf3800_protocol_decode, test_xvf3800_units_and_front_offset, test_xvf3800_reasons_and_fallback,
         test_xvf3800_thread_and_unplug, test_xvf3800_gate_and_hold,
         test_goldens_c2_only_gained_entries, test_shipped_graph_unchanged, test_server_routes_and_dashboard]


def main(argv):
    only = argv[argv.index("--only") + 1].split(",") if "--only" in argv else None
    failed = 0
    for fn in TESTS:
        if only and fn.__name__ not in only:
            continue
        try:
            fn()
            print("PASS", fn.__name__, flush=True)
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print("FAIL", fn.__name__, "%s: %s" % (type(e).__name__, e), flush=True)
    for k, v in REPORT.items():
        print("%s: %s" % (k, v))
    shutil.rmtree(TMP, ignore_errors=True)
    ran = len([f for f in TESTS if not only or f.__name__ in only])
    print("sound tests: %d/%d passed" % (ran - failed, ran))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
