"""Horloge simulée.

Le temps simulé est exprimé en jours (float) depuis le début du run. Une saison dure
`season_days` jours. Chaque événement porte deux temps (exigence C3) :

* `sim_time`     : le moment simulé où l'événement se produit dans le monde ;
* `processed_at` : le moment réel (horloge murale) où le système l'a traité, pauses déduites.

En mode synchrone, l'horloge avance par pas imposés par l'orchestrateur, quelle que
soit la latence des LLM. En mode asynchrone, elle avance avec le temps réel (cadence
`sim_hours_per_second`), si bien qu'un agent qui réfléchit 20 s agit plus tard, dans le
monde, qu'un agent qui réfléchit 1 s. Quand aucun agent ne réfléchit, elle peut
accélérer (`idle_speedup`) : personne n'est alors désavantagé par sa lenteur.

Le joueur peut mettre la partie en pause et changer la vitesse (`speed`, un facteur appliqué à
`sim_hours_per_second`). En pause, ni le temps simulé ni `processed_at` n'avancent.
"""
from __future__ import annotations

import math
import time

SPEED_MIN, SPEED_MAX = 0.05, 64.0


def fmt_sim(t: float, season_days: float) -> str:
    season = int(t // season_days) + 1
    day_f = t - (season - 1) * season_days
    day = int(day_f)
    minutes = int(round((day_f - day) * 24 * 60))
    if minutes >= 24 * 60:
        day, minutes = day + 1, 0
    return f"S{season} · J{day} {minutes // 60:02d}:{minutes % 60:02d}"


class SimClock:
    def __init__(self, season_days: float, sim_hours_per_second: float, idle_speedup: float, fast: bool):
        self.season_days = season_days
        self.base_rate = sim_hours_per_second / 24.0   # jours simulés par seconde réelle à la vitesse ×1
        self.speed = 1.0                               # facteur de vitesse choisi par le joueur
        self.idle_speedup = idle_speedup
        self.fast = fast
        self._now = 0.0
        self._wall0 = time.monotonic()
        self._paused_at: float | None = None
        self._paused_total = 0.0
        self.in_flight = 0  # nombre d'appels LLM en cours (information)

    @property
    def rate(self) -> float:
        """Jours simulés par seconde réelle, vitesse du joueur comprise."""
        return self.base_rate * self.speed

    def set_speed(self, speed: float) -> float:
        self.speed = min(SPEED_MAX, max(SPEED_MIN, float(speed)))
        return self.speed

    @property
    def paused(self) -> bool:
        return self._paused_at is not None

    def pause(self) -> None:
        if self._paused_at is None:
            self._paused_at = time.monotonic()

    def resume(self) -> None:
        if self._paused_at is not None:
            self._paused_total += time.monotonic() - self._paused_at
            self._paused_at = None

    def now(self) -> float:
        return self._now

    def wall_elapsed(self) -> float:
        """Secondes réelles de jeu écoulées depuis le début du run, pauses exclues."""
        ref = self._paused_at if self._paused_at is not None else time.monotonic()
        return ref - self._wall0 - self._paused_total

    def set(self, t: float) -> None:
        if t < self._now - 1e-9:
            raise RuntimeError(f"l'horloge simulée ne recule pas ({t} < {self._now})")
        self._now = t

    def advance_wall(self, dt_wall: float, next_due: float | None, busy: bool) -> None:
        """Mode async : fait avancer le temps simulé d'après le temps réel écoulé."""
        if not busy and next_due is not None:
            if self.fast or math.isinf(self.idle_speedup):
                self._now = max(self._now, next_due)
                return
            step = dt_wall * self.rate * self.idle_speedup
        else:
            step = dt_wall * self.rate
        if next_due is not None:
            # on s'arrête pile à l'échéance suivante pour la déclencher à son heure exacte
            step = min(step, max(0.0, next_due - self._now))
        self._now += step

    def label(self, t: float | None = None) -> str:
        return fmt_sim(self._now if t is None else t, self.season_days)

    def season_of(self, t: float | None = None) -> int:
        return int((self._now if t is None else t) // self.season_days) + 1

    def season_start(self, season: int) -> float:
        return (season - 1) * self.season_days
