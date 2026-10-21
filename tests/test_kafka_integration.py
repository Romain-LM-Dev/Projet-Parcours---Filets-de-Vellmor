"""Intégration avec un vrai broker Kafka (ignorée s'il n'y en a pas sur 127.0.0.1:19092).

    docker compose up -d && python -m pytest tests/test_kafka_integration.py

Chaque test travaille sur des topics à son nom : le broker du jeu n'est pas touché.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid

import pytest

from filets.bus import (OFFSET_BEGINNING, KafkaBus, kafka_assigned_consumer, last_run_start_offset)
from filets.engine import Engine
from filets.indicators import IndicatorEngine
from filets.pipeline import IndicatorPublisher
from filets.schemas import validate_status
from helpers import cfg_for, play

BOOTSTRAP = "127.0.0.1:19092"


def broker_up() -> bool:
    try:
        from confluent_kafka.admin import AdminClient
        AdminClient({"bootstrap.servers": BOOTSTRAP}).list_topics(timeout=3)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not broker_up(), reason="aucun broker Kafka sur 127.0.0.1:19092")


@pytest.fixture
def kcfg(tmp_path):
    """Configuration pointant vers des topics jetables."""
    from confluent_kafka.admin import AdminClient

    cfg = cfg_for(tmp_path)
    tag = uuid.uuid4().hex[:8]
    cfg["bus"]["kind"] = "kafka"
    cfg["bus"]["bootstrap"] = BOOTSTRAP
    cfg["bus"]["topics"] = {k: f"filets.test.{tag}.{k}" for k in cfg["bus"]["topics"]}
    yield cfg
    admin = AdminClient({"bootstrap.servers": BOOTSTRAP})
    for fut in admin.delete_topics(list(cfg["bus"]["topics"].values())).values():
        try:
            fut.result(10)
        except Exception:
            pass


def publish_all(bus, events):
    for ev in events:
        bus.publish("events", ev, key=ev.get("actor"))
    bus.flush()


def read_topic(cfg, key, expected, timeout=20.0):
    """Lit un topic depuis le début jusqu'à `expected` messages (ou le délai)."""
    c = kafka_assigned_consumer(cfg, f"t-{uuid.uuid4().hex[:6]}", {key: OFFSET_BEGINNING})
    out, t0 = [], time.monotonic()
    while len(out) < expected and time.monotonic() - t0 < timeout:
        m = c.poll(0.5)
        if m is not None and not m.error():
            out.append(json.loads(m.value()))
    c.close()
    return out


def test_service_started_late_still_finds_the_start_of_the_current_run(kcfg, tmp_path):
    """Le bug d'origine : un service qui rejoint après `run_start` calculait des pourcentages de stock sur une
    capacité inconnue (7600 % au lieu de 76 %). Reprendre au dernier `run_start` donne les chiffres du run."""
    a = play(tmp_path, run_id="a", seasons=2, time__mode="sync")
    b = play(tmp_path, run_id="b", seasons=3, time__mode="sync", population__fishers=6)
    bus = KafkaBus(BOOTSTRAP, kcfg["bus"]["topics"], consume_commands=False)
    publish_all(bus, a + b)

    start = last_run_start_offset(kcfg)
    assert start == len(a)                                   # le run_start de « b », pas celui de « a »

    pub_bus = KafkaBus(BOOTSTRAP, kcfg["bus"]["topics"], consume_commands=False)
    pub = IndicatorPublisher(pub_bus, str(tmp_path / "runs"), 0.5, journal=False)
    consumer = kafka_assigned_consumer(kcfg, "filets-indicators-test", {"events": start})
    seen, t0 = 0, time.monotonic()
    while seen < len(b) and time.monotonic() - t0 < 30:
        m = consumer.poll(0.5)
        if m is None or m.error():
            continue
        pub.on_event(json.loads(m.value()))
        seen += 1
    consumer.close()
    pub_bus.flush()

    expected = [o for o in (IndicatorEngine(0.5).ingest(e) for e in b)]       # calcul direct, sans Kafka
    ref = IndicatorEngine(0.5)
    ref_seasons = [o["values"] for o in (ref.ingest(e) for e in b) if o and o["trigger"] == "season_end"]
    got = [m["payload"]["values"] for m in read_topic(kcfg, "indicators", 10_000, timeout=3)
           if m["payload"]["trigger"] == "season_end"]
    assert len(got) == 3 and got == ref_seasons
    assert all(v["capacity"] == 6 * 12.5 and 0 <= v["stock_ratio"] <= 1 for v in got)
    assert all(v["fishers"] == 6 for v in got)


def test_scan_handles_empty_topic_and_topic_without_run_start(kcfg, tmp_path):
    bus = KafkaBus(BOOTSTRAP, kcfg["bus"]["topics"], consume_commands=False)
    assert last_run_start_offset(kcfg) == 0
    events = play(tmp_path, seasons=1, time__mode="sync")
    publish_all(bus, [e for e in events if e["type"] != "run_start"])
    assert last_run_start_offset(kcfg) == 0                  # rien à retrouver : on repart du début


def test_scan_finds_a_run_start_buried_deep_in_a_long_topic(kcfg, tmp_path):
    events = play(tmp_path, seasons=3, time__mode="sync")
    tail = [e for e in events if e["type"] != "run_start"]
    bus = KafkaBus(BOOTSTRAP, kcfg["bus"]["topics"], consume_commands=False)
    publish_all(bus, events + tail + tail)                   # run_start à plus de 2 000 messages de la fin : plusieurs blocs
    assert len(events) + 2 * len(tail) > 2500
    assert last_run_start_offset(kcfg) == 0


def test_engine_lobby_over_kafka_waits_for_its_partition_then_plays(kcfg, tmp_path):
    """Commandes, état et événements passent tous par le broker, comme avec le pont Godot."""
    statuses, stop = [], threading.Event()

    def watch_status():
        c = kafka_assigned_consumer(kcfg, f"w-{uuid.uuid4().hex[:6]}", {"status": OFFSET_BEGINNING})
        while not stop.is_set():
            m = c.poll(0.2)
            if m is not None and not m.error():
                statuses.append(json.loads(m.value()))
        c.close()

    watcher = threading.Thread(target=watch_status, daemon=True)
    watcher.start()

    async def scenario():
        engine_bus = KafkaBus(BOOTSTRAP, kcfg["bus"]["topics"], group=f"engine-{uuid.uuid4().hex[:6]}")
        eng = Engine(kcfg, engine_bus, quiet=True)
        task = asyncio.create_task(eng.serve())

        async def until(cond, timeout=60.0):
            t0 = time.monotonic()
            while not cond():
                assert time.monotonic() - t0 < timeout, "délai dépassé"
                await asyncio.sleep(0.1)

        await until(lambda: statuses and statuses[-1]["state"] == "idle")      # annoncé une fois la partition reçue
        client = KafkaBus(BOOTSTRAP, kcfg["bus"]["topics"], consume_commands=False)
        req = {"mode": "sync", "seasons": 2, "seed": 3, "communication": "valley", "catches_visible": True,
               "llm": "scripted", "speed": "max",
               "population": {"elder": True, "elder_kind": "rule", "fishers": [
                   {"first_name": "Aldric", "hamlet": "Ostrel", "archetype": "taiseux", "experience": 20,
                    "wealth": 500, "debt_payment": 0, "kind": "rule", "tier": "auto"},
                   {"first_name": "Odile", "hamlet": "Tilque", "archetype": "beau_parleur", "experience": 12,
                    "wealth": 400, "debt_payment": 0, "kind": "rule", "tier": "auto"}]}}
        client.send_command({"type": "start_game", "config": req})
        client.flush()
        await until(lambda: statuses[-1]["state"] == "ended")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        eng.close()
        engine_bus.close()

    asyncio.run(scenario())
    stop.set()
    watcher.join(3)
    for s in statuses:
        assert validate_status(s) == [], s
    states = []
    for s in statuses:
        if not states or states[-1] != s["state"]:
            states.append(s["state"])
    assert states == ["idle", "starting", "running", "ended"]
    assert statuses[-1]["end_reason"] == "completed"
    # le journal des événements est bien dans Kafka, depuis son run_start
    events = read_topic(kcfg, "events", 100_000, timeout=3)
    assert events[0]["type"] == "run_start" and events[-1]["type"] == "run_end"
    assert events[0]["payload"]["lake"]["capacity"] == 25.0
