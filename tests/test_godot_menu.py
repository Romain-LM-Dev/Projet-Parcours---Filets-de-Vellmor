"""Contrat entre le menu Godot et le moteur : ce que le menu envoie, le moteur l'accepte et le joue.

Lance Godot sans fenêtre sur `godot/tests/menu_test.gd` (ignoré si Godot est introuvable : variable GODOT_PATH,
ou l'emplacement habituel). Le script manipule le menu comme le ferait le joueur et imprime la demande finale.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from filets.catalog import build_catalog
from filets.config import ROOT, load_config
from filets.engine import build_game_config, validate_request
from helpers import cfg_for, read_events

CANDIDATES = [os.environ.get("GODOT_PATH"), r"C:\Godot_v4.7.2-stable_win64.exe\Godot_v4.7.2-stable_win64.exe",
              shutil.which("godot")]
GODOT = next((c for c in CANDIDATES if c and os.path.exists(c)), None)

pytestmark = pytest.mark.skipif(GODOT is None, reason="Godot introuvable (définir GODOT_PATH)")


def run_menu_test(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps(build_catalog(load_config(None))), encoding="utf-8")
    proc = subprocess.run([GODOT, "--headless", "--path", str(ROOT / "godot"), "-s", "res://tests/menu_test.gd",
                           "--", f"--catalog={catalog}"], capture_output=True, text=True, timeout=120, encoding="utf-8")
    return proc


def menu_request(tmp_path):
    """Fait jouer le script de test au menu et renvoie la demande finale qu'il a construite."""
    proc = run_menu_test(tmp_path)
    out = proc.stdout
    assert "SCRIPT ERROR" not in out and "SCRIPT ERROR" not in proc.stderr, out + proc.stderr
    assert "MENUTEST fails=0" in out, out
    assert proc.returncode == 0
    cfg_line = next(line for line in out.splitlines() if line.startswith("CONFIG:"))
    return json.loads(cfg_line[len("CONFIG:"):])


def test_menu_builds_valid_requests_and_behaves(tmp_path):
    request = menu_request(tmp_path)
    assert validate_request(request) == [], validate_request(request)
    assert len(request["population"]["fishers"]) == 9


def test_the_request_built_by_the_menu_is_played_by_the_engine(tmp_path):
    from helpers import play

    request = menu_request(tmp_path)
    request.update({"llm": "scripted", "speed": "max", "seasons": 2})      # rapide, sans IA ni attente
    cfg = build_game_config(cfg_for(tmp_path), request)
    events = play(tmp_path, cfg=cfg)
    start = events[0]["payload"]
    fishers = [a for a in start["agents"] if a["role"] == "pecheur"]
    want = request["population"]["fishers"]
    assert [a["hamlet"] for a in fishers] == [f["hamlet"] for f in want]
    assert [a["kind"] for a in fishers] == [f["kind"] for f in want]
    assert [a["archetype"] for a in fishers] == [f["archetype"] for f in want]
    assert request["lake"]["capacity"] == 140.0                         # la limite du stock choisie dans le menu...
    assert start["lake"]["capacity"] == pytest.approx(140.0)            # ...est celle du lac joué (et non 12,5 t par pêcheur)
    assert request["lake"]["growth_rate"] == pytest.approx(0.8) and request["stop_on_extinction"] is True
    assert start["lake"]["growth_rate"] == pytest.approx(0.8)           # le taux de repeuplement du menu est celui du lac
    assert start["lake"]["sustainable_yield"] == pytest.approx(0.8 * 140.0 / 4.0)
    assert start["scenario"]["assembly_rounds"] == 3
    assert cfg["llm"]["reflection"] == "complete"
    assert max(e["payload"]["stock"] for e in events if e["type"] == "lake_update") <= 140.0 + 1e-6
    assert sum(1 for e in events if e["type"] == "season_end") == 2
