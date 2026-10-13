"""Les annonces du joueur (« Diffuser ») doivent avoir un effet visible, et traçable.

Avant : une annonce n'était qu'un souvenir parmi d'autres, retrouvé par la mémoire dans moins d'une décision sur trois
(il faisait la course contre les paroles de la veillée), et le faux LLM ignorait tout ce qu'on lui écrivait.
Désormais : les rumeurs actives sont dans chaque décision à IA, dans une rubrique à elles, pendant deux saisons ;
elles sont tracées dans les éléments « retrouvés pour décider » ; le faux LLM y réagit ; les agents à règles, témoins
de l'expérience, restent sourds.
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from filets.bus import LocalBus
from filets.cli import verify
from filets.pipeline import IndicatorPublisher
from filets.world import World
from helpers import cfg_for, make_world, read_events

HEADING = "Rumeurs qui courent dans la vallée"


def fisher(first, hamlet, arch, kind="llm", tier="petit"):
    return {"first_name": first, "hamlet": hamlet, "archetype": arch, "experience": 20, "wealth": 500,
            "debt_payment": 0, "kind": kind, "tier": tier}


FOUR = [fisher("Mathis", "Ostrel", "ancienne_famille"), fisher("Inès", "Bramois", "nouveau_venu"),
        fisher("Elwen", "Tilque", "taiseux"), fisher("Théo", "Hennad", "beau_parleur")]


class Recorder:
    """Faux fournisseur compatible OpenAI : enregistre ce qu'on lui demande, répond avec un JSON valide."""

    def __init__(self, prise: float = 3.0, reject: tuple = ()):
        self.requests: list[dict] = []
        self.reject = reject                      # formats de réponse refusés par ce fournisseur (HTTP 400), ex. ("json_schema",)
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                user = body["messages"][-1]["content"]
                fmt = body.get("response_format")
                outer.requests.append({"user": user, "system": body["messages"][0]["content"],
                                       "max_tokens": body.get("max_tokens"), "response_format": fmt})
                if fmt and fmt.get("type") in outer.reject:
                    err = json.dumps({"error": {"message": "response_format non pris en charge"}}).encode()
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(err)))
                    self.end_headers()
                    self.wfile.write(err)
                    return
                content = (json.dumps({"prise": prise, "justification": "Je reste raisonnable."}) if '"prise"' in user
                           else json.dumps({"message": "Je compte pêcher trois tonnes.", "destinataire": "tous",
                                            "proposition_quota": None, "soutien": None, "promesse": 3, "accuse": None}))
                out = json.dumps({"choices": [{"message": {"content": content}}],
                                  "usage": {"prompt_tokens": 100, "completion_tokens": 20}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown()


def play_with_announcement(tmp_path, run_id, text, seasons=3, population=FOUR, elder=False, provider=None, announce_at=1,
                           llm_overrides=None, **over):
    """Joue une partie ; `text` est annoncé au début de la saison `announce_at` (None : aucune annonce)."""
    cfg = cfg_for(tmp_path, seasons=seasons, time__mode="sync", population__custom=population, population__elder=elder,
                  population__elder_kind="rule", **over)
    cfg["llm"]["providers"]["scripted"]["latency_scale"] = 0.0
    if provider is not None:
        cfg["llm"]["providers"]["fake"] = {"base_url": provider.url, "api_key_env": None, "rpm": 0}
        cfg["llm"]["tiers"] = {"grand": {"provider": "fake", "model": "m"}, "petit": {"provider": "fake", "model": "m"}}
    for k, v in (llm_overrides or {}).items():
        cfg["llm"][k] = v
    bus = LocalBus()
    pub = IndicatorPublisher(bus, cfg["output"]["runs_dir"], cfg["scenario"]["quota_tolerance"])
    bus.subscribe("events", pub.on_event)
    world = World(cfg, bus, run_id)
    box = {}

    def on_event(ev):
        if text and ev["type"] == "season_start" and ev["season"] == announce_at:
            box["loop"].call_soon(world.handle_command, {"type": "announcement", "text": text})   # comme en jeu, par la boucle

    bus.subscribe("events", on_event)

    async def main():
        box["loop"] = asyncio.get_running_loop()
        await world.run()

    asyncio.run(main())
    return world, read_events(tmp_path, run_id)


def season_of(user_prompt: str) -> int:
    return int(re.search(r"\(saison (\d+)\)", user_prompt).group(1))


# ---------------------------------------------------------------- ce que reçoit l'IA
def test_active_rumors_are_in_every_ai_decision_for_two_seasons_and_only_once(tmp_path):
    rec = Recorder()
    world, events = play_with_announcement(tmp_path, "r1", "Le prix du poisson va doubler à Tilque", provider=rec)
    rec.close()
    text = "Le prix du poisson va doubler à Tilque"
    by_season = {}
    for r in rec.requests:
        by_season.setdefault(season_of(r["user"]), []).append(r["user"])
    assert set(by_season) == {1, 2, 3}
    for s in (1, 2):                                                    # la saison de l'annonce et la suivante
        for u in by_season[s]:
            assert HEADING in u and u.count(text) == 1, f"saison {s} : rumeur absente ou en double"
    assert all(HEADING not in u and text not in u for u in by_season[3])       # deux saisons plus tard : oubliée
    # la rumeur est dans les prises ET dans les paroles
    assert any('"prise"' in u and HEADING in u for u in by_season[1])
    assert any('"message"' in u and HEADING in u for u in by_season[1])
    assert any("Une rumeur qui te concerne" in u for u in by_season[1] if '"prise"' in u)
    assert any("Une rumeur court" in u for u in by_season[1] if '"message"' in u)


def test_the_rumor_is_traced_among_what_was_retrieved_to_decide(tmp_path):
    rec = Recorder()
    world, events = play_with_announcement(tmp_path, "r2", "Ines ment sur ce qu'elle ramène", provider=rec)
    rec.close()
    inj = next(e for e in events if e["type"] == "injection" and e["payload"]["injection_type"] == "announcement")
    decisions = [e for e in events if e["type"] == "decision" and e["payload"]["agent_kind"] == "llm"]
    with_rumor = [d for d in decisions if any(r["source"] == "rumor" for r in d["payload"]["retrieved"])]
    seasons_with = {d["season"] for d in with_rumor}
    assert seasons_with == {1, 2}
    for d in with_rumor:
        entry = next(r for r in d["payload"]["retrieved"] if r["source"] == "rumor")
        assert entry["id"] == inj["event_id"] and "Ines ment" in entry["text"]
        assert inj["event_id"] in d["payload"]["used_event_ids"]            # traçable jusqu'à l'événement brut (F6)
    assert len(with_rumor) == len([d for d in decisions if d["season"] in (1, 2)])      # chaque décision, pas une sur trois
    assert verify("r2", world.cfg)                                           # et aucune information venue du futur (C6)


def test_rumors_no_longer_compete_with_memories_for_a_place_in_the_prompt(tmp_path):
    """Le souvenir « rumeur » existe toujours (inspecteur, mémoire), mais il ne remonte pas en doublon par la mémoire."""
    rec = Recorder()
    world, events = play_with_announcement(tmp_path, "r3", "Ines ment sur ce qu'elle ramène", provider=rec, seasons=2)
    rec.close()
    mems = [e for e in events if e["type"] == "memory_write" and e["payload"]["kind"] == "rumeur"]
    assert len(mems) == len(world.agents)                                    # un souvenir par habitant de la vallée
    for r in rec.requests:
        assert r["user"].count("Ines ment") <= 1


def test_without_any_announcement_nothing_changes_in_the_prompts(tmp_path):
    rec = Recorder()
    play_with_announcement(tmp_path, "r4", None, provider=rec, seasons=1)
    rec.close()
    assert rec.requests and all(HEADING not in r["user"] for r in rec.requests)


# ---------------------------------------------------------------- les agents à règles restent sourds
def test_rule_agents_ignore_announcements(tmp_path):
    rules = [fisher(n, h, a, kind="rule") for n, h, a in (("Mathis", "Ostrel", "ancienne_famille"),
                                                          ("Inès", "Bramois", "nouveau_venu"),
                                                          ("Elwen", "Tilque", "taiseux"), ("Théo", "Hennad", "beau_parleur"))]
    _, with_rumor = play_with_announcement(tmp_path, "rule-a", "Sécheresse : il n'y aura plus de poisson", population=rules, seasons=2)
    _, without = play_with_announcement(tmp_path, "rule-b", None, population=rules, seasons=2)
    key = lambda evs: [(e["payload"]["agent"], e["season"], e["payload"]["requested"]) for e in evs if e["type"] == "catch"]
    assert key(with_rumor) == key(without) and key(with_rumor)


# ---------------------------------------------------------------- le faux LLM réagit (pour que le mode test montre un effet)
def test_a_scarcity_rumor_makes_scripted_fishers_more_cautious(tmp_path):
    text = "Grosse sécheresse : il n'y aura bientôt plus de poisson"
    _, with_rumor = play_with_announcement(tmp_path, "s-a", text, seasons=1)
    _, without = play_with_announcement(tmp_path, "s-b", None, seasons=1)
    req = lambda evs: {e["payload"]["agent"]: e["payload"]["requested"] for e in evs if e["type"] == "catch"}
    a, b = req(with_rumor), req(without)
    assert set(a) == set(b) == {"F01", "F02", "F03", "F04"}
    for agent in a:
        assert a[agent] == pytest.approx(round(b[agent] * 0.85, 1), abs=0.11), agent
        assert a[agent] <= b[agent]
    assert any(a[x] < b[x] for x in a)


def test_a_rumor_naming_a_fisher_gets_them_accused_and_defending_themselves(tmp_path):
    world, events = play_with_announcement(tmp_path, "t-a", "Inès ment sur ce qu'elle ramène", seasons=1)
    ines = next(a.id for a in world.fishers if a.profile.first_name == "Inès")
    accusations = [e["payload"] for e in events if e["type"] == "accusation"]
    assert accusations, "une rumeur accusatrice qui nomme un pêcheur doit déclencher une accusation à la veillée"
    assert all(a["accused"] == ines for a in accusations)
    accusers = {a["accuser"] for a in accusations}
    by_arch = {a.id: a.profile.archetype for a in world.fishers}
    assert accusers and all(by_arch[x] in ("ancienne_famille", "beau_parleur") for x in accusers)
    said = {e["payload"]["speaker"]: e["payload"]["text"] for e in events if e["type"] == "utterance"}
    assert "On raconte des choses sur moi" in said[ines]                    # la visée se défend
    # et elle se montre sobre à la saison suivante... ici, dès la pêche de la saison de l'annonce
    _, base = play_with_announcement(tmp_path, "t-b", None, seasons=1)
    ask = lambda evs: next(e["payload"]["requested"] for e in evs if e["type"] == "catch" and e["payload"]["agent"] == ines)
    assert ask(events) == pytest.approx(round(ask(base) * 0.8, 1), abs=0.11)


def test_a_harmless_rumor_is_echoed_in_speech_without_accusing_anyone(tmp_path):
    world, events = play_with_announcement(tmp_path, "h-a", "Il paraît que la fête d'Ostrel sera belle cette année", seasons=1)
    assert not [e for e in events if e["type"] == "accusation"]
    texts = [e["payload"]["text"] for e in events if e["type"] == "utterance"]
    assert texts and any("fête d'Ostrel" in t or "rumeurs" in t for t in texts)


# ---------------------------------------------------------------- la commande elle-même
def test_announcements_are_trimmed_and_empty_ones_ignored(tmp_path):
    world, bus, _ = make_world(tmp_path, "cmd", seasons=1, time__mode="sync")
    world.handle_command({"type": "announcement", "text": "   "})
    world.handle_command({"type": "announcement", "text": "x" * 500})
    assert len(world.rumors) == 1 and len(world.rumors[0]["text"]) == 300


def test_named_fishers_are_found_without_regard_to_accents_or_case(tmp_path):
    world, bus, _ = make_world(tmp_path, "names", seasons=1, time__mode="sync", population__custom=FOUR,
                               population__elder=False)
    ids = {a.profile.first_name: a.id for a in world.fishers}
    assert world.named_fishers(["INES ment"]) == [ids["Inès"]]
    assert set(world.named_fishers(["Mathis et théo ont triché", "rien sur F03"])) == {ids["Mathis"], ids["Théo"], ids["Elwen"]}
    assert world.named_fishers(["personne n'est nommé ici"]) == []
