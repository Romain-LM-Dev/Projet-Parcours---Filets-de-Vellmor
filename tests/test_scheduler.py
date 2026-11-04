"""L'ordonnanceur unique (`filets/scheduler.py`, spécification `docs/temps.md`) : réfléchir ne prend pas de temps simulé, agir en
prend. Une IA lente ne fait perdre aucune sortie et ne change pas le monde ; les décisions que rien ne sépare sont demandées en
parallèle ; une décision voit tout ce qui s'est passé avant son horizon ; rien ne part après la fermeture de la pêche."""
from __future__ import annotations

import asyncio
import time

import pytest

from filets.scripted import ScriptedClient
from helpers import make_world, read_events

LLM = dict(population__fishers=8, population__rule_fraction=0.0)


def kinds(events, kind):
    return [e for e in events if e["type"] == kind]


def slow_provider(monkeypatch, delay: float, log: list | None = None):
    """Le faux LLM dort `delay` secondes avant de répondre, et note quand chaque appel part et revient."""
    orig = ScriptedClient.complete

    async def complete(self, model, messages, hint, tier):
        start = time.monotonic()
        await asyncio.sleep(delay)
        res = await orig(self, model, messages, hint, tier)
        if log is not None:
            log.append((hint.get("purpose"), start, time.monotonic()))
        return res
    monkeypatch.setattr(ScriptedClient, "complete", complete)


def play(tmp_path, run_id, seasons=2, **over):
    world, _, _ = make_world(tmp_path, run_id, seasons=seasons, **{**LLM, **over})
    asyncio.run(world.run())
    return world, read_events(tmp_path, run_id)


def outcome(events):
    """Ce que le monde a vécu (et non l'ordre dans lequel les modèles ont répondu) : prises, ventes, déclarations, stock final."""
    keep = {"catch": ("agent", "requested", "landed", "stock_before", "stock_after", "lake"),
            "report": ("agent", "declared", "landed"), "sale": ("agent", "tonnes", "income")}
    rows = [(e["type"], e["sim_time"], *(e["payload"].get(k) for k in keep[e["type"]])) for e in events if e["type"] in keep]
    return sorted(rows, key=repr)


def test_two_games_with_the_same_seed_give_the_same_journal(tmp_path):
    def journal(run_id):
        _, events = play(tmp_path, run_id, seasons=2, **{"time__departure_spread_days": [0.0, 4.0]})
        return [{k: v for k, v in e.items() if k not in ("run_id", "event_id", "processed_at", "wall_clock", "payload")}
                | {"payload": str(e["payload"]).replace(run_id, "R")} for e in events]
    a, b = journal("zz1"), journal("zz2")
    assert len(a) > 100 and len(a) == len(b)
    assert [(x["type"], x["sim_time"]) for x in a] == [(x["type"], x["sim_time"]) for x in b]
    assert a == b


def test_a_slow_ai_loses_no_outing_and_does_not_change_the_world(tmp_path, monkeypatch):
    _, fast = play(tmp_path, "vite", seasons=1)
    slow_provider(monkeypatch, 0.05)
    world, slow = play(tmp_path, "lent", seasons=1)
    assert not [e for e in slow if e["type"] == "incident" and e["payload"]["incident_type"] == "missed_window"]
    assert len(kinds(slow, "catch")) == len(world.fishers) == len(kinds(fast, "catch"))
    assert outcome(slow) == outcome(fast)


def test_decisions_with_no_event_between_them_are_asked_in_parallel(tmp_path, monkeypatch):
    log: list = []
    slow_provider(monkeypatch, 0.15, log)
    world, events = play(tmp_path, "para", seasons=1, time__departure_spread_days=[0.0, 0.2])
    catches = sorted((s, e) for p, s, e in log if p == "catch")
    assert len(catches) == len(world.fishers)
    # les huit départs tiennent dans une même journée (une sortie dure un jour) : tous les appels se chevauchent
    assert catches[-1][0] < min(e for _, e in catches), "les décisions ont été demandées l'une après l'autre"


def test_a_decision_after_an_outing_sees_its_catch(tmp_path):
    world, events = play(tmp_path, "voit", seasons=1, time__departure_spread_days=[0.0, 4.0])
    stocks = [(e["sim_time"], e["payload"]["stock"]) for e in kinds(events, "lake_update")]
    seen = [(d["payload"]["info_horizon"], d["payload"]["observed"]["stock_true"]) for d in kinds(events, "decision")
            if d["payload"]["decision_type"] == "catch"]
    assert len(seen) == len(world.fishers)
    for h, stock_true in seen:
        before = [s for t, s in stocks if t <= h + 1e-9]
        assert stock_true == pytest.approx(before[-1], abs=0.01), f"à J{h:.2f}, la décision ne voit pas l'état du lac"
    # les départs s'étalent sur plusieurs jours : au moins une décision tombe après la fin d'une sortie, et le lac a baissé
    assert min(s for _, s in seen) < max(s for _, s in seen) - 0.5


def test_nothing_sails_after_the_fishing_close(tmp_path):
    world, events = play(tmp_path, "ferme", seasons=2, time__departure_spread_days=[3.0, 4.0], time__fishing_close_day=12.0)
    for season in (1, 2):
        close = (season - 1) * world.T["season_days"] + world.T["fishing_close_day"]
        for e in events:
            if e["season"] == season and e["type"] in ("catch", "report", "sale") or (
                    e["season"] == season and e["type"] == "lake_update" and e["payload"]["cause"] == "catch"):
                assert e["sim_time"] <= close + 1e-6, (e["type"], e["sim_time"], close)
    for c in kinds(events, "catch"):
        assert c["payload"]["outings"]
        assert max(o["day"] for o in c["payload"]["outings"]) + 1.0 <= world.T["fishing_close_day"] + 1e-6


def test_the_road_to_another_lake_adds_its_days_to_both_ends(tmp_path):
    lakes = [{"name": "Vellmor", "capacity": 100, "stock_ratio": 1.0, "villages": ["Ostrel", "Bramois"]},
             {"name": "Orsane", "capacity": 100, "stock_ratio": 1.0, "villages": ["Tilque", "Hennad"]}]
    world, _, _ = make_world(tmp_path, "route", population__fishers=8, lake__lakes=lakes, economy__luck=0.0)
    home, away = world.lakes["Vellmor"], world.lakes["Orsane"]
    a = next(f for f in world.fishers if world.lake_of(f) is home)
    route = world.distance(home, away)
    assert route > 0
    here = world.outings(a, 1)
    a.outings.clear()
    there = world.outings(a, 1, lake=away)
    close = world.T["fishing_close_day"]
    assert there[0]["day"] == pytest.approx(here[0]["day"] + route, abs=0.01)                    # l'aller
    assert there[-1]["day"] + 1.0 + route <= close + 1e-6 and here[-1]["day"] + 1.0 <= close + 1e-6       # le retour tient avant la fermeture
    assert there[-1]["day"] < here[-1]["day"]
