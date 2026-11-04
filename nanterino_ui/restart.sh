#!/usr/bin/env bash
# Restart the three Nanterino user services (STT, LLM, core) and show their state.
# Used by the hub button and nanterino-restart.desktop (run inside gnome-terminal).
# One restart at a time: a second launch while one runs only says so (flock -n on /tmp/nanterino-restart.lock).
exec 9>/tmp/nanterino-restart.lock
if ! flock -n 9; then
  echo "Redémarrage déjà en cours"
  read -p "Entrée pour fermer"
  exit 0
fi
systemctl --user restart nanterino-stt nanterino-llm nanterino
sleep 15
systemctl --user --no-pager status nanterino nanterino-stt nanterino-llm | grep -E '●|Active'
read -p "Entrée pour fermer"
