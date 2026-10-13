"""Bout en bout, sans Kafka : un vrai processus `python -m filets serve` et un client WebSocket qui fait ce que
fait Godot (catalogue, état, lancement d'une partie, pause, vitesse, mode, nouvelle partie, client en retard)."""
from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time

import pytest
from websockets.asyncio.client import connect

from filets.config import ROOT


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def fisher(first, hamlet, arch):
    return {"first_name": first, "hamlet": hamlet, "archetype": arch, "experience": 20, "wealth": 500,
            "debt_payment": 0, "kind": "rule", "tier": "auto"}


def request(seasons=4, mode="sync", speed=1.0):
    return {"mode": mode, "seasons": seasons, "seed": 5, "communication": "valley", "catches_visible": True,
            "llm": "scripted", "speed": speed,
            "population": {"elder": True, "elder_kind": "rule", "fishers": [
                fisher("Aldric", "Ostrel", "taiseux"), fisher("Odile", "Tilque", "beau_parleur"),
                fisher("Rémi", "Hennad", "nouveau_venu")]}}


class Client:
    def __init__(self, ws):
        self.ws = ws
        self.messages: list[dict] = []
        self._task = asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for raw in self.ws:
                self.messages.append(json.loads(raw))
        except Exception:
            pass

    def of(self, topic):
        return [m["data"] for m in self.messages if m["topic"] == topic]

    def events(self, etype=None):
        return [e for e in self.of("events") if etype is None or e["type"] == etype]

    @property
    def status(self):
        s = self.of("status")
        return s[-1] if s else {}

    async def send(self, **cmd):
        await self.ws.send(json.dumps(cmd))

    async def until(self, cond, timeout=40.0, what="condition"):
        t0 = time.monotonic()
        while not cond():
            if time.monotonic() - t0 > timeout:
                raise AssertionError(f"délai dépassé : {what}\nétat={self.status}")
            await asyncio.sleep(0.05)


async def connect_when_up(port, timeout=30.0):
    t0 = time.monotonic()
    while True:
        try:
            return await connect(f"ws://127.0.0.1:{port}", max_size=2 ** 22)
        except OSError:
            if time.monotonic() - t0 > timeout:
                raise
            await asyncio.sleep(0.2)


def test_a_player_session_against_a_real_engine_process(tmp_path):
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "filets", "serve", "--ws-port", str(port), "--mode", "sync",
         "--set", f"output.runs_dir={tmp_path / 'runs'}", "--set", "time.sim_hours_per_second=720"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")

    async def session():
        ws = await connect_when_up(port)
        c = Client(ws)
        # --- 1. à la connexion : le catalogue, puis l'état du salon
        await c.until(lambda: c.of("catalog") and c.status.get("state") == "idle", 20, "salon ouvert")
        cat = c.of("catalog")[0]
        assert cat["defaults"]["mode"] == "sync" and len(cat["base_population"]) == 8
        assert [m["topic"] for m in c.messages[:3]] == ["catalog", "status", "hello"]
        assert c.status["lobby"] is True and c.status["controls"] is True

        # --- 2. lancer la partie depuis le menu
        await c.send(type="start_game", config=request())
        await c.until(lambda: c.status.get("state") == "running" and c.events("catch"), what="partie lancée")
        run_id = c.status["run_id"]
        assert c.events("run_start")[0]["payload"]["lake"]["capacity"] == pytest.approx(37.5)

        # --- 3. pause : plus aucun événement ; reprise : ça repart
        await c.send(type="pause")
        await c.until(lambda: c.status.get("state") == "paused", what="pause")
        await asyncio.sleep(0.2)
        frozen = len(c.of("events"))
        await asyncio.sleep(1.2)
        assert len(c.of("events")) == frozen, "aucun événement ne doit passer en pause"
        assert c.status["paused"] is True
        await c.send(type="resume")
        await c.until(lambda: c.status.get("state") == "running" and len(c.of("events")) > frozen, what="reprise")

        # --- 4. changement de mode : annoncé tout de suite, appliqué à la saison suivante
        await c.send(type="set_mode", value="async")
        await c.until(lambda: c.status.get("pending_mode") == "async", what="mode annoncé")
        n_seasons = len(c.events("season_start"))
        await c.until(lambda: any(e["payload"].get("mode") == "async" for e in c.events("season_start")),
                      what="saison asynchrone")
        assert c.status["pending_mode"] is None or c.status["mode"] == "async"

        # --- 5. vitesse maximale : la fin arrive vite
        await c.send(type="set_speed", value="max")
        await c.until(lambda: c.status.get("fast") is True, what="vitesse max")
        await c.until(lambda: c.status.get("state") == "ended", 40, "fin de partie")
        assert c.status["end_reason"] == "completed" and c.status["lobby"] is True
        modes = [e["payload"]["mode"] for e in c.events("season_start")]
        assert modes[0] == "sync" and "async" in modes and len(modes) == 4
        injected = [e["payload"]["injection_type"] for e in c.events("injection")]
        assert injected[:2] == ["pause", "resume"] and "set_mode" in injected and "set_speed" in injected

        # --- 6. une deuxième partie, autre composition, sans rien relancer
        req2 = request(seasons=2, mode="async", speed="max")
        req2["population"]["fishers"] = req2["population"]["fishers"][:2]
        await c.send(type="start_game", config=req2)
        await c.until(lambda: c.status.get("state") == "ended" and c.status.get("run_id") != run_id, 40, "2e partie")
        run2 = c.status["run_id"]
        assert c.events("run_start")[-1]["run_id"] == run2
        assert len([a for a in c.events("run_start")[-1]["payload"]["agents"] if a["role"] == "pecheur"]) == 2

        # --- 7. un client qui arrive en retard : catalogue, état, et seulement la dernière partie
        late = Client(await connect_when_up(port))
        await late.until(lambda: late.status.get("state") == "ended" and late.events("run_end"), what="rattrapage")
        assert late.of("catalog") and {e["run_id"] for e in late.events()} == {run2}
        assert [m["topic"] for m in late.messages[:3]] == ["catalog", "status", "hello"]
        inds = late.of("indicators")
        assert inds and all(i["run_id"] == run2 for i in inds)
        season_end = [i for i in inds if i["payload"]["trigger"] == "season_end"]
        assert [i["season"] for i in season_end] == [1, 2]
        assert all(0 <= i["payload"]["values"]["stock_ratio"] <= 1 for i in season_end)
        await ws.close()
        await late.ws.close()

    try:
        asyncio.run(asyncio.wait_for(session(), 150))
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
    out = proc.stdout.read()
    assert "Traceback" not in out, out
