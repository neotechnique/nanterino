"""Tests of nanterino_ui.corpus (lot L43, 2026-11-04): native corpus explorer.

logging: robotlog via nanterino_ui.corpus (action + file name only).

Purpose
    list / filter, title parse, new-from-template (comment block stripped, existing name refused), atomic save,
    rename, delete-to-trash (never unlink), path traversal rejected, unsaved-change guard (dialogs stubbed).
Boundary
    QT_QPA_PLATFORM=offscreen. Works ONLY on a temp copy of the real fiches folder (copied, never written back);
    no network (the reload button is not clicked), no single-instance socket.
How to run (repo root)
    .venv/bin/python -m tests.test_ui_corpus      # prints PASS / FAIL and `ui_corpus tests: n/n passed`
"""
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, "/opt/robot/lib")
sys.path.insert(0, "/opt/robot/nanterino")
from PySide6.QtWidgets import QApplication  # noqa: E402

from nanterino_ui import corpus as C  # noqa: E402

res = []


def check(name, cond, info=""):
    res.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  " + str(info)), flush=True)


def main():
    app = QApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix="corpus-test-")
    folder = os.path.join(tmp, "fiches")
    shutil.copytree(C.DEFAULT_DIR, folder, ignore=shutil.ignore_patterns(".corbeille"))
    n_real = len([f for f in os.listdir(folder) if f.endswith(".md")])
    os.makedirs(os.path.join(folder, ".hidden-dir"))
    open(os.path.join(folder, ".caché.md"), "w").close()

    st = C.CorpusStore(folder)
    sheets = st.list_sheets()
    check("list: every .md, hidden ignored, template apart", len(sheets) == n_real and n_real > 10
          and all(not s["file"].startswith(".") and s["file"] != C.TEMPLATE for s in sheets), len(sheets))
    check("title: first # heading", C.title_of("intro\n# Mon Lieu\n- x", "f.md") == "Mon Lieu")
    check("title: file name fallback", C.title_of("pas de titre", "f.md") == "f.md")
    check("slugify: accents + punctuation", C.slugify("Parc André Malraux !") == "parc-andre-malraux" and C.slugify("???") == "")

    # ---- traversal / bad names
    bad = ["../x.md", "a/b.md", "..\\x.md", ".hidden.md", "x.txt", "", "UP.md", "/etc/passwd"]
    refused = 0
    for b in bad:
        try:
            st.path(b)
        except C.StoreError:
            refused += 1
    check("traversal and odd names rejected", refused == len(bad), refused)
    try:
        st.save("../evil.md", "x")
        wrote = os.path.exists(os.path.join(tmp, "evil.md"))
    except C.StoreError:
        wrote = False
    check("save outside the folder refused, nothing written", not wrote)

    # ---- window
    asked = []
    answers = {"unsaved": "cancel", "name": None, "confirm": True}
    w = C.CorpusWindow(folder,
                       ask_unsaved=lambda n: asked.append(n) or answers["unsaved"],
                       ask_name=lambda t, l, d="": answers["name"],
                       ask_confirm=lambda t: answers["confirm"])
    check("window lists all sheets + template row", w.listw.count() == n_real + 1, w.listw.count())
    w.filter.setText("compost")
    shown = [w.listw.item(i).data(C.Qt.UserRole) for i in range(w.listw.count())]
    check("filter by name/content", "pratique-dechets-alimentaires-compost.md" in shown and len(shown) < n_real, shown)
    w.filter.setText("zzzqqqnomatch")
    check("filter: no match -> empty list", w.listw.count() == 0)
    w.filter.setText("")

    # template: read-only
    w.open_sheet(C.TEMPLATE)
    check("template read-only, rename/delete disabled", w.editor.isReadOnly() and not w.btn_delete.isEnabled()
          and not w.btn_rename.isEnabled())

    # new sheet
    answers["name"] = "Parc de l'Été"
    w.new_sheet()
    p = os.path.join(folder, "parc-de-l-ete.md")
    txt = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    check("new: file created from template, title set, comment block stripped",
          txt.startswith("# Parc de l'Été") and "<!--" not in txt and "- Catégorie :" in txt, txt[:80])
    check("new: opened in the editor", w.current == "parc-de-l-ete.md" and w.tabs.currentWidget() is w.editor)
    before = open(p, encoding="utf-8").read()
    answers["name"] = "parc de l ete"
    w.new_sheet()
    check("new: existing name refused, file untouched", open(p, encoding="utf-8").read() == before
          and "existe déjà" in w.status.text(), w.status.text())

    # edit + atomic save
    w.editor.setPlainText(before + "\nligne ajoutée\n")
    check("edit marks dirty", w.dirty and "*" in w.windowTitle())
    w.save_current()
    check("save: written, clean, no tmp left, hint shown",
          open(p, encoding="utf-8").read().endswith("ligne ajoutée\n") and not w.dirty
          and not os.path.exists(p + ".tmp") and "recharger" in w.status.text())

    # unsaved guard: cancel keeps selection, discard drops
    w.editor.setPlainText("brouillon")
    other = next(i for i in range(w.listw.count()) if w.listw.item(i).data(C.Qt.UserRole) == "parc-hoche.md")
    answers["unsaved"] = "cancel"
    w.listw.setCurrentRow(other)
    check("unsaved + cancel: stays on the edited sheet", w.current == "parc-de-l-ete.md" and w.dirty
          and asked and w.listw.currentItem().data(C.Qt.UserRole) == "parc-de-l-ete.md", w.current)
    answers["unsaved"] = "discard"
    w.listw.setCurrentRow(other)
    check("unsaved + discard: switches, disk unchanged", w.current == "parc-hoche.md" and not w.dirty
          and open(p, encoding="utf-8").read().endswith("ligne ajoutée\n"))
    w.open_sheet("parc-de-l-ete.md")
    w.editor.setPlainText("sauvé par la garde\n")
    answers["unsaved"] = "save"
    w.listw.setCurrentRow(next(i for i in range(w.listw.count()) if w.listw.item(i).data(C.Qt.UserRole) == "parc-hoche.md"))
    check("unsaved + save: written then switched", open(p, encoding="utf-8").read() == "sauvé par la garde\n"
          and w.current == "parc-hoche.md")

    # rename
    w.open_sheet("parc-de-l-ete.md")
    answers["name"] = "Parc d'Été"
    w.rename_sheet()
    check("rename: old gone, new present, content kept", not os.path.exists(p)
          and open(os.path.join(folder, "parc-d-ete.md"), encoding="utf-8").read() == "sauvé par la garde\n")
    answers["name"] = "parc hoche"
    w.rename_sheet()
    check("rename onto an existing name refused", os.path.exists(os.path.join(folder, "parc-d-ete.md"))
          and "existe déjà" in w.status.text())

    # delete -> trash
    w.delete_sheet()
    tdir = os.path.join(folder, C.TRASH)
    trashed = os.listdir(tdir) if os.path.isdir(tdir) else []
    check("delete: moved to .corbeille with timestamp, original gone, status says so",
          not os.path.exists(os.path.join(folder, "parc-d-ete.md")) and len(trashed) == 1
          and trashed[0].startswith("parc-d-ete-") and "corbeille" in w.status.text(), trashed)
    check("trash not listed", all(s["file"] != trashed[0] for s in st.list_sheets()) and w.current is None)
    answers["confirm"] = False
    w.open_sheet("parc-hoche.md")
    w.delete_sheet()
    check("delete declined: nothing moves", os.path.exists(os.path.join(folder, "parc-hoche.md")))

    # close guard
    w.editor.setPlainText("encore sale")
    answers["unsaved"] = "cancel"
    check("close with unsaved + cancel is ignored", w.close() is False)
    w.dirty = False
    w._set_dirty(False)

    shutil.rmtree(tmp)
    print(f"ui_corpus tests: {sum(res)}/{len(res)} passed")
    return 0 if all(res) else 1


if __name__ == "__main__":
    sys.exit(main())
