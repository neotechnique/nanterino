"""Central logging for Nanterino.

logging: robotlog -> /var/log/robot/nanterino.log ; WARN/ERROR also in /var/log/robot/errors.log.
Privacy rule (cahier des charges §7): NEVER log transcripts, LLM answers, audio, images or
face data. Log only states, transitions, durations, device names and errors.
"""
import sys

sys.path.insert(0, "/opt/robot/lib")
from robotlog import get_logger  # noqa: E402

log = get_logger("nanterino")
