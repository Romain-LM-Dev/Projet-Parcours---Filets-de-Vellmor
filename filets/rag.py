"""Base de connaissances (RAG, exigence F1).

Le corpus fictif de la vallée (récits de pénuries, comptes des marchés, accords passés,
observations du lac) est découpé en passages et indexé par BM25. Le choix de BM25
plutôt que d'un index vectoriel est délibéré pour ce premier build : le corpus est petit,
écrit en français contrôlé, l'index tient en mémoire, il ne coûte aucun appel et le
score est explicable lors de l'évaluation de la récupération (F2). La classe `Retriever`
isole ce choix : un index vectoriel peut la remplacer sans toucher aux agents.

Contrôle d'accès : un passage n'est visible que par les hameaux listés dans
`visible_to` ; et jamais avant son `sim_time` (cohérence temporelle, C6).
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

STOP = set("""
a au aux avec ce ces cette d de des du elle en et eux il ils je j l la le les leur leurs lui m ma mais me meme
mes moi mon n ne nos notre nous on ou par pas pour qu que qui s sa se ses son sur t ta te tes toi ton tu un une
vos votre vous y est sont ete etre avoir a ont fait plus moins tres bien tout tous toute toutes si dont donc
comme alors aussi chaque cela ca quand sans sous entre vers chez apres avant encore deja ici
""".split())


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", normalize(text))
    out = []
    for t in toks:
        if t in STOP or len(t) < 2:
            continue
        # racinisation minimale : pluriels et quelques terminaisons
        for suf in ("ements", "ement", "ations", "ation", "euses", "euse", "eurs", "eur", "es", "s", "e"):
            if len(t) > len(suf) + 3 and t.endswith(suf):
                t = t[: -len(suf)]
                break
        out.append(t)
    return out


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.4, b: float = 0.75):
        self.docs = docs
        self.k1, self.b = k1, b
        self.N = len(docs)
        self.avgdl = sum(map(len, docs)) / self.N if self.N else 0
        df = Counter()
        for d in docs:
            df.update(set(d))
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()}
        self.tfs = [Counter(d) for d in docs]

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for d, tf in zip(self.docs, self.tfs):
            s = 0.0
            dl = len(d) or 1
            for q in query:
                if q not in tf:
                    continue
                f = tf[q]
                s += self.idf.get(q, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1)))
            out.append(s)
        return out


@dataclass
class Passage:
    id: str
    title: str
    text: str
    visible_to: list[str]
    sim_time: float
    tokens: list[str] = field(default_factory=list)


def _front_matter(raw: str) -> tuple[dict, str]:
    if not raw.startswith("---"):
        return {}, raw
    _, fm, body = raw.split("---", 2)
    meta = {}
    for line in fm.strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, body


def render(text: str, values: dict) -> str:
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: str(values.get(m.group(1), m.group(0))), text)


class Retriever:
    def __init__(self, corpus_dir: Path, values: dict):
        self.passages: list[Passage] = []
        for path in sorted(Path(corpus_dir).glob("*.md")):
            meta, body = _front_matter(path.read_text(encoding="utf-8"))
            doc_id = meta.get("id", path.stem)
            title = meta.get("title", doc_id)
            vis = [v.strip() for v in meta.get("visible_to", "all").split(",")]
            t = float(meta.get("sim_time", 0))
            paras = [p.strip() for p in re.split(r"\n\s*\n", render(body, values)) if p.strip()]
            for i, p in enumerate(paras):
                if p.startswith("#"):
                    continue
                self.passages.append(Passage(f"{doc_id}#{i}", title, p, vis, t, tokenize(title + " " + p)))
        self.bm25 = BM25([p.tokens for p in self.passages]) if self.passages else None

    def search(self, query: str, hamlet: str, horizon: float, k: int) -> list[tuple[Passage, float]]:
        if not self.bm25:
            return []
        scores = self.bm25.scores(tokenize(query))
        cands = [
            (p, s) for p, s in zip(self.passages, scores)
            if s > 0 and p.sim_time <= horizon and ("all" in p.visible_to or hamlet in p.visible_to)
        ]
        cands.sort(key=lambda x: -x[1])
        return cands[:k]
