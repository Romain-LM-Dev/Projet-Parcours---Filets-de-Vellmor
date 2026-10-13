"""Réflexion « rapide » des IA : des prompts plus courts et des réponses bornées, pour qu'un modèle local ne mette plus
une demi-minute à répondre. Le profil « complète » reste celui des expériences (réponses libres, contexte entier).
"""
from __future__ import annotations

from filets import prompts
from filets.prompts import BRIEF_MAX_TOKENS, BRIEF_STYLE, catch_messages, context_block, speak_messages
from test_rumors import Recorder, play_with_announcement


class Profile:
    name = "Théo de Hennad"
    archetype_label = "beau parleur"
    hamlet = "Hennad"
    experience = 19
    traits = "Il aime avoir raison."
    voice = "grandiloquente"


def long_obs() -> dict:
    """Un état de monde chargé, comme à la sixième saison : beaucoup de souvenirs, de prises connues, de documents."""
    return {
        "label": "S6 · J3 08:00", "season": 6, "stock_estimate": 61.2, "role": "pecheur", "wealth": 612.0, "upkeep": 150.0,
        "debt_payment": 0.0, "price": 100.0, "boat_capacity": 10.0, "own_history": ["S4 7.5 t", "S5 6.0 t"],
        "known_catches": [f"F{i:02d} a pêché {i}.0 t à la saison {i % 5 + 1}, ce que tout le monde a vu depuis la rive" for i in range(24)],
        "memories": [f"Souvenir numéro {i} : " + "il s'est passé beaucoup de choses ce soir-là au bord du lac. " * 5 for i in range(6)],
        "documents": ["Archive " + "du vieux registre du lac, très longue explication. " * 12 for _ in range(3)],
        "norms": ["Quota de 3 t par pêcheur depuis la saison 4"], "pinned": ["Tu as promis de ne pas dépasser 4 t"],
        "participants": [{"id": f"F{i:02d}", "name": f"Pêcheur {i}", "label": "taiseux"} for i in range(1, 9)],
        "transcript": [f"F{i:02d} : " + "voici ce que je pense de la situation, elle est grave et durable. " * 4 for i in range(14)],
        "proposals": ["P1 : 3 t par pêcheur (F02)"], "scope_label": "toute la vallée", "round": 2,
    }


def total(messages):
    return sum(len(m["content"]) for m in messages)


# ---------------------------------------------------------------- les prompts
def test_the_brief_profile_gives_much_shorter_prompts():
    obs, p = long_obs(), Profile()
    for build in (catch_messages, speak_messages):
        full = total(build(p, obs, 100.0, brief=False))
        brief = total(build(p, obs, 100.0, brief=True))
        assert brief < full * 0.6, (build.__name__, brief, full)


def test_the_brief_profile_asks_for_one_short_sentence_and_the_full_one_does_not():
    obs, p = long_obs(), Profile()
    brief_catch, full_catch = catch_messages(p, obs, 100.0, True), catch_messages(p, obs, 100.0, False)
    assert BRIEF_STYLE in brief_catch[0]["content"] and BRIEF_STYLE not in full_catch[0]["content"]
    assert "1 phrase courte" in brief_catch[1]["content"] and "1 à 3 phrases" in full_catch[1]["content"]
    brief_speak, full_speak = speak_messages(p, obs, 100.0, True), speak_messages(p, obs, 100.0, False)
    assert "1 phrase courte" in brief_speak[1]["content"] and "1 à 3 phrases" in full_speak[1]["content"]


def test_the_brief_context_is_trimmed_but_keeps_what_decides():
    obs = long_obs()
    brief, full = context_block(obs, brief=True), context_block(obs, brief=False)
    assert len(brief) < len(full)
    # tronqué : les 8 dernières prises connues, 4 souvenirs, 2 documents
    assert brief.count("a pêché") == 8 and full.count("a pêché") == 24
    assert brief.count("Souvenir numéro") == 4 and full.count("Souvenir numéro") == 6
    assert brief.count("Archive") == 2 and full.count("Archive") == 3
    # intact : le stock, les finances, les règles, les engagements
    for must in ("61", "612 écus", "Quota de 3 t", "Tu as promis de ne pas dépasser 4 t"):
        assert must in brief, must


def test_the_brief_transcript_keeps_the_latest_lines():
    obs = long_obs()
    brief = speak_messages(Profile(), obs, 100.0, True)[1]["content"]      # 14 répliques (F00 à F13) : on garde les 8 dernières
    assert "F13 : voici" in brief and "F06 : voici" in brief and "F05 : voici" not in brief and "F00 : voici" not in brief
    assert speak_messages(Profile(), obs, 100.0, False)[1]["content"].count(" : voici") == 14


def test_prompts_are_unchanged_by_default():
    """Sans le mot « rapide », rien ne change : le profil de référence des expériences reste celui de toujours."""
    obs, p = long_obs(), Profile()
    assert catch_messages(p, obs, 100.0) == catch_messages(p, obs, 100.0, brief=False)
    assert not prompts.is_brief({}) and not prompts.is_brief({"reflection": "complete"}) and prompts.is_brief({"reflection": "rapide"})


# ---------------------------------------------------------------- ce qui part vraiment vers le modèle
def play(tmp_path, run_id, reflection, seasons=2):
    rec = Recorder()
    play_with_announcement(tmp_path, run_id, None, provider=rec, seasons=seasons, llm_overrides={"reflection": reflection})
    rec.close()
    return rec.requests


def test_the_brief_profile_bounds_the_length_of_every_answer(tmp_path):
    requests = play(tmp_path, "brief", "rapide")
    catches = [r for r in requests if '"prise"' in r["user"]]
    talks = [r for r in requests if '"message"' in r["user"]]
    assert catches and talks
    assert all(r["max_tokens"] == BRIEF_MAX_TOKENS["catch"] for r in catches)
    assert all(r["max_tokens"] == BRIEF_MAX_TOKENS["speak"] for r in talks)


def test_the_full_profile_keeps_the_configured_answer_length(tmp_path):
    requests = play(tmp_path, "full", "complete")
    assert requests and all(r["max_tokens"] == 350 for r in requests)
    assert all("Sois très bref" not in r["system"] for r in requests)


def test_the_brief_profile_sends_fewer_characters_over_a_game(tmp_path):
    brief = play(tmp_path, "b3", "rapide", seasons=3)
    full = play(tmp_path, "f3", "complete", seasons=3)
    sent = lambda reqs: sum(len(r["system"]) + len(r["user"]) for r in reqs)
    assert len(brief) == len(full)                                       # autant d'appels : seule leur taille change
    assert sent(brief) < sent(full)
