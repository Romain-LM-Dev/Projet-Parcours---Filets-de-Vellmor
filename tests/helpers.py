"""Outils communs aux tests : configuration rapide, lancement d'une partie, lecture du journal."""
from __future__ import annotations

import asyncio
import json

from filets.bus import LocalBus
from filets.cli import run_once
from filets.config import load_config, normalize
from filets.pipeline import IndicatorPublisher
from filets.world import World


def cfg_for(tmp_path, seasons=3, **over):
    """Configuration de test : sans attente d'affichage, faux LLM sans latence, runs dans `tmp_path`."""
    cfg = load_config(None)
    cfg["output"]["runs_dir"] = str(tmp_path / "runs")
    cfg["time"]["fast"] = True
    cfg["run"]["seasons"] = seasons
    cfg["llm"]["providers"]["scripted"]["latency_scale"] = 0.0
    for k, v in over.items():
        sec, key = k.split("__")
        cfg[sec][key] = v
    return normalize(cfg)


def read_events(tmp_path, run_id):
    with open(tmp_path / "runs" / run_id / "events.jsonl", encoding="utf-8") as f:
        return [json.loads(x) for x in f]


def play(tmp_path, run_id="t", **kw):
    """Joue une partie complète et renvoie ses événements."""
    cfg = kw.pop("cfg", None) or cfg_for(tmp_path, **kw)
    rid = asyncio.run(run_once(cfg, quiet=True, run_id=run_id))
    return read_events(tmp_path, rid)


def make_world(tmp_path, run_id="w", latency_scale=0.0, **over):
    """Monde + bus local + éditeur d'indicateurs, pour piloter une partie à la main dans un test."""
    cfg = cfg_for(tmp_path, **over)
    cfg["llm"]["providers"]["scripted"]["latency_scale"] = latency_scale
    bus = LocalBus()
    pub = IndicatorPublisher(bus, cfg["output"]["runs_dir"], cfg["scenario"]["quota_tolerance"])
    bus.subscribe("events", pub.on_event)
    return World(cfg, bus, run_id), bus, pub
