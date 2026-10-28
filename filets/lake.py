"""Le lac de Vellmor : une ressource à croissance logistique, régénérée une fois par saison."""
from __future__ import annotations

import random


EXTINCT_BELOW = 0.05     # tonnes : sous 50 kg, le stock s'affiche « 0.0 t » et la croissance logistique n'a plus rien à faire croître


class Lake:
    def __init__(self, capacity: float, initial_ratio: float, growth_rate: float, collapse_ratio: float,
                 observation_noise: float, name: str = "Vellmor", label: str = "Lac de Vellmor"):
        self.name, self.label = name, label
        self.capacity = capacity
        self.stock = capacity * initial_ratio
        self.r = growth_rate
        self.collapse_ratio = collapse_ratio
        self.noise = observation_noise
        self.collapsed = False

    def take(self, amount: float) -> float:
        landed = max(0.0, min(amount, self.stock))
        self.stock -= landed
        return landed

    def regrow(self, rate_factor: float = 1.0) -> float:
        """Repeuplement de la saison ; `rate_factor` : la saison de l'année et les événements (voir `climate.py`)."""
        before = self.stock
        r = self.r * rate_factor
        self.stock = min(self.capacity, self.stock + r * self.stock * (1 - self.stock / self.capacity))
        return self.stock - before

    def observe_far(self, rng: random.Random) -> float:
        """Ce qu'on croit d'un lac où l'on ne pêche pas, vu de loin (par ouï-dire) : deux fois plus d'erreur que sur son propre lac."""
        est = self.stock * (1 + rng.uniform(-2 * self.noise, 2 * self.noise))
        return round(max(0.0, est), 1)

    def shock(self, factor: float) -> float:
        before = self.stock
        self.stock *= factor
        return self.stock - before

    def observe(self, rng: random.Random) -> float:
        """Ce qu'un pêcheur estime du stock : la vérité entachée d'une erreur relative."""
        est = self.stock * (1 + rng.uniform(-self.noise, self.noise))
        return round(max(0.0, est), 1)

    def is_collapsed(self) -> bool:
        return self.stock < self.capacity * self.collapse_ratio

    def is_extinct(self) -> bool:
        """Plus un poisson : le repeuplement logistique part du stock, donc un lac à 0 ne se refait jamais."""
        return self.stock < EXTINCT_BELOW
