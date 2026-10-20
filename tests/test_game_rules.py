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


# ---------------------------------------------------------------- au moins la moitié
@pytest.mark.parametrize("supporters, adopted", [(4, True), (3, False)])
def test_half_of_the_fishers_present_is_enough_to_adopt_a_rule(tmp_path, supporters, adopted):
    world, asm = world_with_assembly(tmp_path)
    assert len(world.fishers) == 8
    for a in world.fishers[:supporters]:
        speak(world, asm, a, proposition_quota=3.0)
    world.close_assembly(asm)
    assert len(world.norms) == (1 if adopted else 0)
