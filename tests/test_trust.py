"""Prises secrètes, déclarations à l'ancien, indices, mensonges, confiance et interdiction de pêche.

Chacun déclare sa prise à l'ancien en rentrant, et peut mentir : seuls lui et le joueur connaissent la vraie. Un mensonge ne se
découvre pas au hasard mais sur des indices : le radar de la vallée (une zone du lac par saison), les voisins qui pêchent du même
côté, une barque d'interdit vue partant, un train de vie, les comptes du lac. L'ancien les pèse à la fin de la veillée. La
confiance bouge sur ce qui est public ; tombé à presque rien, un pêcheur est interdit de pêche et ne peut plus que pêcher en
cachette.
"""
from __future__ import annotations

import asyncio

from filets.bus import LocalBus
from filets.prompts import speak_messages
from filets.world import TRUST, Assembly, Proposal, World
from helpers import cfg_for, make_world, read_events
from test_reflection_profile import Profile, long_obs
from test_rumors import Recorder, fisher

QUIET = {"radar": 0.0, "witness": 0.0, "seen_leaving": 0.0, "lifestyle": 0.0}          # personne ne voit rien
NEIGHBOURS = {"radar": 0.0, "witness": 1.0, "witness_error": 0.0, "seen_leaving": 0.0, "lifestyle": 0.0, "proof": 1.0}
RADAR = {"radar": 1.0, "radar_error": 0.0, "witness": 0.0, "seen_leaving": 0.0, "lifestyle": 0.0}
# Mathis respecte la règle (agent à règles), Elwen la dépasse en déclarant la règle (taiseux à règles : il ment) ; tous deux
# pêchent sur la rive d'Ostrel. Inès et Théo (IA) pêchent 3 t et le disent ; le premier à parler propose 2 t, que la vallée adopte.
VALLEY = [fisher("Mathis", "Ostrel", "ancienne_famille", kind="rule"), fisher("Inès", "Bramois", "nouveau_venu"),
          fisher("Elwen", "Ostrel", "taiseux", kind="rule"), fisher("Théo", "Hennad", "beau_parleur")]


def game(tmp_path, run_id, detection, seasons=3, radar=None, **over):
    """Une partie de la vallée ci-dessus ; `radar` : la zone où le joueur place le radar dès la première saison."""
    rec = Recorder(prise=3.0, propose_first=2.0)
    cfg = cfg_for(tmp_path, seasons=seasons, population__custom=VALLEY, population__elder=False, time__mode="sync",
                  scenario__detection=detection, **over)
    cfg["llm"]["providers"]["fake"] = {"base_url": rec.url, "api_key_env": None, "rpm": 0}
    cfg["llm"]["tiers"] = {"grand": {"provider": "fake", "model": "m"}, "petit": {"provider": "fake", "model": "m"}}
    bus = LocalBus()
    world = World(cfg, bus, run_id)
    box = {}

    def on_event(ev):
        if radar and ev["type"] == "season_start" and ev["season"] == 1:
            box["loop"].call_soon(world.handle_command, {"type": "place_radar", "value": radar})   # comme depuis Godot

    bus.subscribe("events", on_event)

    async def main():
        box["loop"] = asyncio.get_running_loop()
        await world.run()

    asyncio.run(main())
    rec.close()
    return world, read_events(tmp_path, run_id), rec.requests


def kinds(events, kind):
    return [e for e in events if e["type"] == kind]


def elwen_of(world):
    return next(a for a in world.fishers if a.profile.first_name == "Elwen")


def test_others_only_ever_know_what_the_liar_declared(tmp_path):
    world, events, requests = game(tmp_path, "secret", QUIET)
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


def test_a_neighbour_who_saw_the_boat_exposes_the_lie_and_the_cheater_keeps_quiet(tmp_path):
    world, events, requests = game(tmp_path, "voisins", NEIGHBOURS)
    elwen = elwen_of(world)
    [found, *_] = kinds(events, "lie_discovered")
    d = found["payload"]
    mathis = next(a.id for a in world.fishers if a.profile.first_name == "Mathis")
    assert d["agent"] == elwen.id and d["how"] == "temoins" and d["witnesses"] == [mathis] and not d["wrongful"]
    assert d["estimated"] == d["landed"] > d["declared"]                         # estimation exacte ici (aucune erreur)
    # Mathis, honnête, l'a dit devant tous ; Elwen, qui a triché, garde pour lui ce qu'il a vu de Mathis
    clues = [e["payload"] for e in kinds(events, "clue") if e["season"] == found["season"]]
    assert {(c["observer"], c["public"]) for c in clues} == {(mathis, True), (elwen.id, False)}
    hit = next(e["payload"] for e in kinds(events, "trust") if e["payload"]["cause"] == "mensonge établi")
    assert hit["subject"] == elwen.id and set(hit["values"]) == set(world.trust) - {elwen.id}
    # désormais, chacun connaît l'estimation de sa prise, et le sait menteur
    later = [r["user"] for r in requests if f"(saison {found['season'] + 1})" in r["user"]]
    assert later and all(f"Elwen {d['estimated']:g} t (en avait déclaré {d['declared']:g} : mensonge établi)" in u
                         for u in later)


def test_the_radar_measures_the_boats_of_its_zone(tmp_path):
    world, events, _ = game(tmp_path, "radar", RADAR, seasons=2, radar="Ostrel")
    placed = [e["payload"] for e in kinds(events, "radar_placed")]
    assert placed[-1] == {"zone": "Ostrel", "by": "joueur"}            # le joueur l'a placé, et il garde la main
    measured = {e["payload"]["subject"]: e["payload"] for e in kinds(events, "clue") if e["payload"]["kind"] == "radar"}
    assert set(measured) == {a.id for a in world.fishers if a.profile.hamlet == "Ostrel"}      # sa zone, et elle seule
    [found] = [e["payload"] for e in kinds(events, "lie_discovered")]
    assert found["agent"] == elwen_of(world).id and found["how"] == "radar" and found["estimated"] == found["landed"]


def test_the_elder_weighs_clues_and_can_be_wrong(tmp_path):
    world, bus, _ = make_world(tmp_path, "juge")
    got = []
    bus.subscribe("events", got.append)
    a, b, c, d = world.fishers[:4]
    world.trips[1] = [{"agent": x.id, "zone": "large", "landed": landed, "secret": False, "radar": False, "event_id": "t"}
                      for x, landed in ((a, 6.0), (b, 6.0), (c, 4.0), (d, 4.0))]
    for x, said, landed in ((a, 3.0, 6.0), (b, 3.0, 6.0), (c, 4.0, 4.0), (d, 4.0, 4.0)):
        x.declared[1], x.catches[1] = said, landed
    world.lies = {f"r{x.id}": {"agent": x.id, "season": 1, "declared": 3.0, "landed": 6.0} for x in (a, b)}

    def clue(kind, subject, estimate, said):
        world.clues.append({"kind": kind, "observer": None, "subject": subject.id, "zone": "large", "estimate": estimate,
                            "public": True, "declared": said, "season": 1, "t": 0.0, "event_id": "c"})

    clue("temoin", a, 6.0, 3.0)                              # un seul témoin : un soupçon, pas une preuve
    clue("temoin", b, 5.8, 3.0)
    clue("temoin", b, 6.3, 3.0)                              # deux témoins : le mensonge est établi
    clue("temoin", c, 5.6, 4.0)
    clue("temoin", c, 5.4, 4.0)                              # deux témoins qui surestiment un honnête : erreur de jugement
    clue("radar", d, 4.2, 4.0)                               # le radar confirme une déclaration honnête
    world.weigh_evidence(1)
    found = {e["payload"]["agent"]: e["payload"] for e in got if e["type"] == "lie_discovered"}
    assert set(found) == {b.id, c.id} and not found[b.id]["wrongful"] and found[c.id]["wrongful"]
    assert found[b.id]["estimated"] == 6.0 and found[c.id]["estimated"] == 5.5
    assert [e["payload"]["subject"] for e in got if e["type"] == "trust" and e["payload"]["cause"] == "soupçonné"] == [a.id]
    assert world.known_catch(b.id, 1, 1.0) == 6.0 and world.known_catch(a.id, 1, 1.0) is None     # (a n'a pas de report ici)


def test_a_fisher_without_trust_is_banned_and_can_only_fish_in_secret(tmp_path):
    world, events, _ = game(tmp_path, "interdit", NEIGHBOURS, seasons=3, scenario__ban_below=0.3)
    elwen = elwen_of(world)
    [ban] = [e for e in kinds(events, "ban") if e["payload"]["banned"]]
    assert ban["payload"]["agent"] == elwen.id and ban["payload"]["reputation"] <= 0.3
    after = [e["payload"] for e in events if e["season"] > ban["season"] and e["type"] in ("catch", "report")
             and e["payload"]["agent"] == elwen.id]
    # interdit, il ne déclare plus rien ; le taiseux sort quand même, en cachette, loin de sa rive
    assert after and all(p.get("secret") and p["zone"] != "Ostrel" for p in after)
    assert not [p for p in after if "declared" in p]


def test_the_ban_is_lifted_once_trust_is_regained(tmp_path):
    world, bus, _ = make_world(tmp_path, "levee", scenario__ban_lift=0.5)
    got = []
    bus.subscribe("events", got.append)
    a = world.fishers[0]
    world.banned[a.id] = 2
    world.update_bans(3)
    [lifted] = [e["payload"] for e in got if e["type"] == "ban"]
    assert a.id not in world.banned and lifted == {"agent": a.id, "banned": False, "reputation": world.reputation(a.id)}


def test_those_who_keep_the_rule_judge_the_breakers_harder(tmp_path):
    world, events, _ = game(tmp_path, "juges", QUIET, seasons=2)
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
                said = next(e2["payload"]["declared"] for e2 in kinds(events, "report")
                            if e2["season"] == 2 and e2["payload"]["agent"] == p["subject"])
                assert abs(v - trust[o][p["subject"]] - World.over_rule_penalty(said, quota, follows)) < 1e-6
                judged += follows
            trust[o][p["subject"]] = v
    assert judged, "Mathis, qui respecte la règle, a jugé ceux qui la dépassent"


def test_owning_up_to_a_breach_costs_less_than_being_caught_lying():
    """Dépasser la règle et le déclarer coûte un peu de confiance, d'autant plus qu'on la dépasse ; le cacher et se faire
    prendre coûte toujours davantage. Celui qui la dépasse aussi juge moitié moins sévèrement."""
    slight, double = World.over_rule_penalty(2.5, 2.0, True), World.over_rule_penalty(6.0, 2.0, True)
    assert -0.20 <= double < slight < 0 and World.over_rule_penalty(6.0, 2.0, False) == double / 2
    assert TRUST["lie"] < double


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
