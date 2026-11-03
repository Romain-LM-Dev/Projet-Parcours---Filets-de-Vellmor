"""Le lac de Vellmor : une ressource à croissance logistique, régénérée une fois par saison, répartie sur les parcelles de sa maille.

Chaque parcelle (voir `lakes.lake_parcels`) a son poisson et sa chance. Une barque pêche autour de sa parcelle : elle y vide le
poisson d'abord, puis celui des parcelles voisines (le filet porte loin, le poisson nage). Le repeuplement de la saison est celui du
lac entier (la même logistique qu'avant), réparti entre les parcelles selon ce qui y manque ; puis le poisson se redistribue en partie
(`MIX`) vers ses coins habituels. Sans parcelles, le lac en a une seule : tout se passe comme avant.
"""
from __future__ import annotations

import math
import random


EXTINCT_BELOW = 0.05     # tonnes : sous 50 kg, le stock s'affiche « 0.0 t » et la croissance logistique n'a plus rien à faire croître
REACH = 1.6              # parcelles : la portée d'une pêche (l'écart type du noyau gaussien autour de la parcelle de la barque)
MIX = 0.35               # la part du poisson qui regagne ses coins habituels à chaque repeuplement


class Lake:
    def __init__(self, capacity: float, initial_ratio: float, growth_rate: float, collapse_ratio: float,
                 observation_noise: float, name: str = "Vellmor", label: str = "Lac de Vellmor", parcels: list[dict] | None = None):
        self.name, self.label = name, label
        self.capacity = capacity
        self.parcels = parcels or [{"i": 0, "j": 0, "depth": 0, "share": 1.0, "luck": 1.0}]
        self.cap_cells = [capacity * p["share"] for p in self.parcels]
        self.cells = [c * initial_ratio for c in self.cap_cells]
        self._stock = capacity * initial_ratio
        self.open_cells = list(self.cells)          # les parcelles à l'ouverture de la saison (voir `fill_near`)
        self.r = growth_rate
        self.collapse_ratio = collapse_ratio
        self.noise = observation_noise
        self.collapsed = False

    @property
    def stock(self) -> float:
        return self._stock

    @stock.setter
    def stock(self, value: float):
        """Fixer le stock d'un coup (sécheresse, tests) : chaque parcelle dans la même proportion."""
        value = max(0.0, value)
        k = value / self._stock if self._stock > 0 else None
        self.cells = [c * k for c in self.cells] if k is not None else [c * value / self.capacity for c in self.cap_cells]
        self._stock = value

    def _kernel(self, at: int) -> list[float]:
        p = self.parcels[at]
        return [math.exp(-((q["i"] - p["i"]) ** 2 + (q["j"] - p["j"]) ** 2) / (2 * REACH * REACH)) for q in self.parcels]

    def take(self, amount: float, at: int | None = None) -> float:
        """Prend `amount` tonnes (au plus ce qu'il y a). `at` : la parcelle où pêche la barque ; le poisson vient d'abord d'elle et de
        ses voisines, puis, s'il en manque, de tout le lac. Sans `at`, de partout à la fois."""
        landed = max(0.0, min(amount, self._stock))
        rest = landed
        if at is not None and len(self.cells) > 1:
            for _ in range(3):
                # (selon le poisson de l'ouverture, pas celui du moment : l'ordre des retours n'y change rien)
                w = [o * k if c > 1e-12 else 0.0 for c, o, k in zip(self.cells, self.open_cells, self._kernel(at))]
                total = sum(w)
                if total <= 1e-12 or rest <= 1e-9:
                    break
                got = 0.0
                for j, wj in enumerate(w):
                    r = min(self.cells[j], rest * wj / total)
                    self.cells[j] -= r
                    got += r
                rest -= got
        if rest > 1e-12:
            left = sum(self.cells)
            k = max(0.0, 1 - rest / left) if left > 0 else 0.0
            self.cells = [c * k for c in self.cells]
        self._stock = max(0.0, self._stock - landed)
        return landed

    def open_season(self):
        """L'ouverture de la pêche : ce que chaque coin a gardé des saisons passées fait son rendement de la saison."""
        self.open_cells = list(self.cells)

    def fill_near(self, at: int) -> float:
        """Le remplissage autour de la parcelle `at` à l'ouverture de la saison (son poisson et celui de ses voisines, sur ce
        qu'elles tiennent pleines), rapporté à celui du lac : moins de 1, les barques y ont trop pêché les saisons passées. (Le
        même pour toutes les barques de la saison, quel que soit l'ordre de leurs retours.)"""
        k = self._kernel(at)
        here = sum(c * w for c, w in zip(self.open_cells, k)) / max(sum(c * w for c, w in zip(self.cap_cells, k)), 1e-9)
        return here / max(sum(self.open_cells) / self.capacity, 1e-9)

    def regrow(self, rate_factor: float = 1.0) -> float:
        """Repeuplement de la saison ; `rate_factor` : la saison de l'année et les événements (voir `climate.py`). Le lac entier
        croît comme avant ; la croissance va aux parcelles selon ce qui leur manque, puis une part du poisson regagne ses coins."""
        before = self._stock
        r = self.r * rate_factor
        after = min(self.capacity, before + r * before * (1 - before / self.capacity))
        grow = after - before
        w = [max(0.0, c * (1 - c / cc)) for c, cc in zip(self.cells, self.cap_cells)]
        if sum(w) <= 1e-12:
            w = [max(0.0, cc - c) for c, cc in zip(self.cells, self.cap_cells)]
        total = sum(w) or 1.0
        cells = [c + grow * wj / total for c, wj in zip(self.cells, w)]
        self.cells = [(1 - MIX) * c + MIX * after * p["share"] for c, p in zip(cells, self.parcels)]
        self._stock = after
        return after - before

    def observe_far(self, rng: random.Random) -> float:
        """Ce qu'on croit d'un lac où l'on ne pêche pas, vu de loin (par ouï-dire) : deux fois plus d'erreur que sur son propre lac."""
        est = self.stock * (1 + rng.uniform(-2 * self.noise, 2 * self.noise))
        return round(max(0.0, est), 1)

    def shock(self, factor: float) -> float:
        before = self._stock
        self.stock = before * factor
        return self._stock - before

    def observe(self, rng: random.Random) -> float:
        """Ce qu'un pêcheur estime du stock : la vérité entachée d'une erreur relative."""
        est = self.stock * (1 + rng.uniform(-self.noise, self.noise))
        return round(max(0.0, est), 1)

    def is_collapsed(self) -> bool:
        return self.stock < self.capacity * self.collapse_ratio

    def is_extinct(self) -> bool:
        """Plus un poisson : le repeuplement logistique part du stock, donc un lac à 0 ne se refait jamais."""
        return self.stock < EXTINCT_BELOW
