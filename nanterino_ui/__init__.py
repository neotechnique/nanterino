"""Native Qt (PySide6) UI for Nanterino: face + technical dashboard, no web browser.

logging: robotlog -> /var/log/robot/nanterino-ui.log (via nanterino_ui.app).
The UI is a thin client of nanterino.service (HTTP API on 127.0.0.1:8080): all dialogue logic,
audio and AI engines stay in the core service, so the UI can crash/restart without stopping the robot.
"""
