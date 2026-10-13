"""Pilotage d'une partie en cours : pause, vitesse, mode de temps, arrêt.

Les commandes arrivent de l'interface (Godot) par le bus ; `World.handle_command` les applique
ici, et les orchestrateurs (synchrone / asynchrone) consultent cet objet aux points de passage :

* `checkpoint()` bloque tant que la partie est en pause et lève `StopRun` si l'arrêt est demandé ;
* `sleep()` est une attente (vitesse ×1) qui respecte la pause et les changements de vitesse ;
* `guard()` fait la course entre un travail (appels LLM en cours) et l'arrêt demandé.

Le mode (synchrone / asynchrone) ne change qu'aux frontières de saison : c'est le seul moment
où les deux orchestrations parlent de la même chose (voir `world.World.run`).
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, TypeVar

from .clock import SimClock

T = TypeVar("T")

MODES = ("sync", "async")


class StopRun(Exception):
    """L'arrêt de la partie a été demandé : remonte jusqu'à `World.run`."""


class GameControl:
    def __init__(self, clock: SimClock, mode: str):
        self.clock = clock
        self.mode = mode                      # mode de la saison en cours
        self.pending_mode: str | None = None  # mode demandé, appliqué au début de la prochaine saison
        self._run = asyncio.Event()           # levé = la partie avance
        self._run.set()
        self._stop = asyncio.Event()
        self.on_change: Callable[[], None] | None = None

    # ------------------------------------------------------------------ état
    @property
    def paused(self) -> bool:
        return not self._run.is_set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def _changed(self) -> None:
        if self.on_change:
            self.on_change()

    # ------------------------------------------------------------------ commandes
    def pause(self) -> bool:
        if self.paused or self.stopping:
            return False
        self._run.clear()
        self.clock.pause()
        self._changed()
        return True

    def resume(self) -> bool:
        if not self.paused:
            return False
        self.clock.resume()
        self._run.set()
        self._changed()
        return True

    def set_speed(self, speed: float) -> float:
        value = self.clock.set_speed(speed)
        self._changed()
        return value

    def set_fast(self, fast: bool) -> None:
        self.clock.fast = bool(fast)
        self._changed()

    def request_mode(self, mode: str) -> bool:
        if mode not in MODES:
            return False
        self.pending_mode = None if mode == self.mode else mode
        self._changed()
        return True

    def take_mode(self) -> str:
        """Appelé au début de chaque saison : applique le mode demandé, le cas échéant."""
        if self.pending_mode:
            self.mode, self.pending_mode = self.pending_mode, None
        return self.mode

    def request_stop(self) -> None:
        if not self._stop.is_set():
            self._stop.set()
            self.clock.resume()     # le temps de l'arrêt ne compte pas comme une pause
            self._run.set()         # libère ce qui attendait la fin de la pause
            self._changed()

    # ------------------------------------------------------------------ points de passage
    async def checkpoint(self) -> bool:
        """Renvoie True si la partie a dû attendre (elle était en pause). Lève `StopRun` si l'arrêt est demandé."""
        waited = False
        while True:
            if self._stop.is_set():
                raise StopRun()
            if self._run.is_set():
                return waited
            waited = True
            await self._run.wait()

    async def sleep(self, seconds: float) -> None:
        """Attente de `seconds` secondes à la vitesse ×1 : plus courte si la vitesse augmente, suspendue en pause."""
        remaining = float(seconds)
        last = time.monotonic()
        while remaining > 1e-3 and not self.clock.fast:
            if await self.checkpoint():
                last = time.monotonic()
            speed = self.clock.speed
            await asyncio.sleep(min(0.05, remaining / speed))
            now = time.monotonic()
            remaining -= (now - last) * speed
            last = now

    async def guard(self, work: Awaitable[T]) -> T:
        """Exécute `work` ; si l'arrêt est demandé avant la fin, l'annule et lève `StopRun`."""
        task = asyncio.ensure_future(work)
        stopper = asyncio.ensure_future(self._stop.wait())
        try:
            await asyncio.wait({task, stopper}, return_when=asyncio.FIRST_COMPLETED)
            if task.done():
                return task.result()
            raise StopRun()
        finally:
            stopper.cancel()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
