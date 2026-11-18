# Vidéo de démonstration

Les scripts, en documents : [vidéo de démonstration](script-video-longue.md) ([PDF](script-video-longue.pdf)) et [vidéos courtes](script-videos-courtes.md) ([PDF](script-videos-courtes.pdf)), tirés de `scenario.json` et `short.json` par `python docs/demo/scripts.py` (à relancer après chaque changement de texte).

Sans voix off : [FILETS-demo-sans-voix.mp4](FILETS-demo-sans-voix.mp4) (la capture de l'étape 4 avec `--no-captions`, encodée sans son, `-an`) ; les vidéos courtes aussi, `short.py … sans-voix` ([verticale](FILETS-short-sans-voix.mp4), [paysage](FILETS-short-paysage-sans-voix.mp4) : même découpage et mêmes titres, sans voix, sous-titres ni son). Le [descriptif détaillé de la solution](descriptif-solution.md) ([PDF](descriptif-solution.pdf)) présente le projet et complète toutes les vidéos (écrit à la main, mis en page par `scripts.py`).

1. Partie (`runs/demo_ia/`, non versionnée) : `.venv/Scripts/python -m filets run --config config/demo_ia.yaml --run-id demo_ia --fast --no-linger` (~20 min de calcul sur une RTX 3060 6 Go, vrais modèles : Qwen 2.5 3B et 1,5B, tev1 0,8B, et le 7B pour le narrateur) ; préchauffer tev1 avant par `/v1/systemone` (son premier chargement dépasse 60 s). `--fast` n'attend pas l'affichage : la partie est la même, la vidéo la rejoue à son rythme. Le scénario lit `runs/demo_ia/events.jsonl` ; ses textes sont calés sur CETTE partie (une autre partie demande de les réécrire).
2. Voix (voix neuronale en ligne, seul le texte part chez Microsoft) : dans un venv jetable `pip install edge-tts`, puis `python docs/demo/narrate.py <ffmpeg>` (un WAV par temps dans `docs/demo/voice/`, durées affichées ; voix et débit dans `scenario.json`, champ `voice` ; ce que la voix doit dire
   autrement que le sous-titre, champ `pron` : la liaison avant « IA » (« les zia »), « RAG » lu comme un mot).
   Pour corriger la voix de quelques temps sans tout refaire : `python docs/demo/narrate.py <ffmpeg> --only=1,18 --out=<dossier>` (les
   nouvelles voix), puis `python docs/demo/revoice.py <ffmpeg> <dossier> 1 18` (python avec numpy) : chaque ancienne voix est retrouvée dans la
   bande son de `FILETS-demo.mp4`, la nouvelle prend sa place à la même durée, l'image est copiée telle quelle (pas de capture).
3. Rythme : `godot --headless --path godot -s res://tests/demo_test.gd` imprime pour chaque temps (`DEMO temps …`) sa durée à l'écran ; elle doit rester à `hold` près celle de sa voix. Une réplique reste au moins 2,5 s à l'écran : si une veillée dure plus que sa voix, la découper en temps ou allonger le texte, sinon la vidéo a des blancs.
4. Capture en 1920x1080 : créer le temps de la capture `godot/override.cfg` ([display] window/size/viewport_width=1920, viewport_height=1080), puis le supprimer (~15 min, AVI de 1 à 2 Go à garder hors du dépôt) : `Godot --path godot --write-movie <dossier>/demo.avi --fixed-fps 30 -- --demo=<chemin absolu de scenario.json>`.
5. Conversion : `npm i ffmpeg-static@5.2.0` dans un dossier temporaire, puis `ffmpeg -i demo.avi -c:v libx264 -crf 23 -preset medium -pix_fmt yuv420p -c:a aac -movflags +faststart docs/demo/FILETS-demo.mp4`.
6. Le lecteur est `godot/scripts/demo.gd` (activé par `--demo=` dans `main.gd`, sans moteur ni menu).

## Vidéo courte (réseaux sociaux)

Moins d'une minute, aux couleurs de l'EIGSI Casablanca (relevées sur le logo et le site eigsica.ma : bleu `#0064B0`, vert `#7CC357`,
turquoise `#53AFA8`, bleu clair `#2EA6CE`, bleu nuit `#263286`), en deux formats, mêmes plans :
[FILETS-short.mp4](FILETS-short.mp4) (verticale 1080x1920) et [FILETS-short-paysage.mp4](FILETS-short-paysage.mp4) (paysage 1920x1080).

1. Capture sans sous-titre, même minutage que la démo : l'étape 4 ci-dessus avec `--no-captions` après `--demo=…` (vers `clean.avi`).
2. `python docs/demo/short.py <ffmpeg> <clean.avi> portrait` (ou `paysage`), avec un python qui a edge-tts : voix et mots minutés (edge-tts),
   titres et sous-titres mot à mot en ASS (libass, police Segoe UI Black de Windows), souffle à chaque coupe, son à -14 LUFS. Plans fixes et
   coupes franches, sans effet de zoom. En portrait, les plans sont recadrés sur la partie floutée et teintée ; en paysage, l'écran du jeu reste
   plein cadre et net (agrandi de 1,6 au plus vers la zone du plan, entourée de vert), titre et sous-titres sur des bandeaux. La carte de fin
   porte le logo de l'école,
   [eigsi-casablanca.png](eigsi-casablanca.png) (rendu du logo vectoriel du site eigsica.ma, fond transparent), sur une carte blanche.
   Texte, titres, plans (`src` en secondes de la capture, `crop` dans l'image 1920x1080), mise en page des deux formats (`formats`) et
   prononciation (`pron` : la liaison avant « IA », « RAG » lu comme un mot, « IABD » épelé ; le sous-titre garde le mot) :
   [short.json](short.json). Le script refuse une vidéo de plus de 60 s.
