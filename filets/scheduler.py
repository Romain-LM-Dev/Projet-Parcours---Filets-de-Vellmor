"""L'ordonnanceur d'une saison : une simulation à événements discrets (spécification : `docs/temps.md`).

Réfléchir ne prend pas de temps simulé ; agir en prend. La file porte deux sortes d'éléments, classés sur (t, classe, clé) :

* un **effet** : une action du monde, appliquée à son instant (fin d'une sortie, retour, ouverture de la veillée, repeuplement…) ;
* une **décision** : un appel d'agent (IA ou règle) de durée nulle, attachée à un horizon `t` (elle ne voit que ce qui s'est passé
  avant). L'horloge ne dépasse jamais l'horizon d'une décision demandée et pas encore rendue.

Les décisions de la tête de file qui n'ont aucun effet entre elles forment un lot : elles sont demandées ensemble et tournent en même
temps (dans la limite de la carte graphique, `ModelGate`). Une décision porte un `lag`, le plus court délai avant que son effet
s'applique (une sortie dure un jour) : tant que l'horizon d'une suivante le précède, la suivante ne dépend de rien qu'elle ne puisse
voir, et le lot s'allonge ; sinon elle attend, car la première est susceptible de changer ce qu'elle voit (c'est une chaîne). Les
résultats s'appliquent dans l'ordre de la file, jamais dans celui où les modèles répondent : à graine égale, même journal.

Pendant une décision, `SimClock.now()` vaut son horizon (voir `SimClock.local`) ; entre deux échéances, l'horloge avance au rythme
d'affichage (pause, vitesse et arrêt viennent de `control.py`).
"""
from __future__ import annotations

import asyncio
import heapq
import inspect
import itertools
import random
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .agents import decide_catch, speak
from .clock import SimClock

# l'ordre des acteurs à instant égal
MONDE, LACS, PECHEURS, PATROUILLE, CONSEIL, FERMETURE = range(6)


@dataclass
class Decision:
    """Un appel d'agent attaché à un horizon (`t`) ; `make()` le lance, `then(résultat)` en tire les effets, dans l'ordre de la file."""
    agent: str
    lag: float
    make: Callable[[], Awaitable[Any]]
    then: Callable[[Any], None]


class SeasonScheduler:
    TICK = 0.02
    ROUND_STEP = 0.05          # ≈ 1 h 12 simulées entre deux tours de parole

    def __init__(self, w, season: int):
        self.w = w
        self.c = w.clock
        self.season = season
        self.t0 = self.c.season_start(season)
        self.q: list = []
        self.seq = itertools.count()
        self.recit: asyncio.Future | None = None
        self.last = time.monotonic()          # le dernier instant réel compté pour l'affichage (la réflexion n'en fait pas partie)

    # ------------------------------------------------------------------ la file
    def key(self, ident: str) -> float:
        """L'ordre à classe égale : tiré de la graine, le même d'une partie à l'autre."""
        return random.Random(f"{self.w.cfg['run']['seed']}|order|{self.season}|{ident}").random()

    def at(self, t: float, cls: int, ident: str, item) -> None:
        """Inscrit un effet (fonction, éventuellement asynchrone) ou une `Decision` à l'instant `t`."""
        heapq.heappush(self.q, (round(t, 6), cls, self.key(ident), next(self.seq), item))

    # ------------------------------------------------------------------ l'horloge d'affichage
    async def show(self, t: float):
        """Montre le temps qui passe jusqu'à `t` (vitesse, accélération entre deux échéances et pause comprises), puis y est."""
        ctl, c = self.w.ctl, self.c
        while c.now() < t - 1e-9 and not c.fast:
            if await ctl.checkpoint():          # reprise après une pause : on ne rattrape pas le temps de la pause
                self.last = time.monotonic()
            now_wall = time.monotonic()
            dt, self.last = now_wall - self.last, now_wall
            c.advance_wall(dt, t, busy=False)
            if c.now() < t - 1e-9:
                await asyncio.sleep(self.TICK)
        await ctl.checkpoint()                  # une pause demandée pendant l'attente fige le monde avant le saut
        c.set(max(t, c.now()))

    # ------------------------------------------------------------------ la boucle
    async def play(self) -> asyncio.Future:
        """Joue la saison. Renvoie la tâche du récit du narrateur, qui ne bloque pas la préparation de la suivante."""
        self.at(self.t0, MONDE, "ouverture", self.open_season)
        while self.q:
            await self.w.ctl.checkpoint()
            t, _, _, _, item = self.q[0]
            if isinstance(item, Decision):
                await self.run_batch()
                continue
            heapq.heappop(self.q)
            await self.show(t)
            out = item()
            if inspect.isawaitable(out):
                await self.w.ctl.guard(out)
        return self.recit or asyncio.ensure_future(asyncio.sleep(0))

    async def run_batch(self):
        """Le lot de décisions de la tête de file : toutes celles qu'aucun effet ne sépare (ni les leurs, qui viendraient trop tôt)."""
        batch = [heapq.heappop(self.q)]
        limit = batch[0][0] + batch[0][4].lag
        while self.q and isinstance(self.q[0][4], Decision):
            t = self.q[0][0]
            if t >= limit - 1e-9 and t > batch[0][0] + 1e-9:
                break
            nxt = heapq.heappop(self.q)
            batch.append(nxt)
            limit = min(limit, t + nxt[4].lag)
        await self.show(batch[0][0])
        names = [d[4].agent for d in batch]
        self.think(names, True)

        async def one(t: float, d: Decision):
            with SimClock.local(t):           # elle se prend à son horizon, quel que soit l'affichage
                return await d.make()
        try:
            results = await self.w.ctl.guard(asyncio.gather(*(one(d[0], d[4]) for d in batch)))
        finally:
            self.think(names, False)
            self.last = time.monotonic()
        for d, res in zip(batch, results):
            with SimClock.local(d[0]):
                d[4].then(res)

    def think(self, names: list[str], on: bool):
        """Qui réfléchit en ce moment (l'interface le montre, dans l'état du moteur)."""
        for n in names:
            if on:
                self.w.thinking.append(n)
            elif n in self.w.thinking:
                self.w.thinking.remove(n)
        self.w.publish_status()

    # ------------------------------------------------------------------ la saison
    def open_season(self):
        w, T, t0 = self.w, self.w.T, self.t0
        w.begin_season(self.season)
        opening = t0 + T["fishing_open_day"]
        self.at(opening, MONDE, "pêche", lambda: w.events.emit("phase", {"name": "fishing", "state": "open"}))
        for a in w.fishers:
            h = opening + a.offset_days            # son jour de départ ; sa décision de prise a cet instant pour horizon
            self.at(h, PECHEURS, a.id, Decision(a.id, 1.0, lambda a=a, h=h: decide_catch(w, a, h),
                                                lambda o, a=a, h=h: self.depart(a, o, h)))
        self.at(t0 + T["fishing_close_day"], FERMETURE, "pêche", lambda: w.events.emit("phase", {"name": "fishing", "state": "close"}))
        self.at(t0 + T["assembly_day"], CONSEIL, "veillée", self.evening)
        self.at(t0 + T["regrowth_day"], MONDE, "repeuplement", self.regrowth)

    def depart(self, a, o, h: float):
        """Sa décision est prise : il part. Chaque sortie retire son poisson à sa fin ; le retour (la dernière, plus la route) vend,
        déclare et laisse les indices."""
        w = self.w
        trip = w.plan_trip(a, o.value, o.decision, h, declared=o.data.get("declaration"), lake_name=o.data.get("lake"))
        if trip is None:
            return
        for k, out in enumerate(trip.outs):
            self.at(self.t0 + out["day"] + 1.0, PECHEURS, a.id, lambda k=k: w.land_outing(trip, k))
        back = self.t0 + trip.outs[-1]["day"] + 1.0 + trip.days if trip.outs else h + 2 * trip.days
        self.at(back, PECHEURS, a.id, lambda: w.finish_trip(trip))

    # ------------------------------------------------------------------ la veillée (provisoire : tours dépendants)
    async def evening(self):
        """Chacun parle à son tour et entend ceux qui ont parlé avant lui ; les veillées de villages différents sont indépendantes
        et se déroulent en parallèle. (Provisoire : elle sera refaite au fil de l'eau, voir `docs/temps.md`.)"""
        w, T, t0 = self.w, self.w.T, self.t0
        ta = t0 + T["assembly_day"]
        asms = w.open_assemblies(self.season, t0 + T["assembly_close_day"])
        if not asms:
            return
        w.events.emit("phase", {"name": "assembly", "state": "open"})
        await asyncio.gather(*(self.village(asm, ta) for asm in asms))
        with SimClock.local(ta + int(w.scn["assembly_rounds"]) * self.ROUND_STEP):
            await w.ballots(asms)                      # le bulletin de ceux qui n'ont rien soutenu
        self.last = time.monotonic()

        def close():
            for asm in asms:
                w.close_assembly(asm)
            w.events.emit("phase", {"name": "assembly", "state": "close"})
        self.at(t0 + T["assembly_close_day"], CONSEIL, "clôture", close)

    async def village(self, asm, ta: float):
        w = self.w
        step = self.ROUND_STEP / (len(asm.participants) + 1)
        for rnd in range(1, int(w.scn["assembly_rounds"]) + 1):
            for k, aid in enumerate(asm.participants):
                await w.ctl.checkpoint()
                a, h = w.agents[aid], ta + (rnd - 1) * self.ROUND_STEP + k * step
                with SimClock.local(h):
                    if w.has_reason_to_speak(a, asm, rnd):
                        self.think([aid], True)
                        try:
                            o = await speak(w, a, asm, rnd, h)
                        finally:
                            self.think([aid], False)
                        w.post_utterance(a, asm, o, rnd, h)

    # ------------------------------------------------------------------ la fin
    def regrowth(self):
        w, t = self.w, self.t0 + self.w.T["regrowth_day"]
        w.events.emit("phase", {"name": "regrowth", "state": "open"})
        w.end_season(self.season)

        async def narrate():
            with SimClock.local(t):             # le récit est de la fin de la saison, même s'il s'écrit pendant la suivante
                await w.narrate(self.season)
        self.recit = asyncio.ensure_future(narrate())
