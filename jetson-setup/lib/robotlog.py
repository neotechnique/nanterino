"""robotlog.py - central logging for every Python script on this Jetson.

Usage:
    import sys; sys.path.insert(0, "/opt/robot/lib")
    from robotlog import get_logger
    log = get_logger("my-component")

Writes UTC ISO-8601 lines to /var/log/robot/<component>.log; WARNING+ also go to
/var/log/robot/errors.log. Uncaught exceptions are logged with an incident id and a
bounded traceback (last 30 lines) before the process exits.
"""
import datetime
import logging
import os
import random
import sys
import traceback

LOG_DIR = "/var/log/robot"


class _UTCFormatter(logging.Formatter):
    def __init__(self, component: str, script: str, parent: str):
        super().__init__()
        self.ctx = f"[{component}] pid={os.getpid()} script={script} parent={parent}"

    def format(self, record):
        ts = datetime.datetime.fromtimestamp(record.created, datetime.timezone.utc)
        level = {"WARNING": "WARN", "CRITICAL": "ERROR"}.get(record.levelname, record.levelname)
        return f"{ts.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z {level} {self.ctx} {record.getMessage()}"


def get_logger(component: str | None = None) -> logging.Logger:
    script = os.path.realpath(sys.argv[0]) if sys.argv and sys.argv[0] else "python"
    component = component or os.path.splitext(os.path.basename(script))[0]
    logger = logging.getLogger(f"robot.{component}")
    if logger.handlers:  # already configured in this process
        return logger
    logger.setLevel(logging.INFO)
    fmt = _UTCFormatter(component, script, os.environ.get("ROBOT_PARENT", "none"))
    handlers = [
        (logging.FileHandler(os.path.join(LOG_DIR, f"{component}.log")), logging.INFO),
        (logging.FileHandler(os.path.join(LOG_DIR, "errors.log")), logging.WARNING),
        (logging.StreamHandler(sys.stdout), logging.INFO),
    ]
    for handler, level in handlers:
        handler.setLevel(level)
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    os.environ["ROBOT_PARENT"] = script  # children see who launched them

    def _excepthook(exc_type, exc, tb):
        incident = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{random.randint(0, 99999)}"
        lines = "".join(traceback.format_exception(exc_type, exc, tb)).splitlines()[-30:]
        logger.error("incident=%s uncaught %s: %s | traceback: %s", incident, exc_type.__name__, exc, " | ".join(lines))

    sys.excepthook = _excepthook
    logger.info("start")
    return logger
