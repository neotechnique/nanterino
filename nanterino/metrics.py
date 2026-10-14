"""Live hardware metrics from `tegrastats` (CPU, GPU, RAM, temperatures, power).

logging: robotlog via nanterino.log. Warns once per episode on high temperature.
"""
import re
import subprocess
import threading

from .log import log

TEMP_WARN_C = 85.0


class Metrics:
    def __init__(self):
        self.data: dict = {}
        self._hot = False
        threading.Thread(target=self._run, daemon=True, name="tegrastats").start()

    def _run(self):
        try:
            p = subprocess.Popen(["tegrastats", "--interval", "1000"], stdout=subprocess.PIPE, text=True)
        except FileNotFoundError:
            log.warning("tegrastats not found, metrics disabled")
            return
        for line in p.stdout:
            try:
                self.data = self.parse(line)
                self._check(self.data)
            except Exception:
                log.exception("tegrastats parse failed")

    @staticmethod
    def parse(line: str) -> dict:
        d: dict = {}
        if m := re.search(r"RAM (\d+)/(\d+)MB", line):
            d["ram_used_mb"], d["ram_total_mb"] = int(m[1]), int(m[2])
        if m := re.search(r"CPU \[([^\]]+)\]", line):
            loads = [int(x.split("%")[0]) for x in m[1].split(",") if "%" in x]
            d["cpu_pct"] = round(sum(loads) / len(loads)) if loads else None
        if m := re.search(r"GR3D_FREQ (\d+)%", line):
            d["gpu_pct"] = int(m[1])
        d["temps"] = {k: float(v) for k, v in re.findall(r"(\w+)@(-?[\d.]+)C", line)}
        if m := re.search(r"VDD_IN (\d+)mW", line):
            d["power_w"] = round(int(m[1]) / 1000, 1)
        return d

    def _check(self, d: dict):
        hot = max(d.get("temps", {}).values(), default=0) >= TEMP_WARN_C
        if hot and not self._hot:
            log.warning("temperature high max=%.1fC", max(d["temps"].values()))
        self._hot = hot
