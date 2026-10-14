"""L'API FastAPI : le WebSocket de Godot (catalogue, état, historique du run en cours, ordres vers le moteur) et le REST."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from websockets.asyncio.client import connect

from filets.api import ApiServer, LocalRuns


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


def run_api(scenario, catalog=None, runs=None, on_command=None):
    async def main():
        commands = []
        api = ApiServer("127.0.0.1", 0, on_command or commands.append, catalog=catalog, runs=runs)
        await api.start()
        try:
            return await scenario(api, f"ws://127.0.0.1:{api.port}", commands)
        finally:
            await api.stop()
    return asyncio.run(main())


# ---------------------------------------------------------------- le WebSocket de Godot
def test_new_client_gets_catalog_then_status_then_history_of_the_current_run():
    async def scenario(api, url, commands):
        api.push("events", ev("run_start", run="old"))
        api.push("events", ev("catch", run="old"))
        api.push("events", ev("run_start", run="new"))
        api.push("events", ev("season_start", run="new"))
        api.push("status", {"state": "running", "run_id": "new"})
        api.push("status", {"state": "paused", "run_id": "new"})        # seul le dernier état est conservé
        await api.drain()
        async with connect(url) as ws:
            return await read_all(ws)

    got = run_api(scenario, catalog={"hamlets": ["Ostrel"]})
    assert [m["topic"] for m in got] == ["catalog", "status", "hello", "events", "events"]
    assert got[0]["data"] == {"hamlets": ["Ostrel"]}
    assert got[1]["data"]["state"] == "paused"
    assert got[2]["data"]["buffered"] == 2                                  # l'ancien run n'est pas rejoué
    assert [m["data"]["type"] for m in got[3:]] == ["run_start", "season_start"]


@pytest.mark.parametrize("path", ["", "/ws"])
def test_godot_connects_at_the_root_and_so_does_any_client_at_ws(path):
    async def scenario(api, url, commands):
        async with connect(url + path) as ws:
            return await read_all(ws, 0.2)

    assert [m["topic"] for m in run_api(scenario)] == ["hello"]


def test_indicators_of_another_run_or_already_seen_are_dropped():
    async def scenario(api, url, commands):
        api.push("events", ev("run_start", run="r2"))
        api.push("indicators", ind(run="r1", src="a"))          # reste d'un run précédent
        api.push("indicators", ind(run="r2", src="b"))
        api.push("indicators", ind(run="r2", src="b"))          # republié par un service redémarré
        api.push("indicators", ind(run="r2", src="c"))
        await api.drain()
        async with connect(url) as ws:
            return await read_all(ws)

    got = run_api(scenario)
    kept = [m["data"]["payload"]["source_event_id"] for m in got if m["topic"] == "indicators"]
    assert kept == ["b", "c"]


def test_live_messages_reach_connected_clients_and_status_is_not_replayed_as_history():
    async def scenario(api, url, commands):
        async with connect(url) as ws:
            first = await read_all(ws, 0.2)                      # hello seul
            api.push("events", ev("run_start"))
            api.push("status", {"state": "running"})
            api.push("indicators", ind())
            live = await read_all(ws, 0.3)
            return first, live, api.buffer

    first, live, buffer = run_api(scenario)
    assert [m["topic"] for m in first] == ["hello"]
    assert [m["topic"] for m in live] == ["events", "status", "indicators"]
    assert len(buffer) == 2                                      # événements et indicateurs seulement


def test_commands_from_the_interface_are_forwarded_and_garbage_is_ignored():
    async def scenario(api, url, commands):
        async with connect(url) as ws:
            await read_all(ws, 0.2)
            await ws.send(json.dumps({"type": "pause"}))
            await ws.send(json.dumps({"type": "start_game", "config": {"mode": "sync"}}))
            await ws.send("pas du json")
            await ws.send(json.dumps({"pas_de_type": 1}))
            await ws.send(json.dumps([1, 2]))
            await ws.send(b"\x00\x01")                           # un message binaire n'est pas une commande
            await asyncio.sleep(0.3)
        return commands

    assert run_api(scenario) == [{"type": "pause"}, {"type": "start_game", "config": {"mode": "sync"}}]


def test_a_failing_command_handler_does_not_drop_the_connection():
    def boom(cmd):
        raise RuntimeError("bus indisponible")

    async def scenario(api, url, commands):
        async with connect(url) as ws:
            await read_all(ws, 0.2)
            await ws.send(json.dumps({"type": "pause"}))
            await asyncio.sleep(0.2)
            api.push("events", ev("run_start"))
            return await read_all(ws, 0.3)

    assert [m["topic"] for m in run_api(scenario, on_command=boom)] == ["events"]


def test_an_asynchronous_command_handler_is_awaited():
    seen = []

    async def handler(cmd):
        await asyncio.sleep(0.01)
        seen.append(cmd["type"])

    async def scenario(api, url, commands):
        async with connect(url) as ws:
            await read_all(ws, 0.1)
            await ws.send(json.dumps({"type": "resume"}))
            await asyncio.sleep(0.2)

    run_api(scenario, on_command=handler)
    assert seen == ["resume"]


def test_the_engine_catalog_travels_with_its_status_and_replaces_the_default():
    """Avec Kafka, le pont est un autre processus : c'est le moteur qui dit quelles options le menu propose."""
    async def scenario(api, url, commands):
        async with connect(url) as ws:
            await read_all(ws, 0.2)
            api.push("status", {"state": "idle", "engine_id": "e1", "catalog": {"defaults": {"mode": "sync"}}})
            api.push("status", {"state": "idle", "engine_id": "e1", "catalog": {"defaults": {"mode": "sync"}}})
            live = await read_all(ws, 0.3)
        async with connect(url) as late:
            joined = await read_all(late, 0.3)
        return live, joined

    live, joined = run_api(scenario, catalog={"defaults": {"mode": "async"}})
    assert [m["topic"] for m in live].count("catalog") == 1                  # inchangé la deuxième fois : pas renvoyé
    assert next(m for m in live if m["topic"] == "catalog")["data"] == {"defaults": {"mode": "sync"}}
    assert all("catalog" not in m["data"] for m in live if m["topic"] == "status")      # l'état reste léger
    assert joined[0]["topic"] == "catalog" and joined[0]["data"] == {"defaults": {"mode": "sync"}}


# ---------------------------------------------------------------- le REST
def rest(scenario, **kw):
    async def inner(api, url, commands):
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{api.port}") as http:
            return await scenario(api, http, commands)
    return run_api(inner, **kw)


def test_health_status_and_catalog_follow_what_the_engine_publishes():
    async def scenario(api, http, commands):
        before = (await http.get("/api/status")).status_code, (await http.get("/api/catalog")).status_code
        api.push("events", ev("run_start", run="r9"))
        api.push("status", {"state": "running", "run_id": "r9", "speed": 1.0})
        await api.drain()
        health = (await http.get("/api/health")).json()
        status = (await http.get("/api/status")).json()
        catalog = (await http.get("/api/catalog")).json()
        return before, health, status, catalog

    before, health, status, catalog = rest(scenario, catalog={"hamlets": ["Ostrel"]})
    assert before == (404, 200)                                  # pas encore d'état ; le catalogue du lancement est là
    assert health == {"status": "ok", "clients": 0, "run_id": "r9", "engine_state": "running"}
    assert status["state"] == "running" and catalog == {"hamlets": ["Ostrel"]}


def test_a_valid_command_is_accepted_and_forwarded():
    async def scenario(api, http, commands):
        r = await http.post("/api/commands", json={"type": "set_speed", "value": 0.25})
        r2 = await http.post("/api/commands", json={"type": "announcement", "text": "Le lac baisse."})
        return r, r2, commands

    r, r2, commands = rest(scenario)
    assert r.status_code == 202 and r.json() == {"accepted": True, "type": "set_speed"}
    assert r2.status_code == 202
    assert commands == [{"type": "set_speed", "value": 0.25}, {"type": "announcement", "text": "Le lac baisse."}]


@pytest.mark.parametrize("body", [{"type": "teleport"}, {"value": 1}, {"type": "set_speed", "value": 1, "text": 5}, []])
def test_an_invalid_command_is_refused_before_it_reaches_the_engine(body):
    async def scenario(api, http, commands):
        return await http.post("/api/commands", json=body), commands

    r, commands = rest(scenario)
    assert r.status_code == 422 and commands == []


def test_a_command_the_engine_cannot_receive_is_a_503_not_a_silent_success():
    def boom(cmd):
        raise RuntimeError("Kafka injoignable")

    async def scenario(api, http, commands):
        return await http.post("/api/commands", json={"type": "pause"})

    assert rest(scenario, on_command=boom).status_code == 503


def make_run(tmp_path, run_id, n=6, finished=True):
    d = tmp_path / run_id
    d.mkdir(parents=True)
    kinds = ["run_start", "season_start", "catch", "catch", "utterance", "run_end"]
    (d / "events.jsonl").write_text("\n".join(json.dumps({"type": kinds[i % len(kinds)], "seq": i, "run_id": run_id,
                                                          "payload": {"i": i}}) for i in range(n)) + "\n", encoding="utf-8")
    (d / "config.json").write_text(json.dumps({"run": {"seed": 1}}), encoding="utf-8")
    if finished:
        (d / "summary.json").write_text(json.dumps({"reason": "extinction", "seasons_completed": 3, "final_stock": 0.0,
                                                    "capacity": 100.0, "llm_calls": 12, "wall_s": 41.5,
                                                    "by_system": {"S2": {"calls": 12, "tokens": 900}}}), encoding="utf-8")


def test_recorded_runs_can_be_listed_read_and_paged(tmp_path):
    make_run(tmp_path, "run-a")
    make_run(tmp_path, "run-b", finished=False)

    async def scenario(api, http, commands):
        listing = (await http.get("/api/runs")).json()
        one = (await http.get("/api/runs/run-a")).json()
        events = (await http.get("/api/runs/run-a/events", params={"type": "catch"})).json()
        paged = (await http.get("/api/runs/run-a/events", params={"limit": 2, "offset": 1})).json()
        return listing, one, events, paged

    listing, one, events, paged = rest(scenario, runs=LocalRuns(tmp_path))
    assert {r["run_id"]: r["finished"] for r in listing} == {"run-a": True, "run-b": False}
    assert one["reason"] == "extinction" and one["config"] == {"run": {"seed": 1}} and one["by_system"]["S2"]["tokens"] == 900
    assert [e["seq"] for e in events] == [2, 3]
    assert [e["seq"] for e in paged] == [1, 2]


@pytest.mark.parametrize("path, code", [("/api/runs/nope", 404), ("/api/runs/nope/events", 404), ("/api/runs/..%2F..%2Fsecret", 404),
                                        ("/api/runs/.hidden", 422), ("/api/runs/a b", 422)])
def test_unknown_or_dangerous_run_ids_are_refused(tmp_path, path, code):
    async def scenario(api, http, commands):
        return (await http.get(path)).status_code

    assert rest(scenario, runs=LocalRuns(tmp_path)) == code


def test_without_run_storage_the_run_routes_say_so():
    async def scenario(api, http, commands):
        return (await http.get("/api/runs")).status_code

    assert rest(scenario) == 501


def test_the_collective_memory_search_needs_pgvector():
    async def scenario(api, http, commands):
        return (await http.get("/api/runs/r1/memories", params={"q": "lac"})).status_code

    assert rest(scenario) == 501


def test_the_api_documents_itself_and_only_local_pages_may_call_it():
    async def scenario(api, http, commands):
        spec = (await http.get("/openapi.json")).json()
        docs = (await http.get("/docs")).status_code
        ok = await http.get("/api/health", headers={"Origin": "http://localhost:3000"})
        other = await http.get("/api/health", headers={"Origin": "http://evil.example"})
        return spec, docs, ok.headers.get("access-control-allow-origin"), other.headers.get("access-control-allow-origin")

    spec, docs, allowed, refused = rest(scenario)
    assert {"/api/health", "/api/status", "/api/catalog", "/api/commands", "/api/runs", "/api/runs/{run_id}",
            "/api/runs/{run_id}/events"} <= set(spec["paths"])
    assert docs == 200 and allowed == "http://localhost:3000" and refused is None


def test_the_server_stops_cleanly_with_clients_still_connected():
    async def scenario(api, url, commands):
        ws = await connect(url)
        await read_all(ws, 0.1)
        return ws

    ws = run_api(scenario)                      # `stop()` est appelé avec le client encore là : pas de blocage
    assert ws is not None
