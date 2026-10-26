#!/usr/bin/env bash
# Switch robot's auto-login desktop: icewm (light, Win95) or gnome (original); status shows current. GNOME stays installed.
# Logs: /var/log/robot/desktop-session.log (WARN/ERROR also in errors.log)
source /opt/robot/lib/robotlog.sh "desktop-session"

# Usage: desktop-session.sh icewm|gnome|status   (run with sudo; restarts the graphical login)
# Why: GNOME (~1.2 GB RAM) replaced by IceWM on 2026-10-16 WITHOUT uninstalling it, so going back
# is one command. Robot services (nanterino*, PipeWire) are systemd --user units with linger:
# they keep running across the switch; only the on-screen windows (face/hub) are closed.
AS=/var/lib/AccountsService/users/robot
cur=$(awk -F= '/^Session=/{print $2}' "$AS")
case "${1:-status}" in
  status) echo "session=${cur:-ubuntu(default)} xrdp=$(systemctl is-enabled xrdp 2>/dev/null)"; exit 0;;
  icewm)  sess=icewm-session;;
  gnome)  sess=ubuntu;;
  *) echo "usage: $0 icewm|gnome|status" >&2; exit 2;;
esac
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 2; }
cp -n "$AS" "$AS.bak-before-session-switch" 2>/dev/null
# GDM autologin uses the session stored by AccountsService.
sed -i -e "s/^Session=.*/Session=$sess/" -e "/^XSession=/d" "$AS"
sed -i "/^Session=/a XSession=$sess" "$AS"
[ "$sess" = ubuntu ] && systemctl disable --now xrdp xrdp-sesman
systemctl restart accounts-daemon
log_info "switch session $cur -> $sess; restarting gdm"
systemctl restart gdm3
sleep 8
if [ "$sess" = icewm-session ]; then
  # Remote desktop: xrdp (relay to x11vnc) replaces gnome-remote-desktop on port 3389.
  # The user manager survives the switch (linger), so free 3389 from g-r-d explicitly.
  systemctl --user -M robot@ stop gnome-remote-desktop 2>/dev/null
  systemctl disable --now xrdp-sesman 2>/dev/null   # not needed by the vnc relay
  systemctl enable xrdp && systemctl restart xrdp || log_error "xrdp failed to start"
fi
log_info "after switch: $(loginctl list-sessions --no-legend | tr '\n' ' ')"
echo "session=$sess"
