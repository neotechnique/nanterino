"""Tests of nanterino_ui.explorer (lot L43 extension, 2026-11-04): general native file explorer.

logging: robotlog via nanterino_ui.explorer (action + base name only).

Purpose
    navigate (path bar, up, back, bad path), list order + hidden toggle, text preview (md rendered, log plain,
    binary refused), open (dir stays inside, file goes to the opener seam), new folder, rename, trash move
    (freedesktop files/ + info/*.trashinfo, never unlink), name validation.
Boundary
    QT_QPA_PLATFORM=offscreen; temp dirs only (the trash is a temp dir too); xdg-open is a stub.
How to run (repo root)
    .venv/bin/python -m tests.test_ui_explorer      # prints PASS / FAIL and `ui_explorer tests: n/n passed`
"""
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, "/opt/robot/lib")
sys.path.insert(0, "/opt/robot/nanterino")
from PySide6.QtWidgets import QApplication  # noqa: E402

from nanterino_ui import explorer as E  # noqa: E402

res = []


def check(name, cond, info=""):
    res.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  " + str(info)), flush=True)


def names(w):
    return [r["name"] for r in w.rows]


def main():
    app = QApplication(sys.argv)
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="explorer-test-"))
    root = os.path.join(tmp, "root")
    trash = os.path.join(tmp, "trash")
    os.makedirs(os.path.join(root, "sub", "deep"))
    os.makedirs(os.path.join(root, "alpha"))
    for rel, data in (("zeta.txt", b"zeta"), ("note.md", b"# Titre\n\ntexte"), ("a.log", b"ligne1\nligne2\n"),
                      (".secret", b"x"), ("blob.bin", b"\x00\x01\x02"), ("sub/in.txt", b"dedans")):
        with open(os.path.join(root, rel), "wb") as f:
            f.write(data)

    opened, answers = [], {"name": None, "confirm": True}
    w = E.ExplorerWindow(root, trash_dir=trash, opener=opened.append,
                         ask_name=lambda t, l, d="": answers["name"], ask_confirm=lambda t: answers["confirm"])
    check("start: dirs first then files by name, hidden off", names(w) == ["alpha", "sub", "a.log", "blob.bin", "note.md", "zeta.txt"], names(w))
    w.hidden.setChecked(True)
    check("hidden toggle shows .secret", ".secret" in names(w))
    w.hidden.setChecked(False)

    # navigation
    w.open_row(names(w).index("sub"))
    check("double click on a folder stays inside the explorer", w.cwd == os.path.join(root, "sub") and not opened)
    w.go_up()
    check("up", w.cwd == root)
    w.go_back()
    check("back returns to the previous folder", w.cwd == os.path.join(root, "sub"))
    w.pathbar.setText(os.path.join(root, "alpha"))
    w.pathbar.returnPressed.emit()
    check("path bar navigates", w.cwd == os.path.join(root, "alpha"))
    check("bad path refused, cwd unchanged", w.navigate(os.path.join(root, "nope")) is False and w.cwd == os.path.join(root, "alpha")
          and "introuvable" in w.status.text())
    w.navigate(root)

    # preview
    w.table.setCurrentCell(names(w).index("note.md"), 0)
    check("preview: markdown rendered (no # marker)", "Titre" in w.preview.toPlainText() and "# Titre" not in w.preview.toPlainText(),
          w.preview.toPlainText())
    w.table.setCurrentCell(names(w).index("a.log"), 0)
    check("preview: log plain text", w.preview.toPlainText() == "ligne1\nligne2\n")
    w.table.setCurrentCell(names(w).index("blob.bin"), 0)
    check("preview: unknown extension gives no preview", w.preview.toPlainText() == "")

    # open file -> opener seam
    w.open_row(names(w).index("zeta.txt"))
    check("file goes to the opener", opened == [os.path.join(root, "zeta.txt")], opened)

    # new folder
    answers["name"] = "nouveau"
    w.new_folder()
    check("new folder created and selected", os.path.isdir(os.path.join(root, "nouveau")) and w.selected()["name"] == "nouveau")
    w.new_folder()
    check("new folder over an existing name refused", "existe déjà" in w.status.text())
    for bad in ("../x", "a/b", "..", ""):
        answers["name"] = bad
        w.new_folder()
    check("odd names create nothing", not os.path.exists(os.path.join(tmp, "x")) and not os.path.exists(os.path.join(root, "a")))

    # rename
    w.table.setCurrentCell(names(w).index("zeta.txt"), 0)
    answers["name"] = "omega.txt"
    w.rename_selected()
    check("rename", not os.path.exists(os.path.join(root, "zeta.txt")) and open(os.path.join(root, "omega.txt")).read() == "zeta")
    answers["name"] = "note.md"
    w.rename_selected()
    check("rename onto existing refused, both files intact", os.path.exists(os.path.join(root, "omega.txt"))
          and "existe déjà" in w.status.text())

    # trash
    answers["confirm"] = False
    w.delete_selected()
    check("delete declined: nothing moves", os.path.exists(os.path.join(root, "omega.txt")))
    answers["confirm"] = True
    w.delete_selected()
    tfile = os.path.join(trash, "files", "omega.txt")
    tinfo = os.path.join(trash, "info", "omega.txt.trashinfo")
    check("trash: moved to files/, content intact, info written",
          not os.path.exists(os.path.join(root, "omega.txt")) and open(tfile).read() == "zeta"
          and os.path.isfile(tinfo) and "[Trash Info]" in open(tinfo).read()
          and "Path=%s" % os.path.join(root, "omega.txt") in open(tinfo).read(), os.listdir(trash) if os.path.isdir(trash) else "no trash")
    # same name again: unique suffix, first one untouched
    with open(os.path.join(root, "omega.txt"), "w") as f:
        f.write("second")
    w.refresh()
    w.table.setCurrentCell(names(w).index("omega.txt"), 0)
    w.delete_selected()
    check("trash: name clash gets a suffix, nothing overwritten", open(tfile).read() == "zeta"
          and open(os.path.join(trash, "files", "omega.txt.2")).read() == "second")
    # folder trash
    w.table.setCurrentCell(names(w).index("alpha"), 0)
    w.delete_selected()
    check("trash: a folder moves as a whole", os.path.isdir(os.path.join(trash, "files", "alpha")) and not os.path.exists(os.path.join(root, "alpha")))

    st = E.ExplorerStore(trash)
    try:
        st.trash("/")
        refused = False
    except E.ExplorerError:
        refused = True
    check("trashing / refused", refused)

    shutil.rmtree(tmp)
    print(f"ui_explorer tests: {sum(res)}/{len(res)} passed")
    return 0 if all(res) else 1


if __name__ == "__main__":
    sys.exit(main())
