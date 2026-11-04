"""Base de connaissances (RAG, exigence F1).

Le corpus fictif de la vallée (récits de pénuries, comptes des marchés, accords passés,
observations du lac) est découpé en passages et indexé par BM25. Le choix de BM25
plutôt que d'un index vectoriel est délibéré pour ce premier build : le corpus est petit,
écrit en français contrôlé, l'index tient en mémoire, il ne coûte aucun appel et le
score est explicable lors de l'évaluation de la récupération (F2). La classe `Retriever`
isole ce choix : avec `rag.backend: pgvector`, `VectorRetriever` la remplace sans toucher aux agents (mêmes passages,
mêmes droits, recherche par similarité de sens dans PostgreSQL + pgvector, voir `vectors.py`).

Contrôle d'accès : un passage n'est visible que par les hameaux listés dans
`visible_to` ; et jamais avant son `sim_time` (cohérence temporelle, C6).
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
import unicodedata
import zlib
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
    # passage de partie (« lore ») : l'agent qu'il caractérise et son poids ; vide pour le corpus fixe
    agent: str = ""
    importance: float = 0.0
    source: str = "corpus"


def lore_passage(event_id: str, agent: str, text: str, visible_to: list[str], t: float, importance: float) -> Passage:
    return Passage(f"lore:{event_id}", "Ce que la vallée sait", text, visible_to, t, tokenize("Ce que la vallée sait " + text),
                   agent, importance, "lore")


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


# Le registre d'un village de la vallée générée qui n'a pas de registre écrit à la main (`corpus/comptes-marche-<village>.md`) : le même
# texte, avec l'une de ces trois phrases selon son nom.
REGISTER_VARIANTS = [
    "Le marché de {v} est petit : on y vend surtout le matin, entre voisins, et le registre n'est pas toujours tenu avec soin.",
    "À {v}, chaque vente est consignée devant témoin ; le registre est tenu avec soin, mais les ventes faites hors du hameau n'y figurent pas.",
    "Les pêcheurs de {v} vendent une part de leur prise au marché de {market} ; le registre de {v} ne compte que ce qui se vend sur place.",
]


def register_body(village: str, market: str) -> str:
    variant = REGISTER_VARIANTS[zlib.crc32(village.encode()) % len(REGISTER_VARIANTS)].format(v=village, market=market or village)
    return "\n\n".join([
        f"# Registre du marché de {village}",
        f"Le registre du marché de {village} consigne, saison après saison, ce que chaque pêcheur du hameau a vendu. Ces dernières "
        "années, le poisson s'y vend autour de {{price}} écus la tonne. Une famille a besoin de quelque {{upkeep}} écus par saison "
        "pour vivre.",
        variant,
        "Le registre ne mentionne que les ventes du hameau : ce que les pêcheurs des autres hameaux ramènent reste inconnu, sauf quand "
        f"on décide de tout afficher sur la place de {market or village}."])


class Retriever:
    def __init__(self, corpus_dir: Path, values: dict, villages: tuple = (), market: str = ""):
        self.passages: list[Passage] = []
        self.files: dict[str, Path] = {}          # document → fichier source
        docs = []
        for path in sorted(Path(corpus_dir).glob("*.md")):
            meta, body = _front_matter(path.read_text(encoding="utf-8"))
            self.files[meta.get("id", path.stem)] = path
            docs.append((meta, body, path.stem))
        for v in villages:                         # les villages de la vallée sans registre écrit en reçoivent un
            doc_id = f"comptes-marche-{normalize(v)}"
            if doc_id not in self.files:
                docs.append(({"id": doc_id, "title": f"Registre du marché de {v}", "visible_to": v, "sim_time": "-180"},
                             register_body(v, market), doc_id))
        for meta, body, stem in docs:
            doc_id = meta.get("id", stem)
            title = meta.get("title", doc_id)
            vis = [v.strip() for v in meta.get("visible_to", "all").split(",")]
            t = float(meta.get("sim_time", 0))
            paras = [p.strip() for p in re.split(r"\n\s*\n", render(body, values)) if p.strip()]
            for i, p in enumerate(paras):
                if p.startswith("#"):
                    continue
                self.passages.append(Passage(f"{doc_id}#{i}", title, p, vis, t, tokenize(title + " " + p)))
        self.lore: list[Passage] = []              # passages de la partie en cours : en mémoire seulement, jamais écrits sur disque
        self._index()

    def _index(self) -> None:
        self._all = self.passages + self.lore      # un seul index : corpus fixe et lore concourent sur le même score BM25
        self.bm25 = BM25([p.tokens for p in self._all]) if self._all else None

    def add_lore(self, p: Passage, cap: int) -> list[Passage]:
        """Ajoute un passage de partie ; au-delà de `cap` par agent, le moins important (puis le plus ancien) est retiré.
        Rend les passages retirés (éventuellement `p` lui-même)."""
        if any(x.id == p.id for x in self.lore):
            return []
        self.lore.append(p)
        mine = [x for x in self.lore if x.agent == p.agent]
        gone = sorted(mine, key=lambda x: (x.importance, x.sim_time))[:max(0, len(mine) - cap)]
        self.lore = [x for x in self.lore if x not in gone]
        self._index()                              # shortcut: réindexation complète, le lore reste de quelques dizaines de passages
        return gone

    def search(self, query: str, hamlet: str, horizon: float, k: int) -> list[tuple[Passage, float]]:
        if not self.bm25:
            return []
        scores = self.bm25.scores(tokenize(query))
        cands = [
            (p, s) for p, s in zip(self._all, scores)
            if s > 0 and p.sim_time <= horizon and ("all" in p.visible_to or hamlet in p.visible_to)
        ]
        cands.sort(key=lambda x: -x[1])
        return cands[:k]

    # interface asynchrone commune avec `VectorRetriever`
    async def open(self) -> None:
        pass

    async def asearch(self, query: str, hamlet: str, horizon: float, k: int) -> list[tuple[Passage, float]]:
        return self.search(query, hamlet, horizon, k)

    async def aclose(self) -> None:
        pass


log = logging.getLogger("filets.rag")


class VectorRetriever:
    """Le corpus dans PostgreSQL + pgvector : les mêmes passages que `Retriever` (même découpage, mêmes valeurs rendues),
    vectorisés une fois et gardés dans la base (une partie suivante avec le même corpus ne recalcule rien). Les fichiers
    sources vont au stockage objet, et chaque passage garde la clé de son document. Si la base ne répond plus en cours de
    partie, la recherche se rabat sur BM25, en mémoire : une décision n'est jamais privée de contexte pour autant."""

    def __init__(self, corpus_dir: Path, values: dict, store, embedder, objects=None, min_score: float = 0.0,
                 villages: tuple = (), market: str = ""):
        self.local = Retriever(corpus_dir, values, villages, market)
        self.passages = self.local.passages
        self.by_id = {p.id: p for p in self.passages}
        self.store, self.embedder, self.objects, self.min_score = store, embedder, objects, min_score
        digest = hashlib.sha1()
        for p in self.passages:
            digest.update("\x1f".join([p.id, p.title, p.text, ",".join(p.visible_to), repr(p.sim_time)]).encode() + b"\x1e")
        self.corpus = digest.hexdigest()[:16]     # empreinte du corpus rendu : capacité, prix… sont dans le texte
        self.degraded = False
        self.run_id = ""                          # la partie dont le lore est rangé dans la base (posé par `World`)
        self._new: list[Passage] = []             # lore pas encore vectorisé ni écrit (l'ajout est synchrone, l'écriture non)
        self._gone: set[str] = set()              # lore retiré (plafond) à effacer de la base

    def add_lore(self, p: Passage, cap: int) -> list[Passage]:
        gone = self.local.add_lore(p, cap)
        self._new.append(p)
        self._gone.update(g.id for g in gone)
        return gone

    async def _flush_lore(self) -> None:
        new, gone = [p for p in self._new if p.id not in self._gone], list(self._gone)
        self._new, self._gone = [], set()
        try:
            if gone:
                await self.store.delete_lore(self.run_id, gone)
            if new:
                vecs = await self.embedder.embed([f"{p.title} {p.text}" for p in new])
                await self.store.put_lore(self.run_id, [(p.id, p.agent, p.text, p.visible_to, p.sim_time, p.importance, v)
                                                        for p, v in zip(new, vecs)])
        except Exception:
            self._new, self._gone = new + self._new, set(gone) | self._gone     # à reprendre à la prochaine recherche
            raise

    async def open(self) -> None:
        if await self.store.count_chunks(self.corpus) >= len(self.passages):
            return                                # déjà vectorisé par une partie précédente
        keys: dict[str, str] = {}
        if self.objects is not None:
            for doc_id, path in self.local.files.items():
                keys[doc_id] = await self.objects.put_bytes(f"corpus/{self.corpus}/{path.name}", path.read_bytes())
        vecs = await self.embedder.embed([f"{p.title} {p.text}" for p in self.passages])
        await self.store.put_chunks(self.corpus, [
            (p.id, p.title, p.text, p.visible_to, p.sim_time, keys.get(p.id.split("#", 1)[0]), v)
            for p, v in zip(self.passages, vecs)])

    async def asearch(self, query: str, hamlet: str, horizon: float, k: int) -> list[tuple[Passage, float]]:
        if not self.degraded:
            try:
                await self._flush_lore()
                [q] = await self.embedder.embed([query])
                rows = await self.store.search_chunks(self.corpus, q, hamlet, horizon, k, self.min_score)
                out = [(self.by_id[r["id"]], float(r["score"])) for r in rows if r["id"] in self.by_id]
                if self.local.lore:               # le lore de CETTE partie concourt sur le même score cosinus
                    lore = {p.id: p for p in self.local.lore}
                    rows = await self.store.search_lore(self.run_id, q, hamlet, horizon, k, self.min_score)
                    out += [(lore[r["id"]], float(r["score"])) for r in rows if r["id"] in lore]
                return sorted(out, key=lambda x: -x[1])[:k]
            except Exception as exc:              # base ou modèle de plongement perdus : BM25 prend le relais
                self.degraded = True
                log.warning("recherche vectorielle indisponible (%s) : BM25 en mémoire prend le relais", exc)
        return self.local.search(query, hamlet, horizon, k)

    def search(self, query: str, hamlet: str, horizon: float, k: int) -> list[tuple[Passage, float]]:
        return self.local.search(query, hamlet, horizon, k)

    async def aclose(self) -> None:
        """Fin de partie : le lore de ce run_id est effacé de la base (le corpus fixe n'est pas touché)."""
        if self.run_id and self.store.pool is not None:
            try:
                await self.store.drop_lore(self.run_id)
            except Exception as exc:
                log.warning("lore de la partie non effacé (jamais relu par une autre partie) : %s", exc)
