"""Prises secrètes, déclarations à l'ancien, mensonges et confiance.

Chacun déclare sa prise à l'ancien en rentrant, et peut mentir : seuls lui et le joueur connaissent la vraie. Un mensonge finit
souvent par éclater (un voisin honnête le dénonce, ou l'ancien fait ses comptes au marché). La confiance de chacun envers chaque
pêcheur bouge sur ce qui est public, et ceux qui respectent la règle sont les plus durs avec ceux qui la dépassent.
"""
from __future__ import annotations

from filets.prompts import speak_messages
from filets.world import TRUST, Assembly, Proposal
from helpers import make_world
from test_reflection_profile import Profile, long_obs
from test_rumors import Recorder, fisher, play_with_announcement

NEVER = {"base": 0.0, "per_season": 0.0, "per_tonne": 0.0, "max": 0.0}
ALWAYS = {"base": 1.0, "per_season": 0.0, "per_tonne": 0.0, "max": 1.0}
# Mathis respecte la règle (agent à règles), Elwen la dépasse en déclarant la règle (taiseux à règles : il ment), Inès et Théo
# (IA) pêchent 3 t et le disent ; le premier à parler propose 2 t, que la vallée adopte.
VALLEY = [fisher("Mathis", "Ostrel", "ancienne_famille", kind="rule"), fisher("Inès", "Bramois", "nouveau_venu"),
          fisher("Elwen", "Ostrel", "taiseux", kind="rule"), fisher("Théo", "Hennad", "beau_parleur")]


def game(tmp_path, run_id, discovery, seasons=3):
    rec = Recorder(prise=3.0, propose_first=2.0)
    world, events = play_with_announcement(tmp_path, run_id, None, seasons=seasons, population=VALLEY, provider=rec,
                                           scenario__lie_discovery=discovery)
    rec.close()
    return world, events, rec.requests


def kinds(events, kind):
    return [e for e in events if e["type"] == kind]


def test_others_only_ever_know_what_the_liar_declared(tmp_path):
    world, events, requests = game(tmp_path, "secret", NEVER)
    elwen = next(a for a in world.fishers if a.profile.first_name == "Elwen")
    lies = [e["payload"] for e in kinds(events, "report") if e["payload"]["agent"] == elwen.id
            and e["payload"]["landed"] - e["payload"]["declared"] > 0.05]
    assert lies, "le taiseux pêche au-delà de la règle et déclare la règle"
    assert not kinds(events, "lie_discovered")
    for lie in lies:            # le joueur a les deux chiffres dans le journal ; les autres, jamais la vérité
        assert f"Elwen {lie['landed']:g} t" not in "".join(r["user"] for r in requests)
    assert any(f"Elwen {lies[0]['declared']:g} t" in r["user"] for r in requests)
    assert all(e["payload"]["declared"] <= e["payload"]["landed"] for e in kinds(events, "report"))
    # l'ancien raconte la saison d'après les déclarations : il ne sait rien du mensonge
    facts = " ".join(f for n in kinds(events, "narration") for f in n["payload"]["facts"])
    assert "Mensonge" not in facts and f"Elwen {lies[0]['landed']:g} t" not in facts


def test_a_lie_that_comes_out_costs_the_liar_everyones_trust(tmp_path):
    world, events, requests = game(tmp_path, "eclat", ALWAYS)
    [found, *_] = kinds(events, "lie_discovered")
    d = found["payload"]
    assert d["landed"] > d["declared"] and d["how"] == "temoin" and d["by"]          # un voisin qui n'a pas menti
    hit = next(e["payload"] for e in kinds(events, "trust") if e["payload"]["cause"] == "mensonge découvert")
    assert hit["subject"] == d["agent"] and set(hit["values"]) == set(world.trust) - {d["agent"]}
    # désormais, chacun connaît la vraie prise du menteur, et le sait menteur
    later = [r["user"] for r in requests if f"(saison {found['season'] + 1})" in r["user"]]
    assert later and all(f"Elwen {d['landed']:g} t (en avait déclaré {d['declared']:g} : mensonge découvert)" in u
                         for u in later)
    assert world.reputation(d["agent"]) < min(world.reputation(a.id) for a in world.fishers if a.id != d["agent"])


def test_those_who_keep_the_rule_judge_the_breakers_harder(tmp_path):
    world, events, _ = game(tmp_path, "juges", NEVER, seasons=2)
    quota = next(e["payload"]["quota"] for e in kinds(events, "norm_adopted"))
    tol = world.scn["quota_tolerance"]
    truth = {e["payload"]["agent"]: e["payload"]["landed"] for e in kinds(events, "report") if e["season"] == 2}
    trust = {o: {s: 0.5 for s in truth if s != o} for o in truth}
    judged = 0
    for e in kinds(events, "trust"):
        p = e["payload"]
        for o, v in p["values"].items():
            if p["cause"] == "dépasse la règle":
                follows = truth[o] <= quota + tol
                assert abs(v - trust[o][p["subject"]] - TRUST["over_rule" if follows else "over_rule_soft"]) < 1e-6
                judged += follows
            trust[o][p["subject"]] = v
    assert judged, "Mathis, qui respecte la règle, a jugé ceux qui la dépassent"


def test_after_the_first_round_only_those_with_a_reason_speak(tmp_path):
    world, _, _ = make_world(tmp_path, "parole", scenario__quiet_listeners=True)
    a, b = [x for x in world.fishers if x.profile.kind == "llm"][:2]
    asm = Assembly("valley", [a.id, b.id], 1, 99.0)

    def says(who, text, at, to="tous"):
        asm.utterances.append({"sim_time": at, "payload": {"speaker": who.id, "to": to, "text": text, "round": 1,
                                                           "info_horizon": at - 0.05}})

    says(a, "Je pêcherai trois tonnes.", 1.05)
    assert world.has_reason_to_speak(a, asm, 1)                      # au premier tour, tout le monde parle
    says(b, "Le lac a l'air bien.", 1.1)
    assert not world.has_reason_to_speak(a, asm, 2)                  # rien de neuf pour lui : il écoute
    says(b, "Je te parle à toi.", 1.15, to=a.id)
    assert world.has_reason_to_speak(a, asm, 2)                      # on s'adresse à lui
    asm.utterances.pop()
    says(b, f"{a.profile.first_name} pêche trop.", 1.15)
    assert world.has_reason_to_speak(a, asm, 2)                      # on le nomme
    asm.utterances.pop()
    asm.accused.append((1.2, a.id))
    assert world.has_reason_to_speak(a, asm, 2)                      # on l'accuse
    asm.accused.clear()
    asm.proposals["P1"] = Proposal("P1", a.id, 3.0, 1.0, "e1", "valley")
    asm.proposals["P2"] = Proposal("P2", b.id, 2.0, 1.1, "e2", "valley")
    assert world.has_reason_to_speak(a, asm, 2)                      # une proposition concurrence la sienne
    world.scn["quiet_listeners"] = False
    asm.proposals.clear()
    assert world.has_reason_to_speak(a, asm, 2)                      # sans le réglage, chacun reparle à chaque tour


def test_the_evening_prompt_keeps_what_matters_and_drops_the_archives():
    obs = {**long_obs(), "capacity": 100.0, "carnet": ["saison 5 : tu as pêché 6 t et déclaré 4 t à l'ancien ; personne ne le sait."],
           "trust": [("Loïc", 0.2), ("Elwen", 0.5), ("Théo", 0.9)]}
    brief = speak_messages(Profile(), obs, 100.0, brief=True)[1]["content"]
    assert "Ton carnet" in brief and "déclaré 4 t à l'ancien" in brief and "Prises déclarées à l'ancien" in brief
    assert "Loïc très faible, Théo forte; les autres, moyenne." in brief          # seuls les écarts sont nommés
    assert "Archive" not in brief and "Rappel : le lac est à" in brief
