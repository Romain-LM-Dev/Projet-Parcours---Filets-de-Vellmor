"""Le modèle de décision open (« système 1 », `POST /v1/systemone` d'Ollama, ex. tev1 0,8B) à côté de Qwen : les prises de
routine et les bulletins de vote lui sont posés en questions typées (un niveau, une option), Qwen garde la réflexion. S'il
manque, le petit modèle de langage prend le relais, sans perte de décision.
"""
from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from filets import prompts
from filets.config import load_config
from filets.engine import GameRequestError, preflight, used_models
from filets.indicators import IndicatorEngine
from filets.llm import SystemOneClient
from test_rumors import Recorder, play_with_announcement
from test_system12 import GRANDS, obs_routine


class FakeSystemOne:
    """Faux Ollama pour les modèles de décision : `GET /api/tags`, `POST /v1/systemone`, le reste répond {}.
    Les réponses ont la forme documentée : `answers` par nom de question, sans le type ; `score` = niveau moyen pondéré
    (depuis 0) avec `legend` et `probabilities` ; `choice` avec ses probabilités ; `noul` = probabilité de vrai ; `usage`."""

    def __init__(self, level: float = 3, choice: str | None = None, status: int = 200, models=("tev1:0.8b",),
                 as_list: bool = False, probs=None):
        self.requests: list[dict] = []
        self.level, self.choice, self.status, self.as_list = level, choice, status, as_list
        self.probs = probs                # None : pic sur le niveau ; un dict : ces probabilités ; False : aucune
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code: int, obj: dict) -> None:
                out = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def do_GET(self):
                if self.path == "/api/tags":
                    self._send(200, {"models": [{"name": m} for m in models]})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"path": self.path, **body})
                if self.path != "/v1/systemone":
                    self._send(200, {})
                    return
                if outer.status != 200:
                    self._send(outer.status, {"error": f"model '{body.get('model')}' not found"})
                    return
                answers = {}
                for name, q in body["questions"].items():
                    if q["type"] == "score":
                        n = len(q["criteria"])
                        peak = min(max(round(outer.level), 0), n - 1)
                        answers[name] = {"type": "score", "score": outer.level, "confidence": 0.8,
                                         "legend": {str(i): c for i, c in enumerate(q["criteria"])}}
                        if outer.probs is not False:
                            answers[name]["probabilities"] = outer.probs or {
                                str(i): (0.9 if i == peak else 0.1 / (n - 1)) for i in range(n)}
                    elif q["type"] == "choice":
                        pick = outer.choice or next(iter(q["criteria"]))
                        answers[name] = {"choice": pick, "confidence": 0.9,
                                         "probabilities": {k: (0.9 if k == pick else 0.1 / (len(q["criteria"]) - 1))
                                                           for k in q["criteria"]}}
                    else:
                        answers[name] = {"noul": 0.93}
                if outer.as_list:
                    answers = list(answers.values())
                self._send(200, {"model": body["model"], "answers": answers,
                                 "usage": {"input_tokens": 60, "output_tokens": 1}})

        self.server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def asked(self) -> list[dict]:
        return [r for r in self.requests if r["path"] == "/v1/systemone"]

    def close(self) -> None:
        self.server.shutdown()


PERSONA = type("P", (), {"name": "Théo de Hennad", "archetype_label": "beau parleur", "hamlet": "Hennad",
                         "traits": "Il aime parler."})()


async def ask(server: FakeSystemOne, spec: dict):
    client = SystemOneClient("s1", server.url, {"timeout_s": 5})
    try:
        return await client.complete("tev1:0.8b", [], {"system_one": spec}, "reflexe")
    finally:
        await client.http.aclose()


# ---------------------------------------------------------------- les questions typées
def test_the_routine_catch_is_a_scale_of_catches_over_the_same_state_as_the_reflex():
    spec = prompts.reflex_system_one(PERSONA, obs_routine())
    q = spec["questions"]["prise"]
    assert q["type"] == "score" and len(q["criteria"]) == 10 and q["criteria"][0].startswith("0 t")
    assert spec["values"]["prise"] == prompts.catch_levels(10.0) == [0.0, 1.1, 2.2, 3.3, 4.4, 5.6, 6.7, 7.8, 8.9, 10.0]
    assert "95 %" in spec["state"] and "J'ai promis 3 t." in spec["state"] and "pas plus de 3 t" in spec["state"]
    assert "JSON" not in spec["state"]                       # un modèle de décision ne rédige rien


def test_the_ballot_is_a_choice_between_the_proposals_or_none():
    spec = prompts.ballot_system_one(PERSONA, {"P1": "1.5 t par pêcheur", "P2": "3 t par pêcheur"}, 80.0, 100.0)
    q = spec["questions"]["vote"]
    assert q["type"] == "choice" and list(q["criteria"]) == ["P1", "P2", "aucune"]
    assert "80 %" in spec["state"] and "Théo de Hennad" in spec["state"]


def test_the_client_turns_a_level_into_the_catch_it_stands_for():
    s1 = FakeSystemOne(level=3)
    spec = prompts.reflex_system_one(PERSONA, obs_routine())
    res = asyncio.run(ask(s1, spec))
    s1.close()
    assert res.status == "ok" and json.loads(res.text) == {"prise": 3.3, "_confiance": {"prise": 0.8}}
    assert (res.prompt_tokens, res.completion_tokens) == (60, 1)
    sent = s1.asked()[0]
    assert sent["model"] == "tev1:0.8b" and sent["state"] == spec["state"] and sent["questions"] == spec["questions"]
    assert "values" not in sent                              # la correspondance niveau → tonnes reste de ce côté-ci


def test_the_most_probable_level_is_the_decision_not_the_weighted_mean():
    """Réponse réelle de tev1 : 62 % sur le niveau 2, 29 % sur le niveau 0, score moyen 1,37. La prise est le niveau 2 (2,2 t)."""
    probs = {"0": 0.29, "1": 0.07, "2": 0.62, "3": 0.01, "4": 0.002, "5": 0.002, "6": 0.001, "7": 0.001, "8": 0.001, "9": 0.0001}
    s1 = FakeSystemOne(level=1.3746, probs=probs)
    res = asyncio.run(ask(s1, prompts.reflex_system_one(PERSONA, obs_routine())))
    s1.close()
    assert json.loads(res.text)["prise"] == 2.2


def test_without_probabilities_the_weighted_level_falls_between_two_catches():
    """3,5 : à mi-chemin entre le niveau 3 (3,3 t) et le niveau 4 (4,4 t)."""
    s1 = FakeSystemOne(level=3.5, probs=False)
    res = asyncio.run(ask(s1, prompts.reflex_system_one(PERSONA, obs_routine())))
    s1.close()
    assert json.loads(res.text)["prise"] == 3.85


def test_out_of_range_levels_are_clamped_and_choices_returned_as_is():
    s1 = FakeSystemOne(level=42, choice="P2")
    catch = asyncio.run(ask(s1, prompts.reflex_system_one(PERSONA, obs_routine())))
    vote = asyncio.run(ask(s1, prompts.ballot_system_one(PERSONA, {"P1": "a", "P2": "b"}, 80.0, 100.0)))
    s1.close()
    assert json.loads(catch.text)["prise"] == 10.0
    assert json.loads(vote.text) == {"vote": "P2", "_confiance": {"vote": 0.9}}


def test_answers_given_as_a_list_in_question_order_are_understood_too():
    s1 = FakeSystemOne(choice="aucune", as_list=True)
    res = asyncio.run(ask(s1, prompts.ballot_system_one(PERSONA, {"P1": "a"}, 80.0, 100.0)))
    s1.close()
    assert json.loads(res.text)["vote"] == "aucune"


def test_a_missing_model_is_an_error_not_an_answer():
    s1 = FakeSystemOne(status=404)
    res = asyncio.run(ask(s1, prompts.reflex_system_one(PERSONA, obs_routine())))
    s1.close()
    assert res.status == "error" and res.text is None and "404" in res.detail


# ---------------------------------------------------------------- dans une partie
def open_game(tmp_path, run_id, s1, seasons=4, propose_first=None):
    rec = Recorder(prise=3.0, propose_first=propose_first)
    prov = {"fake": {"base_url": rec.url, "api_key_env": None, "rpm": 0, "json_schema": True, "seed": True},
            "scripted": {"latency_scale": 0.0},
            "s1": {"base_url": s1.url, "kind": "systemone", "local": True, "timeout_s": 5}}
    tiers = {"grand": {"provider": "fake", "model": "m"}, "petit": {"provider": "fake", "model": "m"},
             "reflexe": {"provider": "s1", "model": "tev1:0.8b"}}
    world, events = play_with_announcement(tmp_path, run_id, None, provider=rec, seasons=seasons, population=GRANDS,
                                           lake__capacity=400.0,
                                           llm_overrides={"reflection": "adaptive", "providers": prov, "tiers": tiers})
    rec.close()
    return world, events, rec.requests


def test_routine_catches_go_to_the_decision_model_and_reflection_stays_with_qwen(tmp_path):
    s1 = FakeSystemOne(level=3)
    world, events, chat = open_game(tmp_path, "so1", s1)
    s1.close()
    calls = [e["payload"] for e in events if e["type"] == "llm_call"]
    reflex = [c for c in calls if c["tier"] == "reflexe"]
    assert reflex and all(c["system"] == "S1" and c["model"] == "tev1:0.8b" and c["status"] == "ok" for c in reflex)
    assert all(c["tier"] != "reflexe" for c in calls if c.get("system") == "S2")
    decisions = [e["payload"] for e in events if e["type"] == "decision" and e["payload"].get("system") == "S1"]
    level3 = prompts.catch_levels(10.0, lo=1.0)[3]                  # l'échelle part de la prise minimale (1 t) : 4 t
    assert decisions and all(d["tier"] == "reflexe" and not d["fallback"] and d["value"] == level3 == 4.0 for d in decisions)
    assert all(d["justification"].startswith("Réflexe (système 1, tev1:0.8b)") and "Confiance 0.80" in d["justification"]
               for d in decisions)
    assert not [r for r in chat if list(r["response_format"]["json_schema"]["schema"]["properties"]) == ["prise"]]


def test_ballots_are_choices_put_to_the_decision_model(tmp_path):
    s1 = FakeSystemOne(level=3)
    world, events, _ = open_game(tmp_path, "so2", s1, seasons=2, propose_first=1.5)
    s1.close()
    ballots = [r for r in s1.asked() if "vote" in r["questions"]]
    assert ballots and all(r["questions"]["vote"]["type"] == "choice" for r in ballots)
    assert all(list(r["questions"]["vote"]["criteria"])[-1] == "aucune" for r in ballots)
    votes = [e["payload"] for e in events if e["type"] == "llm_call" and e["payload"]["purpose"] == "vote"]
    assert votes and all(c["tier"] == "reflexe" and c["system"] == "S1" for c in votes)


def test_the_decision_model_costs_a_few_tokens_counted_as_system_one(tmp_path):
    s1 = FakeSystemOne(level=3)
    world, events, _ = open_game(tmp_path, "so3", s1)
    s1.close()
    eng = IndicatorEngine(0.5)
    for e in events:
        eng.ingest(e)
    v = eng.last_values
    n = len(s1.asked())
    assert world.router.usage.by_tier["reflexe"] == {"calls": n, "tokens": 61 * n}
    assert v["llm_calls_s1"] >= n and v["llm_tokens_s1"] >= 61 * n


def test_without_the_decision_model_qwen_answers_and_no_decision_is_lost(tmp_path):
    s1 = FakeSystemOne(status=404)
    world, events, chat = open_game(tmp_path, "so4", s1)
    s1.close()
    failed = [e for e in events if e["type"] == "llm_call" and e["payload"]["tier"] == "reflexe"]
    assert failed and all(e["payload"]["status"] == "error" for e in failed)
    # essayé par les réflexes partis ensemble au premier instant, puis écarté pour toute la partie
    assert len({e["sim_time"] for e in failed}) == 1 and len(s1.asked()) == len(failed)
    decisions = [e["payload"] for e in events if e["type"] == "decision" and e["payload"].get("system") == "S1"]
    assert len(decisions) > len(failed) and all(d["tier"] == "petit" and not d["fallback"] for d in decisions)
    assert [r for r in chat if list(r["response_format"]["json_schema"]["schema"]["properties"]) == ["prise"]]


# ---------------------------------------------------------------- préparation de la partie
def test_the_open_preset_needs_the_decision_model_too():
    wanted = used_models(load_config("config/ollama_open.yaml"))
    assert wanted == {"ollama": {"qwen2.5:3b", "qwen2.5:1.5b"}, "ollama_s1": {"tev1:0.8b"}}
    assert "ollama_s1" not in used_models(load_config("config/ollama_fast.yaml"))


def s1_cfg(s1: FakeSystemOne) -> dict:
    cfg = load_config(None)
    cfg["llm"]["providers"]["fake"] = {"base_url": "http://127.0.0.1:9/v1", "api_key_env": None}
    cfg["llm"]["providers"]["s1"] = {"base_url": s1.url, "kind": "systemone", "local": True}
    cfg["llm"]["tiers"] = {"grand": {"provider": "fake", "model": "m"}, "petit": {"provider": "fake", "model": "m"},
                           "reflexe": {"provider": "s1", "model": "tev1:0.8b"}}
    return cfg


def test_preflight_loads_the_decision_model_with_a_question():
    s1 = FakeSystemOne()
    steps = []
    asyncio.run(preflight(s1_cfg(s1), steps.append))
    s1.close()
    loaded = s1.asked()
    assert len(loaded) == 1 and loaded[0]["model"] == "tev1:0.8b" and loaded[0]["keep_alive"] == "30m"
    assert any("tev1:0.8b" in s for s in steps)


def test_a_missing_decision_model_does_not_block_the_game():
    """Le modèle de décision est une économie : s'il manque (Ollama trop ancien), la partie se lance quand même, sans le
    niveau `reflexe`, et le joueur sait pourquoi ; aucun appel ne lui est envoyé."""
    s1 = FakeSystemOne(models=("qwen2.5:3b",))
    cfg, steps = s1_cfg(s1), []
    asyncio.run(preflight(cfg, steps.append))
    s1.close()
    assert "reflexe" not in cfg["llm"]["tiers"] and not s1.asked()
    assert any("tev1:0.8b absent" in s and "ollama pull tev1:0.8b" in s for s in steps)


def test_a_missing_language_model_still_blocks_the_game():
    s1 = FakeSystemOne(models=("tev1:0.8b",))
    cfg = s1_cfg(s1)
    cfg["llm"]["providers"]["s1b"] = {"base_url": s1.url, "local": True}
    cfg["llm"]["tiers"]["petit"] = {"provider": "s1b", "model": "qwen2.5:1.5b"}
    with pytest.raises(GameRequestError, match="ollama pull qwen2.5:1.5b"):
        asyncio.run(preflight(cfg))
    s1.close()
