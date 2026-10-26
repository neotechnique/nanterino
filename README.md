# Nanterino

Robot d'accueil parlant de Néotechnique, sur Jetson Orin Nano (JetPack 7.2.1) : il voit les
visiteurs, les salue, répond à l'oral sur Nanterre et les bons gestes écologiques à partir d'un
corpus de fiches, et chante sa chanson. Tout tourne en local sur le robot, sans service cloud.

## Chaîne

```
micro ─► AudioIn (VAD) ─► STT whisper.cpp CUDA ─► Corpus (fiches/) ─► LLM llama.cpp CUDA ─► TTS Piper ─► enceinte
caméra RealSense ─► YuNet TensorRT ─► suivi de visage ─► accueil automatique, regard du visage animé
```

- `nanterino/` : serveur FastAPI (port 8080) et cerveau (machine d'états), audio, vision, moteurs, corpus.
- `nanterino_ui/` : interface Qt plein écran (visage, tableau de bord).
- `web/` : visage et tableau de bord web (`face.html`, `dash.html`).
- `fiches/` : corpus local (lieux de Nanterre, fiches de bonnes pratiques écologiques).
- `song/` : fabrication de la chanson (musique `soundgen`, voix Piper chantée, choix des prises par Whisper).
- `tests/` : résultats de tests.
- `jetson-setup/` : scripts système du Jetson (`/opt/robot`) : compilation des moteurs GPU, session, bureau à distance, journalisation, outil son. Voir son README.

## Non versionné

Les modèles (`models/`, re-téléchargeables), l'environnement Python (`.venv/`), les WAV générés
(`media/*.wav`, `song/build/`) et `config.json` (réglages propres à la machine) sont exclus par `.gitignore`.
