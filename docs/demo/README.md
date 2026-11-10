# Vidéo de démonstration
1. Partie (non versionnée, mais identique à chaque fois) : `.venv/Scripts/python -m filets run --config config/demo.yaml --run-id demo --fast --no-linger` écrit `runs/demo/events.jsonl` ; le déroulé est dans `docs/demo/scenario.json`.
2. Voix : `powershell -ExecutionPolicy Bypass -File docs/demo/narrate.ps1` (un WAV par temps dans `docs/demo/voice/`, Hortense).
3. Capture en 1920x1080 : créer le temps de la capture `godot/override.cfg` ([display] window/size/viewport_width=1920, viewport_height=1080), puis le supprimer (~15 min, AVI de ~1 Go à garder hors du dépôt) : `Godot --path godot --write-movie <dossier>/demo.avi --fixed-fps 30 -- --demo=<chemin absolu de scenario.json>`.
4. Conversion : `npm i ffmpeg-static@5.2.0` dans un dossier temporaire, puis `ffmpeg -i demo.avi -c:v libx264 -crf 23 -preset medium -pix_fmt yuv420p -c:a aac -movflags +faststart docs/demo/FILETS-demo.mp4`.
5. Le lecteur est `godot/scripts/demo.gd` (activé par `--demo=` dans `main.gd`, sans moteur ni menu).
