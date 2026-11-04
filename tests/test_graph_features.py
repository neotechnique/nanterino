"""Tests of the graph editor's second wave: icons, simulator, new actions / triggers, `enabled`, versions,
live journal, editable intents (logging: robotlog via nanterino.log, through tests.test_brain_graph).

Purpose
    One test per feature of the 2026-10-31 backend lot (see Notes/graph-visual-format.md, "Évolutions"):
    icons registry, opening-hours parser, `enabled: false`, simulator (parity with the real Brain, isolation
    from a live Brain, error cases), say_text cache, set_expression, wait, gaze, personnes_multiples,
    ouverture / fermeture / dans_les_horaires, inactivite_longue, intents (new intent -> event, invalid regex
    -> error naming the intent), versions list / restore, journal of 50 chains.

Boundary
    Most tests use the simulator (virtual clock, no thread, instant). A few use the real threaded Brain with
    the fake world of nanterino/sim.py through tests.test_brain_graph.H (real time, muted). Files go to /tmp.
    The server routes are not imported here (server.py starts the real engines); they are checked live.

How to run (repo root):
    .venv/bin/python -m tests.test_graph_features          # ~25 s
"""
import copy
import datetime
import json
import os
import shutil
import sys
import time

sys.path.insert(0, "/opt/robot/lib")

from nanterino import config, graph as G, graph_visual as V, hours, sim  # noqa: E402
from tests import test_brain_graph as tbg  # noqa: E402

CFG = dict(config.DEFAULTS)
CFG.update(tbg.BASE_CFG)
TMP = "/tmp/test_graph_features"

# The exact list written in Notes/graph-visual-format.md (the web builder vendors these 37 SVGs).
CONTRACT_ICONS = (
    "arrow-right, bell, bolt, calendar-time, circle-dot, clock, door-exit, ear, eraser, eye, flag, git-branch, "
    "hand-move, hand-stop, hourglass, keyboard, lock, lock-open, message, microphone, microphone-off, mood-smile, "
    "moon, music, player-play, plus, power, question-mark, refresh, scan-eye, square, text-caption, user-off, "
    "users, volume, volume-off, x").split(", ")


def default_raw():
    return V.load_raw(G.DEFAULT_PATH)


def mini(veille=(), a=(), b=(), glob=(), intents=None):
    """Tiny raw graph: veille (the start), eteint, a, b. Each argument is a list of raw transitions."""
    def st(trs):
        d = {"description": "état de test"}
        if trs:
            d["transitions"] = [dict(t, description=t.get("description", "test")) for t in trs]
        return d
    raw = {"version": 1, "states": {"veille": st(veille), "eteint": st([]), "a": st(a), "b": st(b)}}
    if glob:
        raw["global"] = [dict(t, description=t.get("description", "test")) for t in glob]
    if intents:
        raw["intents"] = intents
    return raw


def run(raw, steps, **kw):
    cfg = dict(CFG)
    cfg.update(kw.pop("cfg", {}))
    return sim.simulate(raw, cfg, kw.pop("start_state", "veille"), steps, **kw)


def moves(res):
    return [(e["from"], e["to"], e["reason"]) for e in res["trace"] if e["moved"]]


# ---------------------------------------------------------------- icons / vocabulary
def test_icons_and_vocabulary():
    assert G.all_icons() == sorted(CONTRACT_ICONS), (set(G.all_icons()) ^ set(CONTRACT_ICONS))
    assert len(CONTRACT_ICONS) == 37
    v = G.vocabulary(CFG, G.load_graph(G.DEFAULT_PATH, CFG))
    for k in ("events", "actions", "guards", "delays", "since", "states", "intents", "kinds"):
        assert v[k], k
        for x in v[k]:
            assert x["icon"] and x["icon"] in CONTRACT_ICONS, (k, x)
    assert [k["id"] for k in v["kinds"]] == ["start", "trigger", "condition", "action", "goto", "end"]
    assert {k["id"]: k["icon"] for k in v["kinds"]}["trigger"] == "bolt"
    ids = {e["id"] for e in v["events"]}
    assert {"personnes_multiples", "ouverture", "fermeture", "inactivite_longue", "say_done", "visage_perdu"} <= ids
    assert {a["id"] for a in v["actions"]} >= {"say_text", "set_expression", "wait", "gaze"}
    assert "dans_les_horaires" in {g["id"] for g in v["guards"]}
    args = {a["id"]: {x["name"]: x for x in a["args"]} for a in v["actions"]}
    assert args["say_text"]["text"]["type"] == "text" and args["say_text"]["text"]["max_len"] == 300
    assert args["set_expression"]["name"]["options"] == ["content", "surpris", "reflechit", "triste", "neutre"]
    assert args["set_expression"]["seconds"]["type"] == "number"
    assert args["gaze"]["mode"]["options"] == ["suivre", "devant", "errer"]
    assert args["wait"]["seconds"]["options"] == list(G.DELAY_DOC)
    it = {i["id"]: i for i in v["intents"]}
    assert it["au_revoir"]["shared"] is True and it["au_revoir"]["words_from"] == "refusal_words"
    assert "shared" not in it["chanson"] and it["chanson"]["regex"] and it["appel"]["words"] == ["nanter"]
    assert it["question"]["fixed"] is True
    assert {s["id"]: s["icon"] for s in v["states"]}["veille"] == "moon"
    json.dumps(v)


# ---------------------------------------------------------------- opening hours
def test_hours_parser():
    t = hours.parse({"lun-ven": "09:00-18:00", "sam": ["10:00-12:00", "14:00-17:00"]})
    mon = lambda h, m: datetime.datetime(2026, 11, 2, h, m)       # 2026-11-02 is a Monday  # noqa: E731
    assert hours.is_open(t, mon(9, 0)) and hours.is_open(t, mon(17, 59))
    assert not hours.is_open(t, mon(8, 59)) and not hours.is_open(t, mon(18, 0))
    sat = lambda h: datetime.datetime(2026, 11, 7, h, 0)         # noqa: E731
    assert hours.is_open(t, sat(10)) and not hours.is_open(t, sat(13)) and hours.is_open(t, sat(14))
    assert not hours.is_open(t, datetime.datetime(2026, 11, 8, 10, 0))   # Sunday
    assert hours.parse({}) is None and hours.is_open(None, mon(3, 0))     # empty = always open
    night = hours.parse({"ven": "22:00-02:00"})                           # past midnight, belongs to Friday
    assert hours.is_open(night, datetime.datetime(2026, 11, 6, 23, 0))
    assert hours.is_open(night, datetime.datetime(2026, 11, 7, 1, 0))
    assert not hours.is_open(night, datetime.datetime(2026, 11, 7, 3, 0))
    assert not hours.is_open(night, datetime.datetime(2026, 11, 6, 1, 0))  # Friday 01:00 is Thursday's tail: not set
    for bad in ({"lun": "9h-18h"}, {"xyz": "09:00-18:00"}, {"lun": "25:00-26:00"}, "lun 9-18"):
        try:
            hours.parse(bad)
        except ValueError:
            continue
        raise AssertionError("accepted: %r" % (bad,))
    assert hours.safe_parse({"lun": "bad"}) is None          # a typo never locks the robot out
    assert hours.parse({"lun,mer": "08:00-09:00"})[2] == [(480, 540)]


# ---------------------------------------------------------------- enabled: false
def test_enabled_false_is_ignored_and_roundtrips():
    raw = default_raw()
    g = G.parse_graph(copy.deepcopy(raw), CFG, "<t>")
    dis = [(s, t) for s, st in g.states.items() for t in st.transitions if not t.enabled]
    assert sorted(s for s, _ in dis) == ["ecoute", "relance"] and all(t.on == "visage_perdu" and t.to == "cloture" for _, t in dis)
    steps = [{"event": "start"}, {"wait_s": 3}, {"event": "visage_perdu"}, {"wait_s": 0.5}]
    res = run(raw, steps)
    assert res["final"]["state"] == "ecoute", "disabled chain must not fire"
    enabled = copy.deepcopy(raw)
    for t in enabled["states"]["ecoute"]["transitions"]:
        if t.get("on") == "visage_perdu":
            t.pop("enabled")
    res = run(enabled, steps)
    assert ("ecoute", "cloture", "visage_perdu") in moves(res)
    # visual round trip keeps the flag, explicit on every trigger, and compiles back
    doc = json.loads(json.dumps(V.to_visual(raw)))
    trig = [n for n in doc["nodes"] if n["kind"] == "trigger"]
    assert all(isinstance(n["params"]["enabled"], bool) for n in trig if n["params"]["type"] != "enter")
    assert sorted(n["group"] for n in trig if n["params"].get("enabled") is False) == ["ecoute", "relance"]
    raw2, _, errs = V.from_visual(doc, CFG)
    sts = copy.deepcopy(G.parse_graph(copy.deepcopy(raw2), CFG, "<t>").to_dict()["states"])
    for st in sts.values():   # shared exclusive branches come back tagged with a (no-op) fan id
        for t in st["transitions"]:
            t.pop("fan", None)
    assert not errs and sts == g.to_dict()["states"]
    assert "enabled: false" in V.dump_yaml(raw2)
    # a non-boolean flag and a disabled `enter` trigger are refused
    bad = json.loads(json.dumps(doc))
    t0 = next(n for n in bad["nodes"] if n["kind"] == "trigger" and n["params"]["type"] == "event")
    t0["params"]["enabled"] = "no"
    assert V.from_visual(bad, CFG)[0] is None
    bad = json.loads(json.dumps(doc))
    # CHANGED (lot L1): the on_enter trigger is now "etat becomes X" (var_changed on etat)
    ent = next(n for n in bad["nodes"] if n["kind"] == "trigger" and (n["params"]["type"] == "enter" or (
        n["params"].get("event") == "var_changed" and n["params"].get("name") == "etat")))
    ent["params"]["enabled"] = False
    assert any(e["node"] == ent["id"] for e in V.from_visual(bad, CFG)[2])


# ---------------------------------------------------------------- simulator
def test_sim_matches_real_brain_and_parity():
    h = tbg.H({})
    h.post("visage"); h.settle(); h.say("Au revoir"); h.settle(1.0)
    real = h.close()
    real_moves = [(e[1], e[2], e[3]) for e in real if e[0] == "go"]
    real_plays = [e[1] for e in real if e[0] == "play"]
    res = run(default_raw(), [{"event": "visage"}, {"wait_s": 3}, {"say": "Au revoir"}, {"wait_s": 5}])
    assert moves(res) == real_moves, (moves(res), real_moves)
    plays = [x.split(" ", 1)[1] for e in res["trace"] for x in e["effects"] if x.startswith("play ")]
    assert plays == real_plays, (plays, real_plays)
    first = res["trace"][0]
    assert first["step"] == -1 and first["chain"] == "veille/enter" and first["reason"] == "start"
    chains = [e["chain"] for e in res["trace"] if e["moved"]]
    # CHANGED (lot G1): the visage greeting is veille/t1 (t0 = the deaf-face note chain)
    # CHANGED (lot G2): accueil greeting_done is accueil/t3 (t0..t2 = the greeting choice on conversation_started)
    # CHANGED (lot G3): the au revoir chain is ecoute/t2 (t1 = the visitor-left timeout)
    assert chains == ["veille/t1", "accueil/t3", "ecoute/t2", "cloture/t1"], chains
    # CHANGED (lot L1): `final` also carries the variable values (system ones included)
    fv = res["final"].pop("vars")
    assert fv["names"]["etat"] == "veille" and fv["names"]["tours"] == 0 and "salutations" in fv["lists"], fv
    assert res["final"] == {"state": "veille", "turns": 0, "expression": None, "gaze_mode": "suivre"}
    res["final"]["vars"] = fv
    # same input, same trace (no real time involved)
    assert run(default_raw(), [{"event": "visage"}, {"wait_s": 3}, {"say": "Au revoir"}, {"wait_s": 5}]) == res
    # timers: silence -> relance -> cloture -> veille on the virtual clock only
    t0 = time.monotonic()
    res = run(default_raw(), [{"event": "start"}, {"wait_s": 60}], cfg={"silence_relance_s": 8, "silence_cloture_s": 15})
    # CHANGED (lot G3): the simulated room has no face at all, so 20 s after the start the relance window ends with the
    # visitor-left rule (11 s of silence) instead of silence_cloture_s
    assert [m[2] for m in moves(res)] == ["ui", "greeting_done", "silence", "visiteur_parti", "cloture_done"], moves(res)
    assert time.monotonic() - t0 < 5, "60 virtual seconds must not take real time"


def test_sim_isolation_from_live_brain():
    h = tbg.H({})
    try:
        h.post("start"); h.wait_state("ecoute"); h.settle()
        before = (h.brain.state, h.brain.turns, h.brain.since, len(h.rec.events), len(h.brain.journal),
                  list(h.brain.history), copy.deepcopy(h.cfg), h.out.muted)
        listing = sorted(os.listdir("/opt/robot/nanterino"))
        mt = os.path.getmtime(G.DEFAULT_PATH)
        res = run(default_raw(), [{"event": "start"}, {"wait_s": 5}, {"say": "Où est le parc ?"}, {"wait_s": 20}, {"event": "off"}],
                  cfg={"silence_relance_s": 4})
        assert len(res["trace"]) > 4
        h.settle(0.3)
        after = (h.brain.state, h.brain.turns, h.brain.since, len(h.rec.events), len(h.brain.journal),
                 list(h.brain.history), copy.deepcopy(h.cfg), h.out.muted)
        assert before == after, (before, after)
        assert listing == sorted(os.listdir("/opt/robot/nanterino")) and mt == os.path.getmtime(G.DEFAULT_PATH)
    finally:
        h.close()


def test_sim_errors():
    raw = default_raw()
    for steps, frag in (([{"event": "nope"}], "inconnu"), ([{"wait_s": -1}], "wait_s"), ([{"say": ""}], "say"),
                        ([{"faces": 99}], "faces"), ([{"zap": 1}], "inconnue"), ([{"event": "tick"}], "inconnu"),
                        ([{"wait_s": 3000}, {"wait_s": 3000}], "temps"), ("x", "liste"), ([{}] * 101, "Trop")):
        try:
            run(raw, steps)
        except sim.SimError as e:
            assert any(frag in x["message"] for x in e.errors), (steps, e.errors)
        else:
            raise AssertionError("accepted: %r" % (steps,))
    for kw in ({"start_state": "nowhere"}, {"overrides": {"volume": 1}}, {"start_time": "yesterday"}):
        try:
            run(raw, [], **kw)
        except sim.SimError:
            continue
        raise AssertionError("accepted: %r" % (kw,))
    loop = mini(veille=[{"on": "start", "do": [{"emit": {"event": "ask"}}]}], glob=[{"on": "ask", "do": [{"emit": {"event": "start"}}]}])
    try:                       # two chains posting each other forever are cut, not hung
        run(loop, [{"event": "start"}])
    except (sim.SimError, RecursionError):
        pass
    else:
        raise AssertionError("event loop not detected")
    s = run(raw, [], start_state="ecoute")                          # any state can be the start
    assert s["final"]["state"] == "ecoute" and s["trace"][0]["chain"] == "ecoute/enter"


# ---------------------------------------------------------------- new actions
def test_set_expression_and_gaze_in_sim():
    raw = mini(veille=[{"on": "start", "do": [{"set_expression": {"name": "content", "seconds": 2}}, {"gaze": {"mode": "devant"}}], "to": "a"}],
               a=[{"on": "stop", "to": "veille"}])
    r = run(raw, [{"event": "start"}, {"wait_s": 1}])
    assert r["final"]["expression"]["name"] == "content" and 0 < r["final"]["expression"]["left_s"] <= 1.0
    assert r["final"]["gaze_mode"] == "devant"
    r = run(raw, [{"event": "start"}, {"wait_s": 3}])
    assert r["final"]["expression"] is None, "expression expires and the state's own look returns"
    assert r["final"]["gaze_mode"] == "devant", "gaze lasts while the conversation lasts"
    r = run(raw, [{"event": "start"}, {"wait_s": 1}, {"event": "stop"}])
    assert r["final"]["gaze_mode"] == "suivre", "back to the default gaze when idle"
    for bad in ({"set_expression": {"name": "furieux", "seconds": 2}}, {"set_expression": {"name": "content", "seconds": 0}},
                {"gaze": {"mode": "loin"}}, {"say_text": {"text": ""}}, {"say_text": {"text": "x" * 301}}):
        try:
            G.parse_graph(mini(veille=[{"on": "start", "do": [bad]}]), CFG, "<t>")
        except G.GraphError:
            continue
        raise AssertionError("accepted: %r" % (bad,))


def test_wait_does_not_block_and_is_cancelled_by_stop():
    raw = mini(veille=[{"on": "start", "do": [{"wait": {"seconds": 2}}], "to": "a", "reason": "waited", "then": [{"set_expression": {"name": "triste", "seconds": 5}}]},
                       {"on": "ask", "to": "b", "reason": "other"}],
               glob=[{"on": "stop", "do": ["cancel_all"], "to": "veille", "reason": "stopped"}])
    r = run(raw, [{"event": "start"}, {"wait_s": 0.5}, {"event": "ask"}, {"wait_s": 3}])
    # journal order = order the chains started: `start` (paused), then `ask`, which flowed while it waited
    assert sorted(moves(r)) == sorted([("veille", "a", "waited"), ("veille", "b", "other")]), moves(r)
    assert r["final"]["state"] == "a" and r["final"]["expression"]["name"] == "triste", "the rest of the chain ran after the wait"
    assert run(raw, [{"event": "start"}, {"wait_s": 1.8}])["final"]["state"] == "veille", "not before the delay"
    assert run(raw, [{"event": "start"}, {"wait_s": 2.3}])["final"]["state"] == "a", "resumed by the heartbeat deadline"
    r = run(raw, [{"event": "start"}, {"wait_s": 0.5}, {"event": "stop"}, {"wait_s": 3}])
    assert [m[1] for m in moves(r)] == ["veille"] and r["final"]["state"] == "veille", "stop cancels the pending rest of the chain"
    cfgkey = mini(veille=[{"on": "start", "do": [{"wait": {"seconds": "silence_relance_s"}}], "to": "a"}])
    r = run(cfgkey, [{"event": "start"}, {"wait_s": 2.5}], cfg={"silence_relance_s": 2})
    assert r["final"]["state"] == "a"


def test_say_text_is_cached_at_load_and_stays_muted():
    text = "Bonsoir à tous, la médiathèque ferme bientôt."
    raw = mini(veille=[{"on": "start", "do": [{"say_text": {"text": text}}], "to": "a"}], a=[{"on": "say_done", "to": "b", "reason": "dit"}],
               glob=[{"on": "stop", "do": ["cancel_all"], "to": "veille"}])
    raw["states"]["veille"]["on_enter"] = ["mic_on"]               # the harness waits for the first trace event
    path = "/tmp/g_say_text.yaml"
    with open(path, "w", encoding="utf-8") as f:
        f.write(V.dump_yaml(raw))
    h = tbg.H({"graph_file": path})
    try:
        h.wait(lambda: text in h.brain._phrases, 5)                 # synthesised at graph load, not at play time
        calls = []
        real = h.tts.synth
        h.tts.synth = lambda t: (calls.append(t), real(t))[1]
        h.post("start"); h.wait_state("b"); h.settle()
        assert ["play", text] in h.rec.events and calls == [], ("synth at play time", calls)
        assert h.out.muted is True and h.brain.state == "b"
        # a reload brings a NEW phrase into the cache before it is ever spoken
        new = "Nouvelle phrase libre."
        raw2 = copy.deepcopy(raw)
        raw2["states"]["b"] = {"description": "x", "transitions": [{"on": "ask", "do": [{"say_text": {"text": new}}], "description": "x"}]}
        with open(path, "w", encoding="utf-8") as f:
            f.write(V.dump_yaml(raw2))
        h.post("stop"); h.wait_state("veille"); h.settle()
        ok, err = h.brain.reload_graph()
        assert ok and err is None
        h.wait(lambda: new in h.brain._phrases, 5)
    finally:
        h.close()
        os.remove(path)
    r = run(raw, [{"event": "start"}, {"wait_s": 3}])                # simulator: spoken, then say_done
    assert any(("play " + text) in e["effects"] for e in r["trace"]) and moves(r)[-1] == ("a", "b", "dit")


# ---------------------------------------------------------------- new triggers
def test_personnes_multiples():
    raw = mini(veille=[{"on": "personnes_multiples", "to": "a", "reason": "foule"}], a=[{"on": "personnes_multiples", "to": "b", "reason": "encore"}])
    r = run(raw, [{"faces": 2}, {"wait_s": 0.6}])
    assert moves(r) == [], "needs 1 s"
    r = run(raw, [{"faces": 2}, {"wait_s": 1.5}])
    assert moves(r) == [("veille", "a", "foule")]
    r = run(raw, [{"faces": 2}, {"wait_s": 6}])
    assert moves(r) == [("veille", "a", "foule")], "posted once while the crowd stays"
    r = run(raw, [{"faces": 2}, {"wait_s": 0.6}, {"faces": 1}, {"wait_s": 1}, {"faces": 3}, {"wait_s": 0.6}])
    assert moves(r) == [], "a gap below 2 faces restarts the second"
    r = run(raw, [{"faces": 2}, {"wait_s": 1.5}, {"faces": 1}, {"wait_s": 0.3}, {"faces": 2}, {"wait_s": 1.5}])
    assert [m[2] for m in moves(r)] == ["foule", "encore"], "re-armed once it dropped below 2"


def test_opening_hours_events_and_guard():
    hrs = {"lun-ven": "09:00-18:00"}
    raw = mini(veille=[{"on": "ouverture", "to": "a", "reason": "ouvert"},
                       {"on": "visage", "when": [{"not": "dans_les_horaires"}], "to": "b", "reason": "ferme"},
                       {"on": "visage", "when": "dans_les_horaires", "do": ["cancel_all"], "reason": "ouvert_visage"}],
               a=[{"on": "fermeture", "to": "veille", "reason": "ferme"}])
    r = run(raw, [{"wait_s": 90}], cfg={"opening_hours": hrs}, start_time="2026-11-02T08:59:30")      # Monday
    assert moves(r) == [("veille", "a", "ouvert")], moves(r)
    r = run(raw, [{"wait_s": 90}], cfg={"opening_hours": hrs}, start_time="2026-11-02T17:59:30", start_state="a")
    assert moves(r) == [("a", "veille", "ferme")], moves(r)
    r = run(raw, [{"wait_s": 5}], cfg={"opening_hours": hrs}, start_time="2026-11-02T10:00:00")
    assert moves(r) == [], "no event at boot, none without a crossing"
    r = run(raw, [{"wait_s": 5}], cfg={}, start_time="2026-11-02T08:59:58")
    assert moves(r) == [], "empty hours: always open, no events"
    r = run(raw, [{"event": "visage"}], cfg={"opening_hours": hrs}, start_time="2026-11-07T10:00:00")   # Saturday
    assert moves(r) == [("veille", "b", "ferme")]
    r = run(raw, [{"event": "visage"}], cfg={"opening_hours": hrs}, start_time="2026-11-04T10:00:00")   # Wednesday
    assert moves(r) == []                                      # in hours: a chain with no `to` only runs (no move)
    assert any(e["reason"] == "ouvert_visage" and not e["moved"] for e in r["trace"])
    r = run(raw, [{"event": "visage"}], cfg={}, start_time="2026-11-07T10:00:00")
    assert moves(r) == [], "empty hours: the guard is true"


def test_inactivite_longue():
    raw = mini(veille=[{"on": "inactivite_longue", "to": "a", "reason": "idle"}], a=[{"on": "inactivite_longue", "to": "b", "reason": "idle2"}])
    c = {"idle_long_s": 30}
    assert moves(run(raw, [{"wait_s": 29}], cfg=c)) == []
    assert moves(run(raw, [{"wait_s": 31}], cfg=c)) == [("veille", "a", "idle")]
    assert moves(run(raw, [{"wait_s": 200}], cfg=c)) == [("veille", "a", "idle")], "posted once until activity"
    r = run(raw, [{"wait_s": 20}, {"faces": 1}, {"faces": 0}, {"wait_s": 20}], cfg=c)
    assert moves(r) == [], "a face is activity: the timer restarts"
    r = run(raw, [{"wait_s": 20}, {"faces": 1}, {"faces": 0}, {"wait_s": 35}, {"faces": 1}, {"faces": 0}, {"wait_s": 35}], cfg=c)
    assert [m[2] for m in moves(r)] == ["idle", "idle2"], "re-armed after activity"
    r = run(raw, [{"wait_s": 20}, {"say": "bonjour tout le monde"}, {"wait_s": 20}], cfg=c)
    assert moves(r) == [], "speech is activity too"
    r = run(raw, [{"faces": 1}, {"wait_s": 100}], cfg=c)
    assert moves(r) == [], "someone present: not inactive"


# ---------------------------------------------------------------- intents
def _with_intent():
    raw = default_raw()
    raw["intents"]["horaires"] = {"words": ["horaire", "ouvert"], "only_in": ["ecoute"], "description": "Question sur les horaires."}
    raw["states"]["ecoute"]["transitions"].insert(0, {"on": "intent.horaires", "do": [{"say_text": {"text": "Nous ouvrons à neuf heures."}}], "description": "Répondre sur les horaires."})
    return raw


def test_editable_intents():
    doc = json.loads(json.dumps(V.to_visual(_with_intent())))
    raw, _, errs = V.from_visual(doc, CFG)
    assert not errs, errs
    r = run(raw, [{"event": "start"}, {"wait_s": 3}, {"say": "Quels sont vos horaires ?"}, {"wait_s": 1}])
    hit = next(e for e in r["trace"] if e["event"] == "intent.horaires")
    assert hit["chain"] == "ecoute/t0" and not hit["moved"] and "play Nous ouvrons à neuf heures." in hit["effects"], hit
    assert run(raw, [{"event": "start"}, {"wait_s": 3}, {"say": "Où est le parc ?"}, {"wait_s": 1}])["trace"][-1]["event"] != "intent.horaires"

    def intent_errors(mutate):                  # invalid edits are refused, naming the intent
        d = json.loads(json.dumps(doc))
        mutate(d["intents"])
        _raw, _l, errors = V.from_visual(d, CFG)
        assert _raw is None
        return errors
    errs = intent_errors(lambda i: i["chanson"].update(regex="(unclosed"))
    assert any(e.get("intent") == "chanson" and "regex" in e["message"] for e in errs), errs
    errs = intent_errors(lambda i: i["horaires"].update(words=[]))
    assert any(e.get("intent") == "horaires" for e in errs), errs
    errs = intent_errors(lambda i: i.update({"Bad Name": {"words": ["x"], "description": "x"}}))
    assert any(e.get("intent") == "Bad Name" for e in errs), errs
    errs = intent_errors(lambda i: i["horaires"].update(only_in=["nowhere"]))
    assert any(e.get("intent") == "horaires" and "nowhere" in e["message"] for e in errs), errs
    errs = intent_errors(lambda i: i.update({"question": {"words": ["x"]}}))
    assert any(e.get("intent") == "question" for e in errs), errs
    # the shared refusal list stays linked to the config
    assert doc["intents"]["au_revoir"]["words_from"] == "refusal_words"
    # editing words / only_in is saved and used
    d = json.loads(json.dumps(doc))
    d["intents"]["horaires"].update(words=["ouverture"], only_in=["ecoute", "relance"])
    raw3, _, errs = V.from_visual(d, CFG)
    assert not errs
    r = run(raw3, [{"event": "start"}, {"wait_s": 3}, {"say": "L'ouverture est quand ?"}])
    assert any(e["event"] == "intent.horaires" for e in r["trace"])


# ---------------------------------------------------------------- versions
def test_versions_list_and_restore():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    gp, lp = os.path.join(TMP, "graph.yaml"), os.path.join(TMP, "graph.layout.json")
    base = V.to_visual(default_raw())
    for delay in (8, 9, 10):
        d = copy.deepcopy(base)
        next(n for n in d["nodes"] if n["kind"] == "trigger" and n["params"].get("type") == "after"
             and n["group"] == "ecoute")["params"]["delay"] = delay
        next(n for n in d["nodes"] if n["kind"] == "trigger" and n["params"].get("event") == "stop")["x"] = 1000 + delay
        assert V.save(d, CFG, gp, lp)[0]
    vs = V.list_versions(gp)
    assert len(vs) == 2 and vs[0]["id"] >= vs[1]["id"], vs                      # newest first, 3 saves = 2 backups
    for v in vs:
        assert set(v) == {"id", "date", "size", "summary"} and v["size"] > 100
        assert v["summary"]["states"] == 7 and v["summary"]["chains"] >= 30 and v["summary"]["disabled"] == 2, v
        datetime.datetime.fromisoformat(v["date"])
    oldest = vs[-1]["id"]                                                         # backup of the save with delay 8
    current = open(gp, encoding="utf-8").read()
    ok, status, msg = V.restore_version(oldest, CFG, gp, lp)
    assert ok and status == 200, (ok, status, msg)
    g = G.load_graph(gp, CFG)
    assert next(t for t in g.states["ecoute"].transitions if t.after is not None).after == 8
    assert len(V.list_versions(gp)) == 3, "the version being replaced was backed up first"
    assert any(open(os.path.join(TMP, f), encoding="utf-8").read() == current for f in os.listdir(TMP) if f.startswith("graph.yaml.bak-"))
    lay = V.load_layout(lp)
    assert lay["nodes"]["global/t0/0"]["x"] == 1008, "layout comes back with the version"
    for bad in ("../../etc/passwd", "nope", "20261031-101500", "", None, "20261031-101500-x"):
        ok, status, _ = V.restore_version(bad, CFG, gp, lp)
        assert not ok and status == 404, (bad, status)
    # a backup that no longer validates is refused and nothing changes
    victim = V.list_versions(gp)[0]["id"]
    with open("%s.bak-%s" % (gp, victim), "a", encoding="utf-8") as f:
        f.write("\nsurprise: true\n")
    before = open(gp, encoding="utf-8").read()
    ok, status, _ = V.restore_version(victim, CFG, gp, lp)
    assert not ok and status == 400 and open(gp, encoding="utf-8").read() == before
    shutil.rmtree(TMP, ignore_errors=True)


# ---------------------------------------------------------------- journal
def test_journal_keeps_50_and_feeds_last_transition():
    h = tbg.H({})
    try:
        assert h.brain.last_transition() is None and h.brain.snapshot()["last_transition"] is None
        for _ in range(60):
            h.post("hush")                         # veille: global rule 'hush', do cancel_all, no state change
        h.wait(lambda: sum(1 for e in h.rec.events if e == ["cancel"]) >= 60, 10)
        h.settle(0.3)
        assert len(h.brain.journal) == 50, len(h.brain.journal)
        tr = h.brain.trace()
        assert len(tr) == 50 and tr == sorted(tr, key=lambda e: e["t"])
        last = h.brain.snapshot()["last_transition"]
        assert last["chain"] == "global/t4" and last["event"] == "hush" and last["moved"] is False, last
        assert last["actions"] == ["cancel_all"] and last["from"] == last["to"] == "veille" and 0 <= last["age_s"] < 5
        json.dumps(h.brain.snapshot())
        h.post("start"); h.wait_state("accueil"); h.settle()
        e = h.brain.trace()
        start = next(x for x in reversed(e) if x["event"] == "start")
        # CHANGED (lot G1): veille/t1 -> veille/t2, the deaf-face note chain was inserted before the visage greeting
        # CHANGED (lot G2): veille/t2 -> veille/t3 (+ the outside-hours note chain); greeting_done accueil/t0 -> t3
        assert start["chain"] == "veille/t3" and start["moved"] and (start["from"], start["to"], start["reason"]) == ("veille", "accueil", "ui")
        assert e[-1]["reason"] == "greeting_done" and e[-1]["chain"] == "accueil/t3"
        assert h.brain.snapshot()["heartbeat"]["trips"] == 0
    finally:
        h.close()


# ---------------------------------------------------------------- branches multiples (GC2-like fan-out / fan-in)
def vdoc(nodes, links, order=None):
    """Editor document from {id: (kind, params)} and [(from, port, to)] on the mini() states."""
    return {"nodes": [{"id": i, "kind": k, "x": 0, "y": n * 10, "description": "", "params": dict(p)} for n, (i, (k, p)) in enumerate(nodes.items())],
            "links": [{"from": a, "port": pt, "to": b} for a, pt, b in links],
            "states": [{"id": x} for x in ("veille", "eteint", "a", "b")], **({"order": order} if order else {})}


def vcompile(doc):
    rep = {}
    raw, _lay, errs = V.from_visual(doc, CFG, rep)
    assert not errs, errs
    return raw, rep


EXPR = {"action": "set_expression", "args": {"name": "content", "seconds": 3}, "phase": "do"}
ON_START = {"type": "event", "event": "start"}
IN_VEILLE = {"type": "state", "states": ["veille"], "negate": False}


def test_fan_out_side_chain_and_goto_both_run():
    # the user's case: the trigger also feeds an "expression -> End" side chain (compiled into `global`)
    raw, rep = vcompile(vdoc({"t": ("trigger", ON_START), "c": ("condition", IN_VEILLE), "g": ("goto", {"state": "a"}),
                              "x": ("action", EXPR), "e": ("end", {})},
                             [("t", "out", "c"), ("c", "true", "g"), ("t", "out", "x"), ("x", "out", "e")]))
    assert not rep["warnings"], "one moving branch only: no conflict"
    assert [t.get("fan") for t in raw["global"] + raw["states"]["veille"]["transitions"]] == ["fan-t", "fan-t"]
    r = run(raw, [{"event": "start"}])
    assert r["final"]["state"] == "a" and r["final"]["expression"]["name"] == "content", r["final"]
    chains = [e["chain"] for e in r["trace"] if e["event"] == "start"]
    assert chains == ["global/t0", "veille/t0"], "non-moving side chain first, then the single moving chain"
    # execution order exposed to the editor: side chain 1, goto branch 2
    assert sorted((b["target"], b["rank"]) for b in rep["fans"]["t"]) == [("e", 1), ("g", 2)]
    # the same trigger with the old "first match wins" engine would have lost the move: raw without fan behaves alike
    raw2 = mini(veille=[{"on": "start", "to": "a"}], glob=[{"on": "start", "do": [{"set_expression": {"name": "content", "seconds": 3}}]}])
    r2 = run(raw2, [{"event": "start"}])
    assert r2["final"]["state"] == "a" and r2["final"]["expression"]["name"] == "content"


def test_fan_in_two_triggers_share_one_chain():
    raw, rep = vcompile(vdoc({"t1": ("trigger", ON_START), "t2": ("trigger", {"type": "event", "event": "ask"}),
                              "c": ("condition", IN_VEILLE), "x": ("action", EXPR), "g": ("goto", {"state": "a"})},
                             [("t1", "out", "c"), ("t2", "out", "c"), ("c", "true", "x"), ("x", "out", "g")]))
    assert not rep["warnings"] and len(raw["states"]["veille"]["transitions"]) == 2
    for ev in ("start", "ask"):
        r = run(raw, [{"event": ev}])
        assert r["final"]["state"] == "a" and r["final"]["expression"]["name"] == "content", ev


def test_two_moving_branches_first_wins_conflict_warned_and_journaled():
    doc = vdoc({"t": ("trigger", ON_START), "c": ("condition", IN_VEILLE), "ga": ("goto", {"state": "a"}), "gb": ("goto", {"state": "b"})},
               [("t", "out", "c"), ("c", "true", "ga"), ("t", "out", "gb")])
    raw, rep = vcompile(doc)
    (w,) = rep["warnings"]
    assert w["kind"] == "fan_conflict" and w["node"] == "t" and w["nodes"] == ["gb", "ga"], w   # global branch evaluates first
    assert "Plusieurs branches" in w["message"] and "gb puis ga" in w["message"]
    assert sorted((b["target"], b["rank"], b["ignored"]) for b in rep["fans"]["t"]) == [("ga", 2, True), ("gb", 1, False)]
    r = run(raw, [{"event": "start"}])
    assert r["final"]["state"] == "b", "first moving branch in evaluation order applies"
    rep2 = {}
    _r2, _l2, errs2 = V.from_visual(json.loads(json.dumps(V.to_visual(raw))), CFG, rep2)
    assert not errs2 and [w["kind"] for w in rep2["warnings"]] == ["fan_conflict"], "the warning survives a save / reload (shared fan id)"
    conf = [e for e in r["trace"] if e.get("conflict")]
    assert len(conf) == 1 and conf[0]["chain"] == "veille/t0" and not conf[0]["moved"], r["trace"]
    # exclusive moving branches are NOT a conflict: different states, or a guard and its negation
    raw_ok, rep_ok = vcompile(vdoc({"t": ("trigger", ON_START), "c1": ("condition", IN_VEILLE), "c2": ("condition", {"type": "state", "states": ["a"], "negate": False}),
                                    "ga": ("goto", {"state": "a"}), "gb": ("goto", {"state": "b"})},
                                   [("t", "out", "c1"), ("c1", "true", "ga"), ("t", "out", "c2"), ("c2", "true", "gb")]))
    assert not rep_ok["warnings"]
    # CHANGED (lot B1): the first guard WITHOUT arguments (at_pose, B1, sorts first and needs pose / tolerance);
    # still auto_greet_on_face, the guard this test always used
    guard = sorted(g for g in G.GUARDS if not G.GUARD_ARGS.get(g))[0]
    _raw, rep_g = vcompile(vdoc({"t": ("trigger", ON_START), "c": ("condition", IN_VEILLE), "cg": ("condition", {"type": "guard", "guard": guard, "negate": False}),
                                 "ga": ("goto", {"state": "a"}), "gb": ("goto", {"state": "b"})},
                                [("t", "out", "c"), ("c", "true", "cg"), ("cg", "true", "ga"), ("cg", "false", "gb")]))
    assert not rep_g["warnings"], "guard / not guard never match together"


def test_shared_action_node_runs_once_across_branches():
    doc = vdoc({"t": ("trigger", ON_START), "c": ("condition", IN_VEILLE), "x": ("action", {"action": "count_turn", "args": {}, "phase": "do"}),
                "g": ("goto", {"state": "a"}), "e": ("end", {})},
               [("t", "out", "c"), ("c", "true", "x"), ("x", "out", "g"), ("x", "out", "e")])
    raw, rep = vcompile(doc)
    assert not rep["warnings"]
    r = run(raw, [{"event": "start"}])
    assert r["final"]["state"] == "a" and r["final"]["turns"] == 1, "shared node acts once, not once per path"
    unfanned = copy.deepcopy(raw)
    for t in unfanned["states"]["veille"]["transitions"]:
        t.pop("fan")
    assert run(unfanned, [{"event": "start"}])["final"]["turns"] == 2, "without the fan id the chains are independent"


def test_fan_survives_save_and_reload():
    os.makedirs(TMP, exist_ok=True)
    gp, lp = os.path.join(TMP, "fan.yaml"), os.path.join(TMP, "fan.layout.json")
    for f in (gp, lp):
        if os.path.exists(f):
            os.remove(f)
    doc = vdoc({"t": ("trigger", ON_START), "c": ("condition", IN_VEILLE), "g": ("goto", {"state": "a"}), "x": ("action", EXPR), "e": ("end", {})},
               [("t", "out", "c"), ("c", "true", "g"), ("t", "out", "x"), ("x", "out", "e")])
    rep = {}
    ok, errs = V.save(doc, CFG, gp, lp, rep)
    assert ok and not errs and not rep["warnings"]
    raw = V.load_raw(gp)
    assert "fan: fan-t" in open(gp, encoding="utf-8").read()
    doc2 = json.loads(json.dumps(V.to_visual(raw)))
    raw2, _lay, errs = V.from_visual(doc2, CFG)
    assert not errs and G.parse_graph(copy.deepcopy(raw2), CFG, "<t>").to_dict() == G.parse_graph(copy.deepcopy(raw), CFG, "<t>").to_dict()
    assert run(raw2, [{"event": "start"}])["final"]["state"] == "a"
    for f in [gp, lp] + [os.path.join(TMP, x) for x in os.listdir(TMP) if x.startswith("fan.")]:
        if os.path.exists(f):
            os.remove(f)


def test_non_moving_after_fires_once_per_state_entry():
    raw = mini(veille=[{"after": 1, "do": [{"set_expression": {"name": "content", "seconds": 1}}]}, {"after": 2, "to": "a", "reason": "late"}])
    r = run(raw, [{"wait_s": 3}])
    assert r["final"]["state"] == "a"
    assert [e["chain"] for e in r["trace"] if e["event"] == "after"] == ["veille/t0", "veille/t1"], r["trace"]


TESTS = [test_icons_and_vocabulary, test_hours_parser, test_enabled_false_is_ignored_and_roundtrips,
         test_sim_matches_real_brain_and_parity, test_sim_isolation_from_live_brain, test_sim_errors,
         test_set_expression_and_gaze_in_sim, test_wait_does_not_block_and_is_cancelled_by_stop,
         test_say_text_is_cached_at_load_and_stays_muted, test_personnes_multiples, test_opening_hours_events_and_guard,
         test_inactivite_longue, test_editable_intents, test_versions_list_and_restore,
         test_journal_keeps_50_and_feeds_last_transition,
         test_fan_out_side_chain_and_goto_both_run, test_fan_in_two_triggers_share_one_chain,
         test_two_moving_branches_first_wins_conflict_warned_and_journaled, test_shared_action_node_runs_once_across_branches,
         test_fan_survives_save_and_reload, test_non_moving_after_fires_once_per_state_entry]


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
    ran = len([f for f in TESTS if not only or f.__name__ in only])
    print("graph_features tests: %d passed, %d failed" % (ran - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
