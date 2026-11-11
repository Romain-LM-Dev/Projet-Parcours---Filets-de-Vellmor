"""Affiche A0 de toutes les classes du projet, colorées par zone → docs/uml/FILETS-classes-A0.pdf.

En haut, le diagramme des relations (chaque classe en une boîte à son nom, de la couleur de sa zone) ; en dessous, chaque
classe avec tous ses attributs et méthodes, rangée par zone. Le texte prend la plus grande taille qui tient sur la feuille.
Les classes, leurs membres et leurs relations sont relus dans les diagrammes de classes (docs/uml/classes-*.md) : l'affiche
est l'union de toutes leurs vues (une classe montrée en plusieurs vues y a tous ses membres). La zone d'une classe est la
section où ses membres sont décrits. Il faut Node.js (npx). Depuis la racine du dépôt :  python docs/uml/build_poster.py
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from build_pdf import UML, chrome, run

OUT = UML / "FILETS-classes-A0.pdf"
FILES = ["classes-monde", "classes-decisions", "classes-infrastructure", "classes-godot"]
# zone : (titre de la légende, fond, bordure) ; l'ordre est celui de la légende
ZONES = {
    "Monde": ("Monde : vallée, lacs, pêcheurs, règles, conseil", "#d8ecd2", "#3f7a35"),
    "Temps": ("Temps : horloge, pilotage, saisons, veillées", "#f6e3c3", "#a4691c"),
    "Decisions": ("Décisions : agents, règles d'archétype, routage, invites", "#f8d7d3", "#a8382c"),
    "Modeles": ("Modèles de langage : routeur, clients, limiteurs", "#f3d3e6", "#8f3570"),
    "Memoire": ("Mémoire, RAG et vecteurs", "#e2d9f3", "#5b3f96"),
    "Salon_API": ("Salon, bus et API HTTP / WebSocket", "#cfe3f3", "#2a5f8c"),
    "Evenements_Stockage": ("Événements, indicateurs et stockage", "#cdeeee", "#1f7676"),
    "Services_Config": ("Services, configuration, ligne de commande, banc", "#e6e6cf", "#6c6c28"),
    "Godot": ("Interface Godot (scripts GDScript et shader)", "#fbe9b7", "#9a7a12"),
    "Externes": ("Classes de bibliothèques (Godot, Python) citées sans détail", "#ececec", "#7a7a7a"),
}
# (fichier, numéro de section « ## n. ») → zone ; à défaut, la zone du fichier
SECTIONS = {("classes-monde", 13): "Temps", ("classes-monde", 14): "Temps",
            ("classes-decisions", 3): "Modeles", ("classes-decisions", 4): "Memoire", ("classes-decisions", 5): "Memoire",
            ("classes-infrastructure", 3): "Evenements_Stockage", ("classes-infrastructure", 4): "Evenements_Stockage",
            ("classes-infrastructure", 5): "Services_Config", ("classes-infrastructure", 6): "Services_Config"}
DEFAULT = {"classes-monde": "Monde", "classes-decisions": "Decisions", "classes-infrastructure": "Salon_API",
           "classes-godot": "Godot"}
REL = re.compile(r'^(\w+)\s*(?:"[^"]*"\s*)?([<*o|.\-]*(?:--|\.\.)[>*o|.\-]*)\s*(?:"[^"]*"\s*)?(\w+)')


def parse() -> tuple[dict, list]:
    """classes {nom: {zone, members}} et relations (lignes Mermaid, une par couple et sens de flèche)."""
    classes: dict[str, dict] = {}
    rels: dict[tuple, str] = {}
    for f in FILES:
        num = 0
        text = (UML / f"{f}.md").read_text(encoding="utf-8")
        for m in re.finditer(r"^## (\d+)?[^\n]*$|^```mermaid\n(.*?)^```", text, re.M | re.S):
            if m.group(2) is None:
                num = int(m.group(1) or 0)
                continue
            if not m.group(2).startswith("classDiagram"):
                continue
            cur = None
            for line in m.group(2).splitlines()[1:]:
                s = line.strip()
                head = re.match(r"class (\w+)(~[^~]*~)?\s*\{$", s)
                if head:
                    cur = classes.setdefault(head.group(1), {"zone": SECTIONS.get((f, num), DEFAULT[f]), "members": []})
                elif s == "}":
                    cur = None
                elif cur is not None:
                    if s and s not in cur["members"]:
                        cur["members"].append(s)
                elif (r := REL.match(s)) and not s.startswith("class "):
                    rels.setdefault((r.group(1), r.group(2), r.group(3)), s)
    for a, _, b in rels:
        for n in (a, b):
            classes.setdefault(n, {"zone": "Externes", "members": []})
    return classes, list(rels.values())


def library(c: dict) -> bool:
    """Classe de bibliothèque (nœud du moteur Godot, exception Python…) : citée par les diagrammes, absente de l'affiche."""
    return c["zone"] == "Externes" or "<<Godot>>" in c["members"]


def short(rel: str) -> str:
    """La relation sans son étiquette quand celle-ci dépasse 20 caractères (une liste de noms d'attributs)."""
    m = re.match(r"^(.*?\w)\s+:\s+(.*)$", rel)
    return m.group(1) if m and len(m.group(2)) > 20 else rel


def overview(classes: dict, rels: list) -> str:
    """Le diagramme des relations : toutes les classes, sans leurs membres, chacune de la couleur de sa zone."""
    out = ["classDiagram"]
    for z in ZONES:
        names = [n for n, c in classes.items() if c["zone"] == z]
        out += [f"    namespace {z} {{"] + [f"        class {n}" for n in names] + ["    }"] if names else []
    out += [f"    {r}" for r in rels]
    for n, c in classes.items():
        _, fill, stroke = ZONES[c["zone"]]
        out.append(f"    style {n} fill:{fill},stroke:{stroke},stroke-width:3px")
    return "\n".join(out) + "\n"


def edges(svg: str, classes: dict, width: float = 4, k: float = 2.5) -> str:
    """Rend les liaisons visibles : chacune épaisse et de la couleur de la zone de sa classe de départ (Mermaid les fait
    toutes fines et grises), pointillés allongés, pointes (losanges, triangles) agrandies k fois."""
    names = sorted(classes, key=len, reverse=True)

    def paint(m: re.Match) -> str:
        body = re.sub(r"_\d+_\d+$", "", m[2])      # id_<départ>_<arrivée>_<n>_<m>
        src = next(n for n in names if body.startswith(n + "_") and body[len(n) + 1:] in classes)
        dash = ";stroke-dasharray:18 10" if "edge-pattern-dashed" in m[3] else ""
        return (f'{m[1]}id="my-svg-id_{m[2]}"{m[3]}'
                f'style="stroke:{ZONES[classes[src]["zone"]][2]};stroke-width:{width}px;fill:none{dash}"')

    svg, n = re.subn(r'(<path [^>]*?)id="my-svg-id_([^"]+)"([^>]*class="[^"]*relation" )style="[^"]*"', paint, svg)
    assert n == svg.count('data-edge="true"'), "liaisons non recolorées"

    def grow(m: re.Match) -> str:
        attrs = re.sub(r'(refX|refY|markerWidth|markerHeight)="([\d.]+)"',
                       lambda a: f'{a[1]}="{float(a[2]) * k:g}"', m[1])
        return f"<marker{attrs}><g transform=\"scale({k})\">{m[2]}</g></marker>"

    return re.sub(r"<marker([^>]*)>(.*?)</marker>", grow, svg)


def card(name: str, c: dict) -> str:
    """Une classe en boîte UML : nom (et stéréotype), attributs, méthodes."""
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("~", "")
    stereo = [m for m in c["members"] if m.startswith("<<")]
    attrs = [m for m in c["members"] if m not in stereo and "(" not in m]
    meths = [m for m in c["members"] if "(" in m]
    _, fill, stroke = ZONES[c["zone"]]
    parts = "".join(f'<ul>{"".join(f"<li>{esc(m)}</li>" for m in group)}</ul>' for group in (attrs, meths) if group)
    st = "".join(f"<small>{esc(s)}</small>" for s in stereo)
    return f'<div class="card" style="border-color:{stroke};background:{fill}55"><b style="background:{fill}">{st}{name}</b>{parts}</div>'


def main() -> None:
    every, rels = parse()
    classes = {n: c for n, c in every.items() if not library(c)}
    rels = [short(r) for r in rels if all(n in classes for n in REL.match(r).group(1, 3))]
    work = Path(tempfile.mkdtemp(prefix="filets-a0-"))
    (work / "overview.mmd").write_text(overview(classes, rels), encoding="utf-8")
    (work / "cfg.json").write_text(json.dumps({"maxTextSize": 5_000_000, "maxEdges": 5000,
                                               "class": {"useMaxWidth": False},
                                               "themeVariables": {"fontSize": "36px"}, "layout": "elk",
                                               # tracés droits (l'arrondi de Mermaid tord les coudes d'ELK)
                                               "flowchart": {"curve": "linear"},
                                               "elk": {"nodePlacementStrategy": "LINEAR_SEGMENTS"}}), encoding="utf-8")
    run(f'npx -y @mermaid-js/mermaid-cli@11.4.2 -i "{work / "overview.mmd"}" -o "{work / "overview.svg"}" '
        f'-c "{work / "cfg.json"}" -b white')
    svg = (work / "overview.svg").read_text(encoding="utf-8")
    # Mermaid peint tous les cadres de zone pareil : chacun prend la couleur de sa zone, reconnue à son titre
    paint = lambda m: (f'<rect style="fill:{ZONES[m[2]][1]}66;stroke:{ZONES[m[2]][2]};stroke-width:4px"'
                       + m[1] + m[2] + "</p>")
    svg = re.sub(r'<rect style=""([^>]*/><g class="cluster-label".*?<p>)(\w+)</p>', paint, svg)
    svg = edges(svg, classes)
    assert len(re.findall(r'<rect style="fill:#\w{6}66;', svg)) == len({c["zone"] for c in classes.values()}), "cadres de zone non teints"
    (work / "overview.svg").write_text(svg, encoding="utf-8")
    vw, vh = (float(x) for x in re.search(r'viewBox="[-\d.]+ [-\d.]+ ([\d.]+) ([\d.]+)"', svg).groups())
    ov_h = min(817 * vh / vw, 740)      # mm : le diagramme d'abord (toute la largeur, au plus deux tiers de la hauteur)
    ov_w = ov_h * vw / vh               # les bandes laissées à sa gauche et à sa droite reçoivent aussi des classes
    legend = "".join(f'<span><i style="background:{fill};border-color:{stroke}"></i>{title}</span>'
                     for z, (title, fill, stroke) in ZONES.items() if z != "Externes")
    zones = "".join(
        f'<h2 style="background:{ZONES[z][1]};border-color:{ZONES[z][2]}">{ZONES[z][0]}</h2>'
        + "".join(card(n, c) for n, c in classes.items() if c["zone"] == z and c["members"])
        for z in ZONES if any(c["zone"] == z and c["members"] for c in classes.values()))
    n_members = sum(len(c["members"]) for c in classes.values())
    html = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>FILETS · Classes A0</title><style>
@page {{ size: 841mm 1189mm; margin: 12mm; }}
html, body {{ margin: 0; font-family: "Segoe UI", Arial, sans-serif; color: #1b2530; background: #fff; }}
.sheet {{ width: 817mm; height: 1165mm; display: flex; flex-direction: column; gap: 5mm; }}
.top {{ display: flex; align-items: flex-end; gap: 14mm; border-bottom: 1mm solid #2c6e8a; padding-bottom: 4mm; }}
h1 {{ font-family: Georgia, serif; font-size: 64pt; margin: 0; line-height: 1; }}
.sub {{ font-size: 20pt; color: #2c6e8a; font-style: italic; font-family: Georgia, serif; }}
.note {{ font-size: 12pt; color: #5a6672; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 3mm 9mm; font-size: 15pt; }}
.legend i {{ display: inline-block; width: 12mm; height: 7mm; border: .8mm solid; border-radius: 1.5mm; margin-right: 3mm;
  vertical-align: middle; }}
.mid {{ display: flex; gap: 4mm; height: {ov_h:.0f}mm; flex: none; }}
.overview {{ height: 100%; width: {ov_w:.0f}mm; flex: none; }}
main {{ flex: 1; min-width: 0; min-height: 0; column-width: 26em; column-gap: 1em; column-fill: auto; overflow: hidden;
  font: 6px/1.2 "Arial Narrow", Arial, sans-serif; color: #000; }}
#pool {{ display: none; }}
h2 {{ font: bold 1.5em/1.2 Georgia, serif; margin: 0 0 .6em; padding: .3em .5em; border-left: .6em solid; break-inside: avoid; }}
.card {{ border: .15em solid; border-radius: .4em; margin: 0 0 .7em; break-inside: avoid; background: #fff; }}
.card b {{ display: block; text-align: center; padding: .15em; font: bold 1.15em/1.2 "Segoe UI", Arial, sans-serif; }}
.card small {{ display: block; font-weight: normal; font-size: .8em; }}
.card ul {{ list-style: none; margin: 0; padding: .2em .4em; border-top: .1em solid #9aa4ab; }}
.card li {{ overflow-wrap: anywhere; padding-left: 1em; text-indent: -1em; }}
.card ul + ul {{ border-top-color: #555; }}
</style></head><body><div class="sheet"><div class="top"><h1>FILETS</h1><div><div class="sub">Diagramme de classes de
l'ensemble du projet</div><div class="note">{len(classes)} classes · {n_members} attributs et méthodes · {len(rels)} relations
(les classes des bibliothèques Godot et Python sont omises). En haut, qui possède, référence, hérite ou utilise qui : chaque liaison a la couleur de la zone de la classe
d'où elle part, en pointillé quand c'est une simple utilisation ; en dessous, chaque classe en entier, rangée par zone. + public,
- interne ; *-- possède, o-- référence, &lt;|-- hérite, ..&gt; utilise ; &lt;&lt;module&gt;&gt; : fichier de fonctions.</div>
</div></div><div class="legend">{legend}</div><div class="mid"><main></main><img class="overview" src="overview.svg"><main></main></div>
<main></main></div><div id="pool">{zones}</div>
<script>
// Les classes remplissent, dans l'ordre, la bande gauche, la bande droite puis le bas de la feuille ; on cherche la plus
// grande taille de texte (px) pour laquelle tout tient.
const flows = [...document.querySelectorAll("main")], items = [...document.getElementById("pool").children];
const over = f => f.scrollWidth > f.clientWidth + 1 || f.scrollHeight > f.clientHeight + 1;
function fits(size) {{
  flows.forEach(f => {{ f.style.fontSize = size + "px"; f.replaceChildren(); }});
  let i = 0;
  for (const el of items) {{
    flows[i].appendChild(el);
    while (over(flows[i])) {{
      const prev = el.previousElementSibling;     // un titre de zone suit ses classes
      if (++i >= flows.length) return false;
      if (prev && prev.tagName === "H2") flows[i].appendChild(prev);
      flows[i].appendChild(el);
    }}
  }}
  return true;
}}
let lo = 2, hi = 40;
for (let k = 0; k < 22; k++) {{ const mid = (lo + hi) / 2; if (fits(mid)) lo = mid; else hi = mid; }}
if (!fits(lo)) throw new Error("les classes ne tiennent pas sur la feuille");
document.title = "font=" + lo.toFixed(2);
</script></body></html>"""
    (work / "poster.html").write_text(html, encoding="utf-8")
    subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--allow-file-access-from-files",
                    f"--print-to-pdf={OUT}", (work / "poster.html").as_uri()], check=True, capture_output=True)
    print(f"{OUT} ({OUT.stat().st_size // 1024} Ko) ; pages de travail : {work}")


if __name__ == "__main__":
    main()
