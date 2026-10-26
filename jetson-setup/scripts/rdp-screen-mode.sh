#!/usr/bin/env bash
# At login: RDP shares the real screen if a display is plugged (mirror-primary), else a virtual screen (extend)
# Logs: /var/log/robot/rdp-screen-mode.log (WARN/ERROR also in errors.log)
source /opt/robot/lib/robotlog.sh "rdp-screen-mode"

# Why: GNOME 46 "remote login" handover times out on this Jetson when no display is connected
# (2026-10-15). The robot session is now auto-logged in and shared; with no display the RDP
# client needs a virtual monitor ("extend"), with a display it should mirror the robot screen.
# Autologin leaves the keyring locked; the login keyring has no password (plain), so unlocking
# needs no prompt. gnome-remote-desktop reads its RDP credentials from it.
gdbus call --session --dest org.freedesktop.secrets --object-path /org/freedesktop/secrets \
  --method org.freedesktop.Secret.Service.Unlock "['/org/freedesktop/secrets/collection/login']" >/dev/null \
  && log_info "keyring unlocked" || log_warn "keyring unlock failed"
connected=0
for c in /sys/class/drm/card*-DP-* /sys/class/drm/card*-HDMI-*; do
  [ -e "$c/status" ] && [ "$(cat "$c/status")" = "connected" ] && connected=1
done
mode=$([ $connected = 1 ] && echo mirror-primary || echo extend)
gsettings set org.gnome.desktop.remote-desktop.rdp screen-share-mode "$mode"
log_info "display_connected=$connected screen_share_mode=$mode"
# Restart the sharing daemon so the new mode applies to the next RDP connection.
systemctl --user restart gnome-remote-desktop.service || log_warn "gnome-remote-desktop restart failed"
