"""Pont WebSocket vers Godot.

Godot 4 parle WebSocket nativement (`WebSocketPeer`) mais pas le protocole Kafka : ce pont
relaie les topics `events`, `indicators` et `status` vers la scène, et renvoie dans `commands`
les ordres décidés depuis l'interface (injections, pause, vitesse, lancement d'une partie…).

Il garde en mémoire le run en cours, si bien qu'une scène Godot ouverte en retard reconstitue
tout l'état (mémoires comprises). Seuls les messages du run en cours sont rejoués : les
indicateurs d'un autre run, ou déjà reçus, sont écartés.

Messages vers Godot : {"topic": "catalog"|"status"|"hello"|"events"|"indicators", "data": {...}}
  - `catalog` : ce dont le menu de démarrage a besoin (une fois, à la connexion) ;
  - `status`  : état du moteur ; seul le dernier est conservé et rejoué à la connexion ;
  - `hello`   : nombre de messages d'historique qui suivent.
Messages depuis Godot : {"type": "drought"} | {"type": "pause"} | {"type": "start_game", "config": {...}} | ...
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

from websockets.asyncio.server import serve

log = logging.getLogger("filets.bridge")


class WSBridge:
    def __init__(self, host: str, port: int, on_command: Callable[[dict], None], buffer_max: int = 60000,
                 catalog: dict | None = None):
        self.host, self.port = host, port
        self.on_command = on_command
        self.clients: set = set()
        self.buffer: list[str] = []
        self.buffer_max = buffer_max
        self.loop: asyncio.AbstractEventLoop | None = None
        self.queue: asyncio.Queue | None = None
        self._server = None
        self._pump_task = None
        self._lock = asyncio.Lock()   # ordre garanti : un client reçoit l'historique puis le direct
        self._catalog_msg = json.dumps({"topic": "catalog", "data": catalog}, ensure_ascii=False) if catalog else None
        self.last_status: str | None = None
        self.current_run: str | None = None
        self._seen_indicators: set[str] = set()

    async def start(self):
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue()
        self._server = await serve(self._handler, self.host, self.port, max_size=2 ** 20)
        self._pump_task = asyncio.create_task(self._pump())
        log.info("pont WebSocket sur ws://%s:%d", self.host, self.port)

    async def stop(self):
        if self._pump_task:
            await self.drain()
            self._pump_task.cancel()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def drain(self, timeout: float = 2.0):
        try:
            await asyncio.wait_for(self.queue.join(), timeout)
        except asyncio.TimeoutError:
            pass

    def push(self, topic: str, data: dict):
        """Appelable depuis n'importe quel fil (consommateur Kafka compris)."""
        if self.loop is None:
            return
        if topic == "status" and "catalog" in data:
            # le moteur joint son catalogue à son état : on le relaie à part, l'état reste léger
            cat = json.dumps({"topic": "catalog", "data": data["catalog"]}, ensure_ascii=False)
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("catalog", None, None, None, cat))
            data = {k: v for k, v in data.items() if k != "catalog"}
        msg = json.dumps({"topic": topic, "data": data}, ensure_ascii=False)
        ident = None
        if topic == "indicators":
            p = data.get("payload", {})
            ident = f"{data.get('run_id')}|{p.get('trigger')}|{p.get('source_event_id')}"
        self.loop.call_soon_threadsafe(self.queue.put_nowait, (topic, data.get("type"), data.get("run_id"), ident, msg))

    async def _broadcast(self, msg: str):
        for ws in list(self.clients):
            try:
                await ws.send(msg)
            except Exception:
                self.clients.discard(ws)

    async def _pump(self):
        while True:
            topic, etype, run_id, ident, msg = await self.queue.get()
            try:
                async with self._lock:
                    if topic == "catalog":
                        if msg != self._catalog_msg:          # changé (autre moteur, autres options) : on le renvoie
                            self._catalog_msg = msg
                            await self._broadcast(msg)
                        continue
                    if topic == "status":
                        self.last_status = msg
                        await self._broadcast(msg)
                        continue
                    if topic == "events" and etype == "run_start":
                        self.buffer = []
                        self.current_run = run_id
                        self._seen_indicators.clear()
                    elif topic == "indicators":
                        if self.current_run is not None and run_id != self.current_run:
                            continue                        # indicateur d'un autre run
                        if ident in self._seen_indicators:
                            continue                        # déjà reçu (service redémarré, relecture…)
                        self._seen_indicators.add(ident)
                    self.buffer.append(msg)
                    if len(self.buffer) > self.buffer_max:
                        self.buffer = self.buffer[-self.buffer_max:]
                    await self._broadcast(msg)
            finally:
                self.queue.task_done()

    async def _handler(self, ws):
        async with self._lock:
            if self._catalog_msg:
                await ws.send(self._catalog_msg)
            if self.last_status:
                await ws.send(self.last_status)
            await ws.send(json.dumps({"topic": "hello", "data": {"buffered": len(self.buffer)}}))
            for msg in list(self.buffer):
                await ws.send(msg)
            self.clients.add(ws)
        try:
            async for raw in ws:
                try:
                    cmd = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(cmd, dict) and cmd.get("type"):
                    try:
                        self.on_command(cmd)
                    except Exception:
                        log.exception("commande %r non transmise", cmd.get("type"))
        finally:
            self.clients.discard(ws)
