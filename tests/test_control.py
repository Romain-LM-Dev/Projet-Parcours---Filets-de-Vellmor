"""Pilotage d'une partie : pause, vitesse, mode synchrone/asynchrone, arrêt."""
from __future__ import annotations

import asyncio
import time

import pytest

from filets.cli import verify
from filets.clock import SimClock
from filets.control import GameControl, StopRun
from filets.schemas import validate_status
from helpers import make_world, read_events

# 30 jours simulés par seconde réelle : une saison dure environ une seconde, de quoi piloter sans attendre.
SLOW = dict(time__fast=False, time__sim_hours_per_second=720)


async def drive(world, script):
    """Lance la partie et exécute `script(world)` en parallèle ; renvoie la durée réelle de la partie."""
    t0 = time.monotonic()
    runner = asyncio.create_task(world.run())
    try:
        await script(world)
        await asyncio.wait_for(runner, 60)
    finally:
        if not runner.done():
            runner.cancel()
    return time.monotonic() - t0


def collect(bus):
    seen = {"events": [], "status": []}
    bus.subscribe("events", seen["events"].append)
    bus.subscribe("status", seen["status"].append)
    return seen


def types(events, kind):
    return [e for e in events if e["type"] == kind]


# ---------------------------------------------------------------- GameControl seul
def test_sleep_follows_speed_and_stops_during_pause():
    async def scenario():
        clock = SimClock(30, 3, 20, False)
        ctl = GameControl(clock, "sync")
        t = time.monotonic()
        await ctl.sleep(0.3)
        normal = time.monotonic() - t
        clock.set_speed(6)
        t = time.monotonic()
        await ctl.sleep(0.3)
        fast = time.monotonic() - t
        # pause en cours d'attente : l'attente ne progresse pas, puis reprend
        clock.set_speed(1)
        task = asyncio.create_task(ctl.sleep(0.3))
        await asyncio.sleep(0.1)
        ctl.pause()
        await asyncio.sleep(0.5)
        assert not task.done()
        ctl.resume()
        t = time.monotonic()
        await task
        rest = time.monotonic() - t
        return normal, fast, rest

    normal, fast, rest = asyncio.run(scenario())
    assert 0.25 < normal < 0.5
    assert fast < 0.15
    assert 0.1 < rest < 0.4          # il restait environ 0,2 s d'attente


def test_checkpoint_blocks_while_paused_and_raises_on_stop():
    async def scenario():
        ctl = GameControl(SimClock(30, 3, 20, False), "sync")
        assert await ctl.checkpoint() is False
        ctl.pause()
        waiter = asyncio.create_task(ctl.checkpoint())
        await asyncio.sleep(0.05)
        assert not waiter.done()
        ctl.request_stop()                # l'arrêt libère aussi ce qui attendait la fin de la pause
        with pytest.raises(StopRun):
            await waiter
        with pytest.raises(StopRun):
            await ctl.checkpoint()

    asyncio.run(scenario())


def test_clock_excludes_paused_time_from_processed_at():
    clock = SimClock(30, 3, 20, False)
    time.sleep(0.05)
    before = clock.wall_elapsed()
    clock.pause()
    time.sleep(0.3)
    frozen = clock.wall_elapsed()
    assert frozen == pytest.approx(before, abs=0.02)         # figé pendant la pause
    clock.resume()
    time.sleep(0.05)
    assert clock.wall_elapsed() - before == pytest.approx(0.05, abs=0.04)


def test_speed_is_clamped():
    clock = SimClock(30, 3, 20, False)
    assert clock.set_speed(1000) == 64.0
    assert clock.set_speed(0) == 0.05


# ---------------------------------------------------------------- pause
def test_pause_freezes_the_world_and_resume_continues(tmp_path):
    world, bus, _ = make_world(tmp_path, "pause", seasons=2, time__mode="sync", **SLOW)
    seen = collect(bus)
    report = {}

    async def script(w):
        while not types(seen["events"], "catch"):
            await asyncio.sleep(0.01)
        w.handle_command({"type": "pause"})
        await asyncio.sleep(0.15)
        report["n_frozen"] = len(seen["events"])
        report["clock"] = w.clock.now()
        report["state"] = seen["status"][-1]["state"]
        await asyncio.sleep(0.7)
        report["n_after_wait"] = len(seen["events"])
        report["clock_after_wait"] = w.clock.now()
        w.handle_command({"type": "resume"})

    elapsed = asyncio.run(drive(world, script))
    assert report["state"] == "paused"
    assert report["n_after_wait"] == report["n_frozen"], "aucun événement ne doit sortir pendant la pause"
    assert report["clock_after_wait"] == report["clock"]
    events = read_events(tmp_path, "pause")
    assert len(types(events, "season_end")) == 2
    inj = [e["payload"]["injection_type"] for e in types(events, "injection")]
    assert inj == ["pause", "resume"]
    assert verify("pause", world.cfg)
    # la pause (≈ 0,85 s) est retirée du temps de jeu écoulé
    assert events[-1]["processed_at"] <= world.clock.wall_elapsed() + 1e-6
    assert world.clock._paused_total == pytest.approx(0.85, abs=0.15)
    assert world.clock.wall_elapsed() == pytest.approx(
        time.monotonic() - world.clock._wall0 - world.clock._paused_total, abs=0.05)
    assert elapsed > 0.85


def test_pause_does_not_publish_results_of_calls_already_in_flight(tmp_path, monkeypatch):
    """Un appel LLM déjà parti répond pendant la pause : sa réponse attend la reprise pour entrer dans le monde."""
    from filets.scripted import ScriptedClient

    state = {}
    real = ScriptedClient.complete

    async def slow_complete(self, model, messages, hint, tier):
        state.setdefault("flag", asyncio.Event()).set()
        await asyncio.sleep(0.25)
        return await real(self, model, messages, hint, tier)

    monkeypatch.setattr(ScriptedClient, "complete", slow_complete)
    world, bus, _ = make_world(tmp_path, "inflight", seasons=1, time__mode="sync", **SLOW)
    seen = collect(bus)
    report = {}

    async def script(w):
        while "flag" not in state:
            await asyncio.sleep(0.005)
        await state["flag"].wait()
        w.handle_command({"type": "pause"})
        n0 = len(types(seen["events"], "llm_call"))
        await asyncio.sleep(0.8)                    # les appels (0,25 s) sont finis, leurs réponses doivent attendre
        report["during_pause"] = len(types(seen["events"], "llm_call")) - n0
        w.handle_command({"type": "resume"})

    asyncio.run(drive(world, script))
    assert report["during_pause"] == 0
    assert len(types(read_events(tmp_path, "inflight"), "llm_call")) > 0


def test_pause_and_resume_are_idempotent(tmp_path):
    world, bus, _ = make_world(tmp_path, "idem", seasons=1, time__mode="sync", **SLOW)
    seen = collect(bus)

    async def script(w):
        await started(seen)
        w.handle_command({"type": "resume"})       # rien à reprendre : ignoré
        w.handle_command({"type": "pause"})
        w.handle_command({"type": "pause"})        # déjà en pause : ignoré
        await asyncio.sleep(0.1)
        w.handle_command({"type": "resume"})

    asyncio.run(drive(world, script))
    inj = [e["payload"]["injection_type"] for e in types(seen["events"], "injection")]
    assert inj == ["pause", "resume"]


# ---------------------------------------------------------------- vitesse
async def started(seen):
    while not seen["events"]:           # attend le run_start : une commande plus tôt précéderait le début du journal
        await asyncio.sleep(0.005)


def test_speed_changes_how_long_a_season_takes(tmp_path):
    def run(speed):
        world, bus, _ = make_world(tmp_path, f"v{speed}", seasons=1, time__mode="sync", **SLOW)
        seen = collect(bus)

        async def script(w):
            await started(seen)
            w.handle_command({"type": "set_speed", "value": speed})

        return asyncio.run(drive(world, script)), world

    slow, _ = run(1)
    fast, world = run(4)
    assert fast < slow * 0.6, f"×4 devrait aller nettement plus vite que ×1 ({fast:.2f}s contre {slow:.2f}s)"
    inj = types(read_events(tmp_path, "v4"), "injection")
    assert [(e["payload"]["injection_type"], e["payload"]["params"]["value"]) for e in inj] == [("set_speed", 4.0)]


def test_max_speed_removes_waiting_and_bad_values_are_ignored(tmp_path):
    world, bus, _ = make_world(tmp_path, "max", seasons=2, time__mode="sync", **SLOW)
    seen = collect(bus)

    async def script(w):
        await started(seen)
        w.handle_command({"type": "set_speed", "value": -3})
        w.handle_command({"type": "set_speed", "value": "vite"})
        w.handle_command({"type": "set_speed", "value": True})
        assert not types(seen["events"], "injection")
        w.handle_command({"type": "set_speed", "value": "max"})

    elapsed = asyncio.run(drive(world, script))
    assert elapsed < 1.5                       # deux saisons à 30 j/s dureraient 2 s ou plus
    assert seen["status"][-1]["fast"] is True


# ---------------------------------------------------------------- mode
def test_mode_can_be_switched_between_seasons_both_ways(tmp_path):
    world, bus, _ = make_world(tmp_path, "mode", seasons=4, time__mode="sync")
    seen = collect(bus)
    loop_box = {}

    def later(cmd):
        # comme en jeu : la commande est traitée par la boucle, pas à l'intérieur de l'émission d'un événement
        loop_box["loop"].call_soon(world.handle_command, cmd)

    def on_event(ev):
        if ev["type"] == "season_start" and ev["season"] == 1:
            later({"type": "set_mode", "value": "async"})
        if ev["type"] == "season_start" and ev["season"] == 3:
            later({"type": "set_mode", "value": "sync"})

    bus.subscribe("events", on_event)

    async def script(w):
        loop_box["loop"] = asyncio.get_running_loop()

    asyncio.run(drive(world, script))
    events = read_events(tmp_path, "mode")
    assert [e["payload"]["mode"] for e in types(events, "season_start")] == ["sync", "async", "async", "sync"]
    assert len(types(events, "season_end")) == 4
    assert [e["payload"]["params"]["value"] for e in types(events, "injection")] == ["async", "sync"]
    assert verify("mode", world.cfg)          # schémas valides, ordre et temps simulé monotones à travers les bascules
    announced = [s["pending_mode"] for s in seen["status"] if s["pending_mode"]]
    assert announced and set(announced) == {"async", "sync"}   # la bascule est annoncée avant d'être appliquée
    assert seen["status"][-1]["mode"] == "sync" and seen["status"][-1]["pending_mode"] is None


def test_requesting_the_current_mode_changes_nothing_and_a_request_can_be_cancelled(tmp_path):
    world, bus, _ = make_world(tmp_path, "mode2", seasons=2, time__mode="sync")
    seen = collect(bus)

    async def script(w):
        await started(seen)
        w.handle_command({"type": "set_mode", "value": "sync"})        # déjà le cas
        w.handle_command({"type": "set_mode", "value": "async"})
        assert seen["status"][-1]["pending_mode"] == "async"
        w.handle_command({"type": "set_mode", "value": "sync"})        # annulation
        assert seen["status"][-1]["pending_mode"] is None
        w.handle_command({"type": "set_mode", "value": "turbo"})       # inconnu : ignoré

    asyncio.run(drive(world, script))
    events = read_events(tmp_path, "mode2")
    assert [e["payload"]["mode"] for e in types(events, "season_start")] == ["sync", "sync"]


@pytest.mark.parametrize("first", ["sync", "async"])
def test_a_switched_game_keeps_valid_indicators(tmp_path, first):
    from test_indicators_audit import engine_run, reference

    other = "async" if first == "sync" else "sync"
    world, bus, _ = make_world(tmp_path, "mixed", seasons=3, time__mode=first)
    loop_box = {}
    bus.subscribe("events", lambda ev: ev["type"] == "season_start" and ev["season"] == 1
                  and loop_box["loop"].call_soon(world.handle_command, {"type": "set_mode", "value": other}))

    async def script(w):
        loop_box["loop"] = asyncio.get_running_loop()

    asyncio.run(drive(world, script))
    events = read_events(tmp_path, "mixed")
    _, outs = engine_run(events)
    ref = reference(events)
    got = {o["season"]: o["values"] for o in outs if o["trigger"] == "season_end"}
    assert set(got) == set(ref) == {1, 2, 3}
    for s in ref:
        assert got[s]["total_catch"] == pytest.approx(ref[s]["total_catch"], abs=2e-3)
        assert got[s]["stock_ratio"] == pytest.approx(ref[s]["stock_ratio"], abs=2e-3)


# ---------------------------------------------------------------- arrêt
def test_stop_ends_the_game_promptly_even_while_models_think(tmp_path):
    world, bus, _ = make_world(tmp_path, "stop", seasons=5, time__mode="sync", latency_scale=3.0, **SLOW)
    seen = collect(bus)

    async def script(w):
        while not types(seen["events"], "phase"):
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.3)                    # les pêcheurs « réfléchissent » (3 à 12 s)
        w.handle_command({"type": "stop"})

    elapsed = asyncio.run(drive(world, script))
    assert elapsed < 3, f"l'arrêt doit être immédiat, pas attendre la fin de la réflexion ({elapsed:.1f}s)"
    events = read_events(tmp_path, "stop")
    assert events[-1]["type"] == "run_end" and events[-1]["payload"]["reason"] == "stop"
    assert len(types(events, "season_end")) == 0
    assert seen["status"][-1]["state"] == "ended" and seen["status"][-1]["end_reason"] == "stop"


def test_stop_while_paused(tmp_path):
    world, bus, _ = make_world(tmp_path, "stoppause", seasons=3, time__mode="async", **SLOW)
    seen = collect(bus)

    async def script(w):
        while not types(seen["events"], "season_start"):
            await asyncio.sleep(0.01)
        w.handle_command({"type": "pause"})
        await asyncio.sleep(0.2)
        w.handle_command({"type": "stop"})

    elapsed = asyncio.run(drive(world, script))
    assert elapsed < 3
    assert read_events(tmp_path, "stoppause")[-1]["payload"]["reason"] == "stop"
    assert seen["status"][-1]["state"] == "ended"


def test_collapse_still_stops_at_the_end_of_the_season(tmp_path):
    # un lac à 6 % de sa capacité, huit pêcheurs : il s'effondre pendant la saison 1, qui va à son terme. L'arrêt à l'extinction
    # (immédiat, actif par défaut) est coupé ici : il l'emporterait, le lac étant aussi vidé par la pêche (voir test_extinction.py).
    world, bus, _ = make_world(tmp_path, "collapse", seasons=6, time__mode="sync", run__stop_on_collapse=True,
                               run__stop_on_extinction=False, lake__initial_ratio=0.06)
    asyncio.run(drive(world, lambda w: asyncio.sleep(0)))
    events = read_events(tmp_path, "collapse")
    assert events[-1]["payload"]["reason"] == "collapse"
    assert len(types(events, "season_end")) == 1


# ---------------------------------------------------------------- état publié
def test_every_status_message_is_valid_and_tells_the_story(tmp_path):
    world, bus, _ = make_world(tmp_path, "status", seasons=2, time__mode="sync", **SLOW)
    seen = collect(bus)

    async def script(w):
        while not types(seen["events"], "catch"):
            await asyncio.sleep(0.01)
        w.handle_command({"type": "pause"})
        await asyncio.sleep(0.1)
        w.handle_command({"type": "set_speed", "value": 2})
        w.handle_command({"type": "resume"})

    asyncio.run(drive(world, script))
    for s in seen["status"]:
        assert validate_status(s) == [], s
    states = [s["state"] for s in seen["status"]]
    collapsed = [s for i, s in enumerate(states) if i == 0 or s != states[i - 1]]
    assert collapsed == ["running", "paused", "running", "ended"]
    last = seen["status"][-1]
    assert last["run_id"] == "status" and last["seasons"] == 2 and last["speed"] == 2.0 and last["controls"] is True
    assert last["lobby"] is False


# ---------------------------------------------------------------- robustesse
def test_a_failing_subscriber_never_stops_the_game_or_the_command_pump(tmp_path):
    """Un affichage qui lève (caractère non encodable sur une sortie redirigée…) ne doit ni arrêter la partie ni
    rendre le moteur sourd aux commandes : c'est ce qui figeait la reprise après une pause."""
    world, bus, _ = make_world(tmp_path, "fragile", seasons=2, time__mode="sync", **SLOW)
    calls = {"n": 0}

    def broken(ev):
        calls["n"] += 1
        raise UnicodeEncodeError("charmap", "⚡", 0, 1, "undefined")

    bus.subscribe("events", broken)

    async def script(w):
        await started_via(calls)
        bus.send_command({"type": "pause"})            # par le bus, donc par la pompe de commandes
        await until_true(lambda: w.ctl.paused)
        bus.send_command({"type": "resume"})
        await until_true(lambda: not w.ctl.paused)

    asyncio.run(drive(world, script))
    events = read_events(tmp_path, "fragile")
    assert calls["n"] > 100 and events[-1]["payload"]["reason"] == "completed"
    assert len(types(events, "season_end")) == 2


async def started_via(calls):
    while not calls["n"]:
        await asyncio.sleep(0.005)


async def until_true(cond, timeout=10.0):
    t0 = time.monotonic()
    while not cond():
        assert time.monotonic() - t0 < timeout, "la commande n'a pas été traitée"
        await asyncio.sleep(0.01)


def test_an_error_inside_the_game_is_recorded_as_such(tmp_path):
    world, bus, _ = make_world(tmp_path, "boom", seasons=2, time__mode="sync")
    world.apply_catch = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("panne simulée"))
    with pytest.raises(RuntimeError, match="panne"):
        asyncio.run(drive(world, lambda w: asyncio.sleep(0)))
    events = read_events(tmp_path, "boom")
    assert events[-1]["type"] == "run_end" and events[-1]["payload"]["reason"].startswith("erreur")
