#!/usr/bin/env bash
source /opt/robot/lib/robotlog.sh "nanterino-ui"
# Open a Nanterino folder (corpus sheets, logs) in ONE file-manager window only.
# Used by the hub buttons and the "Fiches du corpus" / "Logs" desktop launchers.
# If a Nautilus or PCManFM window already shows that folder (its title is the folder name), it is
# raised instead of opening a new one; otherwise xdg-open opens it.
# A per-folder flock serialises quick double clicks: the lock is held until the new window exists.
set -u
dir="${1:?usage: open_folder.sh <folder>}"
name="$(basename "$dir")"
exec 9>"/tmp/nanterino-folder-$(id -u)-${name}.lock"
flock -w 5 9

find_window() {
  # Title match only on file-manager windows, so a terminal or editor titled "fiches" is never raised.
  local w
  for w in $(xdotool search --classname '^(org\.gnome\.Nautilus|nautilus|pcmanfm)$' 2>/dev/null); do
    if [ "$(xdotool getwindowname "$w" 2>/dev/null)" = "$name" ]; then
      echo "$w"
      return 0
    fi
  done
  return 1
}

if w="$(find_window)"; then
  log_info "single-instance role=folder:${name} action=raise"
  xdotool windowmap "$w" 2>/dev/null || true
  xdotool windowactivate "$w" 2>/dev/null || xdotool windowraise "$w" 2>/dev/null || true
  exit 0
fi

log_info "single-instance role=folder:${name} action=open"
xdg-open "$dir" >/dev/null 2>&1 &
# Keep the lock until the window shows up (max ~4 s) so a second click raises it instead of opening another.
for _ in $(seq 1 20); do
  sleep 0.2
  if find_window >/dev/null; then break; fi
done
