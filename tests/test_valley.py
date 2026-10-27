"""La vallée générée et ce qui la fait vivre : villages et pêcheurs tirés des paramètres, bateaux de différentes tailles, pêche qui
n'est pas toujours bonne (la réussite du jour), saisons de l'année et événements qui changent la pêche ou le repeuplement du lac.
"""
from __future__ import annotations

import asyncio
import random
import statistics

import pytest

from filets.bus import LocalBus
from filets.catalog import build_catalog, generate_world
from filets.climate import CYCLE, EVENTS, Climate
from filets.config import load_config
from filets.engine import Engine, build_game_config
from filets.lake import Lake
from filets.profiles import BOAT_NAMES, VILLAGE_NAMES, build_population
from helpers import cfg_for, make_world, read_events
from test_engine import request
from test_rumors import fisher


def kinds(events, kind):
    return [e for e in events if e["type"] == kind]


def generated(**pop):
    cfg = load_config(None)
    cfg["population"].update(pop)
    return [p for p in build_population(cfg, random.Random(int(cfg["run"]["seed"]))) if p.role == "pecheur"]


# ============================================================ la génération procédurale
def test_the_valley_follows_its_parameters():
    fishers = generated(villages=6, fishers=14)
    villages = sorted({p.hamlet for p in fishers}, key=VILLAGE_NAMES.index)
    assert villages == VILLAGE_NAMES[:6] and len(fishers) == 14
    per = [sum(p.hamlet == v for p in fishers) for v in villages]
    assert max(per) - min(per) <= 1 and min(per) >= 2                    # chaque village a ses pêcheurs, à peu près autant
    assert {p.boat for p in fishers} <= set(BOAT_NAMES)
    assert len({p.first_name for p in fishers}) == 14                    # des prénoms tous différents


def test_the_same_parameters_make_the_same_valley_and_another_seed_another_one():
    again = generated(villages=5, fishers=10)
    assert [(p.name, p.archetype, p.experience, p.wealth, p.boat) for p in again] == \
        [(p.name, p.archetype, p.experience, p.wealth, p.boat) for p in generated(villages=5, fishers=10)]
    cfg = load_config(None, {"run": {"seed": 7}, "population": {"villages": 5, "fishers": 10}})
    other = [p for p in build_population(cfg, random.Random(7)) if p.role == "pecheur"]
    assert [p.experience for p in other] != [p.experience for p in again]


def test_the_default_valley_is_still_the_four_villages_of_vellmor():
    fishers = generated()
    assert sorted({p.hamlet for p in fishers}) == sorted(VILLAGE_NAMES[:4]) and len(fishers) == 8


def test_a_valley_never_has_more_villages_than_fishers():
    assert len({p.hamlet for p in generated(villages=8, fishers=3)}) == 3
    assert len({p.hamlet for p in generated(villages=1, fishers=6)}) == 1


def test_a_valley_has_at_most_eight_villages(tmp_path):
    with pytest.raises(ValueError, match="entre 1 et 8"):
        cfg_for(tmp_path, population__villages=9)
    with pytest.raises(ValueError, match="entre 1 et 8"):
        cfg_for(tmp_path, population__villages=0)
    assert cfg_for(tmp_path, population__villages=8, population__fishers=16)["population"]["villages"] == 8


def test_the_boat_mix_chooses_the_boats_and_the_character_leans_it():
    big = generated(fishers=24, villages=4, boat_mix={"cotre": 1.0})
    assert {p.boat for p in big} == {"cotre"}
    mixed = generated(fishers=24, villages=4, boat_mix={"barque": 1.0, "chaloupe": 1.0, "cotre": 1.0})
    by = {a: [p.boat for p in mixed if p.archetype == a] for a in ("nouveau_venu", "ancienne_famille")}
    assert by["nouveau_venu"].count("barque") > by["nouveau_venu"].count("cotre")             # l'endetté a emprunté pour une barque
    assert by["ancienne_famille"].count("cotre") > by["ancienne_famille"].count("barque")


def test_the_menu_can_ask_for_a_valley(tmp_path):
    cfg = cfg_for(tmp_path)
    world = generate_world(cfg, 6, 14, 3)
    assert len(world["hamlets"]) == 6 and len(world["base_population"]) == 14
    assert all(s["kind"] == "llm" and s["boat"] in BOAT_NAMES for s in world["base_population"])
    engine = Engine(cfg, LocalBus(), quiet=True)
    engine.generate({"villages": 6, "fishers": 14, "seed": 3, "id": "g1"})
    assert engine.catalog["generation"]["id"] == "g1" and len(engine.catalog["hamlets"]) == 6
    assert len(engine.catalog["base_population"]) == 14 and engine.status()["catalog"]["hamlets"] == world["hamlets"]
    engine.generate({"villages": 9, "fishers": 14, "seed": 3})                      # trop de villages : refusé, rien ne change
    assert engine.error and len(engine.catalog["hamlets"]) == 6
    engine.generate({"villages": 5, "fishers": 3, "seed": 3})
    assert "au moins un pêcheur par village" in engine.error


def test_a_game_can_be_started_from_a_generated_valley(tmp_path):
    cfg = cfg_for(tmp_path)
    world = generate_world(cfg, 3, 9, 11)
    req = request(population={"elder": True, "elder_kind": "rule", "fishers": world["base_population"]}, seed=11)
    game = build_game_config(cfg, req)
    assert game["population"]["fishers"] == 9
    w = make_world(tmp_path, "gen", population__custom=world["base_population"])[0]
    assert w.hamlets == world["hamlets"] and len(w.zones) == 4


# ============================================================ les bateaux
def custom(*boats):
    return [fisher(f"P{i}", ["Ostrel", "Bramois", "Tilque"][i % 3], "ancienne_famille") | {"boat": b}
            for i, b in enumerate(boats)]


def test_a_bigger_boat_holds_more_within_half_the_lake(tmp_path):
    world = make_world(tmp_path, "cale", population__custom=custom("barque", "chaloupe", "cotre"), population__elder=False,
                       lake__capacity=100.0)[0]
    holds = [world.hold[a.id] for a in world.fishers]
    assert holds == [4.0, 7.0, 11.0]                                         # le lac est assez grand : la cale limite
    crowded = make_world(tmp_path, "cale2", population__custom=custom("barque", "chaloupe", "cotre"), population__elder=False,
                         lake__capacity=22.0)[0]
    small = [crowded.hold[a.id] for a in crowded.fishers]
    assert sum(small) == pytest.approx(11.0) and small[0] < small[1] < small[2]            # la moitié du lac, au prorata des cales
    assert small[2] / small[0] == pytest.approx(11 / 4)


def test_a_bigger_boat_costs_more_to_keep(tmp_path):
    world = make_world(tmp_path, "entretien", population__custom=custom("barque", "chaloupe", "cotre"),
                       population__elder=False)[0]
    keep = [world.upkeep(a, 1) for a in world.fishers]
    assert keep == [100 + 20, 100 + 50, 100 + 110] and keep == sorted(keep)


def test_no_catch_ever_exceeds_the_hold_of_the_boat(tmp_path):
    world, bus, _ = make_world(tmp_path, "plein", seasons=4, time__mode="sync", economy__luck=0.4, climate__enabled=True,
                               climate__event_rate=1.0, population__boat_mix={"barque": 1.0, "chaloupe": 1.0, "cotre": 1.0})
    asyncio.run(world.run())
    for e in kinds(read_events(tmp_path, "plein"), "catch"):
        assert e["payload"]["landed"] <= world.hold[e["payload"]["agent"]] + 5e-4          # (la prise est arrondie au kilo près)


# ============================================================ la réussite du jour
def test_the_catch_is_not_always_the_target(tmp_path):
    world, bus, _ = make_world(tmp_path, "chance", seasons=5, time__mode="sync", economy__luck=0.25, population__fishers=8)
    asyncio.run(world.run())
    catches = [e["payload"] for e in kinds(read_events(tmp_path, "chance"), "catch")]
    ratios = [c["yield"] for c in catches]
    assert statistics.pstdev(ratios) > 0.08 and min(ratios) < 0.9 and max(ratios) > 1.1       # il y a de bons et de mauvais jours
    for c in catches:                       # sauf si la cale ou le rationnement la limite, la prise est la prise visée × le rendement
        capped = c["rationed"] or c["landed"] >= world.hold[c["agent"]] - 1e-6
        assert capped or c["landed"] == pytest.approx(c["requested"] * c["yield"], abs=0.01)


def test_the_day_is_the_same_whatever_the_order_the_boats_come_home(tmp_path):
    a = make_world(tmp_path, "ordre-a", economy__luck=0.3)[0]
    b = make_world(tmp_path, "ordre-b", economy__luck=0.3)[0]
    first = [a.outing_yield(x, 1) for x in a.fishers]
    second = [b.outing_yield(x, 1) for x in reversed(b.fishers)][::-1]
    assert first == second


def test_a_good_day_follows_a_good_day(tmp_path):
    """La réussite se prolonge d'une saison à l'autre (`luck_streak`) : la forme du pêcheur est mémorisée."""
    world = make_world(tmp_path, "forme", economy__luck=0.3, economy__luck_streak=0.9)[0]
    forms = []
    for season in range(1, 41):
        world.outing_yield(world.fishers[0], season)
        forms.append(world.fishers[0].form)
    pairs = list(zip(forms, forms[1:]))
    same_sign = sum(1 for x, y in pairs if x * y > 0)
    assert same_sign > 0.7 * len(pairs)
    flat = make_world(tmp_path, "forme2", economy__luck=0.3, economy__luck_streak=0.0)[0]
    flat_forms = []
    for season in range(1, 41):
        flat.outing_yield(flat.fishers[0], season)
        flat_forms.append(flat.fishers[0].form)
    assert sum(1 for x, y in zip(flat_forms, flat_forms[1:]) if x * y > 0) < same_sign


def test_a_low_lake_is_harder_to_fish_and_experience_helps(tmp_path):
    world = make_world(tmp_path, "bas", economy__luck=0.001, economy__luck_streak=0.0)[0]
    a = world.fishers[0]
    full, _ = world.outing_yield(a, 1)
    a.form = 0.0
    world.lake.stock = 0.1 * world.capacity
    low, _ = world.outing_yield(a, 1)
    assert low < 0.8 * full
    veteran, novice = world.fishers[0], world.fishers[1]
    veteran.profile.experience, novice.profile.experience = 40, 2
    world.lake.stock = world.capacity
    veteran.form = novice.form = 0.0
    assert world.outing_yield(veteran, 1)[0] > world.outing_yield(novice, 1)[0]


def test_no_luck_means_the_target_is_the_catch(tmp_path):
    world, bus, _ = make_world(tmp_path, "sans-chance", seasons=2, time__mode="sync")
    asyncio.run(world.run())
    for e in kinds(read_events(tmp_path, "sans-chance"), "catch"):
        p = e["payload"]
        assert p["yield"] == 1.0 and p["luck"] == 1.0
        assert p["rationed"] or p["landed"] == pytest.approx(p["requested"], abs=0.01)


# ============================================================ saisons de l'année et événements
def test_the_seasons_of_the_year_follow_each_other():
    c = Climate({"climate": {"enabled": True, "event_rate": 0.0}}, 1)
    names = [c.begin(s)["climate"] for s in range(1, 9)]
    assert names == [x["name"] for x in CYCLE] * 2
    winter, summer = (Climate({"climate": {"enabled": True, "event_rate": 0.0}}, 1) for _ in range(2))
    winter.begin(4)
    summer.begin(2)
    assert winter.yield_for("chaloupe") < 1.0 < summer.yield_for("chaloupe")                  # l'hiver rapporte moins, l'été plus


def test_the_year_averages_out_so_the_lake_is_not_doomed_by_the_calendar():
    assert sum(x["growth"] for x in CYCLE) / len(CYCLE) == pytest.approx(1.0)
    assert 0.9 < sum(x["yield"] for x in CYCLE) / len(CYCLE) <= 1.0


def test_events_are_seeded_and_last_their_duration():
    def run(seed):
        c = Climate({"climate": {"enabled": True, "event_rate": 1.0}}, seed)
        return [(c.begin(s)["new_event"], [e["kind"] for e in c.active]) for s in range(1, 9)]

    assert run(5) == run(5) and run(5) != run(6)
    c = Climate({"climate": {"enabled": True, "event_rate": 1.0}}, 5)
    assert c.begin(1)["new_event"] is None                                    # pas d'événement la première saison
    seen = {}
    for s in range(2, 30):
        cond = c.begin(s)
        if cond["new_event"]:
            seen.setdefault(cond["new_event"], s)
            assert {e["kind"]: e["until"] for e in cond["events"]}[cond["new_event"]] == s + EVENTS[cond["new_event"]]["duration"] - 1
    assert len(seen) >= 4                                                      # le hasard les fait tous venir


def test_an_event_can_be_switched_off_and_the_climate_too():
    c = Climate({"climate": {"enabled": True, "event_rate": 1.0, "disabled_events": list(EVENTS)[1:]}}, 3)
    assert {c.begin(s)["new_event"] for s in range(2, 20)} <= {list(EVENTS)[0], None}
    off = Climate({"climate": {"enabled": False}}, 3)
    assert off.begin(5)["climate"] is None and off.yield_for("barque") == 1.0 and off.line(5) == ""


def test_a_storm_hurts_the_small_boats_more():
    c = Climate({"climate": {"enabled": True, "event_rate": 0.0}}, 1)
    c.begin(1)
    c.active = [{"kind": "tempete", "until": 9}]
    assert c.yield_for("barque") < c.yield_for("chaloupe") < c.yield_for("cotre") < 1.0


def test_the_lake_regrows_with_the_season_of_the_year():
    lake = Lake(100.0, 0.5, 1.0, 0.05, 0.1)
    summer = Lake(100.0, 0.5, 1.0, 0.05, 0.1)
    assert lake.regrow(0.5) == pytest.approx(0.5 * summer.regrow(1.0))
    assert Lake(100.0, 0.5, 1.0, 0.05, 0.1).regrow() == pytest.approx(summer.stock - 50.0)


def test_the_conditions_reach_the_game_and_the_agents(tmp_path):
    from test_rumors import Recorder
    from test_council import fake_game

    rec = Recorder()
    world, events, dead = fake_game(tmp_path, "meteo", rec, seasons=4, climate__enabled=True, climate__event_rate=1.0)
    starts = kinds(events, "season_start")
    assert [s["payload"]["conditions"]["climate"] for s in starts] == [x["name"] for x in CYCLE]
    news = kinds(events, "world_event")
    assert news and all(n["season"] >= 2 for n in news) and not dead
    assert any("Saison de l'année : hiver" in r["user"] for r in rec.requests)
    assert any("En cours : " in r["user"] for r in rec.requests)
    drops = [e["payload"] for e in kinds(events, "lake_update") if e["payload"]["cause"] == "event"]
    assert all(d["delta"] < 0 for d in drops)                              # un choc sur le stock, et jamais un cadeau
    regrowth = {e["season"]: e["payload"]["delta"] for e in kinds(events, "lake_update") if e["payload"]["cause"] == "regrowth"}
    assert regrowth                                                         # le repeuplement de chaque saison est tracé


def test_the_climate_can_be_left_out_of_the_menu_request(tmp_path):
    base = cfg_for(tmp_path)
    cfg = build_game_config(base, request(climate=False, luck=0.0, event_rate=0.5))
    assert cfg["climate"]["enabled"] is False and cfg["economy"]["luck"] == 0.0 and cfg["climate"]["event_rate"] == 0.5
    assert build_game_config(base, request())["climate"]["enabled"] is True


def test_the_catalog_offers_the_new_settings():
    cat = build_catalog(load_config(None))
    assert cat["limits"]["villages"] == [1, 8] and cat["village_names"][:4] == cat["hamlets"]
    assert [c["id"] for c in cat["councils"]] == ["delegates", "all"]
    assert [m["id"] for m in cat["communications"]] == ["valley", "hamlet", "none"]
    sync, asyn = (m["detail"] for m in cat["modes"])
    assert "dépendants" in sync and "indépendants" in asyn
