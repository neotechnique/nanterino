"""Single instance per native tool (roles: hub, dash, face), per user, over QLocalServer / QLocalSocket.

logging: robotlog -> /var/log/robot/nanterino-ui.log (`single-instance role=.. action=..`, never content).

Purpose
    A second launch of a native tool must not open a second window. The first instance owns a local socket
    named `nanterino-ui-<role>-<uid>`; the second connects, sends {"cmd":"raise","display":D} and reads the
    first instance's display back.
      - same display: the first instance raises its window (handler `on_raise`), the second exits 0;
      - other display (robot screen vs RDP session): the second asks in French whether to take over; Oui sends
        {"cmd":"quit"}, waits (<= 3 s) for the socket to vanish and then owns the lock; Non exits.
    Stale socket files (crashed owner: connect refused) are removed with removeServer before listening.
Boundary
    Client side blocks (waitFor*) so it works before any event loop runs; the server side needs the Qt event
    loop of the owning process. Only QtCore/QtNetwork at import time; QMessageBox is imported lazily.
Invariants
    - acquire() is called after QApplication exists and before the main window is shown.
    - the lock is held for the life of the process (the QLocalServer is kept on the object).
How to test
    .venv/bin/python -m tests.test_ui_single_instance   (offscreen, no real window)
"""
import json
import os
import sys
import time

sys.path.insert(0, "/opt/robot/lib")
from robotlog import get_logger  # noqa: E402

from PySide6.QtCore import QCoreApplication, QTimer  # noqa: E402
from PySide6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402

log = get_logger("nanterino-ui")

ROLE_LABELS = {"dash": "tableau technique", "face": "visage", "hub": "panneau Nanterino"}
_CONNECT_MS = 500   # a live owner answers at once; slower means stale or stuck
_REPLY_MS = 1500
_VANISH_S = 3.0     # max wait for the previous owner to release the socket


def current_display() -> str:
    return os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or ""


def socket_name(role: str) -> str:
    return f"nanterino-ui-{role}-{os.getuid()}"


def prompt_text(role: str, other_display: str) -> str:
    return (f"Le {ROLE_LABELS.get(role, role)} est déjà ouvert sur un autre écran ({other_display}). "
            "L'ouvrir ici et fermer l'autre ?")


def _ask_default(role: str, other_display: str) -> bool:
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(QMessageBox.Question, "Nanterino", prompt_text(role, other_display),
                      QMessageBox.Yes | QMessageBox.No)
    box.button(QMessageBox.Yes).setText("Oui")
    box.button(QMessageBox.No).setText("Non")
    box.setDefaultButton(QMessageBox.No)
    return box.exec() == QMessageBox.Yes


def raise_window(win) -> None:
    """Bring a window to the front: restore from minimised / hidden, then raise and activate."""
    if win.isMinimized():
        win.showNormal()
    win.show()
    win.raise_()
    win.activateWindow()


class SingleInstance:
    def __init__(self, role: str, display: str | None = None, confirm=None):
        self.role = role
        self.display = current_display() if display is None else display
        self.name = socket_name(role)
        self._confirm = confirm or (lambda other: _ask_default(role, other))
        self._server: QLocalServer | None = None
        self.on_raise = lambda: None   # set by the owner once its window exists
        self.on_quit = lambda: QCoreApplication.quit()

    # ---- client side -------------------------------------------------------------------------------------
    def _talk(self, msg: dict) -> dict | None:
        """Send one JSON line to the current owner; its reply, or None when nobody answers (stale / absent)."""
        s = QLocalSocket()
        s.connectToServer(self.name)
        if not s.waitForConnected(_CONNECT_MS):
            return None
        s.write((json.dumps(msg) + "\n").encode())
        s.flush()
        reply: dict = {}
        if s.waitForReadyRead(_REPLY_MS):
            try:
                reply = json.loads(bytes(s.readLine()).decode() or "{}")
            except ValueError:
                reply = {}
        s.disconnectFromServer()
        return reply

    def _listen(self) -> bool:
        srv = QLocalServer()
        srv.setSocketOptions(QLocalServer.UserAccessOption)
        if not srv.listen(self.name):
            QLocalServer.removeServer(self.name)  # stale file of a crashed owner
            if not srv.listen(self.name):
                log.info("single-instance role=%s action=listen-failed", self.role)
                return True  # never block the tool because the lock itself is broken
        srv.newConnection.connect(self._on_connection)
        self._server = srv
        return True

    def acquire(self) -> bool:
        """True: this process owns the lock and should start. False: it must exit 0."""
        reply = self._talk({"cmd": "raise", "display": self.display})
        if reply is None:
            if self._listen():
                log.info("single-instance role=%s action=owner", self.role)
            return True
        other = reply.get("display", "")
        if other == self.display:
            log.info("single-instance role=%s action=raised-existing", self.role)
            return False
        if not self._confirm(other):
            log.info("single-instance role=%s action=declined-takeover", self.role)
            return False
        self._talk({"cmd": "quit"})
        deadline = time.monotonic() + _VANISH_S
        while time.monotonic() < deadline:
            probe = QLocalSocket()
            probe.connectToServer(self.name)
            gone = not probe.waitForConnected(200)
            probe.abort()
            if gone:
                self._listen()
                log.info("single-instance role=%s action=takeover", self.role)
                return True
            time.sleep(0.1)
        log.info("single-instance role=%s action=takeover-timeout", self.role)
        return False

    # ---- server side -------------------------------------------------------------------------------------
    def _on_connection(self):
        while self._server is not None and self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            conn.readyRead.connect(lambda c=conn: self._on_data(c))
            if conn.bytesAvailable():
                self._on_data(conn)

    def _on_data(self, conn: QLocalSocket):
        line = bytes(conn.readLine()).decode().strip()
        if not line:
            return
        try:
            msg = json.loads(line)
        except ValueError:
            return
        cmd = msg.get("cmd")
        conn.write((json.dumps({"display": self.display}) + "\n").encode())
        conn.flush()
        if cmd == "raise" and msg.get("display") == self.display:
            self.on_raise()
        conn.disconnectFromServer()  # flushes the reply; must precede server.close(), which deletes children
        if cmd == "quit":
            # Release the socket at once so the taker sees it vanish, then leave the event loop.
            if self._server is not None:
                self._server.close()
                self._server = None
            log.info("single-instance role=%s action=quit-on-request", self.role)
            QTimer.singleShot(0, self.on_quit)
