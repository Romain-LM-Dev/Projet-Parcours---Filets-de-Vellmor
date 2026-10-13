"""Le salon : une partie lancée depuis le menu, validée, jouée, puis une autre."""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from filets.bus import LocalBus
from filets.engine import Engine, GameRequestError, build_game_config, validate_request
from filets.schemas import validate_status
from helpers import cfg_for, read_events


def fisher(**kw):
    base = {"first_name": "Aldric", "hamlet": "Ostrel", "archetype": "taiseux", "experience": 20, "wealth": 500,
            "debt_payment": 0, "kind": "rule", "tier": "auto"}
    return {**base, **kw}


def with_llm_fisher(req, tier="auto"):
    """Un pêcheur à IA : sans lui, aucun fournisseur d'IA n'est nécessaire et rien n'est vérifié."""
    req["population"]["fishers"][0]["kind"] = "llm"
    req["population"]["fishers"][0]["tier"] = tier
    return req


def request(**over):
    req = {"mode": "sync", "seasons": 2, "seed": 7, "communication": "valley", "catches_visible": True,
           "llm": "scripted", "speed": 1.0,
           "population": {"elder": True, "elder_kind": "rule",
                          "fishers": [fisher(), fisher(first_name="Odile", hamlet="Tilque", archetype="beau_parleur"),
                                      fisher(first_name="Rémi", hamlet="Tilque", archetype="nouveau_venu",
                                             debt_payment=120)]}}
    req.update(over)
    return req


# ---------------------------------------------------------------- validation
def test_a_valid_request_has_no_error():
    assert validate_request(request()) == []


@pytest.mark.parametrize("change, fragment", [
    ({"mode": "turbo"}, "mode"),
    ({"seasons": 0}, "saisons"),
    ({"seasons": 500}, "saisons"),
    ({"seasons": "dix"}, "saisons"),
    ({"seed": -1}, "graine"),
    ({"communication": "radio"}, "communication"),
    ({"catches_visible": "oui"}, "prises visibles"),
    ({"llm": "gpt"}, "moteur d'IA"),
    ({"speed": 0}, "vitesse"),
    ({"speed": "vite"}, "vitesse"),
    ({"population": None}, "population"),
    ({"population": {"fishers": []}}, "au moins un"),
    ({"population": {"fishers": [fisher()] * 30}}, "entre 1 et 24"),
    ({"population": {"fishers": [fisher()], "elder_kind": "robot"}}, "ancien"),
])
def test_invalid_requests_are_explained_in_french(change, fragment):
    errs = validate_request(request(**change))
    assert errs and any(fragment in e for e in errs), errs


def test_max_speed_is_accepted():
    assert validate_request(request(speed="max")) == []


def test_build_game_config_applies_the_menu_choices(tmp_path):
    base = cfg_for(tmp_path)
    cfg = build_game_config(base, request(mode="async", seasons=5, seed=99, communication="hamlet",
                                          catches_visible=False))
    assert cfg["time"]["mode"] == "async" and cfg["run"]["seasons"] == 5 and cfg["run"]["seed"] == 99
    assert cfg["scenario"]["communication"] == "hamlet" and cfg["scenario"]["catches_visible"] is False
    assert cfg["population"]["fishers"] == 3 and cfg["lake"]["capacity_resolved"] == pytest.approx(37.5)
    assert cfg["llm"]["tiers"]["grand"]["provider"] == "scripted"
    assert base["population"].get("custom") in (None, [])        # la base du moteur n'est pas modifiée
    assert base["time"]["mode"] == "async" and base["run"]["seasons"] == 3
    cfg = build_game_config(base, request(llm="ollama"))
    assert cfg["llm"]["tiers"]["grand"] == {"provider": "ollama", "model": "qwen2.5:7b"}
    assert cfg["llm"]["tiers"]["petit"]["model"] == "qwen2.5:1.5b"
    with pytest.raises(GameRequestError, match="saisons"):
        build_game_config(base, request(seasons=0))


# ---------------------------------------------------------------- le salon, de bout en bout (bus local)
async def until(cond, timeout=30.0):
    t0 = time.monotonic()
    while not cond():
        if time.monotonic() - t0 > timeout:
            raise AssertionError("délai dépassé")
        await asyncio.sleep(0.02)


def test_lobby_plays_a_game_then_another(tmp_path):
    async def scenario():
        cfg = cfg_for(tmp_path)
        bus = LocalBus()
        statuses = []
        bus.subscribe("status", statuses.append)
        eng = Engine(cfg, bus, quiet=True)
        task = asyncio.create_task(eng.serve())
        await until(lambda: statuses and statuses[-1]["state"] == "idle")
        assert statuses[-1]["lobby"] is True and statuses[-1]["error"] is None

        bus.send_command({"type": "start_game", "config": request(speed=4)})
        await until(lambda: statuses[-1]["state"] == "ended")
        first = statuses[-1]["run_id"]
        assert statuses[-1]["end_reason"] == "completed" and statuses[-1]["lobby"] is True
        states = []
        for s in statuses:
            if not states or states[-1] != s["state"]:
                states.append(s["state"])
        assert states == ["idle", "starting", "running", "ended"]
        assert any(s["state"] == "running" and s["speed"] == 4.0 for s in statuses)

        # une deuxième partie, autre mode et autre composition, sans repasser par « new_game »
        second_req = request(mode="async", seasons=1)
        second_req["population"]["fishers"] = second_req["population"]["fishers"][:2]
        bus.send_command({"type": "start_game", "config": second_req})
        await until(lambda: statuses[-1]["state"] == "ended" and statuses[-1]["run_id"] != first)
        second = statuses[-1]["run_id"]

        bus.send_command({"type": "new_game"})
        await until(lambda: statuses[-1]["state"] == "idle")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        eng.close()
        return first, second, statuses

    first, second, statuses = asyncio.run(scenario())
    for s in statuses:
        assert validate_status(s) == [], s
    ev1, ev2 = read_events(tmp_path, first), read_events(tmp_path, second)
    a1, a2 = ev1[0]["payload"], ev2[0]["payload"]
    assert a1["mode"] == "sync" and a1["seasons"] == 2 and a1["seed"] == 7
    assert [a["name"] for a in a1["agents"] if a["role"] == "pecheur"] == \
           ["Aldric d’Ostrel", "Odile de Tilque", "Rémi de Tilque"]
    assert a1["lake"]["capacity"] == pytest.approx(37.5)
    assert a2["mode"] == "async" and a2["seasons"] == 1 and len([a for a in a2["agents"] if a["role"] == "pecheur"]) == 2
    assert a2["lake"]["capacity"] == pytest.approx(25.0)
    assert ev1[-1]["payload"]["reason"] == "completed" and ev2[-1]["payload"]["reason"] == "completed"
    # l'identifiant d'agent et le monde sont ceux de la partie, pas de la précédente
    assert {e["run_id"] for e in ev2} == {second}


def test_lobby_reports_an_invalid_request_and_stays_open(tmp_path):
    async def scenario():
        bus = LocalBus()
        statuses = []
        bus.subscribe("status", statuses.append)
        eng = Engine(cfg_for(tmp_path), bus, quiet=True)
        task = asyncio.create_task(eng.serve())
        await until(lambda: statuses and statuses[-1]["state"] == "idle")
        bus.send_command({"type": "start_game", "config": request(seasons=0)})
        await until(lambda: statuses[-1]["state"] == "idle" and statuses[-1]["error"])
        error = statuses[-1]["error"]
        # une demande correcte efface l'erreur et se joue
        bus.send_command({"type": "start_game", "config": request(seasons=1)})
        await until(lambda: statuses[-1]["state"] == "ended")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return error, statuses

    error, statuses = asyncio.run(scenario())
    assert "saisons" in error
    assert statuses[-1]["error"] is None


def test_lobby_ignores_commands_that_need_a_running_game(tmp_path):
    async def scenario():
        bus = LocalBus()
        statuses = []
        bus.subscribe("status", statuses.append)
        eng = Engine(cfg_for(tmp_path), bus, quiet=True)
        task = asyncio.create_task(eng.serve())
        await until(lambda: statuses and statuses[-1]["state"] == "idle")
        for cmd in ({"type": "pause"}, {"type": "drought"}, {"type": "stop"}, {"type": "set_speed", "value": 2}):
            bus.send_command(cmd)
        await asyncio.sleep(0.5)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return statuses

    statuses = asyncio.run(scenario())
    assert {s["state"] for s in statuses} == {"idle"}


def test_double_start_does_not_launch_two_games(tmp_path):
    async def scenario():
        bus = LocalBus()
        statuses, started = [], []
        bus.subscribe("status", statuses.append)
        bus.subscribe("events", lambda e: e["type"] == "run_start" and started.append(e["run_id"]))
        eng = Engine(cfg_for(tmp_path), bus, quiet=True)
        task = asyncio.create_task(eng.serve())
        await until(lambda: statuses and statuses[-1]["state"] == "idle")
        for _ in range(3):                               # clics répétés sur « Démarrer »
            bus.send_command({"type": "start_game", "config": request(seasons=1)})
        await until(lambda: statuses[-1]["state"] == "ended")
        await asyncio.sleep(0.5)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return started

    assert len(asyncio.run(scenario())) == 1


def test_lobby_refuses_unreachable_ollama_with_a_clear_message(tmp_path):
    async def scenario():
        cfg = cfg_for(tmp_path)
        cfg["llm"]["providers"]["ollama"]["base_url"] = "http://127.0.0.1:9/v1"       # rien n'écoute sur ce port
        bus = LocalBus()
        statuses = []
        bus.subscribe("status", statuses.append)
        eng = Engine(cfg, bus, quiet=True)
        task = asyncio.create_task(eng.serve())
        await until(lambda: statuses and statuses[-1]["state"] == "idle")
        bus.send_command({"type": "start_game", "config": with_llm_fisher(request(llm="ollama"))})
        await until(lambda: statuses[-1]["state"] == "idle" and statuses[-1]["error"])
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return statuses[-1]["error"]

    error = asyncio.run(scenario())
    assert "Ollama" in error and "ne répond pas" in error


def test_lobby_refuses_a_missing_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    async def scenario():
        bus = LocalBus()
        statuses = []
        bus.subscribe("status", statuses.append)
        eng = Engine(cfg_for(tmp_path), bus, quiet=True)
        task = asyncio.create_task(eng.serve())
        await until(lambda: statuses and statuses[-1]["state"] == "idle")
        bus.send_command({"type": "start_game", "config": with_llm_fisher(request(llm="groq"))})
        await until(lambda: statuses[-1]["state"] == "idle" and statuses[-1]["error"])
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return statuses[-1]["error"]

    assert "GROQ_API_KEY" in asyncio.run(scenario())


def test_player_can_pause_and_stop_a_lobby_game(tmp_path):
    async def scenario():
        cfg = cfg_for(tmp_path)
        cfg["time"]["fast"] = False
        cfg["time"]["sim_hours_per_second"] = 720
        bus = LocalBus()
        statuses = []
        bus.subscribe("status", statuses.append)
        eng = Engine(cfg, bus, quiet=True)
        task = asyncio.create_task(eng.serve())
        await until(lambda: statuses and statuses[-1]["state"] == "idle")
        bus.send_command({"type": "start_game", "config": request(seasons=5)})
        await until(lambda: statuses[-1]["state"] == "running" and statuses[-1]["season"] >= 1)
        bus.send_command({"type": "pause"})
        await until(lambda: statuses[-1]["state"] == "paused")
        bus.send_command({"type": "stop"})                # on peut arrêter une partie en pause
        await until(lambda: statuses[-1]["state"] == "ended")
        reason = statuses[-1]["end_reason"]
        bus.send_command({"type": "new_game"})
        await until(lambda: statuses[-1]["state"] == "idle")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return reason

    assert asyncio.run(scenario()) == "stop"


def test_idle_and_ended_status_carry_the_catalog_but_running_does_not(tmp_path):
    async def scenario():
        bus = LocalBus()
        statuses = []
        bus.subscribe("status", statuses.append)
        eng = Engine(cfg_for(tmp_path), bus, quiet=True, default_llm="ollama")
        task = asyncio.create_task(eng.serve())
        await until(lambda: statuses and statuses[-1]["state"] == "idle")
        bus.send_command({"type": "start_game", "config": request(seasons=1)})
        await until(lambda: statuses[-1]["state"] == "ended")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return statuses

    statuses = asyncio.run(scenario())
    for s in statuses:
        assert validate_status(s) == [], s
        if s["state"] == "idle":
            assert "catalog" in s
        if s["state"] in ("starting", "running", "paused"):
            assert "catalog" not in s, s["state"]        # pendant la partie, l'état reste léger
    assert statuses[-1]["state"] == "ended" and "catalog" in statuses[-1]      # le menu de la partie suivante en dépend
    assert statuses[0]["catalog"]["defaults"]["llm"] == "ollama"          # l'option passée au lancement du moteur
    assert len(statuses[0]["catalog"]["base_population"]) == 8
