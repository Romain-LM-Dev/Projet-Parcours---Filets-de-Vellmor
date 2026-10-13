"""Mode asynchrone : quand une fenêtre se ferme (pêche, veillée), ceux qui réfléchissent encore ont raté leur tour.

On le constate à l'instant de la fermeture et on abandonne leur appel. Avant, on attendait que chaque réponse arrive,
trop tard pour servir : avec un modèle lent, la fin de chaque saison durait des minutes, pour rien.
"""
from __future__ import annotations

import asyncio
import time

from filets.cli import verify
from filets.indicators import IndicatorEngine
from helpers import make_world, read_events

# 300 jours simulés par seconde réelle quand une IA réfléchit : une réponse d'une seconde arrive des mois trop tard
FAST_WORLD = dict(time__fast=False, time__sim_hours_per_second=7200)


def play(world):
    t0 = time.monotonic()
    asyncio.run(world.run())
    return time.monotonic() - t0


def kinds(events, kind):
    return [e for e in events if e["type"] == kind]


def test_slow_models_lose_their_turn_and_the_season_does_not_wait_for_them(tmp_path):
    # latences de 5 à 20 s (faux LLM étiré) : bien au-delà des fenêtres de pêche et de veillée
    world, bus, _ = make_world(tmp_path, "late", latency_scale=5.0, seasons=1, time__mode="async", **FAST_WORLD)
    elapsed = play(world)
    events = read_events(tmp_path, "late")
    assert elapsed < 8, f"la saison a attendu les réponses trop tardives ({elapsed:.1f} s)"

    missed = [e["payload"] for e in kinds(events, "incident") if e["payload"]["incident_type"] == "missed_window"]
    assert any(m["handled_by"] == "sortie perdue" for m in missed)
    assert any(m["handled_by"] == "réplique perdue" for m in missed)
    assert all("réfléchissait encore" in m["detail"] for m in missed)

    cancelled = [e["payload"] for e in kinds(events, "llm_call") if e["payload"]["status"] == "cancelled"]
    assert cancelled and all(c["completion_tokens"] == 0 and c["latency_s"] >= 0 for c in cancelled)
    # chaque appel abandonné correspond à quelqu'un qui a raté son tour (les agents à règles n'appellent pas d'IA)
    assert len(cancelled) <= len(missed) + 1
    # seuls les agents à règles (qui répondent sans attendre une IA) ont pu parler : aucune réplique d'IA trop tardive n'est entendue
    rule_ids = {a["id"] for a in events[0]["payload"]["agents"] if a["kind"] == "rule"}
    assert {e["payload"]["speaker"] for e in kinds(events, "utterance")} <= rule_ids
    assert len(kinds(events, "season_end")) == 1
    assert verify("late", world.cfg)


def test_the_loss_is_dated_at_the_closing_of_the_window(tmp_path):
    world, bus, _ = make_world(tmp_path, "dated", latency_scale=5.0, seasons=1, time__mode="async", **FAST_WORLD)
    play(world)
    events = read_events(tmp_path, "dated")
    T = world.cfg["time"]
    for e in kinds(events, "incident"):
        p = e["payload"]
        if p["incident_type"] != "missed_window":
            continue
        want = T["fishing_close_day"] if p["handled_by"] == "sortie perdue" else T["assembly_close_day"]
        assert e["sim_time"] == want, (p["handled_by"], e["sim_time"])      # J20 pour la pêche, J29 pour la veillée


def test_cancelled_calls_are_work_lost_not_model_errors(tmp_path):
    world, bus, pub = make_world(tmp_path, "cost", latency_scale=5.0, seasons=1, time__mode="async", **FAST_WORLD)
    play(world)
    events = read_events(tmp_path, "cost")
    eng = IndicatorEngine(0.5)
    for e in events:
        eng.ingest(e)
    v = eng.last_values
    assert v["llm_cancelled"] > 0
    assert v["llm_errors"] == 0                       # un appel abandonné n'est pas une erreur du modèle
    assert world.router.usage.cancelled == v["llm_cancelled"]


def test_fast_models_lose_nothing(tmp_path):
    world, bus, _ = make_world(tmp_path, "fast", latency_scale=0.0, seasons=2, time__mode="async")
    play(world)
    events = read_events(tmp_path, "fast")
    assert not [e for e in kinds(events, "incident") if e["payload"]["incident_type"] == "missed_window"]
    assert not [e for e in kinds(events, "llm_call") if e["payload"]["status"] == "cancelled"]
    assert kinds(events, "utterance")


def test_agents_who_finished_their_rounds_are_not_blamed(tmp_path):
    """Seuls ceux qui réfléchissent à la fermeture ont raté leur tour : pas ceux qui ont fini de parler."""
    world, bus, _ = make_world(tmp_path, "mixed", latency_scale=0.0, seasons=1, time__mode="async",
                               population__rule_fraction=1.0)          # tous à règles : aucune réflexion à perdre
    play(world)
    events = read_events(tmp_path, "mixed")
    assert not [e for e in kinds(events, "incident") if e["payload"]["incident_type"] == "missed_window"]
    assert kinds(events, "utterance")
