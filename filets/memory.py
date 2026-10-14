"""Mémoire propre de chaque agent (exigence A1).

Un flux de souvenirs horodatés en temps simulé. La récupération combine récence,
importance et pertinence (à la manière de Park et al., 2023). Les engagements
(promesses faites, règle en vigueur, accusations reçues) sont « épinglés » : ils
remontent à chaque décision tant qu'ils sont d'actualité, si bien qu'un pêcheur
se souvient la saison suivante de sa promesse, même s'il la trahit.

Un souvenir n'est jamais retrouvé avant son instant simulé (`t <= horizon`) : un agent
ne peut pas agir sur une information qu'il n'avait pas encore (C6).

Avec `rag.backend: pgvector`, `VectorMemory` range aussi chaque souvenir dans PostgreSQL avec son vecteur, et la
pertinence devient une similarité de sens calculée par la base (voir `vectors.py`). Les souvenirs de tous les agents d'une
partie y forment une mémoire collective interrogeable (API `/api/runs/{run_id}/memories`).
"""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass

from .rag import BM25, tokenize

log = logging.getLogger("filets.memory")


@dataclass
class Memory:
    id: str
    t: float
    text: str
    kind: str
    importance: float
    pinned: bool = False
    expires_season: int | None = None
    source_event_id: str | None = None
    event_id: str | None = None      # identifiant de l'événement memory_write correspondant


class MemoryStore:
    def __init__(self, owner: str, decay: float, weights: dict):
        self.owner = owner
        self.items: list[Memory] = []
        self.decay = decay
        self.w = weights
        self._n = 0

    def add(self, t: float, text: str, kind: str, importance: float, pinned=False, expires_season=None,
            source_event_id=None) -> Memory:
        self._n += 1
        m = Memory(f"{self.owner}-m{self._n:04d}", t, text, kind, importance, pinned, expires_season, source_event_id)
        self.items.append(m)
        return m

    def pinned(self, horizon: float, season: int) -> list[Memory]:
        return [m for m in self.items if m.pinned and m.t <= horizon
                and (m.expires_season is None or m.expires_season >= season)]

    def retrieve(self, query: str, horizon: float, k: int, exclude: set[str] | None = None) -> list[tuple[Memory, float]]:
        exclude = exclude or set()
        cands = [m for m in self.items if m.t <= horizon and m.id not in exclude]
        if not cands:
            return []
        rel = BM25([tokenize(m.text) for m in cands]).scores(tokenize(query))
        top = max(rel) or 1.0
        scored = []
        for m, r in zip(cands, rel):
            recency = math.exp(-self.decay * max(0.0, horizon - m.t))
            s = self.w["recency"] * recency + self.w["importance"] * m.importance + self.w["relevance"] * (r / top)
            scored.append((m, round(s, 4)))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]

    async def aretrieve(self, query: str, horizon: float, k: int,
                        exclude: set[str] | None = None) -> list[tuple[Memory, float]]:
        return self.retrieve(query, horizon, k, exclude)


class MemoryBank:
    """Les souvenirs d'une partie dans PostgreSQL + pgvector. L'écriture est différée et groupée : un souvenir ajouté
    attend dans `pending`, et toute recherche commence par écrire ce qui attend (un seul calcul de vecteurs et une seule
    requête pour tous les souvenirs du moment). Aucune recherche ne peut donc manquer un souvenir déjà formé."""

    def __init__(self, store, embedder, run_id: str):
        self.store, self.embedder, self.run_id = store, embedder, run_id
        self.pending: list[tuple[str, Memory]] = []
        self.lock = asyncio.Lock()
        self.degraded = False

    async def flush(self) -> None:
        async with self.lock:
            if not self.pending:
                return
            batch, self.pending = self.pending, []
            try:
                vecs = await self.embedder.embed([m.text for _, m in batch])
                await self.store.put_memories(self.run_id, [(owner, m, v) for (owner, m), v in zip(batch, vecs)])
            except BaseException:
                self.pending[:0] = batch          # rien n'est perdu : réessayé à la prochaine recherche
                raise


class VectorMemory(MemoryStore):
    """La mémoire d'un agent, rangée aussi dans pgvector. Les souvenirs restent dans la liste locale (épinglés, rumeurs,
    identifiants) : si la base ne répond plus en cours de partie, la recherche se rabat sur BM25, sans rien perdre."""

    def __init__(self, owner: str, decay: float, weights: dict, bank: MemoryBank):
        super().__init__(owner, decay, weights)
        self.bank = bank

    def add(self, t: float, text: str, kind: str, importance: float, pinned=False, expires_season=None,
            source_event_id=None) -> Memory:
        m = super().add(t, text, kind, importance, pinned, expires_season, source_event_id)
        if not self.bank.degraded:                # base perdue : la liste locale suffit, rien ne s'accumule
            self.bank.pending.append((self.owner, m))
        return m

    async def aretrieve(self, query: str, horizon: float, k: int,
                        exclude: set[str] | None = None) -> list[tuple[Memory, float]]:
        bank = self.bank
        if not bank.degraded:
            try:
                await bank.flush()
                [q] = await bank.embedder.embed([query])
                rows = await bank.store.search_memories(bank.run_id, self.owner, q, horizon, sorted(exclude or ()),
                                                        self.w, self.decay, k)
                by_id = {m.id: m for m in self.items}
                return [(by_id[r["id"]], round(float(r["score"]), 4)) for r in rows if r["id"] in by_id]
            except Exception as exc:
                bank.degraded = True
                log.warning("mémoire vectorielle indisponible (%s) : BM25 en mémoire prend le relais", exc)
        return self.retrieve(query, horizon, k, exclude)
