"""Le modèle de décision (palier `reflexe`, tev1) rattrape les actions perdues et juge la confiance d'un absent ; sans lui, rien ne change.
Il ne rédige jamais : paroles, prise hors routine et narration restent au grand modèle.
"""
from __future__ import annotations

import asyncio
import socket

import pytest

from filets import bench
from filets.bus import LocalBus
from filets.world import World
from helpers import cfg_for, read_events
from test_council import IDS, fake_game, kinds
from test_rumors import Recorder
from test_system_one import FakeSystemOne

NO_WAIT = dict(time__mode="async", time__fast=False, time__sim_hours_per_second=7200, time__wait_for_ai=False)


def catches(events):
    return [e["payload"] for e in kinds(events, "decision") if e["payload"]["decision_type"] == "catch"]


def test_an_unreadable_answer_is_decided_by_the_decision_model_not_by_the_fallback_rule(tmp_path):
    s1 = FakeSystemOne(level=3)
    world, events, _ = fake_game(tmp_path, "illisible", Recorder(prise="abc"), seasons=1, s1=s1)
    s1.close()
    decs = catches(events)
    assert decs and all(d["tier"] == "reflexe" and d["system"] == "S1" and not d["fallback"] and d["value"] == 2.8
                        for d in decs)
    assert all("reprise" in d["justification"] for d in decs)


def test_without_the_decision_model_an_unreadable_answer_falls_back_to_the_rule_as_before(tmp_path):
    world, events, _ = fake_game(tmp_path, "illisible-seul", Recorder(prise="abc"), seasons=1)
    decs = catches(events)
    assert decs and all(d["fallback"] and d["tier"] != "reflexe" for d in decs)


def test_a_missed_window_is_caught_up_by_the_decision_model(tmp_path):
    cfg = cfg_for(tmp_path, seasons=1, **NO_WAIT)
    cfg["llm"]["providers"]["scripted"]["latency_scale"] = 5.0          # le grand modèle répond bien après la fermeture
    s1 = FakeSystemOne(level=3)
    cfg["llm"]["providers"]["s1"] = {"base_url": s1.url, "kind": "systemone", "local": True, "timeout_s": 5}
    cfg["llm"]["tiers"]["reflexe"] = {"provider": "s1", "model": "tev1:0.8b"}
    world = World(cfg, LocalBus(), "rattrape")
    asyncio.run(world.run())
    s1.close()
    events = read_events(tmp_path, "rattrape")
    missed = [e["payload"] for e in kinds(events, "incident") if e["payload"]["incident_type"] == "missed_window"]
    assert any(m["handled_by"] == "reprise par le réflexe" for m in missed)
    assert not any(m["handled_by"] == "sortie perdue" for m in missed)
    rescued = [d for d in catches(events) if d["tier"] == "reflexe" and "reprise" in d["justification"]]
    assert rescued and all(d["system"] == "S1" and not d["fallback"] for d in rescued)
    assert len(kinds(events, "catch")) == len(world.fishers)             # aucune sortie perdue


def test_a_missed_window_without_the_decision_model_loses_the_outing_as_before(tmp_path):
    cfg = cfg_for(tmp_path, seasons=1, **NO_WAIT)
    cfg["llm"]["providers"]["scripted"]["latency_scale"] = 5.0
    world = World(cfg, LocalBus(), "perdue")
    asyncio.run(world.run())
    missed = [e["payload"] for e in kinds(read_events(tmp_path, "perdue"), "incident")
              if e["payload"]["incident_type"] == "missed_window"]
    assert any(m["handled_by"] == "sortie perdue" for m in missed)


def test_the_debrief_of_an_absent_goes_to_the_decision_model_when_there_is_one(tmp_path):
    s1 = FakeSystemOne(level=5)                                          # +2 pour chaque pêcheur
    rec = Recorder(elect={"Mathis": "Mathis", "Inès": "Mathis", "Elwen": "Théo", "Théo": "Théo"}, debrief={IDS["Théo"]: -2})
    world, events, _ = fake_game(tmp_path, "debrief", rec, seasons=2, s1=s1)
    s1.close()
    asked = [r for r in s1.requests if r.get("questions") and "Qui ce pêcheur" not in str(r["questions"])
             and any("confiance" in q.get("instructions", "") for q in r["questions"].values())]
    assert asked and not [r for r in rec.requests if "Tu n'étais pas au conseil" in r["user"]]
    assert [t for t in kinds(events, "trust") if t["payload"]["delta"] > 0]


def test_the_debrief_stays_with_the_big_model_without_the_decision_model(tmp_path):
    rec = Recorder(elect={"Mathis": "Mathis", "Inès": "Mathis", "Elwen": "Théo", "Théo": "Théo"}, debrief={IDS["Théo"]: -2})
    fake_game(tmp_path, "debrief-seul", rec, seasons=2)
    assert [r for r in rec.requests if "Tu n'étais pas au conseil" in r["user"]]


def test_the_bench_refuses_to_run_while_a_game_answers_on_its_port(tmp_path):
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        port = srv.getsockname()[1]
        assert bench.server_running(port)
        assert bench.run("x", {}, tmp_path, port=port) == 2               # refus avant toute lecture ou tout appel de modèle
    assert not bench.server_running(port)
    assert bench.run("x", {}, tmp_path, port=port) == 1                   # port libre, mais pas d'invites enregistrées


def test_the_bench_measures_agreement_on_recorded_prompts():
    assert bench.same("catch", bench.norm("catch", "prise", 3.0), bench.norm("catch", "prise", 3.4))
    assert not bench.same("catch", 3.0, 3.6)
    assert bench.same("vote", bench.norm("vote", "X1", 0.9), bench.norm("vote", "X1", "oui"))
    assert not bench.same("vote", bench.norm("vote", "X1", 0.2), bench.norm("vote", "X1", "oui"))
