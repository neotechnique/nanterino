# jetson-setup

Copie des scripts système du robot tels qu'installés sur le Jetson Orin Nano sous `/opt/robot`
(instantané du 2026-10-26). Ils ne font pas partie de l'application Nanterino elle-même mais
préparent la machine qui la fait tourner.

| Dossier | Emplacement sur le Jetson | Rôle |
|---|---|---|
| `lib/` | `/opt/robot/lib` | `robotlog.sh` / `robotlog.py` : journalisation commune (`/var/log/robot/<script>.log`, erreurs regroupées dans `errors.log`) |
| `scripts/` | `/opt/robot/scripts` | compilation des moteurs (llama.cpp, whisper.cpp, OpenCV CUDA, YuNet TensorRT), session de bureau IceWM, bureau à distance, calibration du haut-parleur |
| `tools/sound/` | `/opt/robot/tools/sound` | générateur de sons `soundgen` utilisé pour la musique de la chanson ; `samples/` = extraits VSCO 2 Community Edition sous licence CC0 (voir `samples/LICENSE.md`) |

Non inclus : `/opt/robot/engines` (clones des projets tiers llama.cpp, whisper.cpp, OpenCV,
librealsense, recompilés par `scripts/build-engines.sh`) et les modèles (`nanterino/models/`,
re-téléchargeables, exclus par `.gitignore`).

Installation : copier ces dossiers dans `/opt/robot/` sur le Jetson (`sudo mkdir -p /opt/robot`,
propriétaire `robot`), puis lancer les scripts de compilation voulus.
