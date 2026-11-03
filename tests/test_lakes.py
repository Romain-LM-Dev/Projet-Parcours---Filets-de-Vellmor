"""Plusieurs lacs, chacun avec son poisson, son repeuplement et ses villages ; une limite de pêche qui suit le poisson qu'il y a et la
taille des bateaux ; et la vallée tirée au hasard de la graine seule."""
from __future__ import annotations

import asyncio
import collections

import pytest

from filets.config import load_config, normalize
from filets.lakes import LAKE_NAMES, random_valley, resolve_lakes, split_villages
from helpers import cfg_for, make_world, play, read_events

TWO_LAKES = [{"name": "Vellmor", "capacity": 100, "stock_ratio": 0.8, "growth_rate": 1.0, "villages": ["Ostrel", "Bramois"]},
             {"name": "Orsane", "capacity": 40, "stock_ratio": 0.5, "growth_rate": 0.6, "villages": ["Tilque", "Hennad"]}]


def kinds(events, kind):
    return [e for e in events if e["type"] == kind]


# ============================================================ la limite de pêche
def test_the_limit_follows_the_fish_in_the_lake_and_the_size_of_the_boats(tmp_path):
    """Au plus la moitié du poisson du lac, partagée entre les bateaux en proportion de leur cale : un lac plein donne l'ancienne
    part (capacité / 2 / pêcheurs), un lac à moitié vide la moitié de cela, un gros bateau plus qu'un petit."""
    world, bus, _ = make_world(tmp_path, "cale", population__fishers=8, population__boat_mix={"barque": 0.5, "cotre": 0.5})
    small = next(a for a in world.fishers if a.profile.boat == "barque")
    big = next(a for a in world.fishers if a.profile.boat == "cotre")
    assert world.hold_of(big) > world.hold_of(small)
    assert world.hold[big.id] == pytest.approx(world.hold_of(big))                 # (lac plein : l'ancienne part)
    cap, boats = world.lake.capacity, world.lake_boats[world.lake.name]
    assert world.hold_of(big, cap) == pytest.approx(min(11.0, cap / 2 * 11.0 / boats))
    for stock in (cap, cap / 2, cap / 10):
        assert world.hold_of(small, stock) == pytest.approx(min(4.0, 0.5 * stock * 4.0 / boats))
    assert world.hold_of(small, cap / 10) == pytest.approx(world.hold_of(small, cap) / 10)
    assert world.hold_of(small, 0.0) == 0.0                                        # un lac vide ne laisse rien prendre


def test_a_boat_never_lands_more_than_the_lake_lets_it(tmp_path):
    world, bus, _ = make_world(tmp_path, "limite", seasons=4, population__fishers=8, lake__initial_ratio=0.4, time__mode="sync")
    asyncio.run(world.run())
    for e in kinds(read_events(tmp_path, "limite"), "catch"):
        p = e["payload"]
        assert p["landed"] <= world.hold_of(world.agents[p["agent"]], p["stock_at_action"]) + 5e-4


def test_the_range_a_fisher_reads_shrinks_with_the_lake(tmp_path):
    """Le bateau porte 7 t, mais un lac au tiers ne laisse viser que sa part : c'est ce que dit l'invite."""
    from test_council import fake_game
    from test_rumors import Recorder, fisher

    rec = Recorder(prise=10.0)
    fake_game(tmp_path, "plage", rec, population=[fisher("Mathis", "Ostrel", "ancienne_famille"), fisher("Inès", "Tilque", "taiseux")],
              seasons=1, lake__initial_ratio=1.0)
    full = [r["user"] for r in rec.requests if '"prise"' in r["user"]][0]
    rec2 = Recorder(prise=10.0)
    fake_game(tmp_path, "plage2", rec2, population=[fisher("Mathis", "Ostrel", "ancienne_famille"),
                                                    fisher("Inès", "Tilque", "taiseux")], seasons=1, lake__initial_ratio=0.3)
    low = [r["user"] for r in rec2.requests if '"prise"' in r["user"]][0]

    def top(text):
        import re
        return float(re.search(r"tu peux viser de [\d.]+ à ([\d.]+) t", text).group(1))

    assert top(low) < 0.5 * top(full)


# ============================================================ la description des lacs
def test_one_lake_is_the_default_and_the_base_valley_is_unchanged(tmp_path):
    world, bus, _ = make_world(tmp_path, "un", population__fishers=8)
    assert list(world.lakes) == ["Vellmor"] and not world.multi
    assert world.capacity == 100.0 and world.lake is world.lakes["Vellmor"]
    assert world.zones[-1] == "large" and world.zone_label("large") == "le large"


def test_lakes_share_the_villages_in_blocks_and_each_has_twelve_and_a_half_tonnes_per_fisher():
    cfg = load_config(None)
    cfg["lake"]["count"] = 2
    lakes = resolve_lakes(cfg["lake"], ["Ostrel", "Bramois", "Tilque", "Hennad"],
                          {"Ostrel": 2, "Bramois": 2, "Tilque": 2, "Hennad": 2})
    assert [d["villages"] for d in lakes] == [["Ostrel", "Bramois"], ["Tilque", "Hennad"]]
    assert [d["capacity"] for d in lakes] == [50.0, 50.0] and [d["name"] for d in lakes] == LAKE_NAMES[:2]
    assert split_villages(["a", "b", "c", "d", "e"], 2) == [["a", "b", "c"], ["d", "e"]]
    # une capacité totale choisie se partage au prorata des pêcheurs
    cfg["lake"]["capacity"] = 120
    lakes = resolve_lakes(cfg["lake"], ["Ostrel", "Bramois", "Tilque"], {"Ostrel": 1, "Bramois": 1, "Tilque": 4})
    assert [d["capacity"] for d in lakes] == [40.0, 80.0]


def test_each_lake_has_its_own_fish_growth_and_villages(tmp_path):
    world, bus, _ = make_world(tmp_path, "deux", population__fishers=8, lake__lakes=TWO_LAKES)
    v, o = world.lakes["Vellmor"], world.lakes["Orsane"]
    assert (v.capacity, v.stock, v.r) == (100.0, 80.0, 1.0) and (o.capacity, o.stock, o.r) == (40.0, 20.0, 0.6)
    assert world.multi and world.capacity == 140.0 and world.lake_stock() == 100.0
    assert [world.lake_of(a).name for a in world.fishers[:4]] == [world.lake_of_hamlet[a.profile.hamlet] for a in world.fishers[:4]]
    assert world.lake_fishers == {"Vellmor": 4, "Orsane": 4}
    assert world.zones[-2:] == ["large-Vellmor", "large-Orsane"]
    assert world.zone_lake("large-Orsane") is o and world.zone_lake("Tilque") is o and world.zone_lake("Ostrel") is v
    assert world.zone_label("large-Orsane") == "le large du lac d'Orsane"


def test_a_catch_empties_only_the_lake_of_the_fisher_and_events_say_which(tmp_path):
    world, bus, _ = make_world(tmp_path, "pris", seasons=2, population__fishers=8, lake__lakes=TWO_LAKES, time__mode="sync")
    asyncio.run(world.run())
    events = read_events(tmp_path, "pris")
    start = kinds(events, "run_start")[0]["payload"]
    assert [lk["name"] for lk in start["lakes"]] == ["Vellmor", "Orsane"] and start["lake"]["capacity"] == 140.0
    assert {tuple(lk["villages"]) for lk in start["lakes"]} == {("Ostrel", "Bramois"), ("Tilque", "Hennad")}
    for e in kinds(events, "catch"):
        p = e["payload"]
        assert p["lake"] == world.lake_of(world.agents[p["agent"]]).name or p.get("away")      # le sien, ou un autre où il est allé
    updates = kinds(events, "lake_update")
    assert all(set(u["payload"]["lakes"]) == {"Vellmor", "Orsane"} for u in updates)
    assert all(u["payload"]["stock"] == pytest.approx(sum(u["payload"]["lakes"].values()), abs=0.01) for u in updates)
    ends = kinds(events, "season_end")
    assert all(set(e["payload"]["lakes"]) == {"Vellmor", "Orsane"} for e in ends)
    # chaque lac se repeuple selon sa propre croissance
    regrowth = {u["payload"]["lake"] for u in updates if u["payload"]["cause"] == "regrowth"}
    assert regrowth == {"Vellmor", "Orsane"}


def test_a_game_is_extinct_only_when_every_lake_is_empty(tmp_path):
    world, bus, _ = make_world(tmp_path, "eteint", population__fishers=8, lake__lakes=TWO_LAKES)
    world.lakes["Orsane"].stock = 0.0
    world.lake_update("catch", -1.0, world.lakes["Orsane"])
    assert not world.stop_requested and "Orsane" in world.collapsed
    world.lakes["Vellmor"].stock = 0.0
    world.lake_update("catch", -1.0, world.lakes["Vellmor"])
    assert world.stop_requested and world.stopped_reason in ("extinction", "collapse")


@pytest.mark.parametrize("bad, what", [
    ([{"name": "A", "villages": ["Ostrel"]}], "chaque village doit être rattaché"),
    ([{"name": "A", "villages": ["Ostrel", "Bramois", "Tilque"]}, {"name": "A", "villages": ["Hennad"]}], "même nom"),
    ([{"villages": ["Ostrel", "Bramois", "Tilque", "Hennad"]}, {"villages": []}], "chaque village doit être rattaché|au moins un village"),
    ([{"capacity": -4}, {"capacity": 20}], "capacité"),
])
def test_an_incoherent_lake_description_is_refused_in_french(bad, what):
    cfg = load_config(None)
    cfg["lake"]["lakes"] = bad
    with pytest.raises(ValueError, match=what):
        resolve_lakes(cfg["lake"], ["Ostrel", "Bramois", "Tilque", "Hennad"], {v: 2 for v in ["Ostrel", "Bramois", "Tilque", "Hennad"]})
    with pytest.raises(ValueError, match="au moins un village par lac"):
        cfg["lake"]["lakes"] = [{} for _ in range(3)]
        resolve_lakes(cfg["lake"], ["Ostrel", "Bramois"], {"Ostrel": 1, "Bramois": 1})


def test_the_prompts_say_which_lake_is_the_fishers_and_how_full_it_is(tmp_path):
    from test_council import fake_game
    from test_rumors import Recorder, fisher

    rec = Recorder()
    fake_game(tmp_path, "lacs", rec, population=[fisher("Mathis", "Ostrel", "ancienne_famille"), fisher("Inès", "Tilque", "taiseux")],
              seasons=1, lake__lakes=[{"name": "Vellmor", "capacity": 80, "villages": ["Ostrel"]},
                                      {"name": "Orsane", "capacity": 30, "villages": ["Tilque"]}])
    by_fisher = {}
    for r in rec.requests:
        if '"prise"' in r["user"]:
            by_fisher["Mathis" if "Mathis" in r["system"] else "Inès"] = r
    assert "le lac de Vellmor (Ostrel), le lac d'Orsane (Tilque)" in by_fisher["Mathis"]["system"]
    assert "Tu pêches dans le lac de Vellmor (environ 80 tonnes quand il est plein)" in by_fisher["Mathis"]["system"]
    assert "Tu pêches dans le lac d'Orsane (environ 30 tonnes quand il est plein)" in by_fisher["Inès"]["system"]
    assert "(Lac d'Orsane, celui de ton village)" in by_fisher["Inès"]["user"]
    assert "sur 30 à pleine capacité" in by_fisher["Inès"]["user"] and "sur 80 à pleine capacité" in by_fisher["Mathis"]["user"]


def test_a_banned_fisher_sneaks_out_on_his_own_lake_only(tmp_path):
    world, bus, _ = make_world(tmp_path, "cachette", population__fishers=8, lake__lakes=TWO_LAKES)
    for a in world.fishers:
        mine = world.lake_of(a)
        seen = {world.secret_zone(a) for _ in range(40)}
        assert seen and all(world.zone_lake(z) is mine and z != a.profile.hamlet for z in seen)


# ============================================================ la vallée tirée au hasard
def test_a_random_valley_depends_on_the_seed_alone_and_stays_within_limits():
    assert random_valley(7) == random_valley(7)
    shapes = [random_valley(s) for s in range(60)]
    assert len({(v["villages"], v["fishers"], len(v["lakes"]), v["patrols"]) for v in shapes}) > 15            # elles diffèrent
    for v in shapes:
        assert 3 <= v["villages"] <= 6 and 2 * v["villages"] <= v["fishers"] <= min(24, 5 * v["villages"])
        assert 1 <= len(v["lakes"]) <= min(3, v["villages"]) and 0 <= v["patrols"] <= 2
        assert all(0.6 <= k["richness"] <= 1.4 and 0.6 <= k["stock_ratio"] <= 1.0 and 0.6 <= k["growth_rate"] <= 1.4 for k in v["lakes"])
    assert {v["fleet"] for v in shapes} == {"petits", "mixte", "gros"} and {v["patrols"] for v in shapes} == {0, 1, 2}


def test_the_random_setting_draws_the_whole_valley_and_the_manual_one_does_not():
    base = load_config(None)
    assert (base["population"]["villages"], base["population"]["fishers"]) == (4, 8) and not base["population"]["random"]
    for seed in (1, 2, 3, 4, 5):
        cfg = load_config(None)
        cfg["run"]["seed"], cfg["population"]["random"] = seed, True
        cfg = normalize(cfg)
        v = random_valley(seed)
        assert (cfg["population"]["villages"], cfg["population"]["fishers"]) == (v["villages"], v["fishers"])
        assert len(cfg["lake"]["lakes"]) == len(v["lakes"]) and cfg["scenario"]["patrol"]["count"] == v["patrols"]
        assert normalize(cfg) == cfg                                                  # appliquée deux fois : la même vallée
    cfg = load_config(None)
    cfg["population"]["random"] = True
    cfg["population"]["custom"] = [{"first_name": "A", "hamlet": "Ostrel", "archetype": "taiseux"}]
    assert normalize(cfg)["population"]["fishers"] == 1                               # une composition à la main reste la sienne


def test_a_random_valley_plays_through_with_its_lakes_and_boats(tmp_path):
    for seed in (3, 11):
        cfg = cfg_for(tmp_path, seasons=2, run__seed=seed, population__random=True, time__mode="sync")
        events = play(tmp_path, f"hasard{seed}", cfg=cfg)
        start = kinds(events, "run_start")[0]["payload"]
        v = random_valley(seed)
        assert start["population"]["fishers"] == v["fishers"] and len(start["lakes"]) == len(v["lakes"])
        assert sum(len(lk["villages"]) for lk in start["lakes"]) == len(start["hamlets"]) == v["villages"]
        boats = collections.Counter(a["boat"] for a in start["agents"] if a.get("boat"))
        assert sum(boats.values()) == v["fishers"] and len(kinds(events, "season_end")) <= 2


# ============================================================ plusieurs patrouilles
def patrols(count, **extra):
    return {"enabled": True, "count": count, "from_season": 1, "cost": 15, "legs": 2, "days": 10, **extra}


def test_each_patrol_has_its_captain_its_route_and_its_price(tmp_path):
    world, bus, _ = make_world(tmp_path, "deux-patrouilles", seasons=2, population__fishers=8, time__mode="sync",
                               scenario__patrol=patrols(2))
    assert [a.id for a in world.patrol_agents] == ["PAT", "PAT2"] and world.patrol_agent is world.patrol_agents[0]
    assert world.patrol_cost() == 30.0
    a = world.fishers[0]
    assert world.upkeep(a, 1) == world.econ["upkeep_per_season"] + world.boats[a.profile.boat]["upkeep"] + 30.0
    asyncio.run(world.run())
    routes = kinds(read_events(tmp_path, "deux-patrouilles"), "patrol_route")
    assert {r["payload"]["captain"] for r in routes if r["season"] == 1} == {"PAT", "PAT2"}
    first, second = [r["payload"] for r in routes if r["season"] == 1]
    seen = lambda p: {leg.get("follow") or leg["zone"] for leg in p["legs"]}      # noqa: E731
    assert all(leg["by"] == first["captain"] for leg in first["legs"])
    assert seen(first).isdisjoint(seen(second))                                     # la seconde va ailleurs que la première


def test_the_second_captain_reads_the_route_of_the_first(tmp_path):
    world, bus, _ = make_world(tmp_path, "lecture", population__fishers=8, scenario__patrol=patrols(2))
    world.patrol_legs[1] = [{"zone": "Ostrel", "follow": None, "days": 5, "from_day": 1.0, "to_day": 6.0, "by": "PAT"}]
    assert not any("Les autres patrouilles" in x for x in world.patrol_dossier(1, world.patrol_agents[0]))
    assert any("Les autres patrouilles de la saison feront route vers : Ostrel" in x for x in world.patrol_dossier(1, world.patrol_agents[1]))
    share, who = world.patrol_cover(1, "Ostrel", [2.0, 3.0, 8.0, 9.0])
    assert share == 0.5 and who == "PAT"


def test_no_patrol_when_there_are_none_to_send(tmp_path):
    world, bus, _ = make_world(tmp_path, "zero", population__fishers=8, scenario__patrol=patrols(0))
    assert not world.patrol_on and world.patrol_agents == [] and world.patrol_agent is None and world.patrol_cost() == 0.0
    assert world.upkeep(world.fishers[0], 1) == world.econ["upkeep_per_season"] + world.boats[world.fishers[0].profile.boat]["upkeep"]


def test_patrols_can_go_to_the_open_water_of_each_lake(tmp_path):
    world, bus, _ = make_world(tmp_path, "larges", seasons=3, population__fishers=8, lake__lakes=TWO_LAKES, time__mode="sync",
                               scenario__patrol=patrols(2, legs=3))
    asyncio.run(world.run())
    legs = [leg for r in kinds(read_events(tmp_path, "larges"), "patrol_route") for leg in r["payload"]["legs"]]
    assert legs and {leg["zone"] for leg in legs} <= set(world.zones)
    assert all(world.zone_label(leg["zone"]) for leg in legs)
    assert "large-Orsane" in world.zones and "large-Vellmor" in world.zones


# ============================================================ le menu et le moteur
def engine_for(tmp_path, **over):
    from filets.bus import LocalBus
    from filets.engine import Engine

    bus, statuses = LocalBus(), []
    bus.subscribe("status", statuses.append)
    return Engine(cfg_for(tmp_path, **over), bus, quiet=True), statuses


def test_the_catalog_describes_the_lakes_the_patrols_and_their_limits():
    from filets.catalog import build_catalog

    cat = build_catalog(load_config(None))
    assert [k["name"] for k in cat["lakes"]] == ["Vellmor"] and cat["lakes"][0]["capacity"] == 100.0
    assert cat["lakes"][0]["villages"] == cat["hamlets"] and cat["lake_names"] == LAKE_NAMES
    assert cat["defaults"]["lakes"] == 1 and cat["defaults"]["patrols"] == 1 and cat["defaults"]["hold_fraction"] == 0.5
    assert cat["limits"]["lakes"] == [1, 4] and cat["limits"]["patrols"] == [0, 4]
    assert cat["defaults"]["travel_days"] == 1.5 and cat["defaults"]["travel_cost"] == 10.0


def test_the_menu_can_ask_for_a_parametric_or_a_random_valley(tmp_path):
    engine, statuses = engine_for(tmp_path)
    engine.generate({"villages": 4, "fishers": 12, "seed": 3, "fleet": "mixte", "lakes": 2, "patrols": 2, "id": "p1"})
    got = engine.catalog
    assert got["generation"] == {"id": "p1", "villages": 4, "fishers": 12, "seed": 3, "fleet": "mixte", "lakes": 2, "patrols": 2,
                                 "mode": "params"}
    assert [k["name"] for k in got["lakes"]] == ["Vellmor", "Orsane"] and sum(k["capacity"] for k in got["lakes"]) == 12.5 * 12
    engine.generate({"seed": 9, "mode": "random", "id": "r1"})
    drawn, gen = random_valley(9), engine.catalog["generation"]
    assert gen["mode"] == "random" and (gen["villages"], gen["fishers"], gen["lakes"], gen["patrols"], gen["fleet"]) == (
        drawn["villages"], drawn["fishers"], len(drawn["lakes"]), drawn["patrols"], drawn["fleet"])
    assert len(engine.catalog["base_population"]) == drawn["fishers"] and len(engine.catalog["lakes"]) == len(drawn["lakes"])
    again, _ = engine_for(tmp_path)
    again.generate({"seed": 9, "mode": "random", "id": "r2"})
    assert again.catalog["base_population"] == engine.catalog["base_population"] and again.catalog["lakes"] == engine.catalog["lakes"]
    for bad, what in (({"villages": 3, "fishers": 8, "seed": 1, "lakes": 4}, "au moins un village par lac"),
                      ({"villages": 4, "fishers": 8, "seed": 1, "lakes": 9}, "lacs"),
                      ({"villages": 4, "fishers": 8, "seed": 1, "patrols": 9}, "patrouilles"),
                      ({"seed": 1, "mode": "chaos"}, "aléatoire")):
        engine.generate({**bad, "id": "bad"})
        assert what in statuses[-1]["error"] and engine.catalog["generation"]["id"] == "r1"


def test_a_request_with_lakes_patrols_and_a_limit_is_checked_and_applied(tmp_path):
    from filets.engine import build_game_config, validate_request
    from test_engine import fisher, request

    fishers = [fisher(first_name=n, hamlet=h) for n, h in (("A", "Ostrel"), ("B", "Bramois"), ("C", "Tilque"), ("D", "Hennad"))]
    pop = {"elder": True, "elder_kind": "rule", "fishers": fishers}
    good = request(population=pop, patrols=2, hold_fraction=0.7, lake={"lakes": TWO_LAKES})
    assert validate_request(good) == []
    cfg = build_game_config(cfg_for(tmp_path), good)
    assert cfg["lake"]["lakes"] == TWO_LAKES and cfg["scenario"]["patrol"]["count"] == 2 and cfg["economy"]["hold_fraction"] == 0.7
    far = build_game_config(cfg_for(tmp_path), request(population=pop, travel_days=2.5, travel_cost=30))["economy"]
    assert far["travel_days"] == 2.5 and far["travel_cost"] == 30.0 and cfg["economy"]["travel_days"] == 1.5
    assert build_game_config(cfg_for(tmp_path), request(population=pop, patrols=0))["scenario"]["patrol"]["enabled"] is False
    assert build_game_config(cfg_for(tmp_path), request(population=pop, patrol=False))["scenario"]["patrol"] ==         {**cfg_for(tmp_path)["scenario"]["patrol"], "enabled": False, "count": 0}
    for change, what in (({"patrols": 9}, "patrouilles"), ({"patrols": -1}, "patrouilles"), ({"hold_fraction": 2}, "bateau"),
                         ({"travel_days": 50}, "route entre les lacs"), ({"travel_cost": -3}, "coût de la route"),
                         ({"lake": {"lakes": [{"name": "A", "villages": ["Ostrel"]}]}}, "rattaché"),
                         ({"lake": {"lakes": [{"name": "A", "capacity": 5000000, "villages": ["Ostrel", "Bramois", "Tilque", "Hennad"]}]}},
                          "capacité"),
                         ({"lake": {"lakes": []}}, "au moins un lac")):
        errs = validate_request(request(population=pop, **change))
        assert errs and any(what in e for e in errs), (change, errs)


def test_a_game_started_from_the_menu_plays_on_its_lakes(tmp_path):
    import asyncio as aio

    from filets.bus import LocalBus
    from filets.engine import Engine
    from test_engine import fisher, request, until

    fishers = [fisher(first_name=n, hamlet=h) for n, h in (("A", "Ostrel"), ("B", "Bramois"), ("C", "Tilque"), ("D", "Hennad"))]
    pop = {"elder": True, "elder_kind": "rule", "fishers": fishers}

    async def scenario():
        bus, statuses = LocalBus(), []
        bus.subscribe("status", statuses.append)
        eng = Engine(cfg_for(tmp_path), bus, quiet=True)
        task = aio.create_task(eng.serve())
        await until(lambda: statuses and statuses[-1]["state"] == "idle")
        bus.send_command({"type": "start_game", "config": request(population=pop, speed="max", seasons=2, patrols=2,
                                                                   lake={"lakes": TWO_LAKES})})
        await until(lambda: statuses[-1]["state"] == "ended")
        task.cancel()
        await aio.gather(task, return_exceptions=True)
        eng.close()
        return statuses

    statuses = aio.run(scenario())
    assert statuses[-1]["end_reason"] == "completed"
    events = read_events(tmp_path, statuses[-1]["run_id"])
    start = kinds(events, "run_start")[0]["payload"]
    assert [k["name"] for k in start["lakes"]] == ["Vellmor", "Orsane"] and start["lake"]["capacity"] == 140.0
    assert start["scenario"]["patrol"] is True and {r["payload"]["captain"] for r in kinds(events, "patrol_route")} <= {"PAT", "PAT2"}


def test_the_lakes_and_random_configs_load_and_play(tmp_path):
    for name, lakes, villages in (("lakes", 3, 6), ("random", None, None)):
        cfg = load_config(f"config/{name}.yaml")
        cfg["output"]["runs_dir"], cfg["time"]["fast"], cfg["run"]["seasons"] = str(tmp_path / "runs"), True, 1
        cfg["llm"]["providers"]["scripted"]["latency_scale"] = 0.0
        events = play(tmp_path, f"cfg-{name}", cfg=cfg)
        start = kinds(events, "run_start")[0]["payload"]
        if lakes:
            assert len(start["lakes"]) == lakes and len(start["hamlets"]) == villages and start["population"]["fishers"] == 16
            assert start["scenario"]["patrol"] is True
        else:
            assert len(start["lakes"]) == len(random_valley(cfg["run"]["seed"])["lakes"])
        assert kinds(events, "run_end")
