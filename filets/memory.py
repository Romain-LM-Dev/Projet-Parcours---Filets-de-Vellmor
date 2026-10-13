"""Mémoire propre de chaque agent (exigence A1).

Un flux de souvenirs horodatés en temps simulé. La récupération combine récence,
importance et pertinence (à la manière de Park et al., 2023). Les engagements
(promesses faites, règle en vigueur, accusations reçues) sont « épinglés » : ils
remontent à chaque décision tant qu'ils sont d'actualité, si bien qu'un pêcheur
se souvient la saison suivante de sa promesse, même s'il la trahit.

Un souvenir n'est jamais retrouvé avant son instant simulé (`t <= horizon`) : un agent
ne peut pas agir sur une information qu'il n'avait pas encore (C6).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .rag import BM25, tokenize


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
