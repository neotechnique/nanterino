#!/usr/bin/env bash
# Disable background services/apps useless on the robot (reversible: run with 'restore')
# Logs: /var/log/robot/slim-background.log (WARN/ERROR also in errors.log)
source /opt/robot/lib/robotlog.sh "slim-background"

# RAM audit 2026-10-15: 22 copies of nvpmodel_indicator (~440 MB), gnome-software (~120 MB),
# tracker/evolution, docker, printing/modem/etc. Everything here is reversible with "restore".
MODE=${1:-apply}
SYS_SERVICES="docker.service docker.socket containerd.service avahi-daemon.service avahi-daemon.socket ModemManager.service kerneloops.service colord.service fwupd.service lpd.service cups.service cups-browsed.service nvargus-daemon.service"
SYS_TIMERS="apt-daily.timer apt-daily-upgrade.timer update-notifier-download.timer update-notifier-motd.timer motd-news.timer fwupd-refresh.timer man-db.timer"
USER_UNITS="tracker-miner-fs-3.service"
AUTOSTART="nvpmodel_indicator gnome-software-service org.gnome.Evolution-alarm-notify update-notifier"
A=$HOME/.config/autostart
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus XDG_RUNTIME_DIR=/run/user/$(id -u)
if [ "$MODE" = restore ]; then
  sudo -n systemctl unmask $SYS_SERVICES $SYS_TIMERS 2>/dev/null
  sudo -n systemctl enable --now $SYS_TIMERS docker.service containerd.service avahi-daemon.service ModemManager.service 2>/dev/null
  systemctl --user unmask $USER_UNITS 2>/dev/null
  for n in $AUTOSTART; do [ -f $A/$n.desktop ] && grep -q "nanterino-slim" $A/$n.desktop && rm -f $A/$n.desktop; done
  log_info "restore done (log out/in or reboot to restart desktop helpers)"
  exit 0
fi
# System services/timers: one by one (a missing unit, e.g. cups, must not abort the others),
# stop + disable, then mask so other packages cannot start them again.
for u in $SYS_SERVICES $SYS_TIMERS; do
  systemctl list-unit-files "$u" --no-legend 2>/dev/null | grep -q . || continue
  sudo -n systemctl disable --now "$u" >/dev/null 2>&1 || true
  case " $SYS_SERVICES " in *" $u "*) sudo -n systemctl mask "$u" >/dev/null 2>&1 || true;; esac
done
log_info "system services and timers disabled"
# User units.
systemctl --user mask --now $USER_UNITS >/dev/null 2>&1 || true
# Desktop autostart entries: a user copy with Hidden=true overrides /etc/xdg/autostart.
mkdir -p $A
for n in $AUTOSTART; do
  printf '[Desktop Entry]\n# nanterino-slim: disabled on the robot (restore: slim-background restore)\nType=Application\nName=%s\nHidden=true\n' "$n" > $A/$n.desktop
done
# Stop what is already running (by exact program path, never a broad pattern).
for p in $(pgrep -f "^python3 /usr/share/nvpmodel_indicator/nvpmodel_indicator.py"); do kill $p; done
for p in $(pgrep -x gnome-software) $(pgrep -f "evolution-alarm-notify$") $(pgrep -x tracker-miner-f || true); do kill $p 2>/dev/null; done
log_info "desktop helpers stopped and removed from autostart"
