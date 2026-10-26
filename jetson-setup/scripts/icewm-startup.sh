#!/usr/bin/env bash
# IceWM login: AZERTY, no screen blanking, virtual screen size when headless, x11vnc on localhost for xrdp
# Logs: /var/log/robot/icewm-startup.log (WARN/ERROR also in errors.log)
source /opt/robot/lib/robotlog.sh "icewm-startup"

# Called by ~/.icewm/startup at each IceWM login of robot (light desktop since 2026-10-16).
# Why: GNOME was replaced by IceWM to save ~1 GB RAM. GNOME remote desktop is gone, so remote
# viewing = mstsc -> xrdp (port 3389, vnc-any module) -> x11vnc (localhost:5900) -> this X screen.
setxkbmap fr || log_warn "setxkbmap fr failed"
# A robot face must never blank or go to standby.
xset s off s noblank -dpms || log_warn "xset failed"

connected=0
for c in /sys/class/drm/card*-DP-* /sys/class/drm/card*-HDMI-*; do
  [ -e "$c/status" ] && [ "$(cat "$c/status")" = "connected" ] && connected=1
done
if [ $connected = 0 ]; then
  # Headless (no monitor): the NVIDIA X driver starts with AllowEmptyInitialConfiguration;
  # give the remote viewer a usable framebuffer size.
  xrandr --fb 1920x1080 2>/dev/null || log_warn "xrandr --fb 1920x1080 failed (headless size unchanged)"
fi
# Desktop icons (~/Desktop, incl. the Nanterino folder): IceWM has none, pcmanfm draws them
# (teal Win95 background set in ~/.config/pcmanfm/default/desktop-items-0.conf).
pgrep -u "$(id -u)" -f 'pcmanfm --desktop' >/dev/null || setsid pcmanfm --desktop </dev/null >/dev/null 2>&1 &
log_info "display_connected=$connected screen=$(xdpyinfo 2>/dev/null | awk '/dimensions/{print $2}')"

# x11vnc shares THIS screen, only on localhost (xrdp is the network entry point).
# Without a password file it does not start: remote viewing then stays off (safe default).
if [ -s "$HOME/.vnc/passwd" ]; then
  pkill -u "$(id -u)" -x x11vnc 2>/dev/null || true  # none running is normal
  setsid x11vnc -display "$DISPLAY" -localhost -rfbport 5900 -rfbauth "$HOME/.vnc/passwd" \
    -forever -shared -noxdamage -quiet -o /var/log/robot/x11vnc.log </dev/null >/dev/null 2>&1 &
  log_info "x11vnc started on localhost:5900"
else
  log_warn "no ~/.vnc/passwd: remote desktop off; run /opt/robot/scripts/set-rdp-password.sh in an ssh -t terminal"
fi
