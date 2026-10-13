"""Les réglages du menu de début de partie qui touchent le lac et la réflexion des IA :
limite du stock du lac, réflexion rapide ou complète, tours de parole, moteurs d'IA et vitesses conseillées.
"""
from __future__ import annotations

import asyncio

import pytest

from filets.bus import LocalBus
from filets.catalog import LIMITS, LLM_OPTIONS, REFLECTIONS, SPEEDS, build_catalog
from filets.config import load_config
from filets.engine import Engine, build_game_config, validate_request
from filets.indicators import IndicatorEngine
from filets.schemas import validate_status
from filets.world import World
from helpers import cfg_for, play, read_events
from test_engine import fisher, request, until


# ---------------------------------------------------------------- le catalogue
def test_catalog_describes_the_new_options():
    cat = build_catalog(load_config(None))
    assert cat["limits"]["capacity"] == [10, 1000] and cat["limits"]["assembly_rounds"] == [1, 3]
    assert [r["id"] for r in cat["reflections"]] == ["rapide", "complete"]
    d = cat["defaults"]
    assert d["reflection"] == "rapide" and d["assembly_rounds"] == 2 and d["capacity"] is None
    assert d["capacity_per_fisher"] == 12.5 and d["boat_capacity"] == 10.0 and d["growth_rate"] == 1.0
    ids = [o["id"] for o in cat["llm_options"]]
    assert ids == ["scripted", "ollama_fast", "ollama", "groq"]
    assert all("config" not in o for o in cat["llm_options"])               # un détail d'implémentation, pas pour le menu
    assert all(o["async_speed"] in SPEEDS for o in cat["llm_options"])      # une vitesse que le menu sait afficher
    assert {0.0625, 0.125, 0.25} <= set(cat["speeds"])                       # les vitesses lentes existent


def test_slower_engines_are_advised_slower_worlds():
    speed = {o["id"]: o["async_speed"] for o in LLM_OPTIONS}
    assert speed["scripted"] == 1.0
    assert speed["ollama"] < speed["ollama_fast"] < speed["groq"] <= speed["scripted"]


def test_the_fast_preset_fits_the_small_graphics_card():
    """3B + 1,5B tiennent ensemble dans 6 Go : plus d'échange de modèle, qui coûtait de 10 à 30 s à chaque fois."""
    preset = load_config("config/ollama_fast.yaml")["llm"]
    assert preset["tiers"]["grand"] == {"provider": "ollama", "model": "qwen2.5:3b"}
    assert preset["tiers"]["petit"] == {"provider": "ollama", "model": "qwen2.5:1.5b"}
    assert preset["reflection"] == "rapide"
    assert load_config("config/ollama.yaml")["llm"]["tiers"]["grand"]["model"] == "qwen2.5:7b"


# ---------------------------------------------------------------- la demande
@pytest.mark.parametrize("change, fragment", [
    ({"reflection": "profonde"}, "réflexion"),
    ({"reflection": None}, "réflexion"),
    ({"assembly_rounds": 0}, "tours de parole"),
    ({"assembly_rounds": 4}, "tours de parole"),
    ({"assembly_rounds": "2"}, "tours de parole"),
    ({"assembly_rounds": True}, "tours de parole"),
    ({"lake": {"capacity": 9}}, "capacité du lac"),
    ({"lake": {"capacity": 1001}}, "capacité du lac"),
    ({"lake": {"capacity": "grand"}}, "capacité du lac"),
    ({"lake": {"capacity": True}}, "capacité du lac"),
    ({"lake": 100}, "capacité du lac"),
])
def test_invalid_lake_and_reflection_choices_are_explained(change, fragment):
    errs = validate_request(request(**change))
    assert errs and any(fragment in e for e in errs), errs


@pytest.mark.parametrize("change", [
    {}, {"reflection": "rapide"}, {"reflection": "complete"}, {"assembly_rounds": 1}, {"assembly_rounds": 3},
    {"lake": {"capacity": None}}, {"lake": {"capacity": 10}}, {"lake": {"capacity": 1000}}, {"lake": {"capacity": 87.5}},
    {"lake": {}}, {"llm": "ollama_fast"}, {"speed": 0.0625},
])
def test_valid_choices_are_accepted(change):
    assert validate_request(request(**change)) == []


def test_the_lake_limit_chosen_in_the_menu_is_the_one_played(tmp_path):
    base = cfg_for(tmp_path)
    auto = build_game_config(base, request())
    assert auto["lake"]["capacity_resolved"] == pytest.approx(12.5 * 3)       # automatique : 12,5 t par pêcheur
    for chosen in (10, 60.0, 140, 1000):
        cfg = build_game_config(base, request(lake={"capacity": chosen}))
        assert cfg["lake"]["capacity_resolved"] == pytest.approx(float(chosen))
    explicit_auto = build_game_config(base, request(lake={"capacity": None}))
    assert explicit_auto["lake"]["capacity_resolved"] == pytest.approx(12.5 * 3)
    assert base["lake"]["capacity"] == "auto"                                  # la base du moteur n'est pas modifiée


def test_reflection_and_rounds_are_applied_and_the_menu_choice_beats_the_preset(tmp_path):
    base = cfg_for(tmp_path)
    assert base["llm"]["reflection"] == "complete"                             # profil de référence des expériences en ligne de commande
    cfg = build_game_config(base, request(reflection="rapide", assembly_rounds=3))
    assert cfg["llm"]["reflection"] == "rapide" and cfg["scenario"]["assembly_rounds"] == 3
    fast = build_game_config(base, request(llm="ollama_fast", reflection="complete"))
    assert fast["llm"]["reflection"] == "complete"                             # le choix explicite l'emporte sur le moteur d'IA
    assert fast["llm"]["tiers"]["grand"]["model"] == "qwen2.5:3b"
    default_rounds = build_game_config(base, request())
    assert default_rounds["scenario"]["assembly_rounds"] == base["scenario"]["assembly_rounds"]


def play_with_capacity(tmp_path, run_id, capacity, seasons=3):
    cfg = build_game_config(cfg_for(tmp_path, seasons=seasons),
                            request(seasons=seasons, speed="max", lake={"capacity": capacity}, mode="sync"))
    cfg["time"]["fast"] = True
    return cfg, play(tmp_path, run_id=run_id, cfg=cfg)


@pytest.mark.parametrize("capacity", [30, 140, 600])
def test_the_lake_never_exceeds_the_chosen_limit_and_indicators_stay_percentages(tmp_path, capacity):
    cfg, events = play_with_capacity(tmp_path, f"cap{capacity}", capacity)
    start = events[0]["payload"]
    assert start["lake"]["capacity"] == pytest.approx(capacity)
    assert start["lake"]["stock"] == pytest.approx(capacity * cfg["lake"]["initial_ratio"])     # le lac part plein
    assert start["lake"]["sustainable_yield"] == pytest.approx(capacity / 4.0)                 # r·K/4, avec r = 1
    stocks = [e["payload"]["stock"] for e in events if e["type"] == "lake_update"]
    assert stocks and max(stocks) <= capacity + 1e-6 and min(stocks) >= 0
    eng = IndicatorEngine(0.5)
    for e in events:
        eng.ingest(e)
    assert 0.0 <= eng.last_values["stock_ratio"] <= 1.0                       # jamais de « 10000 % »
    assert eng.last_values["capacity"] == pytest.approx(capacity)


def test_a_small_lake_collapses_where_a_large_one_does_not(tmp_path):
    """Le réglage a un effet de jeu réel : mêmes pêcheurs, même graine, seule la limite du stock change."""
    final = {}
    for capacity in (20, 400):
        _, events = play_with_capacity(tmp_path, f"effect{capacity}", capacity, seasons=4)
        eng = IndicatorEngine(0.5)
        for e in events:
            eng.ingest(e)
        final[capacity] = eng.last_values["stock_ratio"]
    assert final[400] > final[20]


# ---------------------------------------------------------------- l'état publié aide l'interface à conseiller la vitesse
def test_status_carries_the_advised_speed_only_when_a_real_ai_plays(tmp_path):
    cfg = cfg_for(tmp_path, seasons=1)
    scripted = World(cfg, LocalBus(), "adv-a", record=False)
    assert scripted.status_payload()["advised_speed"] is None
    real = World(cfg, LocalBus(), "adv-b", record=False, advised_speed=0.25)
    payload = real.status_payload("running")
    assert payload["advised_speed"] == 0.25
    assert validate_status({**payload, "engine_id": "x", "wall_clock": "2026-01-01T00:00:00.000+00:00"}) == []
    assert validate_status({**scripted.status_payload("running"), "engine_id": "x",
                            "wall_clock": "2026-01-01T00:00:00.000+00:00"}) == []


def test_the_lobby_publishes_the_advised_speed_of_the_chosen_engine(tmp_path):
    """Une partie lancée depuis le menu avec le faux LLM ne conseille rien ; le salon n'invente pas de conseil."""
    async def scenario():
        bus = LocalBus()
        statuses = []
        bus.subscribe("status", statuses.append)
        eng = Engine(cfg_for(tmp_path), bus, quiet=True)
        task = asyncio.create_task(eng.serve())
        await until(lambda: statuses and statuses[-1]["state"] == "idle")
        bus.send_command({"type": "start_game", "config": request(speed=8, seasons=1, lake={"capacity": 80})})
        await until(lambda: statuses[-1]["state"] == "ended")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        eng.close()
        return statuses

    statuses = asyncio.run(scenario())
    running = [s for s in statuses if s["state"] == "running"]
    assert running and all(s["advised_speed"] is None and s["ai"] in ([], ["scripted"]) for s in running)
    assert all(validate_status(s) == [] for s in statuses)
    run_id = statuses[-1]["run_id"]
    assert read_events(tmp_path, run_id)[0]["payload"]["lake"]["capacity"] == pytest.approx(80.0)


# ---------------------------------------------------------------- le taux de repeuplement du lac
def test_catalog_describes_the_regrowth_rate_and_the_stop_on_empty():
    cat = build_catalog(load_config(None))
    assert cat["limits"]["growth_rate"] == [0.1, 2.0]
    assert cat["defaults"]["growth_rate"] == 1.0 and cat["defaults"]["stop_on_extinction"] is True


@pytest.mark.parametrize("rate", [0.05, 0.0, -1.0, 2.5, "vite", True, [1.0]])
def test_invalid_regrowth_rates_are_explained(rate):
    errs = validate_request(request(lake={"growth_rate": rate}))
    assert errs and any("taux de repeuplement" in e for e in errs), errs


@pytest.mark.parametrize("rate", [None, 0.1, 0.35, 1, 1.0, 2.0])
def test_valid_regrowth_rates_are_accepted(rate):
    assert validate_request(request(lake={"growth_rate": rate})) == []
    assert validate_request(request(lake={"capacity": 80, "growth_rate": rate})) == []


def test_the_chosen_regrowth_rate_is_the_one_applied(tmp_path):
    base = cfg_for(tmp_path)
    assert build_game_config(base, request())["lake"]["growth_rate"] == 1.0
    cfg = build_game_config(base, request(lake={"capacity": 90, "growth_rate": 0.4}))
    assert cfg["lake"]["growth_rate"] == 0.4 and cfg["lake"]["capacity_resolved"] == 90.0
    only_rate = build_game_config(base, request(lake={"growth_rate": 1.5}))
    assert only_rate["lake"]["growth_rate"] == 1.5 and only_rate["lake"]["capacity_resolved"] == pytest.approx(12.5 * 3)
    assert base["lake"]["growth_rate"] == 1.0                                  # la base du moteur n'est pas modifiée


def test_the_played_lake_uses_the_regrowth_rate_and_the_sustainable_yield_follows(tmp_path):
    cfg = build_game_config(cfg_for(tmp_path, seasons=1), request(seasons=1, speed="max", lake={"capacity": 80, "growth_rate": 0.4}))
    events = play(tmp_path, run_id="rate1", cfg=cfg)
    lake = events[0]["payload"]["lake"]
    assert lake["growth_rate"] == 0.4 and lake["sustainable_yield"] == pytest.approx(0.4 * 80 / 4)


def test_a_slow_lake_regrows_in_proportion_to_its_rate(tmp_path):
    """Mêmes pêcheurs, même graine : seule r change, donc le repeuplement de la saison 1 est proportionnel à r (tant que le lac
    n'est pas rempli jusqu'à sa capacité, où il s'arrête)."""
    gains = {}
    for rate in (0.3, 0.9):
        cfg = build_game_config(cfg_for(tmp_path, seasons=1), request(seasons=1, speed="max", lake={"capacity": 100, "growth_rate": rate}))
        events = play(tmp_path, run_id=f"rate-{rate}", cfg=cfg)
        regrowth = [e["payload"] for e in events if e["type"] == "lake_update" and e["payload"]["cause"] == "regrowth"]
        assert len(regrowth) == 1
        gains[rate] = regrowth[0]["delta"]
    assert 0 < gains[0.3] < gains[0.9]
    assert gains[0.9] / gains[0.3] == pytest.approx(0.9 / 0.3, rel=0.02)
