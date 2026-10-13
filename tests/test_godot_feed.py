"""Ce que le joueur lit dans Godot : répliques perdues dites clairement, annonces visibles, rumeur dans l'inspecteur,
et bouton « Ralentir ». Un run asynchrone enregistré (modèle lent, annonce dès la première saison) est rejoué dans l'interface
principale, hors fenêtre (`godot/tests/main_feed_test.gd`).
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess

import pytest

from filets.bus import LocalBus
from filets.config import ROOT
from filets.pipeline import IndicatorPublisher
from filets.world import World
from helpers import cfg_for

CANDIDATES = [os.environ.get("GODOT_PATH"), r"C:\Godot_v4.7.2-stable_win64.exe\Godot_v4.7.2-stable_win64.exe",
              shutil.which("godot")]
GODOT = next((c for c in CANDIDATES if c and os.path.exists(c)), None)

pytestmark = pytest.mark.skipif(GODOT is None, reason="Godot introuvable (définir GODOT_PATH)")


def slow_async_run_with_announcement(tmp_path, run_id="gdfeed"):
    """Mode asynchrone, modèle 5 fois plus lent que la veillée : des répliques et des sorties sont perdues ; annonce en saison 1."""
    cfg = cfg_for(tmp_path, seasons=2, time__mode="async", time__fast=False, time__sim_hours_per_second=7200)
    cfg["llm"]["providers"]["scripted"]["latency_scale"] = 5.0
    bus = LocalBus()
    pub = IndicatorPublisher(bus, cfg["output"]["runs_dir"], cfg["scenario"]["quota_tolerance"])
    bus.subscribe("events", pub.on_event)
    world = World(cfg, bus, run_id)
    box = {}

    def on_event(ev):
        if ev["type"] == "season_start" and ev["season"] == 1:
            box["loop"].call_soon(world.handle_command, {"type": "announcement", "text": "Ines ment sur ce qu'elle ramene"})

    bus.subscribe("events", on_event)

    async def main():
        box["loop"] = asyncio.get_running_loop()
        await world.run()

    asyncio.run(main())
    return tmp_path / "runs" / run_id / "events.jsonl"


def test_the_main_view_says_clearly_what_was_lost_and_shows_the_announcement(tmp_path):
    events = slow_async_run_with_announcement(tmp_path)
    proc = subprocess.run([GODOT, "--headless", "--path", str(ROOT / "godot"), "-s", "res://tests/main_feed_test.gd", "--",
                           f"--events={events}"], capture_output=True, text=True, timeout=120, encoding="utf-8")
    out = proc.stdout
    assert "SCRIPT ERROR" not in out and "SCRIPT ERROR" not in proc.stderr, out + proc.stderr
    assert "MAINFEEDTEST fails=0" in out, out
    assert proc.returncode == 0
