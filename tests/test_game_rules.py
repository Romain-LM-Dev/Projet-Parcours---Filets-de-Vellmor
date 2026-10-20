"""Deux règles du jeu : une sortie rapporte toujours au moins `economy.min_catch` (on ne revient jamais bredouille), et une
proposition soutenue par au moins la moitié des pêcheurs présents devient une règle."""
from __future__ import annotations

import pytest

from filets.policies import catch_rule
from filets.prompts import catch_levels, catch_messages
from helpers import play
from test_lake_awareness import hist, obs_for
from test_voting import speak, world_with_assembly

PERSONA = type("P", (), {"name": "Théo", "archetype_label": "beau parleur", "hamlet": "Hennad", "experience": 19,
                         "traits": "…", "voice": "…"})()


# ---------------------------------------------------------------- jamais bredouille
def test_no_trip_comes_back_empty(tmp_path):
    catches = [e["payload"] for e in play(tmp_path, run_id="bredouille", seasons=3, time__mode="sync") if e["type"] == "catch"]
    assert catches and all(c["requested"] >= 1.0 and c["landed"] > 0 for c in catches)


@pytest.mark.parametrize("arch", ["ancienne_famille", "nouveau_venu", "taiseux", "beau_parleur"])
def test_rule_fishers_take_at_least_the_minimum_even_from_a_low_lake(arch):
    state = {"stock_estimate": 0.0, "capacity": 100.0, "n_fishers": 8, "quota": None, "boat_capacity": 10.0, "upkeep": 150.0,
             "debt_payment": 120.0, "price": 100.0, "min_catch": 1.0}
    assert catch_rule(arch, state)[0] == 1.0
    assert catch_rule(arch, {**state, "stock_estimate": 40.0, "quota": 0.5})[0] >= 1.0


def test_the_question_tells_the_ai_a_trip_brings_back_the_minimum():
    obs = {**obs_for(38.0, hist(100.0, 70.0)), "min_catch": 1.0}
    text = catch_messages(PERSONA, obs, 100.0)[1]["content"]
    assert "entre 1 et 10" in text and "au moins 1 t" in text and "à quai" not in text
    assert catch_levels(10.0, lo=1.0) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]


def test_a_quota_or_a_promise_below_the_minimum_counts_as_the_minimum(tmp_path):
    world, asm = world_with_assembly(tmp_path)
    a, b = world.fishers[:2]
    speak(world, asm, a, proposition_quota=0.0)
    speak(world, asm, b, promesse=0.0)
    assert [p.quota for p in asm.proposals.values()] == [1.0]
    assert world.promises[(b.id, 2)][0] == 1.0


# ---------------------------------------------------------------- au plus capacité du lac / (2 × pêcheurs)
def test_no_trip_takes_more_than_the_lake_capacity_over_twice_the_fishers(tmp_path):
    events = play(tmp_path, run_id="plafond", seasons=3, time__mode="sync")
    start = events[0]["payload"]
    limit = start["lake"]["capacity"] / (2 * start["population"]["fishers"])
    catches = [e["payload"] for e in events if e["type"] == "catch"]
    assert limit == 6.25 and catches and all(1.0 <= c["requested"] <= limit for c in catches)


def test_a_quota_or_a_promise_above_the_limit_counts_as_the_limit(tmp_path):
    world, asm = world_with_assembly(tmp_path)
    a, b = world.fishers[:2]
    speak(world, asm, a, proposition_quota=9.0)
    speak(world, asm, b, promesse=8.0)
    assert world.max_catch == 6.25
    assert [p.quota for p in asm.proposals.values()] == [6.25]
    assert world.promises[(b.id, 2)][0] == 6.25


def test_the_ai_is_told_the_limit_of_a_trip():
    obs = {**obs_for(38.0, hist(100.0, 70.0)), "min_catch": 1.0, "boat_capacity": 6.25}
    text = catch_messages(PERSONA, obs, 100.0)[1]["content"]
    assert "au plus 6.25 t" in text and "entre 1 et 6.25" in text


# ---------------------------------------------------------------- la règle votée, rappelée au moment de pêcher
def test_the_question_reminds_the_fisher_of_the_rule_the_valley_voted():
    obs = {**obs_for(70.0, hist(100.0, 80.0)), "min_catch": 1.0, "rule": {"quota": 2.0, "supported": True, "visible": True}}
    ask = catch_messages(PERSONA, obs, 100.0)[1]["content"].split("C'est le moment de décider")[1]
    assert "Règle votée à la veillée : pas plus de 2 t par pêcheur cette saison (tu l'as soutenue)" in ask
    assert "les autres le verront au marché" in ask and "ce que tu fais de la règle votée" in ask
    assert ask.index("Règle votée") < ask.index("Réponds en JSON")       # juste avant la question, là où les petits modèles lisent
    hidden = catch_messages(PERSONA, {**obs, "rule": {"quota": 2.0, "supported": False, "visible": False}}, 100.0)[1]["content"]
    assert "tu ne l'as pas soutenue" in hidden and "au marché" not in hidden      # prises cachées : personne ne le verra
    assert "Règle votée" not in catch_messages(PERSONA, {**obs, "rule": None}, 100.0)[1]["content"]


def test_each_fisher_knows_the_rule_in_force_and_whether_they_supported_it(tmp_path):
    import asyncio

    world, asm = world_with_assembly(tmp_path)
    for a in world.fishers[:4]:
        speak(world, asm, a, proposition_quota=3.0)
    world.close_assembly(asm)
    supporter, other = world.fishers[0], world.fishers[7]
    horizon = world.clock.season_start(2) + 0.25
    seen = [asyncio.run(world.observe(a, horizon, "catch"))[0]["rule"] for a in (supporter, other)]
    assert seen == [{"quota": 3.0, "supported": True, "visible": True}, {"quota": 3.0, "supported": False, "visible": True}]


# ---------------------------------------------------------------- au moins la moitié
@pytest.mark.parametrize("supporters, adopted", [(4, True), (3, False)])
def test_half_of_the_fishers_present_is_enough_to_adopt_a_rule(tmp_path, supporters, adopted):
    world, asm = world_with_assembly(tmp_path)
    assert len(world.fishers) == 8
    for a in world.fishers[:supporters]:
        speak(world, asm, a, proposition_quota=3.0)
    world.close_assembly(asm)
    assert len(world.norms) == (1 if adopted else 0)
