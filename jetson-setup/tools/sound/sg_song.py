"""Song mode: note/token parsing and the sequencer (docs/format.md, "Mode song")."""

import copy
import json
import math
import re

import sg_space
from sg_engine import (SR, SoundError, clamp_pan, duck_gains, mix_any, render_layers, render_patch,
                       resolve_automation, resolve_eq, resolve_patch, resolve_sound)

_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
# letter, optional accidental, signed octave. `b` is both a note letter and a flat:
# "bb3" = B-flat 3, "b3" = B 3 (the optional group simply stays empty).
_NOTE_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")
_FREQ_RE = re.compile(r"^(?:\d+\.?\d*|\.\d+)$")
_FRACTION_RE = re.compile(r"^(\d+\.?\d*|\.\d+)/(\d+\.?\d*|\.\d+)$")
_NUMBER_RE = re.compile(r"^(?:\d+\.?\d*|\.\d+)$")


def midi_to_freq(m):
    return 440.0 * 2.0 ** ((m - 69) / 12)


def parse_note(text):
    """Return the frequency in Hz for `C4`, `Bb3`, `F#2` or a bare number like `440`."""
    m = _NOTE_RE.match(text)
    if m:
        letter, acc, octave = m.group(1).upper(), m.group(2), int(m.group(3))
        midi = 12 * (octave + 1) + _SEMITONE[letter] + (1 if acc == "#" else -1 if acc == "b" else 0)
        return midi_to_freq(midi)
    if _FREQ_RE.match(text):
        return float(text)
    raise SoundError("invalid note %r (use e.g. C4, F#3, Bb2 or a frequency in Hz)" % text)


def parse_beats(text):
    """`1`, `0.5`, `1.5`, `1/2`, `3/4` -> beats as float."""
    m = _FRACTION_RE.match(text)
    if m:
        den = float(m.group(2))
        if den == 0:
            raise SoundError("invalid beat length %r (zero denominator)" % text)
        return float(m.group(1)) / den
    if _NUMBER_RE.match(text):
        return float(text)
    raise SoundError("invalid beat length %r (use e.g. 1, 0.5, 1/2, 3/4)" % text)


MAX_PATTERN_DEPTH = 8
_PATTERN_REF_RE = re.compile(r"^@([^*\s]+)(?:\*(\d+))?$")


def parse_velocity(text, token):
    """`!velocity` suffix: a plain non-negative number (`0.6`, `1.2`, `0`); anything else is an error."""
    if not _NUMBER_RE.match(text):
        raise SoundError("invalid velocity %r in token %r (use a number >= 0, e.g. C4!0.6)" % (text, token))
    return float(text)


def parse_token(token):
    """Parse one token into (freqs, beats, is_arp); a `!velocity` suffix is accepted but dropped.

    Legacy 3-tuple view of parse_token_full(), kept for callers that do not need velocity.
    """
    return parse_token_full(token)[:3]


def parse_token_full(token):
    """Parse one token `pitches[:beats][!velocity]` into (freqs, beats, is_arp, velocity).

    The `!velocity` part is split off first (at the LAST `!`), then the `:beats` part.
    velocity defaults to 1 and multiplies the voice volume (a rest may carry one, unused).
    freqs is [] for a rest, one frequency per chord note (`+`), or the notes of an
    arpeggio (`~`) which plays on a single voice. `+` and `~` cannot be mixed.
    """
    velocity = 1.0
    head, bang, vel_text = token.rpartition("!")
    if bang:
        velocity = parse_velocity(vel_text, token)
        token = head
    freqs, beats, is_arp = _parse_pitches_beats(token)
    return freqs, beats, is_arp, velocity


def _parse_pitches_beats(token):
    pitches, sep, beats_text = token.partition(":")
    beats = parse_beats(beats_text) if sep else 1.0
    if pitches in ("r", "R", "-"):
        return [], beats, False
    if not pitches:
        raise SoundError("empty pitch in token %r" % token)
    if "+" in pitches and "~" in pitches:
        raise SoundError("token %r mixes '+' (chord) and '~' (arpeggio)" % token)
    if "~" in pitches:
        parts = pitches.split("~")
        if any(x in ("r", "R", "-") for x in parts):
            raise SoundError("token %r: a rest cannot be part of an arpeggio" % token)
        freqs = [parse_note(part) for part in parts]
        if any(f <= 0 for f in freqs):
            raise SoundError("token %r: arpeggio notes need frequencies > 0" % token)
        return freqs, beats, True
    return [parse_note(part) for part in pitches.split("+")], beats, False


def expand_patterns(text, patterns, depth=0):
    """Return the flat token list of `text` with `@name` / `@name*N` expanded.

    `|` is whitespace. Pattern bodies may reference other patterns up to
    MAX_PATTERN_DEPTH levels; an unknown name or a deeper chain is an error.
    """
    if not isinstance(text, str):
        raise SoundError("track notes / pattern bodies must be strings")
    out = []
    for tok in text.replace("|", " ").split():
        if not tok.startswith("@"):
            out.append(tok)
            continue
        m = _PATTERN_REF_RE.match(tok)
        if not m:
            raise SoundError("bad pattern reference %r (use @name or @name*N)" % tok)
        name, count = m.group(1), int(m.group(2)) if m.group(2) is not None else 1
        if name not in patterns:
            raise SoundError("unknown pattern %r in %r" % (name, tok))
        if depth + 1 > MAX_PATTERN_DEPTH:
            raise SoundError("patterns nested too deeply (max %d) at %r" % (MAX_PATTERN_DEPTH, tok))
        body = expand_patterns(patterns[name], patterns, depth + 1)
        out.extend(body * count)
    return out


def parse_notes(text, patterns=None):
    """Parse a notes string once (no loop); returns [(freqs, beats, is_arp)] (velocity dropped)."""
    return [ev[:3] for ev in parse_notes_full(text, patterns)]


def parse_notes_full(text, patterns=None):
    """Like parse_notes but keeps the velocity: [(freqs, beats, is_arp, velocity)]."""
    if not isinstance(text, str):
        raise SoundError("track notes must be a string")
    if patterns is None:
        patterns = {}
    if not isinstance(patterns, dict):
        raise SoundError("patterns must be an object")
    # `|` is a bar line, treated as whitespace (also when glued to notes).
    return [parse_token_full(tok) for tok in expand_patterns(text, patterns)]


def resolve_instrument(instr, presets):
    """Instrument = preset name, or a patch / layers object (optionally with "preset").

    Returns ("patch", resolved_patch), ("layers", raw_layers_spec) or ("kit", raw_kit_spec). Any
    other mode (expr, bytebeat, song...) is an error: only these can play notes.
    """
    raw = resolve_sound(instr, presets)
    mode = raw.get("mode") or "patch"
    if mode == "patch":
        return "patch", resolve_patch(raw)
    if mode == "layers":
        return "layers", raw
    if mode == "kit":
        if not isinstance(raw.get("map"), dict):
            raise SoundError("kit instrument needs a \"map\" object of MIDI note -> sound")
        return "kit", raw
    raise SoundError("song instrument must be a patch, layers or kit, got mode %r" % mode)


def kit_note(freq):
    """GM note number of a hit frequency: round(69 + 12*log2(freq/440)), round = floor(x + 0.5)."""
    if not freq > 0:
        raise SoundError("kit hits need a frequency > 0, got %r" % (freq,))
    return math.floor(69 + 12 * math.log2(freq / 440) + 0.5)


def resolve_kit_hit(raw, note, presets):
    """Sound of a kit entry for GM note `note`: ("patch", resolved) or ("layers", raw)."""
    key = str(note)
    if key not in raw["map"]:
        raise SoundError("kit has no sound for GM note %d (add \"%d\" to the kit map)" % (note, note))
    snd = resolve_sound(raw["map"][key], presets)
    mode = snd.get("mode") or "patch"
    if mode == "patch":
        return "patch", resolve_patch(snd)
    if mode == "layers":
        return "layers", snd
    raise SoundError("kit note %d must be a patch or layers sound, got mode %r" % (note, mode))


def resolve_duck(raw, ti, n_tracks):
    """Track `duck` {by, amount, release} -> (by, amount, release) or None.

    `by` must be the index of ANOTHER existing track; amount / release default to 0.6 / 0.25.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SoundError("track %d duck must be an object like {\"by\": 0, \"amount\": 0.6, \"release\": 0.25}" % ti)
    by = raw.get("by")
    if isinstance(by, float) and by.is_integer():
        by = int(by)
    if isinstance(by, bool) or not isinstance(by, int):
        raise SoundError("track %d duck.by must be a track index (integer), got %r" % (ti, raw.get("by")))
    if not 0 <= by < n_tracks:
        raise SoundError("track %d duck.by %d is not an existing track (0..%d)" % (ti, by, n_tracks - 1))
    if by == ti:
        raise SoundError("track %d cannot duck by itself" % ti)
    return by, _num(raw, "amount", 0.6), _num(raw, "release", 0.25)


def _voice_key(voice):
    """Cache key of a rendered patch voice, or None when it must never be shared.

    noise / crackle / pluck / breath consume the seeded PRNG (the seed differs per voice), so their voices
    are always rendered; every other voice is identical whatever its seed and can be reused.
    """
    if voice["osc"]["wave"] in ("noise", "crackle", "pluck") or voice["breath"]["level"] != 0:
        return None
    return json.dumps({k: v for k, v in voice.items() if k != "seed"}, sort_keys=True)


def _num(spec, key, default):
    v = spec.get(key)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v - v != 0:
        raise SoundError("%s must be a finite number, got %r" % (key, v))
    return float(v)


def render_song(spec, presets):
    """Mode `song`; returns a Rendered (stereo when any track has pan != 0)."""
    bpm = _num(spec, "bpm", 120.0)
    if bpm <= 0:
        raise SoundError("bpm must be > 0")
    song_gain = _num(spec, "gain", 0.9)
    seed = _num(spec, "seed", 1.0)
    # One beat in seconds, computed once: voice duration and start are `beats * beat * gate` and
    # `cursor * beat * SR` exactly like web/engine.js. Writing them as `x * 60 / bpm` differs by
    # 1 ulp, which can flip ceil() of a patch length by a whole sample (parity bug).
    beat = 60 / bpm
    eq = resolve_eq(spec.get("eq"), "eq")  # master eq on the summed mix, before gain
    space = sg_space.resolve_space(spec.get("space"))  # master space effects, after eq
    patterns = spec.get("patterns")
    tracks = spec.get("tracks")
    if tracks is None:
        tracks = []
    if not isinstance(tracks, list):
        raise SoundError("tracks must be a list")

    n_tracks = len(tracks)
    automation = resolve_automation(spec.get("automation"), bpm)  # master lowpass sweep, after eq
    master_drive = _num(spec, "drive", 0.0)                       # master tanh drive, after space
    voices = []        # [start, left, right, volume, pan, duck_gains]; right is None for mono voices
    voice_track = []   # track index of every entry of `voices` (sidechain triggers / duck targets)
    ducks = {}         # track index -> (by, amount, release)
    cache = {}         # identical non-noise voices render identically: reuse them
    voice_index = 0
    any_pan = False  # stereo-iff: any track pan != 0, even if that track makes no voice
    for ti, track in enumerate(tracks):
        if not isinstance(track, dict):
            raise SoundError("track %d must be an object" % ti)
        kind, inst = resolve_instrument(track.get("instrument"), presets)
        volume = _num(track, "volume", 0.8)
        # format.md: a muted track still renders (keeps voice indices / seeds of later
        # tracks stable) but contributes silence.
        if track.get("mute") is True:
            volume = 0.0
        gate = _num(track, "gate", 0.9)
        loops = int(_num(track, "loop", 1.0))
        # Pan is clamped; a muted track still counts toward the stereo-iff rule (mix_any
        # looks at every part, and muted tracks keep their voices at volume 0).
        pan = clamp_pan(_num(track, "pan", 0.0))
        any_pan = any_pan or pan != 0
        # 3D placement overrides pan; it is applied to every voice separately (own start sample)
        pos = sg_space.resolve_pos(track.get("pos"), "track %d pos" % ti)
        any_pan = any_pan or pos is not None
        duck = resolve_duck(track.get("duck"), ti, n_tracks)
        if duck is not None:
            ducks[ti] = duck
        placed = {}  # static pos (spin == 0): the result only depends on the voice (cache key)
        # Portamento chain (format.md): glide > 0 makes each voice after the track's first
        # sounding token start from the previous sounding token's first frequency.
        # (Ignored by layered instruments: they have no pitch.)
        glide = _num(track, "glide", 0.0)
        prev_freq = None  # first frequency of the previous sounding token (rests keep it)
        events = parse_notes_full(track.get("notes", ""), patterns)
        if kind == "patch":
            base_freq, base_end = inst["osc"]["freq"], inst["osc"]["freqEnd"]
            # Keeps the instrument's sweep shape (e.g. kick 160 -> 42) relative to the note.
            # A zero instrument freq has no ratio: use 1 (same as web/engine.js).
            sweep_ratio = base_end / base_freq if base_freq != 0 else 1.0

        def add_voice(start_idx, left, right, vol, key):
            """Append one voice, applying 3D placement (pos overrides pan) when the track has it."""
            if pos is None:
                voices.append([start_idx, left, right, vol, pan, None])
            else:
                if pos[1] == 0 and key:
                    # static pos: same voice (same cache key) -> same placed pair, start is irrelevant
                    pair = placed.get(key)
                    if pair is None:
                        pair = placed[key] = sg_space.place(sg_space.mono_of(left, right), start_idx, pos)
                else:
                    pair = sg_space.place(sg_space.mono_of(left, right), start_idx, pos)
                voices.append([start_idx, pair[0], pair[1], vol, 0.0, None])
            voice_track.append(ti)

        cursor = 0.0  # position in beats
        for _ in range(max(loops, 0)):
            for freqs, beats, is_arp, velocity in events:
                start = cursor * beat
                start_idx = math.floor(start * SR + 0.5)
                if kind == "kit":
                    # Drum kit: every pitch of the token (chord or arpeggio alike) is one hit; each
                    # hit has its own sound, duration and pitch. voiceIndex +1 per hit in written order.
                    for f in freqs:
                        hit_kind, hit = resolve_kit_hit(inst, kit_note(f), presets)
                        if hit_kind == "layers":
                            snd = copy.deepcopy(hit)
                            snd["seed"] = seed + voice_index
                            voice_index += 1
                            sub = render_layers(snd, presets)
                            add_voice(start_idx, sub[1], sub.right, volume * velocity, None)
                        else:
                            hit["seed"] = seed + voice_index
                            voice_index += 1
                            key = _voice_key(hit)
                            samples = cache.get(key) if key else None
                            if samples is None:
                                samples = render_patch(hit)
                                if key:
                                    cache[key] = samples
                            add_voice(start_idx, samples, None, volume * velocity, key)
                    cursor += beats
                    continue
                if kind == "layers":
                    # Layered instrument (clap, layered kick): ONE voice per sounding token; pitch and
                    # note length are ignored. The layers sound takes seed = song.seed + voiceIndex.
                    if freqs:
                        snd = copy.deepcopy(inst)
                        snd["seed"] = seed + voice_index
                        voice_index += 1
                        sub = render_layers(snd, presets)
                        add_voice(start_idx, sub[1], sub.right, volume * velocity, None)
                    cursor += beats
                    continue
                # An arpeggio is ONE voice at the first note; chords make one voice per note.
                voice_freqs = freqs[:1] if is_arp else freqs
                for f in voice_freqs:
                    voice = copy.deepcopy(inst)
                    voice["duration"] = beats * beat * gate
                    voice["osc"]["freq"] = f
                    voice["osc"]["freqEnd"] = f * sweep_ratio
                    if is_arp:
                        # steps are semitone offsets from the first note (first one is 0)
                        voice["arp"]["steps"] = [12 * math.log2(fk / f) for fk in freqs]
                    if glide > 0 and prev_freq is not None:
                        # every chord voice glides from the SAME previous frequency
                        voice["osc"]["glide"] = glide
                        voice["osc"]["glideFrom"] = prev_freq
                    voice["seed"] = seed + voice_index
                    voice_index += 1
                    key = _voice_key(voice)
                    samples = cache.get(key) if key else None
                    if samples is None:
                        samples = render_patch(voice)
                        if key:
                            cache[key] = samples
                    add_voice(start_idx, samples, None, volume * velocity, key)
                if voice_freqs:
                    prev_freq = voice_freqs[0]
                cursor += beats

    # Sidechain: triggers are the start samples of EVERY voice of the `by` track (muted or not).
    if ducks:
        triggers = {}
        for v, ti in zip(voices, voice_track):
            triggers.setdefault(ti, []).append(v[0])
        for v, ti in zip(voices, voice_track):
            if ti in ducks:
                by, amount, release = ducks[ti]
                v[5] = duck_gains(v[0], len(v[1]), sorted(triggers.get(by, [])), amount, release)

    return mix_any([tuple(v) for v in voices], song_gain, stereo=any_pan, eq=eq, space=space,
                   automation=automation, drive=master_drive)
