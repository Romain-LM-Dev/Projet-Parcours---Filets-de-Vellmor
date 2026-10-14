"""Les services Kafka en asynchrone (aiokafka) : reprise au dernier `run_start`, pont FastAPI, indicateurs.
Un vrai broker sur localhost:9092 (ignoré s'il n'y en a pas) ; chaque test travaille sur des topics à son nom."""
from __future__ import annotations

import asyncio
import json
import socket
import time

import pytest
import websockets

from filets import aio
from filets.bus import KafkaBus, ensure_topics, last_run_start_offset
from filets.indicators import IndicatorEngine
from filets.services import bridge as bridge_service
from filets.services import indicators as indicators_service
from helpers import play
from test_kafka_integration import BOOTSTRAP, broker_up, kcfg, publish_all  # noqa: F401  (kcfg est une fixture)

pytestmark = pytest.mark.skipif(not broker_up(), reason="aucun broker Kafka sur localhost:9092")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def read_topic(cfg, key, expected, timeout=20.0):
    consumer = await aio.assigned_consumer(cfg, {key: aio.OFFSET_BEGINNING})
    out = []

    async def gather():
        async for _topic, data in aio.messages(consumer):
            out.append(data)
            if len(out) >= expected:
                return

    try:
        await asyncio.wait_for(gather(), timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        await consumer.stop()
    return out


async def until(cond, timeout=30.0):
    t0 = time.monotonic()
    while not cond():
        assert time.monotonic() - t0 < timeout, "délai dépassé"
        await asyncio.sleep(0.1)


# ---------------------------------------------------------------- la reprise au dernier run_start
def test_the_async_scan_finds_the_same_run_start_as_the_blocking_one(kcfg, tmp_path):
    a = play(tmp_path, run_id="a", seasons=2, time__mode="sync")
    b = play(tmp_path, run_id="b", seasons=3, time__mode="sync", population__fishers=6)
    bus = KafkaBus(BOOTSTRAP, kcfg["bus"]["topics"], consume_commands=False)
    publish_all(bus, a + b)
    assert asyncio.run(aio.last_run_start_offset(kcfg)) == last_run_start_offset(kcfg) == len(a)


def test_the_async_scan_handles_an_empty_topic_and_a_topic_without_run_start(kcfg, tmp_path):
    bus = KafkaBus(BOOTSTRAP, kcfg["bus"]["topics"], consume_commands=False)
    assert asyncio.run(aio.last_run_start_offset(kcfg)) == 0
    events = play(tmp_path, seasons=1, time__mode="sync")
    publish_all(bus, [e for e in events if e["type"] != "run_start"])
    assert asyncio.run(aio.last_run_start_offset(kcfg)) == 0


def test_the_async_scan_finds_a_run_start_buried_deep_in_a_long_topic(kcfg, tmp_path):
    events = play(tmp_path, seasons=3, time__mode="sync")
    tail = [e for e in events if e["type"] != "run_start"]
    bus = KafkaBus(BOOTSTRAP, kcfg["bus"]["topics"], consume_commands=False)
    publish_all(bus, events + tail + tail)
    assert len(events) + 2 * len(tail) > 2500
    assert asyncio.run(aio.last_run_start_offset(kcfg)) == 0


def test_the_async_consumer_starts_where_asked_and_skips_what_is_not_json(kcfg):
    async def scenario():
        await asyncio.to_thread(ensure_topics, BOOTSTRAP, kcfg["bus"]["topics"])        # le broker ne crée pas les topics tout seul
        prod = await aio.producer(kcfg)
        topic = kcfg["bus"]["topics"]["events"]
        for i in range(5):
            await prod.send_and_wait(topic, json.dumps({"i": i}).encode())
        await prod.send_and_wait(topic, b"ceci n'est pas du json")
        await aio.send(prod, kcfg, "events", {"i": 5}, key="F01")
        await prod.stop()
        from_two = await aio.assigned_consumer(kcfg, {"events": 2})
        got = []
        try:
            async for _t, data in aio.messages(from_two):
                got.append(data["i"])
                if len(got) == 4:
                    break
        finally:
            await from_two.stop()
        return got, await read_topic(kcfg, "events", 6)

    got, everything = asyncio.run(scenario())
    assert got == [2, 3, 4, 5]                                  # depuis l'offset 2, le message illisible écarté
    assert [m["i"] for m in everything] == [0, 1, 2, 3, 4, 5]


# ---------------------------------------------------------------- le pont, en asynchrone de bout en bout
def test_the_bridge_service_relays_kafka_to_the_websocket_and_commands_back(kcfg, tmp_path):
    events = play(tmp_path, seasons=2, time__mode="sync")

    async def scenario():
        port = free_port()
        bus = KafkaBus(BOOTSTRAP, kcfg["bus"]["topics"], consume_commands=False)
        publish_all(bus, events)
        bus.publish("status", {"state": "idle", "engine_id": "e1", "wall_clock": "2026-01-01T00:00:00.000+00:00"}, key="engine")
        bus.flush()
        task = asyncio.create_task(bridge_service.amain(kcfg, "127.0.0.1", port))
        got = []
        try:
            for _ in range(100):                                 # le pont démarre : on se connecte dès qu'il écoute
                try:
                    ws = await websockets.connect(f"ws://127.0.0.1:{port}")
                    break
                except OSError:
                    await asyncio.sleep(0.1)
            else:
                raise AssertionError("le pont n'écoute pas")

            async def read():
                async for raw in ws:
                    got.append(json.loads(raw))

            reader = asyncio.create_task(read())
            await until(lambda: any(m["topic"] == "events" and m["data"]["type"] == "run_end" for m in got))
            await ws.send(json.dumps({"type": "pause"}))
            sent = await read_topic(kcfg, "commands", 1)
            reader.cancel()
            await ws.close()
            return got, sent
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    got, sent = asyncio.run(scenario())
    topics = [m["topic"] for m in got]
    assert topics[0] == "catalog" and "status" in topics and "hello" in topics
    relayed = [m["data"]["type"] for m in got if m["topic"] == "events"]
    assert relayed[0] == "run_start" and relayed[-1] == "run_end" and len(relayed) == len(events)
    assert sent == [{"type": "pause"}]                                  # l'ordre de Godot est dans le topic des commandes


# ---------------------------------------------------------------- les indicateurs, en asynchrone
def test_the_async_indicator_service_computes_what_a_local_engine_computes(kcfg, tmp_path):
    events = play(tmp_path, seasons=3, time__mode="sync")
    ref = IndicatorEngine(0.5)
    expected = [o["values"] for o in (ref.ingest(e) for e in events) if o and o["trigger"] == "season_end"]

    async def scenario():
        bus = KafkaBus(BOOTSTRAP, kcfg["bus"]["topics"], consume_commands=False)
        publish_all(bus, events)
        task = asyncio.create_task(indicators_service.amain(kcfg))
        try:
            got = await read_topic(kcfg, "indicators", 10_000, timeout=25)
            return [m["payload"]["values"] for m in got if m["payload"]["trigger"] == "season_end"]
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    got = asyncio.run(scenario())
    assert len(got) == 3 and got == expected
