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
    return [p for p in build_population(cfg) if p.role == "pecheur"]


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
    other = [p for p in build_population(cfg) if p.role == "pecheur"]
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
    by = {"nouveau_venu": [], "ancienne_famille": []}
    for seed in range(1, 9):                                   # (assez de pêcheurs pour que le penchant se voie)
        cfg = load_config(None, {"run": {"seed": seed}, "population": {"fishers": 24, "villages": 4,
                                                                      "boat_mix": {"barque": 1.0, "chaloupe": 1.0, "cotre": 1.0}}})
        for p in build_population(cfg):
            if p.archetype in by:
                by[p.archetype].append(p.boat)
    assert by["nouveau_venu"].count("barque") > by["nouveau_venu"].count("cotre")             # l'endetté a emprunté pour une barque
    assert by["ancienne_famille"].count("cotre") > by["ancienne_famille"].count("barque")


def test_the_menu_can_ask_for_a_valley(tmp_path):
    cfg = cfg_for(tmp_path)
    world = generate_world(cfg, 6, 14, 3)
    assert len(world["hamlets"]) == 6 and len(world["base_population"]) == 14
    assert all(s["kind"] == "llm" and s["boat"] in BOAT_NAMES for s in world["base_population"])
    bus, statuses = LocalBus(), []
    bus.subscribe("status", statuses.append)
    engine = Engine(cfg, bus, quiet=True)
    engine.generate({"villages": 6, "fishers": 14, "seed": 3, "id": "g1"})
    assert engine.catalog["generation"]["id"] == "g1" and len(engine.catalog["hamlets"]) == 6
    assert len(engine.catalog["base_population"]) == 14 and engine.status()["catalog"]["hamlets"] == world["hamlets"]
    assert statuses[-1]["error"] is None and statuses[-1]["catalog"]["generation"]["id"] == "g1"
    engine.generate({"villages": 9, "fishers": 14, "seed": 3})                      # trop de villages : refusé, rien ne change
    assert "villages" in statuses[-1]["error"] and len(engine.catalog["hamlets"]) == 6
    engine.generate({"villages": 5, "fishers": 3, "seed": 3})
    refusal = statuses[-1]["error"]
    assert "au moins un pêcheur par village" in refusal
    seen = len(statuses)
    engine.generate({"villages": 5, "fishers": 3, "seed": 3})            # le même refus, redemandé, se dit de nouveau
    assert len(statuses) == seen + 1 and statuses[-1]["error"] == refusal and engine.error is None


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
    world, bus, _ = make_world(tmp_path, "plein", seasons=4, economy__luck=0.4, climate__enabled=True,
                               climate__event_rate=1.0, population__boat_mix={"barque": 1.0, "chaloupe": 1.0, "cotre": 1.0})
    asyncio.run(world.run())
    for e in kinds(read_events(tmp_path, "plein"), "catch"):
        assert e["payload"]["landed"] <= world.hold[e["payload"]["agent"]] + 5e-4          # (la prise est arrondie au kilo près)


# ============================================================ la pêche : le temps, la chance, les sorties
def mean(outs, key):
    return sum(o[key] for o in outs) / len(outs)


def test_the_catch_is_not_always_the_target(tmp_path):
    world, bus, _ = make_world(tmp_path, "chance", seasons=5, economy__luck=0.4, climate__enabled=True,
                               population__fishers=8)
    asyncio.run(world.run())
    catches = [e["payload"] for e in kinds(read_events(tmp_path, "chance"), "catch")]
    ratios = [c["yield"] for c in catches]
    assert statistics.pstdev(ratios) > 0.15 and min(ratios) < 0.8 and max(ratios) > 1.2         # il y a de bonnes et de mauvaises pêches
    for c in catches:
        outs = c["outings"]
        # (une règle du conseil sur les sorties en fait faire moins : voir test_rules.py)
        assert 1 <= len(outs) <= world.econ["outings"] and sum(o["tonnes"] for o in outs) == pytest.approx(c["landed"], abs=0.005)
        # le rendement : celui des sorties, et celui du coin de pêche (sa parcelle du lac)
        assert c["yield"] == pytest.approx(mean(outs, "yield") * len(outs) / world.econ["outings"] * c["spot"], abs=0.003)
        assert c["luck"] == pytest.approx(mean(outs, "luck"), abs=0.002)
        if not c["rationed"] and c["stock_after"] > 0.01:      # chaque sortie rapporte sa part de la prise visée, dans la limite de la cale
            limit = world.hold_of(world.agents[c["agent"]], c["stock_at_action"])
            expected = sum(min(c["requested"] * o["yield"] * c["spot"], limit) for o in outs) / world.econ["outings"]
            assert c["landed"] == pytest.approx(expected, abs=0.01)


def test_each_fisher_has_his_own_luck(tmp_path):
    """Au même lac, sous le même ciel, tous n'ont pas la même chance : certains ont une mauvaise saison, d'autres une très bonne."""
    world = make_world(tmp_path, "chacun", economy__luck=0.4, population__fishers=8)[0]
    means = [mean(world.outings(f, s), "luck") for f in world.fishers for s in (1, 2, 3)]
    assert statistics.pstdev(means) > 0.15 and min(means) < 0.8 and max(means) > 1.2
    for s in (1, 2, 3):                                         # et la chance de chacun change d'une sortie à l'autre
        assert all(len({o["luck"] for o in world.outings(f, s)}) > 1 for f in world.fishers)


def test_the_weather_is_the_same_for_the_whole_lake(tmp_path):
    world = make_world(tmp_path, "ciel", economy__luck=0.4, climate__enabled=True, population__fishers=8)[0]
    for season in (1, 2, 3, 4):
        sky = world.weather(season)
        assert len(sky) == 20 and set(sky) <= {"calme", "ordinaire", "agité", "tempête"}
        assert sky == world.weather(season)                                          # tirée une fois pour la saison
        for f in world.fishers:
            assert all(o["weather"] == sky[int(o["day"])] for o in world.outings(f, season))
    assert world.weather(1) != world.weather(2) or world.weather(2) != world.weather(3)
    winters = sum(x in ("agité", "tempête") for s in range(4, 80, 4) for x in world.weather(s))
    summers = sum(x in ("agité", "tempête") for s in range(2, 80, 4) for x in world.weather(s))
    assert winters > 2 * summers                                                      # l'hiver est la saison des gros temps


def test_a_rough_day_hurts_the_small_boats_most_and_a_calm_one_helps_everyone():
    c = Climate({"climate": {"enabled": True}}, 1)
    for season in (1, 2, 3, 4):
        storm = [c.day_factor("tempête", season, b) for b in ("barque", "chaloupe", "cotre")]
        assert storm[0] < storm[1] < storm[2] < 0.5
        assert all(c.day_factor("calme", season, b) > 1.0 for b in ("barque", "chaloupe", "cotre"))
    off = Climate({"climate": {"enabled": False}}, 1)
    assert off.calendar(1, 20) == ["ordinaire"] * 20 and off.day_factor("tempête", 1, "barque") == 1.0


def test_the_calendar_is_seeded_and_the_weather_lingers():
    a, b = Climate({"climate": {"enabled": True}}, 7), Climate({"climate": {"enabled": True}}, 8)
    assert a.calendar(3, 20) == Climate({"climate": {"enabled": True}}, 7).calendar(3, 20) and a.calendar(3, 20) != b.calendar(3, 20)
    days = [x for s in range(1, 60) for x in a.calendar(s, 20)]
    same = sum(x == y for x, y in zip(days, days[1:])) / (len(days) - 1)
    assert same > 0.4                                      # le temps d'hier se prolonge plus souvent que le hasard seul


def test_the_day_is_the_same_whatever_the_order_the_boats_come_home(tmp_path):
    a = make_world(tmp_path, "ordre-a", economy__luck=0.3, climate__enabled=True)[0]
    b = make_world(tmp_path, "ordre-b", economy__luck=0.3, climate__enabled=True)[0]
    first = [a.outings(x, 1) for x in a.fishers]
    second = [b.outings(x, 1) for x in reversed(b.fishers)][::-1]
    assert first == second


def test_a_good_day_follows_a_good_day(tmp_path):
    """La chance se prolonge d'une saison à l'autre, et d'une sortie à l'autre (`luck_streak`)."""
    def probe(streak):
        world = make_world(tmp_path, f"forme{streak}", economy__luck=0.3, economy__luck_streak=streak)[0]
        forms, jumps = [], []
        for season in range(1, 41):
            outs = world.outings(world.fishers[0], season)
            forms.append(world.fishers[0].form)
            jumps += [abs(x["luck"] - y["luck"]) for x, y in zip(outs, outs[1:])]
        same_sign = sum(1 for x, y in zip(forms, forms[1:]) if x * y > 0)
        return same_sign, statistics.mean(jumps)

    steady, flat = probe(0.9), probe(0.0)
    assert steady[0] > 0.7 * 39 and steady[0] > flat[0]                               # la forme de la saison se prolonge
    assert steady[1] < flat[1]                                                        # un bon jour en annonce un autre


def test_a_low_lake_is_harder_to_fish_and_experience_helps(tmp_path):
    world = make_world(tmp_path, "bas", economy__luck=0.001, economy__luck_streak=0.0)[0]
    a = world.fishers[0]
    full = mean(world.outings(a, 1), "yield")
    low = mean(world.outings(a, 2, stock=0.1 * world.capacity), "yield")
    assert low < 0.8 * full
    veteran, novice = world.fishers[0], world.fishers[1]
    veteran.profile.experience, novice.profile.experience = 40, 2
    assert mean(world.outings(veteran, 3), "yield") > mean(world.outings(novice, 3), "yield")


def test_no_luck_means_the_target_is_the_catch(tmp_path):
    world, bus, _ = make_world(tmp_path, "sans-chance", seasons=2)
    asyncio.run(world.run())
    for e in kinds(read_events(tmp_path, "sans-chance"), "catch"):
        p = e["payload"]
        assert p["yield"] == 1.0 and p["luck"] == 1.0 and {o["weather"] for o in p["outings"]} == {"ordinaire"}
        limit = world.hold_of(world.agents[p["agent"]], p["stock_at_action"])       # ce que le lac lui laissait prendre
        assert p["rationed"] or p["landed"] == pytest.approx(min(p["requested"], limit), abs=0.01)


def test_the_patrol_measures_a_boat_in_proportion_to_the_outings_it_met(tmp_path):
    world = make_world(tmp_path, "ronde", population__elder=False)[0]
    world.patrol_legs[1] = [{"zone": "Ostrel", "from_day": 0.25, "to_day": 10.0}, {"zone": "large", "from_day": 10.0, "to_day": 20.0}]
    assert world.patrolled(1, "Ostrel", [1.0, 5.0, 12.0, 15.0]) == 0.5 and world.patrolled(1, "Ostrel", [12.0, 15.0]) == 0.0
    assert world.patrolled(1, "Tilque", [1.0, 12.0]) == 0.0 and world.patrolled(2, "Ostrel", [1.0]) == 0.0
    assert world.patrolled(1, "large", [3.0, 11.0, 19.9]) == pytest.approx(2 / 3)


def test_a_season_of_fishing_is_remembered_with_its_weather(tmp_path):
    world, bus, _ = make_world(tmp_path, "carnet", seasons=2, economy__luck=0.4, climate__enabled=True)
    asyncio.run(world.run())
    for a in world.fishers:
        notes = [m.text for m in a.memory.items if m.kind == "peche"]
        assert any(f"Sur {world.econ['outings']} sorties : " in t for t in notes) and len(a.outings) == 2


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


def test_a_storm_makes_the_weather_rough_and_hurts_the_small_boats_more():
    """L'événement « tempête » se voit dans le temps des jours de pêche, et pèse plus sur une barque que sur un cotre."""
    def season(seed, storm):
        c = Climate({"climate": {"enabled": True, "event_rate": 0.0}}, seed)
        c.begin(1)
        if storm:
            c.active, c.by_season[1] = [{"kind": "tempete", "until": 1}], ["tempete"]
        return c

    def rough(c):
        return sum(d in ("agité", "tempête") for d in c.calendar(1, 20)) / 20

    calm, storm = [statistics.mean(rough(season(s, st)) for s in range(40)) for st in (False, True)]
    assert calm < 0.4 and storm > 0.65
    mean = {b: statistics.mean(c.day_factor(d, 1, b) for s in range(40) for c in [season(s, True)] for d in c.calendar(1, 20))
            for b in ("barque", "chaloupe", "cotre")}
    assert mean["barque"] < mean["chaloupe"] < mean["cotre"] < 0.9              # (un coefficient plat ne distinguait pas les bateaux)
    assert season(1, True).yield_for("barque") == season(1, False).yield_for("barque")      # le temps seul fait la tempête


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
    # un seul mode de temps (docs/temps.md) : le menu n'en propose plus le choix
    assert "modes" not in cat and cat["defaults"]["mode"] == "unique"
