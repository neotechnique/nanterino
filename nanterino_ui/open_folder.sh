#!/usr/bin/env bash
source /opt/robot/lib/robotlog.sh "nanterino-ui"
# Compatibility shim: open a folder in the Nanterino native explorer (nanterino_ui/explorer.py).
# The corpus folder opens the single-instance corpus window instead (it raises an existing one itself).
# Nautilus / PCManFM are no longer used (CSD windows get stuck under IceWM).
set -u
dir="${1:?usage: open_folder.sh <folder>}"
PY=/opt/robot/nanterino/.venv/bin/python
cd /opt/robot/nanterino || exit 2
if [ "$(realpath "$dir")" = "/opt/robot/nanterino/fiches" ]; then
  log_info "open_folder role=corpus"
  nohup "$PY" -m nanterino_ui.corpus >/dev/null 2>&1 &
else
  log_info "open_folder role=explorer folder=$(basename "$dir")"
  nohup "$PY" -m nanterino_ui.explorer "$dir" >/dev/null 2>&1 &
fi
