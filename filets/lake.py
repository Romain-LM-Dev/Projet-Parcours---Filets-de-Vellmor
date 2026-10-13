"""Le lac de Vellmor : une ressource à croissance logistique, régénérée une fois par saison."""
from __future__ import annotations

import random


EXTINCT_BELOW = 0.05     # tonnes : sous 50 kg, le stock s'affiche « 0.0 t » et la croissance logistique n'a plus rien à faire croître


class Lake:
    def __init__(self, capacity: float, initial_ratio: float, growth_rate: float, collapse_ratio: float,
                 observation_noise: float):
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

    def regrow(self) -> float:
        before = self.stock
        self.stock = min(self.capacity, self.stock + self.r * self.stock * (1 - self.stock / self.capacity))
        return self.stock - before

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
