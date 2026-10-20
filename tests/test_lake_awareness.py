"""Les IA doivent voir le lac mourir.

Constat sur des parties réelles (Ollama) : le lac passait de 100 % à 0 % et les pêcheurs demandaient toujours 5 à 7 t chacun,
en disant « le lac semble bien rempli » avec un stock de 0 t. Le stock n'était qu'une ligne parmi dix dans leur contexte, sans
repère ni tendance, et de vieilles paroles de la veillée le contredisaient. Désormais le contexte ouvre sur l'état du lac
(pourcentage, mots, ce que l'agent en a constaté depuis le début, tendance), le rappelle juste avant la question, et date chaque
souvenir.
"""
from __future__ import annotations

import re

import pytest

from filets.cli import verify
from filets.policies import catch_rule
from filets.prompts import (catch_messages, context_block, lake_block, lake_level, lake_reminder, lake_trend, persona,
                            speak_messages, surplus_line)
from test_rumors import FOUR, Recorder, play_with_announcement


def hist(*points, phase="pêche"):
    return [{"label": f"S{i + 1} · J0 06:00", "est": est, "phase": phase, "season": i + 1, "event_id": None}
            for i, est in enumerate(points)]


# ---------------------------------------------------------------- les mots du niveau
@pytest.mark.parametrize("est, words", [
    (0.0, "vide"), (0.04, "vide"), (0.4, "presque vide"), (3.0, "presque vide"), (10.0, "très bas"), (24.0, "très bas"),
    (30.0, "bas"), (44.0, "bas"), (50.0, "à peu près à moitié"), (54.0, "à peu près à moitié"),
    (60.0, "entamé"), (74.0, "entamé"), (80.0, "bien rempli"), (94.0, "bien rempli"), (100.0, "plein"),
])
def test_lake_level_in_words(est, words):
    assert words in lake_level(est, 100.0), (est, lake_level(est, 100.0))


def test_lake_level_follows_the_capacity_not_the_tonnes():
    assert lake_level(35.0, 70.0) == lake_level(50.0, 100.0) == lake_level(100.0, 200.0)
    assert "vide" in lake_level(0.0, 1000.0)


@pytest.mark.parametrize("now, past, words", [
    (12.0, [70.0], "beaucoup baissé"), (60.0, [70.0], "baissé"), (71.0, [70.0], "stable"), (80.0, [70.0], "remonte"),
])
def test_trend_in_words(now, past, words):
    assert words in lake_trend(now, 100.0, hist(*past))


def test_trend_compares_openings_with_openings():
    """L'ouverture de la pêche d'aujourd'hui se compare à la dernière ouverture, pas à la veillée (après la pêche)."""
    h = hist(100.0) + [{"label": "S1 · J25 18:00", "est": 40.0, "phase": "veillée", "season": 1, "event_id": None}]
    assert "stable" in lake_trend(98.0, 100.0, h + [])
    assert lake_trend(10.0, 100.0, []) == ""


# ---------------------------------------------------------------- le bloc d'état
def obs_for(est, history=None, capacity=100.0):
    return {"label": "S3 · J0 06:00", "season": 3, "stock_estimate": est, "role": "pecheur", "capacity": capacity,
            "collapse_ratio": 0.05, "stock_history": history or [], "wealth": 500.0, "upkeep": 150.0, "debt_payment": 0.0,
            "price": 100.0, "boat_capacity": 10.0, "own_history": [], "norms": [], "known_catches": [], "pinned": [],
            "memories": [], "documents": []}


def test_the_block_states_tonnes_percentage_and_level():
    text = lake_block(obs_for(38.0))
    assert "38 tonnes sur 100" in text and "38 %" in text and "bas" in text


def test_an_empty_lake_is_said_to_be_empty():
    text = lake_block(obs_for(0.0, hist(100.0, 55.0)))
    assert "0 %" in text and "vide : il n'y a plus de poisson" in text and "il vient de se vider" in text
    assert "il reste vide" in lake_block(obs_for(0.0, hist(100.0, 0.0)))
    assert "S1 · J0 (ouverture de la pêche) ≈ 100 t" in text and "S2 · J0 (ouverture de la pêche) ≈ 55 t" in text


def test_the_history_names_the_moment_it_was_seen():
    h = hist(100.0) + [{"label": "S1 · J25 18:00", "est": 48.0, "phase": "veillée", "season": 1, "event_id": None}]
    text = lake_block(obs_for(70.0, h))
    assert "S1 · J25 (veillée, la pêche faite) ≈ 48 t" in text and "maintenant ≈ 70 t" in text


def test_without_a_capacity_the_old_single_line_remains():
    obs = obs_for(38.0)
    obs.pop("capacity")
    assert lake_block(obs) == "Ton estimation du stock du lac : environ 38 tonnes."
    assert lake_reminder(obs) == ""


def test_context_opens_with_the_lake_state_and_the_question_repeats_it():
    obs, p = obs_for(38.0, hist(100.0, 70.0)), type("P", (), {"name": "Théo", "archetype_label": "beau parleur", "hamlet": "Hennad",
                                                              "experience": 19, "traits": "…", "voice": "…"})()
    ctx = context_block(obs)
    assert ctx.index("État du lac") < ctx.index("Tes finances")
    msgs = catch_messages(p, obs, 100.0)
    ask = msgs[1]["content"].split("C'est le moment de décider")[1]
    assert "Rappel : le lac est à 38 %" in ask and ask.index("Rappel") < ask.index("Réponds en JSON")
    assert "0 si tu restes à quai" in ask
    obs.update({"participants": [{"id": "F01", "name": "Théo", "label": "beau parleur"}], "transcript": [], "proposals": [],
                "scope_label": "toute la vallée", "round": 1})
    talk = speak_messages(p, obs, 100.0)[1]["content"]
    assert "Rappel : le lac est à 38 %" in talk and talk.index("Rappel") < talk.index("Réponds en JSON")


def test_the_world_text_gives_the_old_sayings_with_the_right_tonnes():
    for cap in (100.0, 140.0, 37.5):
        text = persona(type("P", (), {"name": "Théo", "archetype_label": "x", "hamlet": "Hennad", "experience": 2,
                                      "traits": "", "voice": ""})(), cap)
        assert f"environ {cap / 2:.0f} tonnes" in text and f"environ {cap:.0f} tonnes" in text
        assert "un lac vide ne se refait jamais" in text


# ---------------------------------------------------------------- de bout en bout
def play_greedy(tmp_path, run_id, capacity=40.0, seasons=4, **over):
    """Des pêcheurs qui demandent toujours 10 t (ramenées à la limite d'une sortie), sur un petit lac : il s'effondre en
    quelques saisons."""
    rec = Recorder(prise=10.0)
    world, events = play_with_announcement(tmp_path, run_id, None, provider=rec, seasons=seasons, lake__capacity=capacity,
                                            run__stop_on_extinction=False, **over)      # on veut voir la suite sur un lac mort
    rec.close()
    return world, events, rec.requests


def name_to_id(world):
    return {a.profile.name: a.id for a in world.agents.values()}


def parse(request, world):
    who = re.search(r"Tu es (.+?), ", request["system"]).group(1)
    season = int(re.search(r"\(saison (\d+)\)", request["user"]).group(1))
    return name_to_id(world)[who], season, ("catch" if '"prise"' in request["user"] else "speak")


def test_every_prompt_carries_the_true_state_of_the_lake_as_that_fisher_saw_it(tmp_path):
    world, events, requests = play_greedy(tmp_path, "aw1")
    cap = world.capacity
    seen = {}
    for e in events:
        if e["type"] == "decision" and e["payload"]["agent_kind"] == "llm":
            p = e["payload"]
            seen.setdefault((p["agent"], e["season"], p["decision_type"]), set()).add(round(100 * p["observed"]["stock_estimate"] / cap))
    assert requests
    for r in requests:
        agent, season, kind = parse(r, world)
        pct = int(re.search(r"soit (\d+) %", r["user"]).group(1))
        assert pct in seen[(agent, season, kind)], (agent, season, kind, pct, seen[(agent, season, kind)])
        assert "Rappel : le lac est à" in r["user"]


def test_the_lake_is_called_empty_once_it_is_empty(tmp_path):
    # parti à 45 % (18 t) : les 20 t que les quatre pêcheurs peuvent prendre le vident dès la première saison
    world, events, requests = play_greedy(tmp_path, "aw2", lake__initial_ratio=0.45)
    collapsed_at = next(e["season"] for e in events if e["type"] == "lake_collapsed")
    late = [r for r in requests if parse(r, world)[1] > collapsed_at]
    assert late, "la partie doit continuer après l'effondrement"
    assert all("vide : il n'y a plus de poisson" in r["user"] or "presque vide" in r["user"] for r in late)
    final = [r for r in late if parse(r, world)[1] == max(parse(x, world)[1] for x in late)]
    assert all("0 %" in r["user"] for r in final) and all("il reste vide" in r["user"] for r in final)


def test_what_a_fisher_read_of_past_seasons_is_what_he_estimated_then(tmp_path):
    """La suite de chiffres du prompt est faite de SES propres estimations passées, rien d'inventé ni du futur (C6)."""
    world, events, requests = play_greedy(tmp_path, "aw3", capacity=120.0)
    own = {}
    for e in events:
        if e["type"] == "decision" and e["payload"]["decision_type"] == "catch" and e["payload"]["agent_kind"] == "llm":
            own[(e["payload"]["agent"], e["season"])] = e["payload"]["observed"]["stock_estimate"]
    checked = 0
    for r in requests:
        agent, season, kind = parse(r, world)
        if kind != "catch" or season < 3:
            continue
        for s in range(1, season):
            m = re.search(rf"S{s} · J\d+ \(ouverture de la pêche\) ≈ (\d+) t", r["user"])
            assert m, f"la saison {s} manque dans le contexte de {agent} (saison {season})"
            assert int(m.group(1)) == round(own[(agent, s)]), (agent, s)
            checked += 1
        assert f"S{season} · J" not in r["user"].split("maintenant")[0].split("Ce que tu as constaté")[-1].replace(f"S{season} · J25", "")
    assert checked


def test_the_decision_trace_leads_back_to_the_earlier_observations(tmp_path):
    world, events, _ = play_greedy(tmp_path, "aw4", capacity=120.0)
    decisions = [e for e in events if e["type"] == "decision" and e["payload"]["agent_kind"] == "llm"]
    first = {(e["payload"]["agent"], e["season"], e["payload"]["decision_type"]): e["event_id"] for e in decisions}
    for e in decisions:
        p = e["payload"]
        if p["decision_type"] == "catch" and e["season"] >= 2:
            assert first[(p["agent"], e["season"] - 1, "catch")] in p["used_event_ids"], (p["agent"], e["season"])
    assert verify("aw4", world.cfg)                        # et rien ne vient du futur


def test_memories_carry_their_date(tmp_path):
    world, events, requests = play_greedy(tmp_path, "aw5", capacity=120.0, seasons=3)
    later = [r["user"] for r in requests if parse(r, world)[1] == 3 and '"prise"' in r["user"]]
    assert later
    section = [u.split("Tes souvenirs qui reviennent :")[1].split("Ce qu'on raconte")[0] for u in later]
    assert all(re.search(r"- \(S\d+ · J\d+ \d\d:\d\d\) ", s) for s in section)
    assert all(not re.search(r"^- (?!\(S)", s, re.M) for s in section if "aucun souvenir précis" not in s)


# ---------------------------------------------------------------- les agents à règles ne demandent pas plus que le lac visible
@pytest.mark.parametrize("arch", ["ancienne_famille", "nouveau_venu", "taiseux", "beau_parleur"])
def test_rule_fishers_never_ask_for_more_than_the_lake_they_can_see(arch):
    state = {"stock_estimate": 0.0, "capacity": 100.0, "n_fishers": 8, "quota": None, "boat_capacity": 10.0, "upkeep": 150.0,
             "debt_payment": 120.0, "price": 100.0}
    assert catch_rule(arch, state)[0] == 0.0
    state["stock_estimate"] = 2.5
    assert catch_rule(arch, state)[0] <= 2.5
    state["stock_estimate"] = 100.0
    assert catch_rule(arch, state)[0] <= 10.0


# ---------------------------------------------------------------- le repère des anciens, en tonnes et par pêcheur
def test_the_surplus_line_turns_the_half_lake_mark_into_tonnes_per_fisher():
    obs = obs_for(70.0)
    obs["n_fishers"] = 8
    line = surplus_line(obs)
    assert "il y a 20 tonnes au-dessus de la moitié du lac (50 t), soit 2.5 t par pêcheur (vous êtes 8)" in line
    obs["stock_estimate"] = 30.0                              # sous la moitié : plus rien à prendre sans l'entamer
    assert "il y a 0 tonnes au-dessus de la moitié du lac (50 t), soit 0.0 t par pêcheur" in surplus_line(obs)
    obs["capacity"] = 140.0
    assert "(70 t)" in surplus_line(obs)
    assert surplus_line(obs) in lake_reminder(obs)            # rappelé juste avant la question
    obs.pop("n_fishers")
    assert "par pêcheur" not in surplus_line(obs) and "au-dessus de la moitié" in surplus_line(obs)
    obs.pop("capacity")
    assert surplus_line(obs) == ""


def test_no_prompt_tells_the_equal_share_of_what_is_left():
    """« Si chacun prenait la part égale de ce qui reste » servait d'ancre : à 51 % les pêcheurs demandaient 6 t chacun, soit
    exactement 51/8, c'est-à-dire tout le lac. Cette phrase a été retirée ; le test empêche son retour."""
    obs = obs_for(38.0)
    obs["n_fishers"] = 8
    text = lake_reminder(obs) + context_block(obs)
    assert "il n'en resterait plus du tout" not in text and "si chacun en prenait" not in text


def test_every_ai_prompt_of_a_depleted_lake_carries_the_surplus_per_fisher(tmp_path):
    world, events, requests = play_greedy(tmp_path, "aw6", capacity=40.0, seasons=2)
    assert requests
    for r in requests:
        assert re.search(r"Repère des anciens : il y a \d+ tonnes au-dessus de la moitié du lac \(20 t\), soit \d+\.\d t par pêcheur "
                         r"\(vous êtes 4\)", r["user"]), r["user"][-700:]
