#!/usr/bin/env python3
"""soundgen - generate sound from math (stdlib only).

Subcommands: render, export, expr, bytebeat, presets, show, info, sync-web.
The JSON format is defined in docs/format.md and shared with the web Sound Lab.
"""

import argparse
import fnmatch
import json
import os
import sys
import time

# Make sibling modules importable no matter where the script is launched from.
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import sg_engine  # noqa: E402
import sg_post  # noqa: E402
import sg_wav  # noqa: E402


class CliError(Exception):
    """User-facing error: printed as `error: ...`, exit code 1."""


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except OSError as exc:
        raise CliError("cannot read %s: %s" % (path, exc.strerror or exc))
    except json.JSONDecodeError as exc:
        raise CliError("invalid JSON in %s: %s (line %d, column %d)" % (path, exc.msg, exc.lineno, exc.colno))


def parse_set_value(text):
    """`--set` values are JSON when they parse (numbers, true, "x", [..]), else raw text."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def apply_set(spec, assignment):
    """Apply `a.b.c=value` (list indexes allowed: tracks.0.volume=0.5) in place."""
    key, sep, raw = assignment.partition("=")
    if not sep or not key.strip():
        raise CliError("--set expects key.path=value, got %r" % assignment)
    parts = key.strip().split(".")
    node = spec
    for k in parts[:-1]:
        node = _child(node, k, create=True, path=key)
    last = parts[-1]
    value = parse_set_value(raw)
    if isinstance(node, list):
        try:
            node[int(last)] = value
        except (ValueError, IndexError):
            raise CliError("--set %s: bad list index %r" % (key, last))
    elif isinstance(node, dict):
        node[last] = value
    else:
        raise CliError("--set %s: cannot set a key inside a non-object" % key)


def _child(node, k, create, path):
    if isinstance(node, list):
        try:
            return node[int(k)]
        except (ValueError, IndexError):
            raise CliError("--set %s: bad list index %r" % (path, k))
    if isinstance(node, dict):
        if not isinstance(node.get(k), (dict, list)):
            if not create:
                raise CliError("--set %s: %r is not an object" % (path, k))
            node[k] = {}
        return node[k]
    raise CliError("--set %s: cannot descend into a non-object" % path)


def render_spec(spec, presets):
    """Render a spec; returns (rendered, elapsed) where rendered = (rate, samples) + `.right`."""
    try:
        t0 = time.perf_counter()
        rendered = sg_engine.render_sound(spec, presets)
        return rendered, time.perf_counter() - t0
    except (ValueError, RecursionError) as exc:  # SoundError, ExprError are ValueErrors
        raise CliError(str(exc))


def post_process(rendered, post):
    """Run sg_post on a rendered sound; returns (rate, samples, right_or_None).

    Mono goes through the unchanged mono path; stereo through the two-channel path so both
    channels get the same trim, one joint-peak gain, and per-channel fades / resampling.
    """
    rate, samples = rendered
    if rendered.right is None:
        rate, samples = sg_post.process(samples, rate, **post)
        return rate, samples, None
    return sg_post.process_stereo(samples, rendered.right, rate, **post)


def post_options(args):
    """Validate the post-processing flags (render/export) and return sg_post.process kwargs."""
    for flag in ("fade_in", "fade_out"):
        v = getattr(args, flag, None)
        if v is not None and v < 0:
            raise CliError("--%s expects a number >= 0" % flag.replace("_", "-"))
    if getattr(args, "rate", None) is not None and args.rate < 1:
        raise CliError("--rate expects a sample rate >= 1")
    return {"trim_silence": bool(getattr(args, "trim", False)),
            "normalize_db": getattr(args, "normalize", None),
            "fade_in_s": getattr(args, "fade_in", None) or 0.0,
            "fade_out_s": getattr(args, "fade_out", None) or 0.0,
            "new_rate": getattr(args, "rate", None)}


def finish(rate, samples, out_path, elapsed, play, right=None):
    if not samples:
        raise CliError("nothing to render (0 samples); check duration or notes")
    try:
        sg_wav.write_wav(out_path, rate, samples, right)
    except OSError as exc:
        raise CliError("cannot write %s: %s" % (out_path, exc.strerror or exc))
    print("wrote %s" % os.path.abspath(out_path))
    kind = "" if right is None else ", stereo"
    print("  " + sg_wav.format_stats(rate, sg_wav.stats(samples, rate, right)) + kind
          + "  [rendered in %.2f s]" % elapsed)
    if play:
        play_wav(out_path)


def play_wav(path):
    if sys.platform.startswith("win"):
        import winsound
        winsound.PlaySound(os.path.abspath(path), winsound.SND_FILENAME)
    else:
        print("note: --play is only supported on Windows; open %s manually" % path)


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------

def cmd_render(args):
    post = post_options(args)
    presets = sg_engine.load_presets()
    target = args.target
    if os.path.isfile(target):
        spec = load_json_file(target)
        stem = os.path.splitext(os.path.basename(target))[0]
        out_dir = os.path.dirname(os.path.abspath(target))
    elif target in presets:
        spec = dict(presets[target])
        spec.setdefault("name", target)
        stem, out_dir = target, os.getcwd()
    else:
        hint = ""
        if target.lower().endswith(".json"):
            hint = " (file not found)"
        raise CliError("%r is neither a JSON file nor a preset name%s; run `presets` to list presets"
                       % (target, hint))
    if not isinstance(spec, dict):
        raise CliError("%s must contain a JSON object" % target)
    for assignment in args.set or []:
        apply_set(spec, assignment)
    if args.seed is not None:
        spec["seed"] = args.seed
    if args.variants is None:
        rendered, elapsed = render_spec(spec, presets)
        rate, samples, right = post_process(rendered, post)
        out = args.output or os.path.join(out_dir, stem + ".wav")
        finish(rate, samples, out, elapsed, args.play, right)
        return
    if args.variants < 1:
        raise CliError("--variants expects a number >= 1")
    # Variant k is the same spec with top-level seed + k (k = 0..N-1), see docs/format.md.
    base_seed = spec.get("seed")
    if base_seed is None:
        base_seed = 1
    if isinstance(base_seed, bool) or not isinstance(base_seed, (int, float)):
        raise CliError("seed must be a number to use --variants, got %r" % (base_seed,))
    if args.output:
        out_stem = os.path.splitext(args.output)[0]
    else:
        out_stem = os.path.join(out_dir, stem)
    for k in range(args.variants):
        variant = dict(spec)
        variant["seed"] = base_seed + k
        rendered, elapsed = render_spec(variant, presets)
        rate, samples, right = post_process(rendered, post)
        finish(rate, samples, "%s_%d.wav" % (out_stem, k + 1), elapsed, args.play and k == 0, right)


def add_post_arguments(p, with_fade_in=True):
    """Post-processing flags shared by `render` and `export` (applied after rendering)."""
    p.add_argument("--normalize", type=float, metavar="DB", help="scale so the peak equals DB dBFS (e.g. -1)")
    if with_fade_in:
        p.add_argument("--fade-in", type=float, metavar="SEC", help="linear fade-in length in seconds")
    p.add_argument("--fade-out", type=float, metavar="SEC", help="linear fade-out length in seconds")
    p.add_argument("--trim", action="store_true", help="remove leading/trailing near-silence (abs < 1e-4)")
    p.add_argument("--rate", type=int, metavar="N", help="resample output to N Hz (linear interpolation)")


def resolve_selectors(selectors, presets):
    """Expand selectors to an ordered, de-duplicated list of (name, spec); error if any matches nothing.

    Resolution order per selector: `all`; existing file (.json); `*` pattern over preset names;
    exact preset name. Every selector is validated before anything is rendered.
    """
    found = {}
    for sel in selectors:
        if sel == "all":
            matches = [(n, dict(presets[n])) for n in presets]
        elif os.path.isfile(sel):
            spec = load_json_file(sel)
            if not isinstance(spec, dict):
                raise CliError("%s must contain a JSON object" % sel)
            matches = [(os.path.splitext(os.path.basename(sel))[0], spec)]
        elif "*" in sel or "?" in sel:
            matches = [(n, dict(presets[n])) for n in presets if fnmatch.fnmatchcase(n, sel)]
        elif sel in presets:
            matches = [(sel, dict(presets[sel]))]
        else:
            matches = []
        if not matches:
            raise CliError("selector %r matches no preset or JSON file; run `presets` to list presets" % sel)
        # Kits are song instruments, not sounds: they cannot be exported as WAV. A selector that
        # only matches kits is an error; `all` / wildcards just skip them with a note.
        kits = [m for m in matches if (m[1].get("mode") or "patch") == "kit"]
        if kits:
            if len(kits) == len(matches):
                raise CliError("%r is a drum kit (only valid as a song instrument); export a song that uses it"
                               % sel)
            print("skipped %d drum kit(s) (song instruments only): %s" % (len(kits), ", ".join(n for n, _ in kits)))
            matches = [m for m in matches if m not in kits]
        for name, spec in matches:
            spec.setdefault("name", name)
            found.setdefault(name, spec)  # first selector wins on duplicate names
    return list(found.items())


def cmd_export(args):
    post = post_options(args)
    if args.variants is not None and args.variants < 1:
        raise CliError("--variants expects a number >= 1")
    presets = sg_engine.load_presets()
    items = resolve_selectors(args.selectors, presets)  # validate ALL selectors before rendering
    prefix = args.prefix or ""
    out_dir = args.out
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as exc:
        raise CliError("cannot create %s: %s" % (out_dir, exc.strerror or exc))
    count = args.variants or 1
    sounds, total_bytes, files_written, rates = {}, 0, 0, []
    for name, spec in items:
        out_name = prefix + name
        base_seed = spec.get("seed")
        if base_seed is None:
            base_seed = 1
        if isinstance(base_seed, bool) or not isinstance(base_seed, (int, float)):
            raise CliError("%s: seed must be a number, got %r" % (name, base_seed))
        files, durations, peaks = [], [], []
        channels = 1  # stereo as soon as one variant is (pan does not depend on the seed)
        for k in range(count):
            variant = dict(spec)
            variant["seed"] = base_seed + k  # same rule as `render --variants`
            rendered, _ = render_spec(variant, presets)
            rate, samples, right = post_process(rendered, post)
            if right is not None:
                channels = 2
            if not samples:
                raise CliError("%s: nothing to render (0 samples)" % name)
            rel = "%s_%d.wav" % (out_name, k + 1) if args.variants else out_name + ".wav"
            path = os.path.join(out_dir, rel)
            try:
                sg_wav.write_wav(path, rate, samples, right)
            except OSError as exc:
                raise CliError("cannot write %s: %s" % (path, exc.strerror or exc))
            size = os.path.getsize(path)
            total_bytes += size
            files_written += 1
            files.append(rel)
            durations.append(len(samples) / rate)
            db = sg_post.peak_db(samples, right)
            if db is not None:
                peaks.append(db)
            print("%s  (%.3f s, %d bytes)" % (rel, durations[-1], size))
        rates.append(rate)
        # Duration and peak summarise all variants (longest / loudest) so game code can budget safely.
        sounds[out_name] = {"files": files, "duration": round(max(durations), 6),
                            "peak": round(max(peaks), 3) if peaks else None,
                            "mode": spec.get("mode") or "patch", "variants": count,
                            "sampleRate": rate, "channels": channels}
    # Top-level sampleRate is null only when sounds differ (e.g. a bytebeat); see each sound's own rate.
    manifest = {"generator": "soundgen",
                "sampleRate": rates[0] if len(set(rates)) == 1 else None,
                "sounds": sounds}
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    print("exported %d sound(s), %d file(s), %.1f KiB total -> %s"
          % (len(sounds), files_written, total_bytes / 1024.0, os.path.abspath(out_dir)))


def cmd_expr(args):
    spec = {"mode": "expr", "expr": args.formula, "duration": args.duration, "gain": args.gain}
    (rate, samples), elapsed = render_spec(spec, sg_engine.load_presets())
    finish(rate, samples, args.output or "expr.wav", elapsed, args.play)


def cmd_bytebeat(args):
    spec = {"mode": "bytebeat", "expr": args.formula, "duration": args.duration,
            "rate": args.rate, "gain": args.gain}
    (rate, samples), elapsed = render_spec(spec, sg_engine.load_presets())
    finish(rate, samples, args.output or "bytebeat.wav", elapsed, args.play)


def preset_summary(raw, presets):
    """One-line description; patches show wave and sweep, other modes their length."""
    mode = raw.get("mode") or "patch"
    if mode == "patch":
        p = sg_engine.resolve_patch(raw)
        o = p["osc"]
        return "%-8s %g -> %g Hz  %g s" % (o["wave"], o["freq"], o["freqEnd"], p["duration"])
    label = mode
    if mode == "kit":
        # A kit cannot be rendered on its own (song instrument only): list its size instead.
        return "kit (%d sounds)" % len(raw.get("map") or {})
    if mode == "layers":
        label = "layers (%d)" % len(raw.get("layers") or [])
    try:
        rate, samples = sg_engine.render_sound(raw, presets)  # stereo: left length == right length
        return "%-12s %.3f s" % (label, len(samples) / rate)
    except ValueError as exc:  # a broken preset must not break the whole listing
        return "%-12s error: %s" % (label, exc)


def cmd_presets(_args):
    presets = sg_engine.load_presets()
    width = max(len(n) for n in presets)
    for name, raw in presets.items():
        print("%-*s  %s" % (width, name, preset_summary(raw, presets)))


def cmd_show(args):
    presets = sg_engine.load_presets()
    if args.preset not in presets:
        raise CliError("unknown preset %r; run `presets` to list them" % args.preset)
    raw = presets[args.preset]
    mode = raw.get("mode") or "patch"
    if mode == "patch":
        shown = sg_engine.resolve_patch(raw)
    elif mode == "layers":
        shown = sg_engine.layers_defaults(raw)  # top-level defaults only; layers are shown as written
    else:
        shown = dict(raw)
    shown["name"] = args.preset
    print(json.dumps(_tidy(shown), indent=2))


def _tidy(node):
    """Show integral floats as ints (1.0 -> 1) for readable output."""
    if isinstance(node, dict):
        return {k: _tidy(v) for k, v in node.items()}
    if isinstance(node, float) and node == int(node):
        return int(node)
    return node


def cmd_info(args):
    try:
        rate, samples, channels = sg_wav.read_wav(args.file)
    except (OSError, EOFError) as exc:
        raise CliError("cannot read %s: %s" % (args.file, getattr(exc, "strerror", None) or exc))
    except Exception as exc:  # wave.Error and friends: not a valid WAV
        raise CliError("%s is not a readable 16-bit PCM WAV: %s" % (args.file, exc))
    # read_wav interleaves the channels: split them so "samples" and "seconds" count frames.
    chans = sg_wav.split_channels(samples, channels)
    if channels in (1, 2):
        st = sg_wav.stats(chans[0], rate, chans[1] if channels == 2 else None)
    else:  # >2 channels is not produced by this tool: keep the interleaved estimate
        st = sg_wav.stats(samples, rate)
        st["seconds"] /= channels
    print("%s: %d channel(s), %s" % (args.file, channels, sg_wav.format_stats(rate, st)))


def cmd_sync_web(_args):
    presets = sg_engine.load_presets()
    web = os.path.join(HERE, "web")
    os.makedirs(web, exist_ok=True)
    path = os.path.join(web, "presets.js")
    body = ("// GENERATED from ../presets.json by `soundgen sync-web`. Do not edit by hand.\n"
            "window.SG_PRESETS = %s;\n" % json.dumps(presets, indent=2))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    print("wrote %s (%d presets)" % (path, len(presets)))
    # Song examples become the web Sequencer's demo cards (key = file stem).
    ex_dir = os.path.join(HERE, "examples")
    songs = {}
    # A missing examples/ folder (e.g. a relocated test tree) just yields no demo songs.
    for name in sorted(os.listdir(ex_dir)) if os.path.isdir(ex_dir) else []:
        if name.endswith(".json"):
            with open(os.path.join(ex_dir, name), encoding="utf-8") as fh:
                spec = json.load(fh)
            if spec.get("mode") == "song":
                songs[name[:-5]] = spec
    path = os.path.join(web, "songs.js")
    body = ("// GENERATED from ../examples/*.json (mode song) by `soundgen sync-web`. Do not edit by hand.\n"
            "window.SG_SONGS = %s;\n" % json.dumps(songs, indent=1, ensure_ascii=False))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    print("wrote %s (%d songs)" % (path, len(songs)))


# --------------------------------------------------------------------------
# argument parsing
# --------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(prog="soundgen", description="Generate sound from math (see docs/format.md).")
    sub = ap.add_subparsers(dest="command", required=True)

    r = sub.add_parser("render", help="render a JSON patch/song file or a preset name to WAV")
    r.add_argument("target", help="path to a .json file, or a preset name")
    r.add_argument("-o", "--output", help="output WAV path (default: <stem>.wav)")
    r.add_argument("--set", action="append", metavar="KEY.PATH=VALUE",
                   help="override a field before rendering, e.g. --set osc.freq=880 (repeatable)")
    r.add_argument("--seed", type=int, help="override the PRNG seed")
    r.add_argument("--variants", type=int, metavar="N",
                   help="write N variants <stem>_1.wav .. <stem>_N.wav with seed + 0..N-1")
    add_post_arguments(r)
    r.add_argument("--play", action="store_true", help="play the result (Windows only)")
    r.set_defaults(func=cmd_render)

    x = sub.add_parser("export", help="batch-render presets/JSON files to WAVs + manifest.json for a game")
    x.add_argument("selectors", nargs="+", metavar="selector",
                   help="preset name, prefix pattern with * (footstep-*), .json path, or `all`")
    x.add_argument("--out", default="sound-export", help="output directory (default: ./sound-export)")
    x.add_argument("--variants", type=int, metavar="N", help="N variants <name>_1.wav .. <name>_N.wav")
    x.add_argument("--prefix", help="string prepended to every exported name")
    add_post_arguments(x, with_fade_in=False)
    x.set_defaults(func=cmd_export)

    for name, fn, dur, helptext in (("expr", cmd_expr, 2.0, "render a formula of time t"),
                                    ("bytebeat", cmd_bytebeat, 10.0, "render a bytebeat formula of integer t")):
        e = sub.add_parser(name, help=helptext)
        e.add_argument("formula", help="expression, e.g. \"sin(2*pi*440*t)*exp(-3*t)\"")
        e.add_argument("-d", "--duration", type=float, default=dur, help="seconds (default %(default)s)")
        e.add_argument("-o", "--output", help="output WAV path (default: %s.wav)" % name)
        e.add_argument("--gain", type=float, default=0.8, help="output gain (default %(default)s)")
        e.add_argument("--play", action="store_true", help="play the result (Windows only)")
        if name == "bytebeat":
            e.add_argument("--rate", type=int, default=8000, help="sample rate in Hz (default %(default)s)")
        e.set_defaults(func=fn)

    sub.add_parser("presets", help="list presets").set_defaults(func=cmd_presets)
    s = sub.add_parser("show", help="print a preset with all defaults filled in")
    s.add_argument("preset")
    s.set_defaults(func=cmd_show)
    i = sub.add_parser("info", help="print rate, length, peak and rms of a WAV file")
    i.add_argument("file")
    i.set_defaults(func=cmd_info)
    sub.add_parser("sync-web", help="generate web/presets.js from presets.json").set_defaults(func=cmd_sync_web)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except CliError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
