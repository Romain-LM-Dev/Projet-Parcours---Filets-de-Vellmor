"""Prises secrètes, déclarations à l'ancien, indices, mensonges, confiance et exclusion de pêche.

Chacun déclare sa prise à l'ancien en rentrant, et peut mentir : seuls lui et le joueur connaissent la vraie. Un mensonge ne se
découvre pas au hasard mais sur des indices (radar, voisins, barque d'interdit vue partant, train de vie, comptes du lac), que
l'ancien relate à l'ouverture de la veillée. La confiance, le moteur ne la fixe pas : chaque agent juge lui-même ce que ce qu'il
apprend change pour lui (une IA dans sa réplique ; un agent à règles selon son caractère). Interdire un pêcheur de pêche, ou le
réautoriser, se propose et se vote à la veillée.
"""
from __future__ import annotations

import asyncio

from filets.bus import LocalBus
from filets.policies import JUDGE, sanction_vote, trust_rule
from filets.prompts import speak_messages
from filets.world import Assembly, Proposal, Sanction, World
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


def game(tmp_path, run_id, detection, seasons=3, radar=None, confiance=None, sanction="oui", **over):
    """Une partie de la vallée ci-dessus ; `radar` : la zone où le joueur place le radar dès la première saison ; `confiance` :
    le jugement que renvoie chaque réplique d'IA ; `sanction` : leur vote sur les exclusions."""
    rec = Recorder(prise=3.0, propose_first=2.0, confiance=confiance, sanction=sanction)
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


def named(world, first):
    return next(a for a in world.fishers if a.profile.first_name == first)


def elwen_of(world):
    return named(world, "Elwen")


def test_others_only_ever_know_what_the_liar_declared(tmp_path):
    world, events, requests = game(tmp_path, "secret", QUIET)
    elwen = elwen_of(world)
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
    elwen, mathis = elwen_of(world), named(world, "Mathis").id
    [found, *_] = kinds(events, "lie_discovered")
    d = found["payload"]
    assert d["agent"] == elwen.id and d["how"] == "temoins" and d["witnesses"] == [mathis] and not d["wrongful"]
    assert d["estimated"] == d["landed"] > d["declared"]                         # estimation exacte ici (aucune erreur)
    # Mathis, honnête, l'a dit devant tous ; Elwen, qui a triché, garde pour lui ce qu'il a vu de Mathis
    clues = [e["payload"] for e in kinds(events, "clue") if e["season"] == found["season"]]
    assert {(c["observer"], c["public"]) for c in clues} == {(mathis, True), (elwen.id, False)}
    # l'ancien relate dès l'ouverture de la veillée ; ce que cela change, Mathis le juge lui-même, le soir même
    opinions = [e["payload"] for e in kinds(events, "trust") if e["season"] == found["season"]
                and e["payload"]["subject"] == elwen.id]
    assert opinions and all(p["by"] == mathis and p["delta"] < 0 for p in opinions)
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


def test_the_elder_relates_what_the_clues_establish_and_can_be_wrong(tmp_path):
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

    clue("temoin", a, 6.0, 3.0)                              # un seul témoin : pas une preuve
    clue("temoin", b, 5.8, 3.0)
    clue("temoin", b, 6.3, 3.0)                              # deux témoins : le mensonge est établi
    clue("temoin", c, 5.6, 4.0)
    clue("temoin", c, 5.4, 4.0)                              # deux témoins qui surestiment un honnête : erreur de jugement
    clue("radar", d, 4.2, 4.0)                               # le radar confirme une déclaration honnête
    world.weigh_evidence(1)
    found = {e["payload"]["agent"]: e["payload"] for e in got if e["type"] == "lie_discovered"}
    assert set(found) == {b.id, c.id} and not found[b.id]["wrongful"] and found[c.id]["wrongful"]
    assert found[b.id]["estimated"] == 6.0 and found[c.id]["estimated"] == 5.5
    assert not [e for e in got if e["type"] == "trust"]          # il relate : il ne touche à la confiance de personne
    assert world.known_catch(b.id, 1, 1.0) == 6.0 and world.known_catch(a.id, 1, 1.0) is None     # (a n'a pas de report ici)


def test_the_engine_never_sets_trust_by_itself(tmp_path):
    """Toute variation de confiance est le jugement d'un agent sur un autre : aucune ne vient d'un barème du moteur. Les IA de
    cette partie ne disent rien de leur confiance : seuls les agents à règles (Mathis, Elwen) ont jugé, selon leur caractère."""
    world, events, _ = game(tmp_path, "juges", NEIGHBOURS)
    trust = [e["payload"] for e in kinds(events, "trust")]
    assert trust and all(p["cause"].startswith("jugement de") and set(p["values"]) == {p["by"]} for p in trust)
    assert {p["by"] for p in trust} <= {a.id for a in world.fishers if a.profile.kind == "rule"}


def test_an_ai_says_itself_what_each_act_changes_for_it(tmp_path):
    """Le champ `confiance` d'une réplique d'IA est appliqué tel quel, en dixièmes, borné de −3 à +3 ; un pêcheur s'y désigne par
    son identifiant ou par son nom ; un inconnu, ou soi-même, est ignoré."""
    ids = {f["first_name"]: f"F{i + 1:02d}" for i, f in enumerate(VALLEY)}
    world, events, _ = game(tmp_path, "ia-juge", QUIET, seasons=1,
                            confiance={"Elwen d'Ostrel": -2, ids["Inès"]: 9, "ZZ": 3})
    ines, theo, elwen = named(world, "Inès").id, named(world, "Théo").id, elwen_of(world).id
    assert [ines, theo, elwen] == [ids["Inès"], ids["Théo"], ids["Elwen"]]
    by_ai = [e["payload"] for e in kinds(events, "trust") if e["payload"]["by"] in (ines, theo)]
    assert {(p["by"], p["subject"], p["delta"]) for p in by_ai} == {(ines, elwen, -0.2), (theo, elwen, -0.2),
                                                                    (theo, ines, 0.3)}


def test_each_character_judges_by_its_own_morals():
    """La même chose, jugée par chacun : la famille ancienne est dure avec qui dépasse la règle, le taiseux ne s'en soucie
    guère ; le nouveau venu ne pardonne pas qu'on l'accuse ; le beau parleur tient à la parole donnée."""
    overfisher = {"X": {"over": 1.0}}
    assert trust_rule("ancienne_famille", overfisher)["X"] < 0 and "X" not in trust_rule("taiseux", overfisher)
    accuser = {"X": {"accused_me": True}}
    assert trust_rule("nouveau_venu", accuser)["X"] < trust_rule("ancienne_famille", accuser)["X"]
    broken = {"X": {"over": 0.0, "promise": False}}
    assert trust_rule("beau_parleur", broken)["X"] < trust_rule("taiseux", broken).get("X", 0)
    for j in JUDGE.values():                  # un dépassement avoué se pardonne toujours mieux qu'un mensonge établi
        assert j["lie"] < j["over_big"] <= j["over_slight"]
    assert trust_rule("ancienne_famille", {"X": {"over": 2.0, "lie": True, "promise": False}})["X"] == -3   # borné


def test_a_witness_does_not_denounce_a_friend(tmp_path):
    world, _, _ = make_world(tmp_path, "ami")
    world.detection.update({"radar": 0.0, "witness": 1.0, "witness_error": 0.0, "seen_leaving": 0.0, "lifestyle": 0.0})
    a, b = world.fishers[:2]
    for x in (a, b):
        x.catches[1] = x.declared[1] = 4.0
    world.trips[1] = [{"agent": x.id, "zone": "large", "landed": 4.0, "secret": False, "radar": False, "event_id": "t"}
                      for x in (a, b)]
    world.trust[b.id][a.id] = 0.9            # b fait toute confiance à a : il ne dira rien de lui devant tous
    world.investigate(1)
    assert {(c["observer"], c["subject"]): c["public"] for c in world.clues} == {(a.id, b.id): True, (b.id, a.id): False}


def test_the_valley_votes_to_exclude_a_proven_liar(tmp_path):
    world, events, _ = game(tmp_path, "exclusion", NEIGHBOURS, seasons=4)
    elwen, mathis = elwen_of(world), named(world, "Mathis")
    [found, *_] = kinds(events, "lie_discovered")
    # quand Mathis (famille ancienne) ne lui fait presque plus confiance, il propose de l'interdire de pêche (pas avant le
    # mensonge : Elwen avait d'abord gagné sa confiance en témoignant honnêtement)
    [prop] = [e for e in kinds(events, "sanction_proposal") if e["payload"]["target"] == elwen.id]
    assert prop["payload"]["author"] == mathis.id and prop["payload"]["action"] == "exclure"
    assert prop["season"] >= found["season"]
    [res] = [e["payload"] for e in kinds(events, "sanction_result")
             if e["payload"]["proposal_id"] == prop["payload"]["proposal_id"]]
    assert res["adopted"] and mathis.id in res["for"] and elwen.id not in res["for"] + res["against"]   # ni juge ni partie
    [ban] = [e for e in kinds(events, "ban") if e["payload"]["banned"] and e["payload"]["agent"] == elwen.id]
    assert ban["payload"]["proposal_id"] == prop["payload"]["proposal_id"]
    # interdit, il ne déclare plus rien ; le taiseux sort quand même, en cachette, loin de sa rive
    after = [e["payload"] for e in events if e["season"] > ban["season"] and e["type"] in ("catch", "report")
             and e["payload"]["agent"] == elwen.id]
    assert after and all(p.get("secret") and p["zone"] != "Ostrel" for p in after)


def test_a_fisher_named_instead_of_numbered_is_understood(tmp_path):
    """Un petit modèle propose souvent d'exclure « Bérénice » plutôt que F08 : le nom vaut l'identifiant (avant, la proposition
    se perdait en silence). Un nom qui ne désigne aucun pêcheur, ou plusieurs, ne vise personne."""
    world, _, _ = make_world(tmp_path, "noms")
    a, b, c = world.fishers[:3]
    asm = Assembly("valley", [x.id for x in world.fishers], 1, 99.0)
    world.propose_sanction(a, asm, b.profile.first_name, "exclure", {"event_id": "u"})
    assert [(s.author, s.target, s.votes) for s in asm.sanctions.values()] == [(a.id, b.id, {a.id: True})]
    assert world.fisher_ref(b.id.lower()) == b.id and world.fisher_ref(b.profile.name) == b.id
    assert world.fisher_ref("personne") is None
    assert world.fisher_ref(f"{b.profile.first_name} et {c.profile.first_name}") is None


def test_a_vote_against_keeps_the_fisher_free(tmp_path):
    world, events, _ = game(tmp_path, "refus", NEIGHBOURS, sanction="non")     # les IA votent contre
    results = [e["payload"] for e in kinds(events, "sanction_result")]
    assert results and not any(r["adopted"] for r in results)
    assert not kinds(events, "ban") and not world.banned


def test_a_banned_fisher_is_allowed_back_by_a_vote(tmp_path):
    world, bus, _ = make_world(tmp_path, "grace", population__rule_fraction=1.0)       # tous à règles
    got = []
    bus.subscribe("events", got.append)
    target, *others = world.fishers
    world.banned[target.id] = 2
    for o in others:
        world.trust[o.id][target.id] = 0.6          # ils lui font de nouveau confiance
    asm = Assembly("valley", [a.id for a in world.fishers], 3, 99.0)
    asm.sanctions["X1"] = Sanction("X1", others[0].id, target.id, "reautoriser", 0.0, "e")
    world.close_sanctions(asm)
    [res] = [e["payload"] for e in got if e["type"] == "sanction_result"]
    assert res["adopted"] and target.id not in world.banned
    assert [e["payload"]["banned"] for e in got if e["type"] == "ban"] == [False]
    assert not sanction_vote("ancienne_famille", 0.2, "reautoriser") and sanction_vote("nouveau_venu", 0.4, "reautoriser")


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
    # c'est l'agent qui dit ce que chaque acte change pour lui, et qui propose d'exclure ou de réautoriser
    assert '"confiance": {"<identifiant>": <de -3 à +3>}' in brief and '"exclure"' in brief and '"reautoriser"' in brief
