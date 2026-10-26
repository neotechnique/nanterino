#!/usr/bin/env bash
# Interactive: set the remote-desktop password of robot (GNOME RDP + IceWM VNC relay) (password typed by the user, never logged)
# Logs: /var/log/robot/set-rdp-password.log (WARN/ERROR also in errors.log)
source /opt/robot/lib/robotlog.sh "set-rdp-password"

export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus
# The keyring must be unlocked first, otherwise grdctl waits for an invisible unlock prompt.
gdbus call --session --dest org.freedesktop.secrets --object-path /org/freedesktop/secrets \
  --method org.freedesktop.Secret.Service.Unlock "['/org/freedesktop/secrets/collection/login']" >/dev/null
echo "Mot de passe pour le Bureau a distance (utilisateur robot)."
echo "La saisie est masquee : rien ne s'affiche quand tu tapes, c'est normal."
read -r -s -p "Mot de passe : " P; echo
read -r -s -p "Encore une fois : " P2; echo
if [ -z "$P" ] || [ "$P" != "$P2" ]; then echo "Les deux saisies ne correspondent pas (ou vide). Relance le script."; log_warn "rdp password not set: mismatch or empty"; exit 1; fi
if [ ${#P} -gt 8 ]; then echo "Attention : l'ecran IceWM (VNC) n'utilise que les 8 premiers caracteres."; fi
# IceWM session: xrdp -> x11vnc checks this VNC password file (localhost only).
mkdir -p "$HOME/.vnc" && chmod 700 "$HOME/.vnc"
x11vnc -storepasswd "$P" "$HOME/.vnc/passwd" >/dev/null 2>&1 && chmod 600 "$HOME/.vnc/passwd" \
  && log_info "vnc password file updated" || log_warn "x11vnc -storepasswd failed"
# GNOME session (still installed): gnome-remote-desktop credentials in the keyring.
grdctl rdp set-credentials robot "$P" 2>&1 | grep -vi tpm || true  # empty output is the normal case
unset P P2
if pgrep -u "$(id -u)" -x gnome-shell >/dev/null; then
  systemctl --user restart gnome-remote-desktop
  grdctl status 2>&1 | grep -E "Username|Password"
else
  # Restart the screen sharing of the IceWM session with the new password.
  envf=/proc/$(pgrep -u "$(id -u)" -n -x icewm)/environ
  export DISPLAY=$(tr '\0' '\n' < "$envf" 2>/dev/null | sed -n 's/^DISPLAY=//p')
  export XAUTHORITY=$(tr '\0' '\n' < "$envf" 2>/dev/null | sed -n 's/^XAUTHORITY=//p')
  [ -n "$DISPLAY" ] && /opt/robot/scripts/icewm-startup.sh
fi
log_info "rdp credentials updated"  # the password itself is never logged
echo "C'est bon. Tu peux fermer cette fenetre."
