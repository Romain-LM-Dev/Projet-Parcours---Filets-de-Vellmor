"""Le pont WebSocket : catalogue, état, historique du run en cours, ordres vers le moteur."""
from __future__ import annotations

import asyncio
import json

import pytest
from websockets.asyncio.client import connect

from filets.ws_bridge import WSBridge


def ev(etype, run="r1", **payload):
    return {"type": etype, "run_id": run, "event_id": f"{run}-{etype}", "payload": payload}


def ind(run="r1", src="s1", trigger="season_end"):
    return {"type": "indicator", "run_id": run, "payload": {"trigger": trigger, "source_event_id": src, "values": {}}}


async def read_all(ws, wait=0.3):
    out = []
    try:
        while True:
            out.append(json.loads(await asyncio.wait_for(ws.recv(), wait)))
    except asyncio.TimeoutError:
        return out


def run_bridge(scenario, catalog=None):
    async def main():
        commands = []
        bridge = WSBridge("127.0.0.1", 0, commands.append, catalog=catalog)
        await bridge.start()
        port = next(iter(bridge._server.sockets)).getsockname()[1]
        try:
            return await scenario(bridge, f"ws://127.0.0.1:{port}", commands)
        finally:
            await bridge.stop()
    return asyncio.run(main())


def test_new_client_gets_catalog_then_status_then_history_of_the_current_run():
    async def scenario(bridge, url, commands):
        bridge.push("events", ev("run_start", run="old"))
        bridge.push("events", ev("catch", run="old"))
        bridge.push("events", ev("run_start", run="new"))
        bridge.push("events", ev("season_start", run="new"))
        bridge.push("status", {"state": "running", "run_id": "new"})
        bridge.push("status", {"state": "paused", "run_id": "new"})        # seul le dernier état est conservé
        await bridge.drain()
        async with connect(url) as ws:
            return await read_all(ws)

    got = run_bridge(scenario, catalog={"hamlets": ["Ostrel"]})
    assert [m["topic"] for m in got] == ["catalog", "status", "hello", "events", "events"]
    assert got[0]["data"] == {"hamlets": ["Ostrel"]}
    assert got[1]["data"]["state"] == "paused"
    assert got[2]["data"]["buffered"] == 2                                  # l'ancien run n'est pas rejoué
    assert [m["data"]["type"] for m in got[3:]] == ["run_start", "season_start"]


def test_indicators_of_another_run_or_already_seen_are_dropped():
    async def scenario(bridge, url, commands):
        bridge.push("events", ev("run_start", run="r2"))
        bridge.push("indicators", ind(run="r1", src="a"))          # reste d'un run précédent
        bridge.push("indicators", ind(run="r2", src="b"))
        bridge.push("indicators", ind(run="r2", src="b"))          # republié par un service redémarré
        bridge.push("indicators", ind(run="r2", src="c"))
        await bridge.drain()
        async with connect(url) as ws:
            return await read_all(ws)

    got = run_bridge(scenario)
    kept = [m["data"]["payload"]["source_event_id"] for m in got if m["topic"] == "indicators"]
    assert kept == ["b", "c"]


def test_live_messages_reach_connected_clients_and_status_is_not_replayed_as_history():
    async def scenario(bridge, url, commands):
        async with connect(url) as ws:
            first = await read_all(ws, 0.2)                      # hello seul
            bridge.push("events", ev("run_start"))
            bridge.push("status", {"state": "running"})
            bridge.push("indicators", ind())
            live = await read_all(ws, 0.3)
            return first, live, bridge.buffer

    first, live, buffer = run_bridge(scenario)
    assert [m["topic"] for m in first] == ["hello"]
    assert [m["topic"] for m in live] == ["events", "status", "indicators"]
    assert len(buffer) == 2                                      # événements et indicateurs seulement


def test_commands_from_the_interface_are_forwarded_and_garbage_is_ignored():
    async def scenario(bridge, url, commands):
        async with connect(url) as ws:
            await read_all(ws, 0.2)
            await ws.send(json.dumps({"type": "pause"}))
            await ws.send(json.dumps({"type": "start_game", "config": {"mode": "sync"}}))
            await ws.send("pas du json")
            await ws.send(json.dumps({"pas_de_type": 1}))
            await ws.send(json.dumps([1, 2]))
            await asyncio.sleep(0.3)
        return commands

    commands = run_bridge(scenario)
    assert commands == [{"type": "pause"}, {"type": "start_game", "config": {"mode": "sync"}}]


def test_a_failing_command_handler_does_not_drop_the_connection():
    async def main():
        def boom(cmd):
            raise RuntimeError("bus indisponible")
        bridge = WSBridge("127.0.0.1", 0, boom)
        await bridge.start()
        port = next(iter(bridge._server.sockets)).getsockname()[1]
        try:
            async with connect(f"ws://127.0.0.1:{port}") as ws:
                await read_all(ws, 0.2)
                await ws.send(json.dumps({"type": "pause"}))
                await asyncio.sleep(0.2)
                bridge.push("events", ev("run_start"))
                return await read_all(ws, 0.3)
        finally:
            await bridge.stop()

    got = asyncio.run(main())
    assert [m["topic"] for m in got] == ["events"]


def test_the_engine_catalog_travels_with_its_status_and_replaces_the_bridge_default():
    """Avec Kafka, le pont est un autre processus : c'est le moteur qui dit quelles options le menu propose."""
    async def scenario(bridge, url, commands):
        async with connect(url) as ws:
            await read_all(ws, 0.2)
            bridge.push("status", {"state": "idle", "engine_id": "e1", "catalog": {"defaults": {"mode": "sync"}}})
            bridge.push("status", {"state": "idle", "engine_id": "e1", "catalog": {"defaults": {"mode": "sync"}}})
            live = await read_all(ws, 0.3)
        async with connect(url) as late:
            joined = await read_all(late, 0.3)
        return live, joined

    live, joined = run_bridge(scenario, catalog={"defaults": {"mode": "async"}})
    topics = [m["topic"] for m in live]
    assert topics.count("catalog") == 1                              # inchangé la deuxième fois : pas renvoyé
    assert next(m for m in live if m["topic"] == "catalog")["data"] == {"defaults": {"mode": "sync"}}
    assert all("catalog" not in m["data"] for m in live if m["topic"] == "status")      # l'état reste léger
    assert joined[0]["topic"] == "catalog" and joined[0]["data"] == {"defaults": {"mode": "sync"}}
