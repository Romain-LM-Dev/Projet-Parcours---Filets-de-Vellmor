"""Réunit les diagrammes UML (docs/uml/*.md) en un seul PDF : docs/uml/FILETS-diagrammes-UML.pdf.

Le sommaire vient de la section « Documentation et diagrammes UML » du README. Les diagrammes sont dessinés par mermaid-cli
(en SVG), le texte mis en page par marked, le PDF imprimé par le Chrome que mermaid-cli installe (puppeteer).
Il faut Node.js (npx). Depuis la racine du dépôt :  python docs/uml/build_pdf.py
"""
from __future__ import annotations

import datetime as dt
import glob
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

UML = Path(__file__).resolve().parent
REPO = UML.parent.parent
OUT = UML / "FILETS-diagrammes-UML.pdf"
ORDER = ["cas-utilisation", "sequences", "communication", "classes-monde", "classes-decisions", "classes-infrastructure",
         "classes-godot"]
SECTION = "## Documentation et diagrammes UML"
CSS = """@page { size: A4; margin: 18mm 16mm; }
body { font-family: "Segoe UI", Arial, sans-serif; font-size: 10.5pt; line-height: 1.45; color: #1b2530; }
h1, h2, h3 { font-family: Georgia, "Times New Roman", serif; color: #10202c; line-height: 1.2; }
h1 { font-size: 22pt; margin: 0 0 6mm; padding-bottom: 2mm; border-bottom: 2px solid #2c6e8a; break-before: page; }
h2 { font-size: 14pt; margin: 8mm 0 3mm; break-after: avoid; }
h3 { font-size: 11.5pt; margin: 5mm 0 2mm; break-after: avoid; }
code { font-family: Consolas, "Courier New", monospace; font-size: 9pt; background: #eef2f3; padding: 0 3px; border-radius: 3px; }
pre { background: #eef2f3; padding: 3mm; border-radius: 2mm; white-space: pre-wrap; font-size: 8.5pt; }
table { border-collapse: collapse; width: 100%; font-size: 9pt; margin: 3mm 0; }
th, td { border: 1px solid #cdd3cf; padding: 1.5mm 2mm; text-align: left; vertical-align: top; }
th { background: #e6eef1; } tr { break-inside: avoid; }
img { display: block; max-width: 100%; max-height: 245mm; margin: 4mm auto; break-inside: avoid; }
.cover { height: 250mm; display: flex; flex-direction: column; justify-content: center; }
.cover .kicker { text-transform: uppercase; letter-spacing: .12em; color: #5a6672; font-size: 10pt; }
.cover .title { font-size: 54pt; border: none; margin: 4mm 0 0; break-before: auto; }
.cover .sub { font-family: Georgia, serif; font-style: italic; font-size: 16pt; color: #2c6e8a; }
.cover .what { font-size: 12pt; max-width: 140mm; margin-top: 14mm; }
.cover .date { color: #5a6672; margin-top: 4mm; }"""


def run(cmd: str) -> None:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        sys.exit(f"échec : {cmd[:120]}\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")


def chrome() -> str:
    found = sorted(glob.glob(os.path.expanduser("~/.cache/puppeteer/chrome/*/chrome-*/chrome*")))
    found = [f for f in found if Path(f).name in ("chrome.exe", "chrome")]
    if not found:
        sys.exit("Chrome de puppeteer introuvable : lance d'abord une fois `npx -y @mermaid-js/mermaid-cli@11.4.2 --version`.")
    return found[-1]


def index() -> str:
    """La section UML du README, en titre de premier niveau, sans ses liens vers les fichiers (tout est dans ce PDF)."""
    text = (REPO / "README.md").read_text(encoding="utf-8")
    start = text.index(SECTION)
    end = text.find("\n## ", start + len(SECTION))
    part = text[start:end if end > 0 else None].replace(SECTION, "# Diagrammes UML de FILETS", 1)
    return re.sub(r"\[([^\]]+)\]\((?!http)[^)]*\)", r"\1", part)


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="filets-uml-"))
    parts = [index()] + [re.sub(r"\[([^\]]+)\]\((?!http)[^)]*\.md[^)]*\)", r"\1", (UML / f"{n}.md").read_text(encoding="utf-8"))
                         for n in ORDER]
    (work / "all.md").write_text("\n\n".join(parts), encoding="utf-8")
    run(f'npx -y @mermaid-js/mermaid-cli@11.4.2 -i "{work / "all.md"}" -o "{work / "rendered.md"}" -e svg -b white')
    run(f'npx -y marked@14.1.0 --gfm -i "{work / "rendered.md"}" -o "{work / "body.html"}"')
    today = dt.date.today().strftime("%d/%m/%Y")
    cover = ('<section class="cover"><p class="kicker">Projet Parcours 2 · EIGSI</p><h1 class="title">FILETS</h1>'
             '<p class="sub">La tragédie des communs au lac de Vellmor</p><p class="what">Diagrammes UML : cas d\'utilisation, '
             f'séquences, communication et classes de chaque partie du projet</p><p class="date">{today}</p></section>')
    html = (f'<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>FILETS · Diagrammes UML</title>'
            f'<style>{CSS}</style></head><body>{cover}{(work / "body.html").read_text(encoding="utf-8")}</body></html>')
    (work / "doc.html").write_text(html, encoding="utf-8")
    subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={OUT}",
                    (work / "doc.html").as_uri()], check=True, capture_output=True)
    print(f"{OUT} ({OUT.stat().st_size // 1024} Ko, {len(re.findall(rb'/Type\s*/Page[^s]', OUT.read_bytes()))} pages)")


if __name__ == "__main__":
    main()
