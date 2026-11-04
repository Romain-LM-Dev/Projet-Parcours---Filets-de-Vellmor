"""Un lac de prédilection, et d'autres si l'on a de bonnes raisons d'y aller : la route est une contrainte (une sortie plus longue, donc moins
de prise, et de quoi la payer) ; le choix vient de la réflexion du pêcheur (IA) ou de son caractère (agent à règles), jamais d'un seuil du
moteur ; le moteur ne fait qu'appliquer ce que la route coûte."""
from __future__ import annotations

import asyncio
import re

import pytest

from filets.config import ROOT
from filets.lakes import LAKE_CENTERS, lake_distance
from filets.policies import lake_choice_rule
from helpers import make_world, read_events
from test_council import fake_game
from test_rumors import Recorder, fisher

BIG_AND_POOR = [{"name": "Vellmor", "capacity": 100, "stock_ratio": 1.0, "villages": ["Ostrel", "Bramois"]},
                {"name": "Orsane", "capacity": 20, "stock_ratio": 0.1, "villages": ["Tilque", "Hennad"]}]
TWO_LAKES_RULES = dict(population__fishers=8, population__rule_fraction=1.0, lake__lakes=BIG_AND_POOR, economy__luck=0.0)


def kinds(events, kind):
    return [e for e in events if e["type"] == kind]


def option(name="Orsane", ratio=1.0, hold=4.0, days=0.6, cost=70.0):
    return {"name": name, "label": f"Lac d'{name}", "est": 100 * ratio, "ratio": ratio, "capacity": 100.0, "fishers": 4,
            "days": days, "factor": round(1 / (1 + 2 * days), 3), "cost": cost, "hold": hold}


# ============================================================ la route
def test_the_distance_between_lakes_is_the_distance_between_their_centres_on_the_map():
    assert lake_distance(2, 0, 0, 1.5) == 0.0
    d = lake_distance(2, 0, 1, 1.5)
    assert d == pytest.approx(0.38 * 1.5) and d == lake_distance(2, 1, 0, 1.5)
    assert lake_distance(2, 0, 1, 3.0) == pytest.approx(2 * d)
    assert lake_distance(3, 0, 2, 1.5) > 0.0 and lake_distance(4, 0, 3, 1.5) > lake_distance(4, 0, 1, 1.5)


def test_the_lake_centres_of_the_engine_are_those_of_the_map():
    """La carte (world_view.gd) pose les lacs aux mêmes centres : sinon la route ne serait pas celle que l'on voit."""
    text = (ROOT / "godot" / "scripts" / "world_view.gd").read_text(encoding="utf-8")
    block = text[text.index("const LAKE_BOXES"):text.index("}", text.index("const LAKE_BOXES"))]
    parts = re.split(r"(?m)^\t(\d): ", block)
    rows = dict(zip(parts[1::2], parts[2::2]))
    for n, centres in LAKE_CENTERS.items():
        found = [(float(x), float(y)) for x, y in re.findall(r"\[Vector2\(([\d.]+), ([\d.]+)\), Vector2", rows[str(n)])]
        assert found == centres, (n, found)


def test_a_longer_outing_catches_less_and_the_road_costs_money(tmp_path):
    world, bus, _ = make_world(tmp_path, "route", population__fishers=8, lake__lakes=BIG_AND_POOR, economy__luck=0.0)
    home, away = world.lakes["Vellmor"], world.lakes["Orsane"]
    days = world.distance(home, away)
    assert days == pytest.approx(0.38 * 1.5) and world.distance(home, home) == 0.0
    assert world.travel_factor(0.0) == 1.0 and world.travel_factor(1.0) == pytest.approx(1 / 3)
    assert world.travel_cost(days) == pytest.approx(10 * 2 * days * 6)
    a = next(f for f in world.fishers if world.lake_of(f) is home)
    here = world.outings(a, 1)
    a.outings.clear()
    there = world.outings(a, 1, lake=away)
    assert [t["yield"] for t in there] == pytest.approx([h["yield"] * world.travel_factor(days) for h in here], abs=0.002)


def test_catching_in_another_lake_empties_that_lake_and_pays_the_road(tmp_path):
    world, bus, _ = make_world(tmp_path, "ailleurs", population__fishers=8, lake__lakes=[{**BIG_AND_POOR[0]}, {**BIG_AND_POOR[1],
                               "stock_ratio": 1.0, "capacity": 100}], economy__luck=0.0)
    home, away = world.lakes["Vellmor"], world.lakes["Orsane"]
    a = next(f for f in world.fishers if world.lake_of(f) is home)
    state = {"stock_estimate": 90.0, "stock_true": 100.0, "quota": None}
    dec = world.events.emit("decision", {"agent": a.id, "agent_kind": "llm", "decision_type": "catch", "info_horizon": 0.0,
                                         "justification": "x", "retrieved": [], "used_event_ids": [], "fallback": False,
                                         "observed": {**state, "lake_estimates": {"Vellmor": 90.0, "Orsane": 77.0},
                                                      "lake_stocks": {"Vellmor": 100.0, "Orsane": 100.0}}}, actor=a.id)
    wealth = a.wealth
    ev = world.apply_catch(a, 3.0, dec, 0.0, lake_name="Orsane")["payload"]
    days = world.distance(home, away)
    assert ev["lake"] == "Orsane" and ev["away"] and ev["home_lake"] == "Vellmor" and ev["zone"] == "large-Orsane"
    assert ev["travel_days"] == pytest.approx(days, abs=0.01) and ev["travel_cost"] == pytest.approx(world.travel_cost(days), abs=0.1)
    assert ev["stock_observed"] == 77.0 and ev["stock_before"] == 100.0 and away.stock < 100.0 and home.stock == 100.0
    assert a.wealth == pytest.approx(wealth + ev["landed"] * 100 - world.travel_cost(days))
    assert ev["landed"] == pytest.approx(3.0 * world.travel_factor(days), abs=0.05)         # la route a pris du temps de pêche
    assert a.lake_choice[world.clock.season_of()] == "Orsane"
    trip = world.trips[world.clock.season_of()][-1]
    assert trip["zone"] == "large-Orsane" and world.zone_lake(trip["zone"]) is away


def test_a_banned_fisher_stays_on_his_own_lake_even_if_he_chose_another(tmp_path):
    world, bus, _ = make_world(tmp_path, "interdit", population__fishers=8, lake__lakes=BIG_AND_POOR)
    a = next(f for f in world.fishers if world.lake_of(f).name == "Vellmor")
    world.banned[a.id] = 1
    dec = world.events.emit("decision", {"agent": a.id, "agent_kind": "llm", "decision_type": "catch", "info_horizon": 0.0,
                                         "justification": "x", "retrieved": [], "used_event_ids": [], "fallback": False,
                                         "observed": {"stock_estimate": 90.0, "stock_true": 100.0, "quota": None}}, actor=a.id)
    ev = world.apply_catch(a, 1.0, dec, 0.0, lake_name="Orsane")["payload"]
    assert ev["lake"] == "Vellmor" and "away" not in ev and world.zone_lake(ev["zone"]) is world.lakes["Vellmor"]


# ============================================================ le choix d'un agent à règles
def test_a_rule_fisher_stays_home_unless_another_lake_pays_clearly_more_after_the_road():
    base = {"boat_capacity": 4.0, "price": 100.0, "lake_options": [option(hold=4.0)], "banned": False}
    assert lake_choice_rule("nouveau_venu", base)[0] is None          # aussi bien ailleurs, route en plus : il reste
    good = {**base, "boat_capacity": 1.0, "lake_options": [option(hold=5.0)]}       # net : 5 × 0,45 − 0,7 = 1,55 t, contre 1
    assert lake_choice_rule("nouveau_venu", good)[0] == "Orsane" and "contre 1.0 t chez lui" in lake_choice_rule("nouveau_venu", good)[1]
    assert lake_choice_rule("ancienne_famille", good)[0] is None          # la famille ancienne est attachée à son lac : il lui faut bien plus
    dear = {**good, "lake_options": [option(hold=5.0, cost=400.0)]}         # une route qui coûte plus que ce qu'on y gagne
    assert lake_choice_rule("nouveau_venu", dear)[0] is None
    empty = {**base, "boat_capacity": 0.0, "lake_options": [option(hold=3.0)]}       # son lac est vide : il part, même attaché
    assert lake_choice_rule("ancienne_famille", empty)[0] == "Orsane" and "vide" in lake_choice_rule("ancienne_famille", empty)[1]
    assert lake_choice_rule("nouveau_venu", {**good, "banned": True})[0] is None and lake_choice_rule("taiseux", {})[0] is None


def test_rule_fishers_of_a_poor_lake_go_to_the_rich_one_and_the_rich_stay(tmp_path):
    world, bus, _ = make_world(tmp_path, "migrent", seasons=2, **TWO_LAKES_RULES)
    asyncio.run(world.run())
    catches = kinds(read_events(tmp_path, "migrent"), "catch")
    first = [e["payload"] for e in catches if e["season"] == 1]
    poor = {a.id for a in world.fishers if world.lake_of(a).name == "Orsane"}
    assert poor and {p["agent"] for p in first if p.get("away")} == poor          # tout le lac pauvre est parti, et lui seul
    assert all(p["lake"] == "Vellmor" for p in first if p["agent"] in poor)
    assert all(not p.get("away") and p["lake"] == "Vellmor" for p in first if p["agent"] not in poor)
    away = next(p for p in first if p.get("away"))
    assert away["travel_cost"] > 0 and away["zone"] == "large-Vellmor"
    decisions = [e["payload"] for e in kinds(read_events(tmp_path, "migrent"), "decision")
                 if e["payload"]["decision_type"] == "catch" and e["season"] == 1 and e["payload"]["agent"] in poor]
    assert all(d["lake"] == "Vellmor" and "il pêche dans le lac de Vellmor" in d["justification"] for d in decisions)


def test_nobody_leaves_a_lake_when_there_is_only_one(tmp_path):
    world, bus, _ = make_world(tmp_path, "un-lac", seasons=2, population__fishers=8, population__rule_fraction=1.0)
    asyncio.run(world.run())
    assert not any(e["payload"].get("away") or "lake" in e["payload"] for e in kinds(read_events(tmp_path, "un-lac"), "catch"))
    assert not any("lake_options" in str(e["payload"].get("observed", "")) for e in kinds(read_events(tmp_path, "un-lac"), "decision"))


# ============================================================ le choix d'une IA
POP = [fisher("Mathis", "Ostrel", "ancienne_famille"), fisher("Inès", "Tilque", "taiseux")]
LAKES = [{"name": "Vellmor", "capacity": 80, "villages": ["Ostrel"]}, {"name": "Orsane", "capacity": 80, "villages": ["Tilque"]}]


def test_an_ai_sees_the_other_lakes_the_road_and_what_it_costs(tmp_path):
    rec = Recorder()
    fake_game(tmp_path, "ia-voit", rec, population=POP, seasons=1, lake__lakes=LAKES, schema=True)
    asks = [r for r in rec.requests if '"prise"' in r["user"] and "Mathis" in r["system"]]
    assert asks
    text = asks[0]["user"]
    assert "Tu pêches d'ordinaire dans le lac de Vellmor, celui de ton village" in text
    assert re.search(r"Lac d'Orsane : d'ici, on le dit à \d+ %", text)
    assert re.search(r"à 0\.6 jour de route, chaque sortie dure 2\.1 fois plus longtemps : tu ramènerais environ 47 %", text)
    assert re.search(r"la route te coûterait 68 écus \(0\.7 t de poisson\) ; tu y viserais jusqu'à [\d.]+ t, soit au mieux [\d.]+ t une fois "
                     r"la route payée \(contre [\d.]+ t au mieux chez toi\)", text)
    assert re.search(r"\"prise\": <tonnes dans le lac que tu choisis : entre [\d.]+ et [\d.]+ chez toi ; jusqu'à [\d.]+ t dans le lac d'Orsane>",
                     text)
    assert "ce que tu constates de ton lac et des autres, ce que coûte la route, et où pêcher en conséquence" in text
    props = asks[0]["response_format"]["json_schema"]["schema"]["properties"]
    assert list(props)[:3] == ["justification", "lac", "prise"] and props["lac"]["enum"] == ["Lac de Vellmor", "Lac d'Orsane"]
    assert '"lac": "<le lac où tu pêches : Lac de Vellmor ou Lac d\'Orsane>"' in text


def test_an_ai_that_chooses_another_lake_fishes_there_and_pays_the_road(tmp_path):
    rec = Recorder(prise=2.0, lake="Lac d'Orsane")
    world, events, _ = fake_game(tmp_path, "ia-va", rec, population=POP, seasons=1, lake__lakes=LAKES, schema=True)
    catches = {e["payload"]["agent"]: e["payload"] for e in kinds(events, "catch")}
    mathis, ines = catches["F01"], catches["F02"]
    assert mathis["lake"] == "Orsane" and mathis["away"] and mathis["zone"] == "large-Orsane" and mathis["home_lake"] == "Vellmor"
    assert ines["lake"] == "Orsane" and not ines.get("away") and ines["zone"] == "Tilque"            # chez elle : pas de route
    chosen = [e["payload"] for e in kinds(events, "decision") if e["payload"]["decision_type"] == "catch"]
    assert {d["agent"]: d.get("lake") for d in chosen} == {"F01": "Orsane", "F02": None}


def test_an_unknown_lake_in_the_answer_means_his_own(tmp_path):
    rec = Recorder(prise=2.0, lake="Lac imaginaire")
    world, events, _ = fake_game(tmp_path, "ia-inconnu", rec, population=POP, seasons=1, lake__lakes=LAKES)
    assert all(not e["payload"].get("away") for e in kinds(events, "catch"))
    assert {e["payload"]["lake"] for e in kinds(events, "catch") if e["payload"]["agent"] == "F01"} == {"Vellmor"}


def test_a_sync_game_counts_the_ration_lake_by_lake_where_each_boat_fished(tmp_path):
    rec = Recorder(prise=7.0, lake="Lac d'Orsane")
    world, events, _ = fake_game(tmp_path, "ia-ration", rec, population=POP, seasons=1, lake__lakes=LAKES)
    landed = sum(e["payload"]["landed"] for e in kinds(events, "catch"))
    assert landed <= 80.0 + 1e-6 and all(e["payload"]["lake"] == "Orsane" for e in kinds(events, "catch"))
    updates = [e["payload"]["lakes"] for e in kinds(events, "lake_update") if e["payload"]["cause"] == "catch"]
    assert updates and all(u["Vellmor"] == 80.0 for u in updates)                 # le lac de départ de Mathis n'a pas été touché


def test_another_better_stocked_lake_calls_for_a_real_thought_not_a_reflex():
    from filets.routing import reasons_to_think

    obs = {"capacity": 100.0, "stock_estimate": 90.0, "stock_history": [{"phase": "pêche", "est": 90.0}], "wealth": 900.0,
           "upkeep": 100.0, "debt_payment": 0.0, "pinned": ["x"], "norms": ["y"]}
    assert reasons_to_think(obs) == []
    assert "un autre lac paraît mieux fourni" in reasons_to_think({**obs, "lake_options": [option(ratio=0.95)]})
    assert "un autre lac paraît mieux fourni" not in reasons_to_think({**obs, "lake_options": [option(ratio=0.4)]})


def test_the_fake_llm_chooses_its_lake_like_a_rule_fisher(tmp_path):
    """Sans IA (faux LLM), les pêcheurs du lac pauvre vont eux aussi pêcher dans le riche : de quoi essayer le jeu et le montrer."""
    world, bus, _ = make_world(tmp_path, "faux-llm", seasons=1, population__fishers=8, population__rule_fraction=0.0,
                               lake__lakes=BIG_AND_POOR, economy__luck=0.0)
    asyncio.run(world.run())
    catches = [e["payload"] for e in kinds(read_events(tmp_path, "faux-llm"), "catch")]
    poor = {a.id for a in world.fishers if world.lake_of(a).name == "Orsane"}
    assert {c["agent"] for c in catches if c.get("away")} == poor and all(c["lake"] == "Vellmor" for c in catches)
