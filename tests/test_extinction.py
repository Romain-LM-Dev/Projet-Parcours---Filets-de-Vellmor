"""Un lac à 0 ne se repeuple jamais (la croissance logistique part du stock) : la partie s'arrête dès le dernier poisson pêché,
même en pleine saison, et le dit (raison « extinction »). Le réglage `run.stop_on_extinction` permet de continuer quand même.
"""
from __future__ import annotations

import asyncio

import pytest

from filets.bus import LocalBus
from filets.engine import Engine, build_game_config, validate_request
from filets.lake import EXTINCT_BELOW, Lake
from filets.schemas import validate_status
from helpers import cfg_for, make_world, play, read_events
from test_engine import request, until


def kinds(events, kind):
    return [e for e in events if e["type"] == kind]


def tiny_lake(tmp_path, seasons=6, mode="sync", **over):
    """Huit pêcheurs sur un lac de 15 t : les prises demandées le vident dès la première saison."""
    return cfg_for(tmp_path, seasons=seasons, time__mode=mode, lake__capacity=15.0, **over)


# ---------------------------------------------------------------- le lac
def test_a_lake_is_extinct_below_fifty_kilos():
    lake = Lake(100.0, 1.0, 1.0, 0.05, 0.1)
    assert not lake.is_extinct()
    lake.stock = EXTINCT_BELOW + 0.01
    assert not lake.is_extinct()
    lake.stock = EXTINCT_BELOW - 0.01
    assert lake.is_extinct()
    lake.stock = 0.0
    assert lake.is_extinct() and lake.regrow() == 0.0 and lake.stock == 0.0        # et il ne se refait jamais


def test_the_empty_lake_is_also_collapsed_but_the_two_are_different_things():
    lake = Lake(100.0, 1.0, 1.0, 0.05, 0.1)
    lake.stock = 4.0
    assert lake.is_collapsed() and not lake.is_extinct()          # 4 % : effondré, pas éteint (il se refait, lentement)


# ---------------------------------------------------------------- la partie
@pytest.mark.parametrize("mode", ["sync", "async"])
def test_the_game_stops_as_soon_as_the_lake_is_empty(tmp_path, mode):
    cfg = tiny_lake(tmp_path, mode=mode, time__fast=False, time__sim_hours_per_second=7200) if mode == "async" else tiny_lake(tmp_path)
    events = play(tmp_path, f"ext-{mode}", cfg=cfg)
    end = kinds(events, "run_end")
    assert len(end) == 1 and end[0]["payload"]["reason"] == "extinction"
    assert end[0]["payload"]["seasons_completed"] < 6                        # elle n'est pas allée au bout
    last_stock = kinds(events, "lake_update")[-1]["payload"]["stock"]
    assert last_stock < EXTINCT_BELOW                                        # elle s'arrête sur le lac vide
    assert events[-1]["type"] == "run_end"                                   # et rien ne se passe après
    # aucune saison n'a commencé après l'extinction
    t_empty = next(e["seq"] for e in kinds(events, "lake_update") if e["payload"]["stock"] < EXTINCT_BELOW)
    assert not [e for e in kinds(events, "season_start") if e["seq"] > t_empty]


def test_the_stop_is_immediate_not_at_the_end_of_the_season(tmp_path):
    """En synchrone, la pêche vide le lac au jour 1 ; ni veillée ni bilan n'ont lieu après."""
    events = play(tmp_path, "ext-now", cfg=tiny_lake(tmp_path))
    assert not kinds(events, "assembly_start") and not kinds(events, "season_end")
    assert kinds(events, "season_start")[-1]["season"] == 1


def test_the_game_goes_on_when_the_player_unticks_the_stop(tmp_path):
    cfg = tiny_lake(tmp_path, seasons=3, run__stop_on_extinction=False)
    events = play(tmp_path, "ext-off", cfg=cfg)
    assert kinds(events, "run_end")[0]["payload"]["reason"] == "completed"
    assert len(kinds(events, "season_end")) == 3                              # toutes les saisons, sur un lac mort
    assert kinds(events, "lake_update")[-1]["payload"]["stock"] < EXTINCT_BELOW


def test_a_healthy_lake_is_never_stopped(tmp_path):
    events = play(tmp_path, "ext-ok", seasons=3)
    assert kinds(events, "run_end")[0]["payload"]["reason"] == "completed" and len(kinds(events, "season_end")) == 3


def test_a_drought_that_dries_the_lake_ends_the_game(tmp_path):
    world, bus, _ = make_world(tmp_path, "ext-dry", seasons=4, time__mode="sync", time__fast=False, time__sim_hours_per_second=7200)

    def dry(ev):
        if ev["type"] == "season_start" and ev["season"] == 2:
            world.handle_command({"type": "drought", "factor": 0.0})

    bus.subscribe("events", dry)
    asyncio.run(world.run())
    events = read_events(tmp_path, "ext-dry")
    assert kinds(events, "run_end")[0]["payload"]["reason"] == "extinction"
    assert kinds(events, "season_start")[-1]["season"] == 2


def test_a_user_stop_keeps_its_own_reason(tmp_path):
    world, bus, _ = make_world(tmp_path, "ext-user", seasons=4, time__mode="sync", time__fast=False, time__sim_hours_per_second=7200)

    def stop(ev):
        if ev["type"] == "season_start" and ev["season"] == 2:
            world.handle_command({"type": "stop"})

    bus.subscribe("events", stop)
    asyncio.run(world.run())
    assert kinds(read_events(tmp_path, "ext-user"), "run_end")[0]["payload"]["reason"] == "stop"


# ---------------------------------------------------------------- la demande du menu
@pytest.mark.parametrize("value", ["oui", 1, None, "false"])
def test_stop_on_extinction_must_be_a_boolean(value):
    errs = validate_request(request(stop_on_extinction=value))
    assert errs and any("lac est vide" in e for e in errs), errs


def test_stop_on_extinction_is_accepted_and_applied(tmp_path):
    base = cfg_for(tmp_path)
    assert base["run"]["stop_on_extinction"] is True                              # actif par défaut
    assert build_game_config(base, request())["run"]["stop_on_extinction"] is True
    assert build_game_config(base, request(stop_on_extinction=False))["run"]["stop_on_extinction"] is False
    assert build_game_config(base, request(stop_on_extinction=True))["run"]["stop_on_extinction"] is True


def test_the_lobby_reports_the_extinction_in_the_final_status(tmp_path):
    async def scenario():
        bus = LocalBus()
        statuses = []
        bus.subscribe("status", statuses.append)
        eng = Engine(cfg_for(tmp_path), bus, quiet=True)
        task = asyncio.create_task(eng.serve())
        await until(lambda: statuses and statuses[-1]["state"] == "idle")
        bus.send_command({"type": "start_game", "config": request(speed="max", seasons=5, lake={"capacity": 12.0})})
        await until(lambda: statuses[-1]["state"] == "ended")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        eng.close()
        return statuses

    statuses = asyncio.run(scenario())
    assert statuses[-1]["end_reason"] == "extinction"
    assert all(validate_status(s) == [] for s in statuses)
    events = read_events(tmp_path, statuses[-1]["run_id"])
    assert kinds(events, "run_end")[0]["payload"]["reason"] == "extinction"
