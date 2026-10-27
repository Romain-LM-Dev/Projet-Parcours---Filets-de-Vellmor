"""Le conseil de la vallée : un élu par village, la patrouille du lac votée par le conseil, et les deux façons de dialoguer.

* Chaque village choisit son élu à chaque saison. Seuls les élus (et l'ancien) vont au conseil ; les autres villageois en
  apprennent les décisions et en jugent. Chacun vote et juge par sa propre réflexion (un bulletin à l'IA, un caractère à l'agent
  à règles), jamais par un seuil du moteur : le moteur ne fait que compter.
* La patrouille du lac remplace le radar : le conseil la vote s'il juge qu'il faut démasquer des fraudes ; l'ancien décide de sa
  route de la saison ; elle coûte à chaque pêcheur.
* Synchrone : on parle à tour de rôle et chacun entend les précédents (dialogues dépendants). Asynchrone : chacun s'exprime de son
  côté, sans rien entendre des autres, puis tous votent (dialogues indépendants).
"""
from __future__ import annotations

import asyncio
import re

import pytest

from filets.bus import LocalBus
from filets.policies import elect_rule, patrol_vote
from filets.world import World
from helpers import cfg_for, make_world, read_events
from test_rumors import Recorder, fisher

TWO_VILLAGES = [fisher("Mathis", "Ostrel", "ancienne_famille"), fisher("Inès", "Ostrel", "nouveau_venu"),
                fisher("Elwen", "Tilque", "taiseux"), fisher("Théo", "Tilque", "beau_parleur")]
THREE_VILLAGES = TWO_VILLAGES + [fisher("Rémi", "Hennad", "nouveau_venu")]
IDS = {"Mathis": "F01", "Inès": "F02", "Elwen": "F03", "Théo": "F04", "Rémi": "F05"}


def kinds(events, kind):
    return [e for e in events if e["type"] == kind]


def fake_game(tmp_path, run_id, rec, population=TWO_VILLAGES, seasons=2, mode="sync", elder=False, **over):
    """Une partie dont toutes les IA (grand et petit modèle) sont `rec`, un faux fournisseur qui enregistre ce qu'on lui demande."""
    cfg = cfg_for(tmp_path, seasons=seasons, population__custom=population, population__elder=elder,
                  population__elder_kind="llm", time__mode=mode, **over)
    cfg["llm"]["providers"]["fake"] = {"base_url": rec.url, "api_key_env": None, "rpm": 0}
    cfg["llm"]["tiers"] = {"grand": {"provider": "fake", "model": "m"}, "petit": {"provider": "fake", "model": "m"}}
    bus = LocalBus()
    dead = []
    bus.subscribe("deadletter", dead.append)
    world = World(cfg, bus, run_id)
    asyncio.run(world.run())
    rec.close()
    return world, read_events(tmp_path, run_id), dead


def speeches(rec):
    """Les demandes de parole à la veillée, dans l'ordre où elles ont été faites."""
    return [r["user"] for r in rec.requests if "Veillée chez l'ancien" in r["user"]]


def transcript_lines(user):
    """Les paroles que cette demande de parole fait entendre à l'agent (rien si elles ne sont pas montrées)."""
    m = re.search(r"Ce qui a déjà été dit ce soir :\n(.*?)\n\nPropositions de règle", user, re.S)
    return [] if m is None else [x for x in m.group(1).splitlines() if x.startswith("- ") and "«" in x]


# ============================================================ le conseil des élus
def test_each_village_elects_one_representative(tmp_path):
    world, bus, _ = make_world(tmp_path, "elus", population__fishers=8, population__rule_fraction=1.0)
    got = []
    bus.subscribe("events", got.append)
    asyncio.run(world.prepare_season(1))
    assert sorted(world.reps) == sorted(world.hamlets) and len(world.reps) == 4
    for village, aid in world.reps.items():
        assert world.agents[aid].profile.hamlet == village
    council = world.council_members(1)
    assert council[0] == "ANC" and sorted(council[1:]) == sorted(world.reps.values())      # l'ancien ouvre, puis un élu par village
    elections = [e["payload"] for e in got if e["type"] == "election"]
    assert len(elections) == 4 and all(sum(p["votes"].values()) == p["voters"] == 2 for p in elections)


def test_only_the_elected_speak_and_the_others_still_hear_the_rule(tmp_path):
    world, bus, _ = make_world(tmp_path, "conseil", seasons=2, time__mode="sync", population__fishers=8)
    asyncio.run(world.run())
    events = read_events(tmp_path, "conseil")
    for season in (1, 2):
        sitting = {e["payload"]["representative"] for e in kinds(events, "election") if e["payload"]["season"] == season}
        start = next(e["payload"] for e in kinds(events, "assembly_start") if e["season"] == season)
        assert set(start["participants"]) == sitting | {"ANC"} and set(start["delegates"].values()) == sitting
        assert {e["payload"]["speaker"] for e in kinds(events, "utterance") if e["season"] == season} <= set(start["participants"])
        adopted = [e["payload"] for e in kinds(events, "norm_adopted") if e["season"] == season]
        assert adopted and set(adopted[0]["supporters"]) <= sitting          # seuls les élus soutiennent, donc votent
    sat = {e["payload"]["representative"] for e in kinds(events, "election") if e["payload"]["season"] == 1}
    absent = [a for a in world.fishers if a.id not in sat]
    assert len(absent) == 4
    assert all(any(m.kind == "regle" for m in a.memory.items) for a in absent)     # un villageois absent apprend la règle quand même
    assert not [e for e in kinds(events, "utterance") if e["season"] == 1 and e["payload"]["speaker"] in {a.id for a in absent}]


def test_the_agreement_counts_the_fishers_an_elected_delegate_speaks_for(tmp_path):
    """Seuls les élus soutiennent une règle, mais chaque pêcheur compte comme l'ayant soutenue si l'élu de son village l'a fait."""
    from filets.indicators import IndicatorEngine

    world, bus, _ = make_world(tmp_path, "accord", seasons=3, time__mode="sync", population__fishers=8)
    asyncio.run(world.run())
    eng = IndicatorEngine(world.cfg["scenario"]["quota_tolerance"])
    ends = [o["values"] for o in (eng.ingest(e) for e in read_events(tmp_path, "accord")) if o and o["trigger"] == "season_end"]
    adopted = kinds(read_events(tmp_path, "accord"), "norm_adopted")
    assert adopted and all(p["payload"]["delegates"] for p in adopted)
    for season, values in enumerate(ends, 1):
        under = [p["payload"] for p in adopted if p["payload"]["effective_season"] <= season]
        if not under:
            continue
        norm = under[-1]
        represented = [a for a in world.fishers if a.id in norm["supporters"]
                       or norm["delegates"].get(a.profile.hamlet) in norm["supporters"]]
        assert values["norm_supporters"] == len(represented) > len(norm["supporters"])        # un élu parle pour son village


def test_the_council_can_be_everyone_again(tmp_path):
    world, bus, _ = make_world(tmp_path, "tous", seasons=1, time__mode="sync", population__fishers=8, scenario__council="all")
    asyncio.run(world.run())
    events = read_events(tmp_path, "tous")
    assert not kinds(events, "election")
    assert set(kinds(events, "assembly_start")[0]["payload"]["participants"]) == set(world.agents)


def test_a_villager_votes_by_reflection_not_by_a_threshold(tmp_path):
    """L'élu est celui que chaque électeur choisit sur son bulletin (sa confiance, son caractère, ses intérêts) : le moteur compte."""
    rec = Recorder(elect={"Mathis": "Mathis", "Inès": "Mathis", "Elwen": "Théo", "Théo": "Théo"})
    world, events, _ = fake_game(tmp_path, "bulletins", rec, seasons=1)
    elections = {e["payload"]["hamlet"]: e["payload"] for e in kinds(events, "election")}
    assert elections["Ostrel"]["representative"] == IDS["Mathis"] and elections["Tilque"]["representative"] == IDS["Théo"]
    assert elections["Ostrel"]["ballots"] == {IDS["Mathis"]: IDS["Mathis"], IDS["Inès"]: IDS["Mathis"]}
    ballots = [r["user"] for r in rec.requests if "Pour qui votes-tu" in r["user"]]
    assert len(ballots) == 4 and all("Ta confiance" in b or "toi-même" in b for b in ballots)
    assert all("ans de pêche" in b and "Tes finances" in b for b in ballots)         # son caractère et sa situation y figurent


def test_a_rule_agent_votes_by_its_rule_for_the_one_it_trusts_most():
    assert elect_rule({"F02": 0.7, "F03": 0.4}, {"F02": 5, "F03": 30}, "F01") == "F02"
    assert elect_rule({"F02": 0.5, "F03": 0.5}, {"F02": 5, "F03": 30}, "F01") == "F03"      # à égalité, l'expérience
    assert elect_rule({}, {}, "F01") == "F01"                                                # seul dans son village : lui-même


def test_a_villager_who_stayed_home_judges_what_the_elder_reports(tmp_path):
    """Les absents jugent à la reprise : leur confiance bouge de ce qu'ils disent eux-mêmes (de −3 à +3 dixièmes)."""
    rec = Recorder(elect={"Mathis": "Mathis", "Inès": "Mathis", "Elwen": "Théo", "Théo": "Théo"},
                   debrief={IDS["Théo"]: -2})
    world, events, _ = fake_game(tmp_path, "absents", rec, seasons=2)
    judged = [e["payload"] for e in kinds(events, "trust") if e["payload"]["by"] in (IDS["Inès"], IDS["Elwen"])
              and e["payload"]["subject"] == IDS["Théo"] and e["payload"]["cause"].startswith("jugement de")]
    assert {p["by"] for p in judged} == {IDS["Inès"], IDS["Elwen"]} and all(p["delta"] == -0.2 for p in judged)
    assert any("Tu n'étais pas au conseil" in r["user"] and "le conseil" in r["user"] for r in rec.requests)


def test_a_banned_fisher_cannot_be_elected(tmp_path):
    world, bus, _ = make_world(tmp_path, "banni", population__fishers=8, population__rule_fraction=1.0)
    banned = world.fishers[0]
    world.banned[banned.id] = 1
    for v in world.fishers:                                  # tout son village lui fait pourtant confiance
        if v.profile.hamlet == banned.profile.hamlet and v is not banned:
            world.trust[v.id][banned.id] = 0.99
    asyncio.run(world.prepare_season(2))
    assert world.reps[banned.profile.hamlet] != banned.id


# ============================================================ la patrouille du lac
def test_the_council_installs_a_patrol_and_its_captain_chooses_the_route(tmp_path):
    rec = Recorder(speech={"patrouille": "installer"}, route=[("Tilque", 8)], elect={"Mathis": "Mathis", "Inès": "Mathis"})
    world, events, _ = fake_game(tmp_path, "patrouille", rec, seasons=3, elder=True)
    [vote] = [e["payload"] for e in kinds(events, "sanction_result") if e["payload"]["action"] == "patrouille"][:1]
    assert vote["adopted"] and vote["target"] == ""
    [installed] = [e["payload"] for e in kinds(events, "patrol") if e["payload"]["state"] == "installed"][:1]
    assert installed["effective_season"] == 2 and installed["cost"] == 15
    routes = {e["payload"]["season"]: e["payload"] for e in kinds(events, "patrol_route")}
    assert 1 not in routes and routes[2]["legs"][0]["zone"] == "Tilque" and routes[2]["by"] == "patrouille"
    assert routes[2]["legs"][0]["days"] == 8 and routes[2]["why"] and routes[2]["legs"][0]["follow"] is None
    # elle coûte à chaque pêcheur, dès la saison où elle sort
    a = world.fishers[0]
    assert world.upkeep(a, 2) - world.upkeep(a, 1) == 15
    # et ceux qui pêchent ne l'ignorent pas
    assert any("patrouille du lac mesure" in r["user"] for r in rec.requests if '"prise"' in r["user"])


def test_the_captain_rule_route_takes_over_when_his_ai_says_nothing(tmp_path):
    rec = Recorder(speech={"patrouille": "installer"}, route=None)
    world, events, _ = fake_game(tmp_path, "route-repli", rec, seasons=2, elder=True)
    [route] = [e["payload"] for e in kinds(events, "patrol_route")]
    assert route["by"].endswith("(règle)") and route["legs"][0]["zone"] in world.zones


def test_the_captain_can_follow_a_suspect_and_never_exceeds_his_days_at_sea(tmp_path):
    rec = Recorder(speech={"patrouille": "installer"}, route=[("F03", 5), ("Ostrel", 99), ("F03", 2), ("Narnia", 3)])
    world, events, _ = fake_game(tmp_path, "suivi", rec, seasons=2, elder=True)
    [route] = [e["payload"] for e in kinds(events, "patrol_route")]
    legs = route["legs"]
    assert legs[0]["follow"] == "F03" and legs[0]["zone"] == world.agents["F03"].profile.hamlet     # sur les talons de F03
    assert sum(leg["days"] for leg in legs) <= world.patrol_cfg["days"] and len({leg["follow"] or leg["zone"] for leg in legs}) == len(legs)
    assert all(a["to_day"] <= b["from_day"] for a, b in zip(legs, legs[1:])) and legs[-1]["to_day"] <= 20.0    # l'une après l'autre
    # suivre un pêcheur, c'est le croiser où qu'il pêche
    assert world.patrolled(2, "large", [legs[0]["from_day"] + 1.0], "F03") == 1.0 and world.patrolled(2, "large", [legs[0]["from_day"] + 1.0]) == 0.0


def test_the_captain_reads_what_the_valley_shared(tmp_path):
    rec = Recorder(speech={"patrouille": "installer"}, route=[("Tilque", 6)])
    world, events, _ = fake_game(tmp_path, "dossier", rec, seasons=3, elder=True)
    asked = [r["user"] for r in rec.requests if '"etapes"' in r["user"]]
    assert asked and all("Tilque :" in u and "large :" in u and "Ce que tu as relevé toi-même" in u for u in asked)
    assert "rien encore" in asked[0]                                                     # la première sortie : rien relevé encore
    if len(asked) > 1:
        assert "Saison 2 : je suis allé vers" in asked[1]                                # ensuite, il se souvient de sa route
    dossier = chr(10).join(world.patrol_dossier(3))
    assert all(a.id in dossier for a in world.fishers if a.id not in world.banned)       # chaque pêcheur est dans son village
    me = world.patrol_agent
    assert me.profile.role == "patrouille" and me.id == "PAT" and me.id not in world.agents and any(m.kind == "patrouille" for m in me.memory.items)


def test_a_patrol_that_is_switched_off_does_not_exist(tmp_path):
    rec = Recorder(speech={"patrouille": "installer"}, route=[("Tilque", 6)])
    world, events, _ = fake_game(tmp_path, "sans-patrouille", rec, seasons=3, elder=True, scenario__patrol={"enabled": False})
    assert world.patrol_agent is None and not world.patrol_active(2) and not world.patrol_exists()
    assert not kinds(events, "patrol") and not kinds(events, "patrol_route")
    assert not [e for e in kinds(events, "sanction_proposal") if e["payload"]["action"] in ("patrouille", "fin_patrouille")]
    a = world.fishers[0]
    assert world.upkeep(a, 2) == world.upkeep(a, 1)                                      # aucun coût
    speaking = [r["user"] for r in rec.requests if "Veillée chez l'ancien" in r["user"]]
    assert speaking and not any("patrouille" in u.lower() for u in speaking)             # personne ne la propose, personne n'en parle
    assert kinds(events, "run_start")[0]["payload"]["scenario"]["patrol"] is False


def test_the_council_can_lift_the_patrol(tmp_path):
    rec = Recorder(speech={"patrouille": "retirer"})
    world, events, _ = fake_game(tmp_path, "retrait", rec, seasons=3, scenario__patrol={"cost": 15, "from_season": 1})
    lifted = [e["payload"] for e in kinds(events, "patrol") if e["payload"]["state"] == "lifted"]
    assert lifted and lifted[0]["effective_season"] == 2
    assert [e["payload"]["season"] for e in kinds(events, "patrol_route")] == [1]       # elle sort encore la saison du vote, plus après
    a = world.fishers[0]
    assert world.upkeep(a, 1) > world.upkeep(a, 2)


def test_a_patrol_motion_is_not_proposed_for_a_patrol_that_already_exists(tmp_path):
    rec = Recorder(speech={"patrouille": "installer"})
    world, events, _ = fake_game(tmp_path, "double", rec, seasons=2, scenario__patrol={"cost": 15, "from_season": 1})
    assert not [e for e in kinds(events, "sanction_proposal") if e["payload"]["action"] == "patrouille"]


def test_rule_agents_want_a_patrol_according_to_their_character():
    assert patrol_vote("ancienne_famille", 1, "patrouille") and not patrol_vote("ancienne_famille", 0, "patrouille")
    assert not patrol_vote("taiseux", 5, "patrouille") and patrol_vote("taiseux", 5, "fin_patrouille")
    assert not patrol_vote("nouveau_venu", 2, "patrouille") and patrol_vote("nouveau_venu", 3, "patrouille")     # il rechigne à payer


# ============================================================ synchrone / asynchrone
def test_synchronous_dialogues_depend_on_each_other(tmp_path):
    """À tour de rôle : chacun entend tout ce que les précédents ont dit, et rien de plus."""
    rec = Recorder()
    world, events, _ = fake_game(tmp_path, "sync", rec, population=THREE_VILLAGES, seasons=1, elder=True, mode="sync",
                                 scenario__assembly_rounds=1)
    heard = [len(transcript_lines(u)) for u in speeches(rec)]
    assert heard == list(range(len(heard))) and len(heard) == 4              # l'ancien, puis trois élus : 0, 1, 2, 3 paroles entendues
    first, later = kinds(events, "utterance")[0], kinds(events, "utterance")[-1]
    assert first["payload"]["heard"] == [] and len(later["payload"]["heard"]) == 3


def test_asynchronous_dialogues_are_independent(tmp_path):
    """Chacun s'exprime de son côté : personne n'entend personne, un seul tour, puis tous votent."""
    rec = Recorder(propose_first=2.0)
    world, events, _ = fake_game(tmp_path, "async", rec, population=THREE_VILLAGES, seasons=1, elder=True, mode="async")
    asked = speeches(rec)
    assert len(asked) == 4 and all("sans entendre les autres" in u and not transcript_lines(u) for u in asked)
    assert all("Ce qui a déjà été dit ce soir" not in u and "Propositions de règle sur la table" not in u for u in asked)
    utterances = kinds(events, "utterance")
    assert len(utterances) == 4 and all(u["payload"]["heard"] == [] and u["payload"]["round"] == 1 for u in utterances)
    assert len({u["payload"]["speaker"] for u in utterances}) == 4           # chacun une seule fois


# ============================================================ le reste du monde
def test_every_event_of_a_full_game_obeys_its_schema(tmp_path):
    """Élections, conseil, patrouille, climat, réussite du jour : aucun événement hors contrat (lettres mortes vides)."""
    rec = Recorder(speech={"patrouille": "installer"}, route=[("Ostrel", 6), ("large", 4)], elect={})
    world, events, dead = fake_game(tmp_path, "contrat", rec, population=THREE_VILLAGES, seasons=4, elder=True,
                                    economy__luck=0.25, climate__enabled=True, climate__event_rate=1.0)
    assert not dead, [d for d in dead][:2]
    assert kinds(events, "world_event") and kinds(events, "patrol") and kinds(events, "election")


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_a_full_default_game_runs_in_both_modes(tmp_path, mode):
    world, bus, _ = make_world(tmp_path, f"plein-{mode}", seasons=3, time__mode=mode, economy__luck=0.25,
                               climate__enabled=True, population__fishers=10, population__villages=5,
                               population__boat_mix={"barque": 0.3, "chaloupe": 0.4, "cotre": 0.3})
    dead = []
    bus.subscribe("deadletter", dead.append)
    asyncio.run(world.run())
    events = read_events(tmp_path, f"plein-{mode}")
    assert not dead and kinds(events, "run_end")[0]["payload"]["seasons_completed"] == 3
    assert len(world.hamlets) == 5 and len(world.reps) == 5
