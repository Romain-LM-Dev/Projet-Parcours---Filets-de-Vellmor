"""Modèles locaux (Ollama) : délai propre au fournisseur, plafond de requêtes simultanées, vérification et préchauffage
avant la partie, limités aux modèles réellement utilisés. Un faux serveur Ollama remplace le vrai."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from filets.engine import GameRequestError, build_game_config, preflight, used_models
from filets.llm import OpenAICompatClient
from helpers import cfg_for


class FakeOllama:
    def __init__(self, models, delay=0.0, generate_delay=0.0):
        self.models, self.delay = models, delay
        self.generate_delay = generate_delay       # durée du chargement d'un modèle (POST /api/generate)
        self.generated: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self._lock = threading.Lock()
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, payload):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._send({"models": [{"name": m} for m in outer.models]})

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/api/generate":
                    time.sleep(outer.generate_delay)
                    outer.generated.append(req["model"])
                    return self._send({"done": True})
                with outer._lock:
                    outer.in_flight += 1
                    outer.max_in_flight = max(outer.max_in_flight, outer.in_flight)
                time.sleep(outer.delay)
                with outer._lock:
                    outer.in_flight -= 1
                self._send({"choices": [{"message": {"content": '{"prise": 3}'}}],
                            "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}/v1"

    def close(self):
        self.server.shutdown()


LLM_CFG = {"temperature": 0.7, "max_tokens": 50, "json_mode": False, "timeout_s": 5, "max_retries": 0}


def population(*tiers):
    return [{"first_name": f"P{i}", "hamlet": "Ostrel", "archetype": "taiseux", "experience": 20, "wealth": 500,
             "debt_payment": 0, "kind": "llm", "tier": t} for i, t in enumerate(tiers)]


def request(*tiers, llm="ollama", elder="rule"):
    return {"mode": "sync", "seasons": 1, "seed": 1, "communication": "valley", "catches_visible": True, "llm": llm,
            "speed": 1.0, "population": {"elder": True, "elder_kind": elder, "fishers": population(*tiers)}}


# ---------------------------------------------------------------- client
def test_concurrency_is_capped_and_latency_counts_the_wait():
    srv = FakeOllama(["m"], delay=0.15)

    async def run():
        client = OpenAICompatClient("ollama", srv.base_url, None, 0, LLM_CFG, timeout_s=5, max_concurrency=2)
        try:
            return await asyncio.gather(*(client.complete("m", [{"role": "user", "content": "x"}], {}, "petit")
                                          for _ in range(6)))
        finally:
            await client.http.aclose()

    results = asyncio.run(run())
    srv.close()
    assert all(r.status == "ok" for r in results)
    assert srv.max_in_flight <= 2, f"{srv.max_in_flight} requêtes simultanées malgré le plafond de 2"
    assert max(r.latency_s for r in results) >= 0.4          # la dernière a attendu deux tours avant de partir


def test_without_a_cap_requests_all_go_at_once():
    srv = FakeOllama(["m"], delay=0.15)

    async def run():
        client = OpenAICompatClient("x", srv.base_url, None, 0, LLM_CFG, timeout_s=5)
        try:
            await asyncio.gather(*(client.complete("m", [{"role": "user", "content": "x"}], {}, "petit") for _ in range(5)))
        finally:
            await client.http.aclose()

    asyncio.run(run())
    srv.close()
    assert srv.max_in_flight >= 4


def test_the_provider_timeout_overrides_the_global_one(tmp_path):
    cfg = cfg_for(tmp_path)
    ollama = cfg["llm"]["providers"]["ollama"]
    assert ollama["timeout_s"] >= 120 and ollama["max_concurrency"] >= 1          # défauts adaptés aux modèles locaux
    assert cfg["llm"]["timeout_s"] == 45                                           # les API distantes gardent le leur

    async def check():
        c1 = OpenAICompatClient("ollama", "http://127.0.0.1:1/v1", None, 0, cfg["llm"], ollama["timeout_s"], 2)
        c2 = OpenAICompatClient("groq", "http://127.0.0.1:1/v1", None, 0, cfg["llm"])
        out = (c1.http.timeout.read, c2.http.timeout.read)
        await c1.http.aclose()
        await c2.http.aclose()
        return out

    assert asyncio.run(check()) == (ollama["timeout_s"], 45)


# ---------------------------------------------------------------- vérification et préchauffage
def game_cfg(tmp_path, srv, req):
    base = cfg_for(tmp_path)
    base["llm"]["providers"]["ollama"]["base_url"] = srv.base_url
    return build_game_config(base, req)


def test_only_models_that_are_really_used_are_required_and_warmed_up(tmp_path):
    srv = FakeOllama(["qwen2.5:1.5b"])           # le grand modèle n'est pas installé
    cfg = game_cfg(tmp_path, srv, request("petit", "petit", elder="rule"))
    assert used_models(cfg) == {"ollama": {"qwen2.5:1.5b"}}
    asyncio.run(preflight(cfg))                   # tous les pêcheurs ont le petit modèle : le grand n'est pas nécessaire
    assert srv.generated == ["qwen2.5:1.5b"]      # et le petit est chargé en mémoire avant la partie
    srv.close()


def test_a_missing_model_that_is_used_is_refused_with_the_command_to_install_it(tmp_path):
    srv = FakeOllama(["qwen2.5:1.5b"])
    cfg = game_cfg(tmp_path, srv, request("petit", "grand"))
    with pytest.raises(GameRequestError, match="ollama pull qwen2.5:7b"):
        asyncio.run(preflight(cfg))
    assert srv.generated == []                    # rien n'est chargé tant que tout n'est pas là
    srv.close()


def test_an_llm_elder_needs_the_large_model(tmp_path):
    srv = FakeOllama(["qwen2.5:1.5b"])
    cfg = game_cfg(tmp_path, srv, request("petit", elder="llm"))
    with pytest.raises(GameRequestError, match="qwen2.5:7b"):
        asyncio.run(preflight(cfg))
    srv.close()


def test_no_llm_agent_means_nothing_to_check(tmp_path):
    cfg = cfg_for(tmp_path)
    cfg["llm"]["providers"]["ollama"]["base_url"] = "http://127.0.0.1:9/v1"       # rien n'écoute
    req = request("petit", "petit", elder="rule")
    for f in req["population"]["fishers"]:
        f["kind"] = "rule"
    game = build_game_config(cfg, req)
    assert used_models(game) == {}
    asyncio.run(preflight(game))                  # ne lève rien : aucune IA n'est demandée


def test_scripted_provider_is_never_checked(tmp_path):
    cfg = cfg_for(tmp_path)
    game = build_game_config(cfg, request("petit", llm="scripted"))
    assert used_models(game) == {"scripted": {"scripted-petit"}}
    asyncio.run(preflight(game))


# ---------------------------------------------------------------- le moteur reste joignable pendant la préparation
def test_the_engine_keeps_announcing_itself_while_a_model_loads(tmp_path):
    """Charger un modèle local peut prendre une minute. Pendant ce temps, le moteur doit continuer à publier son état :
    sinon l'interface, qui le croit mort après quelques secondes de silence, affiche « moteur injoignable »."""
    import datetime as dt

    from filets.bus import LocalBus
    from filets.engine import Engine
    from filets.schemas import validate_status

    srv = FakeOllama(["qwen2.5:1.5b"], generate_delay=4.5)

    async def until(cond, timeout=60.0):
        t0 = time.monotonic()
        while not cond():
            assert time.monotonic() - t0 < timeout, "délai dépassé"
            await asyncio.sleep(0.02)

    async def scenario():
        cfg = cfg_for(tmp_path)
        cfg["llm"]["providers"]["ollama"]["base_url"] = srv.base_url
        bus = LocalBus()
        statuses = []
        bus.subscribe("status", statuses.append)
        engine = Engine(cfg, bus, quiet=True)
        task = asyncio.create_task(engine.serve())
        await until(lambda: statuses and statuses[-1]["state"] == "idle")
        req = request("petit", "petit", elder="rule")
        req["speed"] = "max"
        bus.send_command({"type": "start_game", "config": req})
        await until(lambda: statuses[-1]["state"] == "ended")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return statuses

    statuses = asyncio.run(scenario())
    srv.close()
    for s in statuses:
        assert validate_status(s) == [], s
    starting = [s for s in statuses if s["state"] == "starting"]
    stamps = [dt.datetime.fromisoformat(s["wall_clock"]) for s in starting]
    assert (stamps[-1] - stamps[0]).total_seconds() >= 4, "la préparation devait durer le temps du chargement"
    gaps = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:])]
    assert max(gaps) < 2.5, f"le moteur est resté muet {max(gaps):.1f} s pendant la préparation"
    details = [s["detail"] for s in starting if s["detail"]]
    assert any("Vérification" in d for d in details)
    assert any("Chargement du modèle qwen2.5:1.5b (1/1)" in d for d in details)
    assert all(s.get("detail") is None for s in statuses if s["state"] != "starting")  # le détail ne survit pas à la préparation
