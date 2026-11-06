"""Tests of nanterino_ui.single_instance (lot L42, 2026-11-04): one native window per tool.

logging: robotlog via nanterino_ui.single_instance (role/action only).

Purpose
    raise path (same display: owner raises, second exits), stale socket recovery, takeover from another
    display (dialog stubbed: Oui -> owner quits and second owns the lock; Non -> owner untouched), French prompt
    text, hub restart wiring (flock script).
Boundary
    QT_QPA_PLATFORM=offscreen, QCoreApplication only, no window, no real UI process. Roles are unique per run
    (test-<pid>) so the user's real sockets are never touched. The "second launch" is a child process of this
    file (`--child`) because the client side blocks while the owner needs its event loop.
How to run (repo root)
    .venv/bin/python -m tests.test_ui_single_instance      # ~10 s; prints PASS / FAIL and `ui_single_instance tests: n/n passed`
"""
import os
import socket
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/opt/robot/lib")
sys.path.insert(0, "/opt/robot/nanterino")
from PySide6.QtCore import QCoreApplication  # noqa: E402

from nanterino_ui import single_instance as SI  # noqa: E402

PY = sys.executable
ROLE = f"test{os.getpid()}"


def child_main(argv):
    """Second launch: `--child ROLE DISPLAY yes|no`; prints acquired=0/1 and exits."""
    role, display, answer = argv
    QCoreApplication(sys.argv)
    asked = []
    si = SI.SingleInstance(role, display=display, confirm=lambda other: asked.append(other) or answer == "yes")
    ok = si.acquire()
    print(f"acquired={int(ok)} asked={','.join(asked)}", flush=True)
    sys.exit(0)


def run_child(display, answer="no"):
    return subprocess.Popen([PY, "-m", "tests.test_ui_single_instance", "--child", ROLE, display, answer],
                            cwd="/opt/robot/nanterino", stdout=subprocess.PIPE, text=True,
                            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))


def pump(app, child, timeout=15):
    end = time.monotonic() + timeout
    while child.poll() is None and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    for _ in range(20):  # let queued singleShot(0) callbacks run
        app.processEvents()
    out = child.stdout.read() if child.poll() is not None else ""
    return child.returncode, out


def main():
    app = QCoreApplication(sys.argv)
    res = []

    def check(name, cond):
        res.append(cond)
        print(("PASS " if cond else "FAIL ") + name, flush=True)

    # 1. clean start owns the lock; raise from the same display reaches the owner and the second exits 0
    owner = SI.SingleInstance(ROLE, display=":T")
    raised, quit_ = [], []
    owner.on_raise = lambda: raised.append(1)
    owner.on_quit = lambda: quit_.append(1)
    check("first instance acquires", owner.acquire() is True)
    rc, out = pump(app, run_child(":T"))
    check("same display: second exits 0 without lock", rc == 0 and "acquired=0" in out and "asked=" in out.split("acquired=0")[1][:8])
    check("same display: owner raised exactly once", raised == [1] and not quit_)

    # 2. other display, answer Non: owner untouched, second exits
    rc, out = pump(app, run_child(":U", "no"))
    check("other display, Non: second exits, owner alive", rc == 0 and "acquired=0" in out and ":T" in out and not quit_ and len(raised) == 1)

    # 3. other display, answer Oui: owner quits, second owns the lock
    rc, out = pump(app, run_child(":U", "yes"))
    check("other display, Oui: second takes the lock", rc == 0 and "acquired=1" in out)
    check("other display, Oui: owner asked to quit and released socket", quit_ == [1] and owner._server is None)

    # 4. stale socket file (owner crashed): next launch recovers it
    path = os.path.join("/tmp", SI.socket_name(ROLE))
    if os.path.exists(path):
        os.unlink(path)
    s = socket.socket(socket.AF_UNIX)
    s.bind(path)
    s.close()  # file stays, nobody listens
    check("stale socket file exists", os.path.exists(path))
    third = SI.SingleInstance(ROLE, display=":T")
    check("stale socket recovered", third.acquire() is True and third._server is not None)
    third._server.close()

    # 5. pure bits
    check("French prompt text", SI.prompt_text("dash", ":0") ==
          "Le tableau technique est déjà ouvert sur un autre écran (:0). L'ouvrir ici et fermer l'autre ?")
    check("socket name per role and uid", SI.socket_name("dash") == f"nanterino-ui-dash-{os.getuid()}")
    hub_src = open("/opt/robot/nanterino/nanterino_ui/hub.py", encoding="utf-8").read()
    sh_src = open("/opt/robot/nanterino/nanterino_ui/restart.sh", encoding="utf-8").read()
    check("restart wrapped by flock -n", "flock -n 9" in sh_src and "Redémarrage déjà en cours" in sh_src
          and "restart.sh" in hub_src)
    check("entry points acquire a role", 'SingleInstance("hub")' in hub_src and
          'SingleInstance("dash" if dash else "face")' in open("/opt/robot/nanterino/nanterino_ui/app.py", encoding="utf-8").read())

    if os.path.exists(path):
        os.unlink(path)
    print(f"ui_single_instance tests: {sum(res)}/{len(res)} passed")
    sys.exit(0 if all(res) else 1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child_main(sys.argv[2:])
    main()
