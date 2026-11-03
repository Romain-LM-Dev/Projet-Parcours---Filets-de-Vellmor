"""Les types de règle du conseil : quota, reserve (une zone interdite), repos (un lac fermé), sorties (au plus N par saison), bateau
(taille maximale). Une règle = un type + une valeur + une cible + une saison d'effet. Le moteur applique la physique (ce que la règle
change quand on la respecte, comment une infraction se voit) ; respecter ou non reste le choix de l'agent."""
from __future__ import annotations

import asyncio
from collections import Counter

import pytest

from filets import rules
from filets.policies import catch_rule, propose_rule, speak_rule
from filets.world import Assembly
from helpers import make_world, play
from test_voting import Said


def room(tmp_path, run_id="rules", **over):
    world, bus, _ = make_world(tmp_path, run_id, population__fishers=8, population__rule_fraction=0.0, time__mode="sync", **over)
    return world, Assembly("valley", [a.id for a in world.agents.values()], 0, 29.0)      # saison 0 : la règle vaut dès la saison 1


def say(world, asm, agent, **data):
    base = {"message": "Voici.", "destinataire": "tous", "soutien": None, "promesse": None, "accuse": None}
    world.post_utterance(agent, asm, Said(world, agent, **{**base, **data}), 1, world.clock.now())


def adopt(world, asm, n=5, **proposal):
    """Le conseil adopte une règle : `n` pêcheurs la proposent (ou la soutiennent), la veillée se clôt."""
    for a in world.fishers[:n]:
        say(world, asm, a, **proposal)
    world.close_assembly(asm)
    return world.norms[-1]


def decision(world, agent, **extra):
    payload = {"agent": agent.id, "observed": {"stock_estimate": 100.0, "stock_true": 100.0}, **extra}
    return {"event_id": "d0", "payload": payload}


def go(world, agent, requested, **extra):
    return world.apply_catch(agent, requested, decision(world, agent, **extra), world.clock.now())["payload"]


def full_lake(world):
    for lake in world.lakes.values():
        lake.stock = lake.capacity
    world.season_stock = {n: lk.stock for n, lk in world.lakes.items()}


def hamlet_mates(world):
    """Deux pêcheurs du même village (même zone de pêche)."""
    by = {}
    for f in world.fishers:
        by.setdefault(f.profile.hamlet, []).append(f)
    return next(v for v in by.values() if len(v) >= 2)


# ============================================================ chaque type adopté, et sa physique
def test_a_reserve_is_adopted_with_its_zone_and_duration_and_a_fisher_who_respects_it_fishes_elsewhere(tmp_path):
    world, asm = room(tmp_path)
    a = world.fishers[0]
    n = adopt(world, asm, proposition_type="reserve", proposition_valeur=2, proposition_cible=a.profile.hamlet)
    assert (n.kind, n.target, n.value, n.effective_season, n.until) == ("reserve", a.profile.hamlet, 2.0, 1, 2)
    assert world.rule_view(a, 2, 0.0)["reserved"] == {a.profile.hamlet} and not world.rule_view(a, 3, 0.0)["reserved"]   # elle s'éteint
    adopted = [e for e in world.events.index.values() if e["type"] == "norm_adopted"][-1]["payload"]
    assert adopted["kind"] == "reserve" and adopted["until_season"] == 2 and adopted["duration"] == 2 and "rive de" in adopted["text"]
    full_lake(world)
    ev = go(world, a, 2.0, place="large")                        # il quitte sa rive
    assert ev["zone"] == "large" and "breach" not in ev and ev["landed"] > 0
    sector = world.sectors[a.profile.hamlet and world.lake_of(a).name].get(a.profile.hamlet, [])
    cell = next(k for k, p in enumerate(world.lake_of(a).parcels) if [p["i"], p["j"]] == ev["cell"])
    assert len(world.sectors[world.lake_of(a).name]) < 2 or cell not in sector       # et pas dans le coin réservé, même au large
    b = hamlet_mates(world)[1] if hamlet_mates(world)[0] is a else a
    assert world.rule_view(b, 1, 0.0)["reserved"] == ({a.profile.hamlet} if b.profile.hamlet == a.profile.hamlet else set())


def test_fishing_the_reserved_shore_anyway_is_a_breach_the_event_and_the_trip_record(tmp_path):
    world, asm = room(tmp_path)
    a = world.fishers[0]
    adopt(world, asm, proposition_type="reserve", proposition_valeur=1, proposition_cible=a.profile.hamlet)
    full_lake(world)
    ev = go(world, a, 2.0, place="rive")
    assert ev["zone"] == a.profile.hamlet and ev["breach"] == ["reserve"]
    assert world.trips[1][-1]["breach"] == ["reserve"] and world.cheated(a.id, 1)


def test_a_lake_at_rest_is_closed_a_breach_only_if_you_fish_it(tmp_path):
    world, asm = room(tmp_path)
    a, b = world.fishers[0], world.fishers[1]
    lake = world.lake_of(a).name
    n = adopt(world, asm, proposition_type="repos", proposition_valeur=1, proposition_cible=lake)
    assert (n.kind, n.target, n.until) == ("repos", lake, 1)
    full_lake(world)
    assert go(world, a, 2.0)["breach"] == ["repos"]               # il y pêche quand même
    assert "breach" not in go(world, b, 0.0)                      # lui reste à quai : rien à reprocher
    obs, state, _, _ = asyncio.run(world.observe(a, world.clock.now(), "catch"))
    assert state["lake_closed"] and state["min_catch"] == 0.0 and "repos du lac" in " ".join(obs["norms"])
    assert world.rule_view(a, 2, 0.0)["closed"] == set()          # une saison de repos, puis le lac rouvre


def test_limited_outings_mean_a_smaller_catch_and_more_outings_than_allowed_is_a_breach(tmp_path):
    world, asm = room(tmp_path)
    a, b = world.fishers[0], world.fishers[1]
    n = adopt(world, asm, proposition_type="sorties", proposition_valeur=2)
    assert (n.kind, n.value, n.target, n.until) == ("sorties", 2.0, None, None)
    full_lake(world)
    for f in (a, b):
        f.outings[1] = [{"day": 1.0 + i, "weather": "ordinaire", "luck": 1.0, "yield": 1.0} for i in range(6)]
    kept = go(world, a, 3.0, outings=2)
    assert len(kept["outings"]) == 2 and kept["landed"] == pytest.approx(3.0 * 2 / 6, abs=0.02) and "breach" not in kept
    broke = go(world, b, 3.0, outings=6)
    assert len(broke["outings"]) == 6 and broke["landed"] == pytest.approx(3.0, abs=0.02) and broke["breach"] == ["sorties"]


def test_a_boat_size_limit_caps_the_big_boats_hold_and_a_bigger_catch_is_a_breach(tmp_path):
    world, asm = room(tmp_path)
    a = world.fishers[0]
    n = adopt(world, asm, proposition_type="bateau", proposition_valeur=1)           # 1 : la barque (4 t)
    assert (n.kind, n.value) == ("bateau", 1.0)
    full_lake(world)
    assert world.rule_view(a, 1, 0.0)["boat_limit"] == 4.0                          # sa chaloupe (7 t) est plus grosse
    assert "barque" in world.norm_words(n) and "4 t" in world.norm_words(n)
    assert "breach" not in go(world, a, 3.0)
    b = world.fishers[1]
    assert go(world, b, 6.0)["breach"] == ["bateau"]


def test_a_quota_keeps_working_as_before_and_the_old_field_is_still_read(tmp_path):
    world, asm = room(tmp_path)
    n = adopt(world, asm, proposition_quota=3.0)
    assert (n.kind, n.quota, n.target, n.until) == ("quota", 3.0, None, None)
    assert world.applicable_norm(world.fishers[0], 1, 0.0) is n


def test_a_new_quota_replaces_only_the_old_quota_not_the_other_types(tmp_path):
    world, asm = room(tmp_path)
    adopt(world, asm, proposition_type="sorties", proposition_valeur=3)
    asm2 = Assembly("valley", asm.participants, 0, 29.0)
    adopt(world, asm2, proposition_type="quota", proposition_valeur=2.5)
    kinds = {k for k, _ in world.rules_for(world.fishers[0], 1, 0.0)}
    assert kinds == {"sorties", "quota"}


# ============================================================ une violation se voit
def test_a_breach_is_seen_by_the_neighbours_and_established_by_the_elder(tmp_path):
    world, asm = room(tmp_path, scenario__detection={"witness": 1.0, "proof": 1.0})
    a, b = hamlet_mates(world)[:2]
    adopt(world, asm, proposition_type="sorties", proposition_valeur=2)
    full_lake(world)
    for f in (a, b):
        f.outings[1] = [{"day": 1.0 + i, "weather": "ordinaire", "luck": 1.0, "yield": 1.0} for i in range(6)]
    go(world, a, 3.0, outings=6)                                  # il en fait trop
    go(world, b, 3.0, outings=2)                                  # son voisin joue le jeu : il est témoin, et dit ce qu'il a vu
    world.investigate(1)
    world.weigh_evidence(1)
    clues = [c for c in world.clues if c["subject"] == a.id and c["kind"] == "temoin" and c["observer"] == b.id]
    assert clues and clues[0]["public"]
    found = world.established[(a.id, 1)]
    assert found["breach"] == ["sorties"] and not found["secret"]
    ev = [e for e in world.events.index.values() if e["type"] == "lie_discovered"][-1]["payload"]
    assert ev["agent"] == a.id and ev["breach"] == ["sorties"] and not ev["wrongful"]
    assert any("enfreint" in m.text for m in b.memory.items if m.kind == "mensonge")           # chacun s'en souvient, dit comme une règle enfreinte
    facts = world.narrator_facts(1)
    assert any("enfreinte par" in f and "sorties" in f for f in facts)                         # le narrateur sait qui


# ============================================================ une proposition par type et par cible
def test_two_proposals_merge_only_with_the_same_type_and_target(tmp_path):
    world, asm = room(tmp_path)
    f = world.fishers
    say(world, asm, f[0], proposition_type="quota", proposition_valeur=3.0)
    say(world, asm, f[1], proposition_type="sorties", proposition_valeur=3)               # même nombre, autre type : à part
    say(world, asm, f[2], proposition_type="reserve", proposition_valeur=1, proposition_cible=world.hamlets[0])
    say(world, asm, f[3], proposition_type="reserve", proposition_valeur=1, proposition_cible=world.hamlets[1])   # autre cible : à part
    say(world, asm, f[4], proposition_type="reserve", proposition_valeur=1, proposition_cible=world.hamlets[0])   # même cible : rejoint
    say(world, asm, f[5], proposition_quota=3.3)                                                                  # quota proche : rejoint
    assert Counter(p.kind for p in asm.proposals.values()) == {"quota": 1, "sorties": 1, "reserve": 2}
    pid = {p.key: p.id for p in asm.proposals.values()}
    assert asm.support[f[4].id][0] == pid[("reserve", world.hamlets[0])] and asm.support[f[5].id][0] == pid[("quota", None)]


def test_the_closing_vote_only_compares_inside_the_same_type(tmp_path):
    world, asm = room(tmp_path)
    f = world.fishers
    say(world, asm, f[0], proposition_type="sorties", proposition_valeur=3)
    say(world, asm, f[1], proposition_type="quota", proposition_valeur=3.0)
    for a in f[2:7]:
        say(world, asm, a, promesse=3.0)                         # des promesses de 3 t : voisines du quota de 3, pas des 3 sorties
    world.close_assembly(asm)
    n = world.norms[-1]
    assert n.kind == "quota" and len(n.supporters) == 6 and f[0].id not in n.supporters


def test_a_proposal_that_makes_no_sense_is_dropped(tmp_path):
    world, asm = room(tmp_path)
    for data in ({"proposition_type": "sorties", "proposition_valeur": 99}, {"proposition_type": "bateau", "proposition_valeur": 3},
                 {"proposition_type": "inconnu", "proposition_valeur": 2}, {"proposition_type": "reserve", "proposition_valeur": None}):
        say(world, asm, world.fishers[0], **data)
    assert not asm.proposals


# ============================================================ les agents choisissent le type selon la situation
STATE = {"stock_estimate": 60.0, "capacity": 100.0, "n_fishers": 8, "growth_rate": 0.0, "round": 1, "min_catch": 0.0,
         "upkeep": 30.0, "debt_payment": 0.0, "price": 100.0, "wealth": 500.0, "boat_capacity": 6.0, "outings_n": 6,
         "lake_target": "Vellmor", "own_zone": "Hennad", "boat_names": ["barque", "chaloupe", "cotre"]}


def proposed(archetype, **over):
    out, _ = speak_rule(archetype, {**STATE, **over})
    return out["proposition_type"]


def test_rule_agents_pick_the_type_the_situation_calls_for():
    assert proposed("ancien") == "quota" and proposed("beau_parleur") == "quota"            # rien de particulier : un quota
    assert proposed("ancien", stock_estimate=30.0) == "repos"                               # un lac bas
    assert proposed("ancien", hot_zone="Tilque") == "reserve"                               # un coin trop pêché
    assert proposed("beau_parleur", hot_zone="Tilque") == "reserve"
    assert proposed("beau_parleur", big_boats=3) == "bateau"                                # de gros bateaux
    # la famille ancienne et le nouveau venu attendent d'avoir entendu les autres (2e tour), et ne parlent que s'il y a de quoi
    assert proposed("ancienne_famille", stock_estimate=30.0, round=2) == "repos" and proposed("ancienne_famille", round=2) is None
    assert proposed("ancienne_famille", stock_estimate=30.0) is None
    assert proposed("nouveau_venu", big_boats=3, round=2) == "bateau" and proposed("taiseux", stock_estimate=30.0, round=2) is None
    assert proposed("ancien", stock_estimate=30.0, rule_kinds=["repos"]) != "repos"         # pas deux fois la même règle
    out, _ = speak_rule("ancien", {**STATE, "hot_zone": "Tilque"})
    assert out["proposition_valeur"] == 1.0 and out["proposition_cible"] == "Tilque" and "Tilque" in out["message"]


def test_a_seeded_fake_llm_draws_varied_types():
    import random
    rng = random.Random(7)
    kinds = {propose_rule("ancien", {**STATE, "stock_estimate": 45.0, "hot_zone": "Tilque", "big_boats": 3}, rng)[0] for _ in range(40)}
    assert len(kinds) >= 3


def test_rule_agents_obey_or_cheat_according_to_their_character():
    s = {**STATE, "stock_estimate": 40.0, "lake_closed": True}
    assert catch_rule("ancienne_famille", s)[0] == 0.0 and catch_rule("beau_parleur", s)[0] == 0.0       # restent à quai
    assert catch_rule("taiseux", s)[0] > 0                                                                # le taiseux triche
    assert catch_rule("taiseux", {**s, "exposed": True})[0] == 0.0                                        # sauf s'il vient d'être pris
    assert catch_rule("nouveau_venu", {**s, "wealth": 0.0})[0] > 0                                        # l'endetté aussi
    lim = {**STATE, "stock_estimate": 90.0, "boat_limit": 4.0}
    assert catch_rule("ancienne_famille", lim)[0] <= 4.0 and catch_rule("taiseux", lim)[0] > 4.0


def test_the_words_of_a_rule_follow_its_type(tmp_path):
    world, _ = room(tmp_path)
    assert "3 t par pêcheur" in world.rule_words("quota", 3.0)
    assert "interdit de pêcher sur la rive de" in world.rule_words("reserve", 2.0, world.hamlets[0])
    assert "repos du lac" in world.rule_words("repos", 1.0, world.lake.name)
    assert "au plus 3 sorties" in world.rule_words("sorties", 3.0)
    assert "chaloupe" in world.rule_words("bateau", 2.0)
    assert rules.words("sorties", 1.0) == "au plus 1 sortie en mer par pêcheur et par saison"


# ============================================================ une partie scriptée entière
def test_a_scripted_game_of_six_seasons_adopts_at_least_two_different_types(tmp_path):
    events = play(tmp_path, "six", seasons=6, population__fishers=8, population__rule_fraction=0.0, time__mode="sync",
                  economy__luck=0.3)
    adopted = [e["payload"] for e in events if e["type"] == "norm_adopted"]
    assert len({p["kind"] for p in adopted}) >= 2, [p.get("text") for p in adopted]
    assert all(p.get("text") for p in adopted)
    breaches = [e for e in events if e["type"] == "catch" and e["payload"].get("breach")]
    for e in breaches:                                                       # (une infraction nomme toujours des types connus)
        assert set(e["payload"]["breach"]) <= {"reserve", "repos", "sorties", "bateau"}
