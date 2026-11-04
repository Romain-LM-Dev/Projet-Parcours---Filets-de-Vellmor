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

from .agents import ballot, decide_catch, speak
from .clock import SimClock
from .events import EventFactory

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
        results = await self.parallel([(d[0], d[4].agent, d[4].make) for d in batch])
        for d, res in zip(batch, results):
            with SimClock.local(d[0]):
                d[4].then(res)

    async def parallel(self, jobs: list[tuple[float, str, Callable[[], Awaitable[Any]]]]) -> list:
        """Lance ces décisions `(horizon, agent, make)` en même temps. Leurs événements sortent dans l'ordre des `jobs` (celui de la
        file), et non dans celui où les modèles répondent : à graine égale, même journal, quelle que soit la lenteur de chacun."""
        names, bufs = [j[1] for j in jobs], [[] for _ in jobs]
        self.think(names, True)

        async def one(t: float, make, buf: list):
            with SimClock.local(t), EventFactory.defer(buf):         # elle se prend à son horizon, quel que soit l'affichage
                return await make()
        try:
            results = await self.w.ctl.guard(asyncio.gather(*(one(j[0], j[2], b) for j, b in zip(jobs, bufs))))
        finally:
            self.think(names, False)
            self.last = time.monotonic()
        for buf in bufs:
            self.w.events.flush(buf)
        self.w.heal_event_ids(self.w.events.renamed)
        self.w.events.renamed.clear()
        return results

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

    # ------------------------------------------------------------------ la veillée
    async def evening(self):
        """La veillée au fil de l'eau (docs/temps.md). Les répliques se préparent en parallèle sur le compte rendu du moment ; une
        seule personne parle à la fois (`time.speech_minutes` chacune), d'abord quelqu'un à qui l'on vient de s'adresser, puis selon la
        clé de la graine ; une réplique est préparée de nouveau si, avant son tour, on s'est adressé à son auteur ou une autre règle
        a concurrencé la sienne. Les veillées de villages différents avancent de front : leurs décisions partent ensemble, et
        leurs effets s'appliquent village par village, dans le même ordre à chaque partie. Puis les bulletins, en parallèle."""
        w, T, t0 = self.w, self.w.T, self.t0
        ta = t0 + T["assembly_day"]
        asms = w.open_assemblies(self.season, t0 + T["assembly_close_day"])
        if not asms:
            return
        w.events.emit("phase", {"name": "assembly", "state": "open"})
        villages = [Village(self, asm, ta) for asm in asms]
        while True:
            live = [v for v in villages if not v.done]
            jobs = [j for v in live for j in v.prep_jobs()]
            await self.prepare(jobs)
            picks = [(v, v.pick()) for v in live]
            redo = []
            for v, aid in picks:
                if aid is not None:
                    rnd, make = v.redo(aid)
                    if make:
                        redo.append((v, aid, rnd, v.t, make))
            await self.prepare(redo)
            spoke = False
            for v, aid in picks:
                spoke = v.speak(aid) or spoke
            if not spoke and not jobs:
                break
        ballots = [(v.t, a.id, lambda a=a, asm=v.asm: ballot(w, a, asm)) for v in villages for a in w.ballot_candidates(v.asm)]
        if ballots:
            await self.parallel(ballots)

        def close():
            for asm in asms:
                w.close_assembly(asm)
            w.events.emit("phase", {"name": "assembly", "state": "close"})
        self.at(t0 + T["assembly_close_day"], CONSEIL, "clôture", close)

    async def prepare(self, jobs: list[tuple]):
        """Prépare ces répliques `(village, agent, tour, horizon, make)` en parallèle et les range, prêtes, dans leur village."""
        if not jobs:
            return
        outs = await self.parallel([(h, aid, make) for v, aid, rnd, h, make in jobs])
        for (v, aid, rnd, h, _), out in zip(jobs, outs):
            v.prepared[aid] = (out, h, rnd, len(v.asm.utterances), frozenset(v.asm.proposals))

    # ------------------------------------------------------------------ la fin
    def regrowth(self):
        w, t = self.w, self.t0 + self.w.T["regrowth_day"]
        w.events.emit("phase", {"name": "regrowth", "state": "open"})
        w.end_season(self.season)

        async def narrate():
            with SimClock.local(t):             # le récit est de la fin de la saison, même s'il s'écrit pendant la suivante
                await w.narrate(self.season)
        self.recit = asyncio.ensure_future(narrate())


class Village:
    """La veillée d'un village (ou du conseil de la vallée) : qui a préparé quoi, qui a parlé, et l'heure qu'il est dans la salle."""

    def __init__(self, sched: SeasonScheduler, asm, ta: float):
        self.s, self.w, self.asm, self.t = sched, sched.w, asm, round(ta, 6)
        self.rounds = int(self.w.scn["assembly_rounds"])
        self.duration = float(self.w.T.get("speech_minutes", 20)) / 1440.0
        self.close_t = asm.close_t
        self.spoken: dict[str, int] = {aid: 0 for aid in asm.participants}
        self.prepared: dict[str, tuple] = {}         # agent -> (réponse, horizon, tour, paroles connues, propositions connues)
        self.done = False

    def prep_jobs(self) -> list[tuple]:
        """Les répliques à préparer maintenant : celles de ceux qui n'en ont pas de prête, ont encore droit à la parole et ont quelque
        chose à dire (voir `World.has_reason_to_speak`)."""
        if self.done or self.t + self.duration > self.close_t:
            return []
        w, asm = self.w, self.asm
        out = []
        for aid in asm.participants:
            a, rnd = w.agents[aid], self.spoken[aid] + 1
            if aid not in self.prepared and rnd <= self.rounds and w.has_reason_to_speak(a, asm, rnd):
                out.append((self, aid, rnd, self.t, lambda a=a, rnd=rnd, h=self.t: speak(w, a, asm, rnd, h)))
        return out

    def pick(self) -> str | None:
        """Qui parle ensuite : d'abord celui à qui l'on vient de s'adresser, puis les autres selon la clé de la graine."""
        if not self.prepared:
            self.done = True
            return None
        last = self.asm.utterances[-1]["payload"]["to"] if self.asm.utterances else None
        if last in self.prepared:
            return last
        return min(self.prepared, key=lambda aid: self.s.key(f"{self.asm.scope}|{aid}"))

    def stale(self, aid: str) -> bool:
        """Depuis qu'elle est préparée, a-t-on répondu à son auteur (adressé, nommé, accusé) ou concurrencé sa règle ?"""
        w, asm = self.w, self.asm
        _, h, _, n_utt, props = self.prepared[aid]
        new = [u for u in asm.utterances[n_utt:] if u["payload"]["speaker"] != aid]
        if any(u["payload"]["to"] == aid for u in new) or any(t > h and a == aid for t, a in asm.accused):
            return True
        if aid in w.named_fishers([u["payload"]["text"] for u in new]):
            return True
        return any(p.author == aid for p in asm.proposals.values()) and \
            any(p.author != aid and p.id not in props for p in asm.proposals.values())

    def redo(self, aid: str):
        """(tour, `make`) pour préparer de nouveau la réplique de `aid` si elle est périmée, sinon (tour, None)."""
        rnd = self.prepared[aid][2]
        if not self.stale(aid):
            return rnd, None
        del self.prepared[aid]
        a, h = self.w.agents[aid], self.t
        return rnd, lambda: speak(self.w, a, self.asm, rnd, h)

    def speak(self, aid: str | None) -> bool:
        if aid is None or aid not in self.prepared:
            return False
        out, h, rnd, _, _ = self.prepared.pop(aid)
        if self.t + self.duration > self.close_t:
            self.done = True
            return False
        w = self.w
        end = round(self.t + self.duration, 6)         # (arrondi comme le temps des événements : ceux-ci passent avant les horizons suivants)
        with SimClock.local(end):          # la réplique dure ; ses effets s'appliquent à sa fin
            w.post_utterance(w.agents[aid], self.asm, out, rnd, h)
        self.t = end
        self.spoken[aid] += 1
        return True
