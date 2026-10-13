"""Tests de cohérence : python -m pytest -q"""
from __future__ import annotations

import asyncio
import json

import pytest

from filets.bus import LocalBus
from filets.cli import compare_indicators, replay, run_once, verify
from filets.config import load_config
from filets.indicators import IndicatorEngine
from filets.llm import detect_drift, extract_json
from filets.memory import MemoryStore
from filets.rag import Retriever
from filets.config import ROOT


def cfg_for(tmp_path, **over):
    cfg = load_config(None)
    cfg["output"]["runs_dir"] = str(tmp_path / "runs")
    cfg["time"]["fast"] = True
    cfg["run"]["seasons"] = 3
    cfg["llm"]["providers"]["scripted"]["latency_scale"] = 0.0
    for k, v in over.items():
        sec, key = k.split("__")
        cfg[sec][key] = v
    from filets.config import normalize
    return normalize(cfg)


def events(tmp_path, rid):
    with open(tmp_path / "runs" / rid / "events.jsonl", encoding="utf-8") as f:
        return [json.loads(x) for x in f]


def strip(ev):
    return {k: v for k, v in ev.items() if k not in ("processed_at", "wall_clock", "run_id", "event_id")}


def test_sync_is_deterministic(tmp_path):
    a = asyncio.run(run_once(cfg_for(tmp_path, time__mode="sync"), quiet=True, run_id="a"))
    b = asyncio.run(run_once(cfg_for(tmp_path, time__mode="sync"), quiet=True, run_id="b"))
    ea = [strip(e) for e in events(tmp_path, a) if e["type"] != "llm_call"]
    eb = [strip(e) for e in events(tmp_path, b) if e["type"] != "llm_call"]
    as_text = lambda evs: json.dumps(evs).replace('"a-', '"X-')
    assert as_text(ea) == as_text(eb).replace('"b-', '"X-')


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_run_verify_replay(tmp_path, mode):
    cfg = cfg_for(tmp_path, time__mode=mode)
    rid = asyncio.run(run_once(cfg, quiet=True, run_id=f"r-{mode}"))
    assert verify(rid, cfg)
    assert asyncio.run(replay(rid, cfg, speed=0, ws=False, ws_port=0, linger=False))
    evs = events(tmp_path, rid)
    types = {e["type"] for e in evs}
    assert {"catch", "utterance", "decision", "memory_write", "season_end"} <= types


def test_population_size_is_a_parameter(tmp_path):
    cfg = cfg_for(tmp_path, population__fishers=13)
    rid = asyncio.run(run_once(cfg, quiet=True, run_id="n13"))
    start = events(tmp_path, rid)[0]
    assert sum(a["role"] == "pecheur" for a in start["payload"]["agents"]) == 13
    assert start["payload"]["lake"]["capacity"] == pytest.approx(13 * 12.5)


def test_baseline_makes_no_llm_call(tmp_path):
    cfg = cfg_for(tmp_path, population__rule_fraction=1.0)
    rid = asyncio.run(run_once(cfg, quiet=True, run_id="base"))
    assert not [e for e in events(tmp_path, rid) if e["type"] == "llm_call"]


def test_no_communication_means_no_norm(tmp_path):
    cfg = cfg_for(tmp_path, scenario__communication="none")
    rid = asyncio.run(run_once(cfg, quiet=True, run_id="nocom"))
    evs = events(tmp_path, rid)
    assert not [e for e in evs if e["type"] in ("utterance", "norm_adopted")]


def test_scheduled_drought_halves_stock(tmp_path):
    cfg = cfg_for(tmp_path, scenario__scheduled_injections=[{"season": 2, "type": "drought"}])
    rid = asyncio.run(run_once(cfg, quiet=True, run_id="drought"))
    evs = events(tmp_path, rid)
    i = next(k for k, e in enumerate(evs) if e["type"] == "injection")
    upd = next(e for e in evs[i:] if e["type"] == "lake_update")
    assert upd["payload"]["cause"] == "injection"
    before = upd["payload"]["stock"] - upd["payload"]["delta"]
    assert upd["payload"]["stock"] == pytest.approx(before / 2, abs=1e-2)


def test_indicator_detects_temporal_violation():
    eng = IndicatorEngine()
    base = {"run_id": "x", "season": 1, "sim_label": "", "processed_at": 0, "wall_clock": ""}
    eng.ingest({**base, "type": "run_start", "event_id": "s0", "sim_time": 0.0,
                "payload": {"lake": {"capacity": 100.0, "sustainable_yield": 25.0, "stock": 100.0}, "agents": []}})
    eng.ingest({**base, "type": "utterance", "event_id": "u1", "sim_time": 5.0,
                "payload": {"heard": [], "info_horizon": 5.0}})
    eng.ingest({**base, "type": "decision", "event_id": "d1", "sim_time": 4.0,
                "payload": {"info_horizon": 4.0, "used_event_ids": ["u1"]}})
    assert eng.temporal_violations == 1


def test_memory_respects_horizon():
    m = MemoryStore("F01", 0.01, {"recency": 1, "importance": 1, "relevance": 1})
    m.add(1.0, "promesse de pêcher deux tonnes", "promesse", 1.0, pinned=True, expires_season=3)
    m.add(10.0, "le lac est très bas", "peche", 0.9)
    assert [x.text for x, _ in m.retrieve("lac", horizon=5.0, k=5)] == ["promesse de pêcher deux tonnes"]
    assert m.pinned(horizon=0.5, season=1) == []
    assert len(m.pinned(horizon=2.0, season=3)) == 1 and m.pinned(horizon=2.0, season=4) == []


def test_rag_access_control():
    r = Retriever(ROOT / "corpus", {"capacity": "100", "price": "100", "upkeep": "150", "half_capacity": "50"})
    ostrel = {p.id.split("#")[0] for p, _ in r.search("registre marché ventes", "Ostrel", 0, 10)}
    assert "comptes-marche-ostrel" in ostrel and "comptes-marche-tilque" not in ostrel
    assert not r.search("registre marché", "Ostrel", horizon=-10000, k=5) or all(
        p.sim_time <= -10000 for p, _ in r.search("registre marché", "Ostrel", horizon=-10000, k=5))
    assert all("{{" not in p.text for p in r.passages)


def test_invalid_event_goes_to_deadletter(tmp_path):
    from filets.clock import SimClock
    from filets.events import EventFactory
    bus = LocalBus()
    dead = []
    bus.subscribe("deadletter", dead.append)
    f = EventFactory("t", SimClock(30, 12, 20, True), bus, None)
    f.emit("catch", {"agent": "F01"})        # payload incomplet
    assert len(dead) == 1 and bus.counts["events"] == 1   # l'incident schema_violation, lui, passe


def test_json_repair_and_drift():
    assert extract_json('```json\n{"prise": 3, "justification": "ok",}\n```') == {"prise": 3, "justification": "ok"}
    assert extract_json("pas de json") is None
    assert detect_drift("En tant qu'intelligence artificielle, je ne peux pas")[0]
    assert not detect_drift("Je prendrai trois tonnes, pas plus.")[0]


def test_openai_compatible_client_with_retry(tmp_path):
    """Chemin réel d'un fournisseur gratuit (Ollama/Groq…) contre un faux serveur local : 429 puis succès."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    hits = {"n": 0}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            hits["n"] += 1
            if hits["n"] == 1:
                self.send_response(429)
                self.end_headers()
                return
            user = body["messages"][-1]["content"]
            content = (json.dumps({"prise": 3.5, "justification": "Je reste raisonnable."}) if "prise" in user
                       else json.dumps({"message": "Je propose trois tonnes.", "destinataire": "tous",
                                        "proposition_quota": 3, "soutien": None, "promesse": 3, "accuse": None}))
            out = json.dumps({"choices": [{"message": {"content": content}}],
                              "usage": {"prompt_tokens": 100, "completion_tokens": 20}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = cfg_for(tmp_path, time__mode="sync", population__fishers=3)
    cfg["run"]["seasons"] = 1
    cfg["llm"]["max_retries"] = 1
    cfg["llm"]["providers"]["fake"] = {"base_url": f"http://127.0.0.1:{srv.server_port}/v1", "api_key_env": None, "rpm": 0}
    cfg["llm"]["tiers"] = {"grand": {"provider": "fake", "model": "m-grand"}, "petit": {"provider": "fake", "model": "m-petit"}}
    rid = asyncio.run(run_once(cfg, quiet=True, run_id="http"))
    srv.shutdown()
    evs = events(tmp_path, rid)
    calls = [e["payload"] for e in evs if e["type"] == "llm_call"]
    assert calls and all(c["status"] == "ok" for c in calls)
    assert sum(c["retries"] for c in calls) == 1
    llm_catches = [e for e in evs if e["type"] == "decision" and e["payload"]["decision_type"] == "catch"
                   and e["payload"]["agent_kind"] == "llm"]
    assert llm_catches and all(d["payload"]["value"] == 3.5 for d in llm_catches)
    assert any(e["type"] == "norm_adopted" for e in evs)
