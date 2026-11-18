"""Les scripts des vidéos, en documents : docs/demo/script-video-longue.{md,pdf} et script-videos-courtes.{md,pdf}, tirés de
scenario.json et short.json (la source), avec le minutage des voix (docs/demo/voice/, s'il est là) et les prénoms de la partie ;
et descriptif-solution.pdf, mis en page depuis descriptif-solution.md (écrit à la main).
    python docs/demo/scripts.py          (le PDF passe par le Chrome de puppeteer, comme docs/uml/build_pdf.py)"""
import html
import json
import re
import subprocess
import sys
import wave
from pathlib import Path

here = Path(__file__).parent
sys.path.insert(0, str(here.parent / "uml"))
from build_pdf import chrome  # noqa: E402

sc = json.loads((here / "scenario.json").read_text(encoding="utf8"))
sh = json.loads((here / "short.json").read_text(encoding="utf8"))
TITLE_S, GAP = 3.0, 0.15          # carte de titre de la démo (demo.gd) ; souffle entre deux phrases (short.py)


def wav_s(path: Path) -> float | None:
    if not path.exists():
        return None
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def mmss(t: float | None) -> str:
    return "" if t is None else f"{int(t // 60)}:{int(t % 60):02d}"


def names() -> dict:
    """Les prénoms des agents de la partie filmée (pour l'inspecteur)."""
    run = here.parent.parent / sc["run"]
    if not run.exists():
        return {}
    with run.open(encoding="utf8") as f:
        start = json.loads(f.readline())
    return {a["id"]: a["name"] for a in start["payload"].get("agents", [])}


def heard(rules: list, texts: list[str]) -> list[str]:
    """Pour chaque règle de prononciation, un exemple tiré du script : « écrit » → « dit »."""
    out = []
    for rule in rules:
        pattern, say = rule[0], rule[1]
        m = next((m for t in texts for m in [re.search(pattern, t)] if m), None)
        if m:
            out.append(f"« {m.group(0)} » est dit « {re.sub(pattern, say, m.group(0))} »")
    return out


def long_script() -> tuple:
    who = names()
    rows, t, total = [], TITLE_S, None
    for i, b in enumerate(sc["beats"]):
        d = wav_s(here / "voice" / f"{i:02d}.wav")
        season, day = int(b["t"] // 30) + 1, b["t"] % 30
        screen = []
        cam = b.get("camera", "")
        if cam:
            screen.append({"overview": "toute la vallée", "fit": "la carte"}.get(cam, cam.replace("village:", "zoom sur ")))
        if "mesh" in b:
            screen.append("mailles visibles" if b["mesh"] else "sans les mailles")
        if b.get("inspect"):
            screen.append(f"inspecteur : {who.get(b['inspect'], b['inspect']).split(' ')[0]}")
        elif b.get("tab"):
            screen.append(f"onglet « {b['tab']} »")
        hour = round(day % 1 * 24)
        when = f"S{season}, jour {int(day) + 1}" + (f", {hour} h" if hour else "")          # (le jour tel que l'affiche le jeu)
        rows.append([str(i + 1), mmss(t), when, " ; ".join(screen) or "—", b["say"]])
        t = None if (t is None or d is None) else t + d + float(b.get("hold", 0))
    total = t
    head = ["N°", "Vidéo ≈", "Partie", "À l'écran", "Voix"]
    intro = [
        "Vidéo de démonstration du projet FILETS : une partie jouée par les vrais modèles, racontée par une voix off. Public : élèves "
        "d'une école d'ingénieurs généraliste qui choisissent leur dominante.",
        f"Fichier : FILETS-demo.mp4, 1920x1080" + (f", {mmss(total + 3)} environ" if total else "") + ". Voix : "
        f"{sc['voice']['name']} (edge-tts), débit {sc['voice']['rate']}.",
        "Partie filmée : runs/demo_ia (trois saisons ; Qwen 2.5 3B et 1,5B, tev1 0,8B, Qwen 2.5 7B pour le narrateur).",
        f"Carte de titre : {sc['title']}. {sc['subtitle']}. Carte de fin : {' — '.join(sc['end'])}.",
    ]
    pron = heard(sc.get("pron", []), [b["say"] for b in sc["beats"]])
    if pron:
        intro.append("Prononciation (la voix seulement, le sous-titre garde le texte) : " + " ; ".join(pron) + ".")
    intro.append("« Vidéo ≈ » : début du passage dans la vidéo, à une seconde près. « Partie » : saison et jour de jeu où il commence.")
    return "Script de la vidéo de démonstration", intro, head, rows


def short_script() -> tuple:
    crops = {"map": "la carte", "ring": "la veillée", "kpi": "les indicateurs", "chart": "les courbes", "panel": "le panneau de droite",
             "feed": "le fil des interactions"}
    rows, t = [], 0.0
    for i, ln in enumerate(sh["lines"]):
        d = wav_s(here / "voice" / "short" / f"{i:02d}.wav")
        title = re.sub(r"\*(.+?)\*", r"\1", ln.get("title", "")) or "(carte de fin)"
        shots = "; ".join(f"{mmss(s['src'])} de la capture, {crops.get(s['crop'], 'un détail') if isinstance(s['crop'], str) else 'un détail'}"
                          + (f", accéléré x{s['speed']:g}" if s.get("speed") else "") for s in ln.get("shots", []))
        if ln.get("end"):
            shots = "carte de fin : " + " — ".join(sh["end"]["lines"]) + ", logo de l'EIGSI Casablanca"
        rows.append([str(i + 1), mmss(t), title, ln["say"], shots])
        t = None if (t is None or d is None) else t + d + (sh["end"]["hold"] if ln.get("end") else GAP)
    head = ["N°", "Vidéo ≈", "Titre à l'écran", "Voix", "Images"]
    intro = [
        "Vidéos courtes pour les réseaux sociaux, aux couleurs de l'EIGSI Casablanca : un seul script, deux formats, "
        "FILETS-short.mp4 (vertical, 1080x1920) et FILETS-short-paysage.mp4 (paysage, 1920x1080)" + (f", {mmss(t)} environ" if t else "") + ".",
        f"Voix : {sh['voice']['name']} (edge-tts), débit {sh['voice']['rate']}. Sous-titres mot à mot, le mot dit en vert ; titre en haut, son mot "
        "clé en vert ; plans fixes, coupes franches.",
        "Images : extraits de la capture sans sous-titre de la vidéo de démonstration (même partie, même minutage).",
    ]
    pron = heard(sh.get("pron", []), [ln["say"] for ln in sh["lines"]])
    if pron:
        intro.append("Prononciation (la voix seulement, le sous-titre garde le texte) : " + " ; ".join(pron) + ".")
    return "Script des vidéos courtes", intro, head, rows


def md(title, intro, head, rows) -> str:
    cell = lambda s: s.replace("|", "\\|")                                          # noqa: E731
    lines = [f"# {title}", "", *[f"{p}\n" for p in intro],
             "| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|",
             *["| " + " | ".join(cell(c) for c in r) + " |" for r in rows], "",
             "*Généré par `docs/demo/scripts.py` depuis `scenario.json` et `short.json` : modifier le script là, puis relancer.*", ""]
    return "\n".join(lines)


CSS = """@page { size: A4; margin: 16mm 14mm; }
body { font-family: "Segoe UI", Arial, sans-serif; font-size: 10.5pt; color: #1a1f36; }
h1 { color: #263286; font-size: 20pt; margin: 0 0 4mm; border-bottom: 3px solid #7CC357; padding-bottom: 2mm; }
p { margin: 0 0 2.2mm; line-height: 1.4; }
table { border-collapse: collapse; width: 100%; margin-top: 4mm; }
th { background: #0064B0; color: #fff; text-align: left; padding: 2mm; font-size: 9.5pt; }
td { padding: 2mm; vertical-align: top; border-bottom: 1px solid #d6dbe8; line-height: 1.35; }
tr:nth-child(even) td { background: #f2f6fb; }
td:first-child { color: #0064B0; font-weight: 700; } td:nth-child(2) { white-space: nowrap; color: #53607a; }
tr { page-break-inside: avoid; } .foot { margin-top: 4mm; color: #6a7590; font-size: 8.5pt; }"""


def pdf(name: str, title, intro, head, rows, widths) -> Path:
    e = html.escape
    body = (f"<h1>{e(title)}</h1>" + "".join(f"<p>{e(p)}</p>" for p in intro) +
            "<table><colgroup>" + "".join(f'<col style="width:{w}%">' for w in widths) + "</colgroup><tr>" +
            "".join(f"<th>{e(h)}</th>" for h in head) + "</tr>" +
            "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in rows) + "</table>" +
            '<p class="foot">Généré par docs/demo/scripts.py depuis scenario.json et short.json.</p>')
    page = here / f"{name}.html"
    page.write_text(f'<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>{e(title)}</title><style>{CSS}</style></head>'
                    f"<body>{body}</body></html>", encoding="utf8")
    out = here / f"{name}.pdf"
    subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={out}", page.as_uri()],
                   check=True, capture_output=True)
    page.unlink()
    return out


for name, doc, widths in (("script-video-longue", long_script(), (4, 7, 12, 17, 60)),
                          ("script-videos-courtes", short_script(), (4, 7, 18, 45, 26))):
    assert doc[3] and all(len(r) == len(doc[2]) for r in doc[3]), name
    (here / f"{name}.md").write_text(md(*doc), encoding="utf8")
    print("écrit :", here / f"{name}.md", "et", pdf(name, *doc, widths))

# le descriptif de la solution (écrit à la main, en Markdown) : le même gabarit, mis en page par marked comme la doc UML
desc = here / "descriptif-solution.md"
body = here / "descriptif-solution.body.html"
subprocess.run(f'npx -y marked@14.1.0 --gfm -i "{desc}" -o "{body}"', shell=True, check=True, capture_output=True)
page = here / "descriptif-solution.html"
page.write_text('<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>FILETS : descriptif de la solution</title>'
                f'<style>{CSS} h2 {{ color: #0064B0; margin: 6mm 0 2mm; }} h3 {{ color: #263286; margin: 4mm 0 1.5mm; }} '
                f'li {{ margin-bottom: 1.2mm; line-height: 1.4; }} code {{ font-size: 9pt; }} td:nth-child(2) {{ white-space: normal; color: inherit; }}</style></head>'
                f'<body>{body.read_text(encoding="utf8")}</body></html>', encoding="utf8")
subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={here / 'descriptif-solution.pdf'}",
                page.as_uri()], check=True, capture_output=True)
body.unlink()
page.unlink()
print("écrit :", here / "descriptif-solution.pdf")
