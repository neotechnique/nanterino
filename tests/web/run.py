"""Runner of the Nanterino editor web suite (headless Firefox through geckodriver, live server on :8080).

Purpose : run editor scenarios by name, by area or all, and print one `SUMMARY <n> checks, <f> failed: [...]` line
          (the line l7_scenarios.sh and the orchestrator read).
Boundary: drives the live editor only (HTTP + WebDriver); never imports nanterino.server. Never POSTs
          /api/control start/off/on; the only live action is one `hush`. Saving scenarios roll back what they save.
Usage   : cd /opt/robot/nanterino && .venv/bin/python -m tests.web.run <name> [...]
          <name> = a scenario (exact name wins), `area:<area>` or a bare area name that is not also a scenario,
          `all` (every scenario in the order of the former single file), `--list` (print area / scenario table).
          One process = one browser session; l7_scenarios.sh starts one process per scenario.
Layout  : wd.py (WebDriver session), driver.py (check(), shared helpers), one file per editor area with SCENARIOS.
Invariant: M7 moved /opt/robot/scripts/editor6_wd.py here verbatim (26 scenarios, 441 checks); keep the per-scenario
          check counts when moving code between files. L22 adds scenario `progress` (area progress); L23 adds
          `postitsave` (area savegate: post-its, groups and hierarchy edits are save-gated); L29 adds `emptylist`
          (area diagnostics: server empty_list amber badge, gone once a list_add fills the list; never saves); S1 adds
          `domains` (area domains: domains above the columns, two-level jump bar, column moved to another domain,
          domain / column fold cards; saves once, rolled back). C3 adds `mechanics` (area mechanics: the dashboard
          « Mécanique » screen on the simulated body: joints, bounded sliders, set min, e-stop latch / reset, export /
          import; never saves the graph, calibration rolled back).

History of the former scripts/editor6_wd.py (scenario -> lot, kept for reference):
Headless Firefox checks of lot L6 (state nodes, gradient wires, ports, post-its, mouse buttons, context menu).

Usage: editor6_wd.py <scenario> [...]   scenarios: nodes wires tester buttons menu postit ctxsub nav noinput vars testervars
    nostart wiredrag (lot L4: no Start node; wires follow a node / frame drag, undo and zoom)
    menu3 tooltips postit2 diag (lot L5: categorised node menu, tooltips, post-it display modes, node diagnostics;
    screenshots tests/results/editor11-*.png)
    l6 (lot L6: column titles clear of the jump bar, fresh check on save, minimap diagnostics; editor12-*.png)
    human (lot L7: the user's manual checks with real pointer/key/touch actions; VIEWPORT=WxH env, default 1280x700)
    l8 (lot L8: node hover tooltips, minimap press-and-drag navigation, nested groups and post-its in groups;
    screenshots tests/results/editor13-*.png; saves once, rolled back at the end)
    postit3 (lot L9: default post-its of the state columns: text, parent, moves with the column, deletion persists;
    saves, rolled back at the end). L9 also rewrote the nesting part of l8 with human-like pointer drops.
    l10 (lot L10: flat right-click menu, type-to-filter, fragment clipboard, hierarchy panel with fold / badges / filter /
    select + centre / drag-drop filing, inspector of a chain / column; screenshots tests/results/editor15-*.png; never saves).
    vars2 (lot L12: Variables v2 manager: every vocabulary type, bounds, scope / persist, dict / shuffle / history lists,
    save + reload, Réinitialiser, chrono tick + persisted conflict (fetch stub), Tester by scope, time conditions,
    op_sets, out_of_bounds badge; screenshots tests/results/editor16-*.png; saves once, rolled back, state/ removed).
    subgroups (lot L13: default sub-groups inside the state columns: hierarchy Colonne > sous-groupe > chaînes, column /
    sub-group drags move their content and wires, titles clear of the jump bar; editor17-*.png; never saves).
    export (lot L14: toolbar "Exporter l'image" -> options popover -> progress toast -> PNG served as an attachment,
    valid PNG of the robot job's size; editor18-*.png; download kept in memory, never saves).
    props (lot M5: value source picker ▾ in the inspector: $x shorthand, random_from_list, nested calc with typed
    literals, incompatible sources hidden, depth limit, server type badge, Valeur fixe, save + reload, Tester value;
    editor18-props.png; saves once, rolled back).
    progress (lot L22: the one non-blocking progress bar: boot, fast / slow fetch, aggregation, cancel chip, error,
    no overlap / overlay, stubbed save, Valider, real non-cached export with pan + context menu; editor19-progress.png).
    L13 ADAPTED nodes, l8, postit3 and l10 (they assumed flat columns: only column frames / column post-its).
    L10 ADAPTED the older palette / "Insérer un nœud" checks (menu, postit, ctxsub, nav, nostart, menu3, tooltips, human).
Vars L2 (2026-10-31): no State hub / go-to any more (etat is a variable); triggers have no input port; Variables panel.
Writes tests/results/editor6-*.png. Never POSTs /api/control start/off/on; the only live action is one `hush`.
Everything it saves (post-it scenario) is rolled back at the end (reset + its own .bak files removed).
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from tests.web.driver import W, BASE, check, checks  # noqa: E402

# Area files, in the order their scenarios appeared in the former single file (for `all`).
AREAS = ["canvas", "tester", "menu", "frames", "variables", "tooltips", "diagnostics", "human", "hierarchy",
         "export", "inspector", "progress", "savegate", "domains", "mechanics"]
# Order of the former single file, which `all` keeps (the scenarios share one browser session there).
ALL_ORDER = ["nodes", "wires", "tester", "buttons", "menu", "postit", "ctxsub", "nav", "noinput", "vars", "testervars",
             "nostart", "wiredrag", "menu3", "tooltips", "postit2", "diag", "l6", "human", "l8", "postit3", "l10",
             "vars2", "switch", "subgroups", "export", "props", "progress", "postitsave", "emptylist", "domains", "mechanics"]


def registry():
    """{scenario: (area, function)} from every area file's SCENARIOS."""
    reg = {}
    for area in AREAS:
        mod = importlib.import_module("tests.web." + area)
        for name, fn in mod.SCENARIOS.items():
            if name in reg:
                raise SystemExit("scenario %s defined in %s and %s" % (name, reg[name][0], area))
            reg[name] = (area, fn)
    missing = set(reg) ^ set(ALL_ORDER)
    if missing:
        raise SystemExit("ALL_ORDER out of date: %s" % sorted(missing))
    return reg


def expand(args, reg):
    """Scenario names to run; an unknown name is kept and fails as `scenario <x> completed`, as before."""
    out = []
    for a in args:
        if a == "all":
            out += ALL_ORDER
        elif a in reg:
            out.append(a)
        elif a.startswith("area:") or a in AREAS:
            area = a.split(":", 1)[-1]
            out += [n for n in ALL_ORDER if reg[n][0] == area] or [a]
        else:
            out.append(a)
    return out


def main():
    reg = registry()
    if sys.argv[1:] == ["--list"]:
        for n in ALL_ORDER:
            print("%-12s %s" % (reg[n][0], n))
        return
    names = expand(sys.argv[1:], reg)
    wd = W.WD()
    # L7: QA viewport 1280 x 700
    vw, vh = [int(v) for v in os.environ.get("VIEWPORT", "1280x700").split("x")]   # human scenario runs at 1920x1080 / 1366x768 too
    wd.cmd("POST", "/window/rect", {"width": vw, "height": vh, "x": 0, "y": 0})
    try:   # make the INNER viewport 1280 x 700 (the window rect includes the browser chrome)
        wd.go(BASE + "/editor#quiet")
        dw, dh = wd.js("return [outerWidth-innerWidth, outerHeight-innerHeight]")
        wd.cmd("POST", "/window/rect", {"width": vw + dw, "height": vh + dh, "x": 0, "y": 0})
    except Exception as e:  # keep the outer size
        print("viewport adjust failed", e)
    try:
        for name in names:
            print("==", name, flush=True)
            try:
                reg[name][1](wd)
            except Exception as e:  # keep going, report (an unknown name lands here as a KeyError)
                import traceback
                traceback.print_exc()
                check("scenario %s completed" % name, False, repr(e))
    finally:
        wd.close()
    bad = [n for n, ok in checks if not ok]
    print("SUMMARY %d checks, %d failed: %s" % (len(checks), len(bad), bad))
    # exit code for runners (the former script always exited 0; l7_scenarios.sh ignores it)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
