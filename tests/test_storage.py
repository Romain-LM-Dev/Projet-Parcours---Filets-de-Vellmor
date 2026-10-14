"""Le stockage : RAG dans PostgreSQL + pgvector (corpus et souvenirs des agents), historique dans PostgreSQL (au lieu de
SQLite), fichiers bruts dans un stockage objet S3, le tout en asynchrone (asyncpg, miniopy-async, aiokafka).

Les tests qui demandent un service le cherchent sur la machine (`docker compose --profile data up -d`) et sont ignorés
sinon. Ils travaillent dans une base à part (`filets_test`) et un bucket à part (`filets-test`).
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import socket
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from filets.cli import verify
from filets.config import ROOT
from filets.memory import MemoryBank, VectorMemory
from filets.objects import LocalObjects, S3Objects, archive_run
from filets.pgstore import PgHistoryStore
from filets.rag import Retriever, VectorRetriever
from filets.store import HistoryStore
from filets.vectors import EmbeddingError, HashEmbedder, OllamaEmbedder, PgVectorStore
from helpers import cfg_for, play, read_events

ROOT_CORPUS = ROOT / "corpus"
PG_ADMIN = os.environ.get("FILETS_TEST_PG_DSN", "postgresql://filets:filets@127.0.0.1:5433/filets")
S3_ENDPOINT = os.environ.get("FILETS_TEST_S3", "127.0.0.1:8333")
VALUES = {"capacity": "100", "price": "100", "upkeep": "150", "half_capacity": "50", "n_fishers": 8}


def port_open(hostport: str) -> bool:
    host, port = hostport.rsplit(":", 1)
    try:
        with socket.create_connection((host, int(port)), timeout=1.0):
            return True
    except OSError:
        return False


PG_UP = port_open(PG_ADMIN.split("@", 1)[1].split("/", 1)[0])
S3_UP = port_open(S3_ENDPOINT)
needs_pg = pytest.mark.skipif(not PG_UP, reason="aucun PostgreSQL (docker compose --profile data up -d)")
needs_s3 = pytest.mark.skipif(not S3_UP, reason="aucun stockage objet S3 (docker compose --profile data up -d)")


@pytest.fixture(scope="module")
def pg_dsn():
    if not PG_UP:
        pytest.skip("aucun PostgreSQL")
    import asyncpg

    async def make():
        conn = await asyncpg.connect(PG_ADMIN, timeout=5)
        try:
            if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = 'filets_test'"):
                await conn.execute("CREATE DATABASE filets_test")
        finally:
            await conn.close()

    asyncio.run(make())
    return PG_ADMIN.rsplit("/", 1)[0] + "/filets_test"


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch):
    for var in ("FILETS_PG_DSN", "FILETS_S3_ACCESS_KEY", "FILETS_S3_SECRET_KEY"):
        monkeypatch.delenv(var, raising=False)


def cos(a, b):
    return sum(x * y for x, y in zip(a, b))


class Counting(HashEmbedder):
    """Plongement haché qui compte les textes qu'on lui fait calculer."""

    def __init__(self, dim=64):
        super().__init__(dim)
        self.texts = 0

    async def embed(self, texts):
        self.texts += len(texts)
        return await super().embed(texts)


def pg_game_cfg(tmp_path, dsn, seasons=2, **over):
    cfg = cfg_for(tmp_path, seasons=seasons, time__mode="sync", **over)
    cfg["rag"]["backend"] = "pgvector"
    cfg["rag"]["embeddings"] = {"kind": "hash", "dim": 64}
    cfg["storage"]["postgres"]["dsn"] = dsn
    return cfg


# ---------------------------------------------------------------- plongements
def test_hash_vectors_are_deterministic_unit_length_and_follow_shared_words():
    e = HashEmbedder(384)
    a, b, c, empty = asyncio.run(e.embed(["Le lac se vide : pénurie de poissons", "pénurie au lac, les poissons manquent",
                                          "le prix de la laine au marché", "et de la"]))
    assert math.isclose(cos(a, a), 1.0, rel_tol=1e-9) and math.isclose(cos(empty, empty), 1.0, rel_tol=1e-9)
    assert cos(a, b) > 0.5 > cos(a, c)
    assert asyncio.run(e.embed(["Le lac se vide : pénurie de poissons"]))[0] == a


class FakeEmbed:
    """Faux `POST /api/embed` d'Ollama : un vecteur par texte, de la dimension demandée."""

    def __init__(self, dim=8):
        self.calls: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.calls.append(body)
                vecs = [[float(len(t))] + [0.0] * (dim - 1) for t in body["input"]]
                out = json.dumps({"model": body["model"], "embeddings": vecs}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"


def test_the_ollama_embedder_batches_caches_and_runs_on_the_cpu():
    fake = FakeEmbed(dim=8)

    async def main():
        e = OllamaEmbedder(fake.url, "embeddinggemma", 8, cpu=True, batch=2)
        try:
            first = await e.embed(["a", "bb", "a", "ccc"])
            again = await e.embed(["bb", "ccc"])
            return first, again
        finally:
            await e.aclose()

    first, again = asyncio.run(main())
    fake.server.shutdown()
    assert [v[0] for v in first] == [1.0, 2.0, 1.0, 3.0] and [v[0] for v in again] == [2.0, 3.0]
    assert [c["input"] for c in fake.calls] == [["a", "bb"], ["ccc"]]      # par lots de 2, chaque texte une seule fois
    assert all(c["options"] == {"num_gpu": 0} and c["keep_alive"] == "30m" for c in fake.calls)


def test_a_model_of_the_wrong_dimension_is_refused():
    fake = FakeEmbed(dim=8)

    async def main():
        e = OllamaEmbedder(fake.url, "autre", 768)
        try:
            await e.embed(["a"])
        finally:
            await e.aclose()

    with pytest.raises(EmbeddingError, match="768"):
        asyncio.run(main())
    fake.server.shutdown()


# ---------------------------------------------------------------- stockage objet
def test_local_objects_store_list_and_refuse_keys_outside_their_folder(tmp_path):
    async def main():
        o = LocalObjects(tmp_path / "objets")
        await o.open()
        await o.put_bytes("runs/r1/summary.json", b"{}")
        await o.put_bytes("corpus/abc/lac.md", "Le lac é".encode())
        assert await o.get_bytes("corpus/abc/lac.md") == "Le lac é".encode()
        assert await o.list("runs/") == ["runs/r1/summary.json"] and await o.exists("runs/r1/summary.json")
        with pytest.raises(ValueError):
            await o.put_bytes("../dehors.txt", b"x")

    asyncio.run(main())


@needs_s3
def test_s3_objects_round_trip_and_archive_a_game(tmp_path):
    play(tmp_path, run_id="arch", seasons=1, time__mode="sync")
    run_dir = tmp_path / "runs" / "arch"
    tag = uuid.uuid4().hex[:8]

    async def main():
        o = S3Objects(S3_ENDPOINT, "filets-test", "filets", "filets-secret")
        try:
            await o.open()
            await o.put_bytes(f"t/{tag}/a.txt", "pénurie".encode())
            assert await o.get_bytes(f"t/{tag}/a.txt") == "pénurie".encode()
            assert await o.exists(f"t/{tag}/a.txt") and not await o.exists(f"t/{tag}/absent.txt")
            keys = await archive_run(o, run_dir, f"arch-{tag}")
            listed = await o.list(f"runs/arch-{tag}/")
            events = await o.get_bytes(f"runs/arch-{tag}/events.jsonl")
            return keys, listed, events
        finally:
            await o.aclose()

    keys, listed, events = asyncio.run(main())
    assert sorted(keys) == listed and {k.rsplit("/", 1)[1] for k in listed} >= {"events.jsonl", "config.json", "summary.json"}
    assert events == (run_dir / "events.jsonl").read_bytes()


def test_wrong_s3_credentials_are_refused():
    if not S3_UP:
        pytest.skip("aucun stockage objet S3")
    from miniopy_async.error import S3Error

    async def main():
        o = S3Objects(S3_ENDPOINT, "filets-test", "filets", "mauvais-secret")
        try:
            await o.put_bytes("t/x.txt", b"x")
        finally:
            await o.aclose()

    with pytest.raises(S3Error):
        asyncio.run(main())


# ---------------------------------------------------------------- pgvector : le corpus
@needs_pg
def test_corpus_search_applies_hamlet_rights_and_simulated_time_in_the_base(pg_dsn):
    corpus = f"t-{uuid.uuid4().hex[:8]}"
    e = HashEmbedder(64)

    async def main():
        store = PgVectorStore(pg_dsn, e)
        await store.open()
        try:
            texts = [("p0", ["all"], 0.0, "pénurie de poissons au lac"), ("p1", ["Ostrel"], 0.0, "pénurie racontée à Ostrel"),
                     ("p2", ["all"], 50.0, "pénurie de la saison future")]
            vecs = await e.embed([t for *_, t in texts])
            await store.put_chunks(corpus, [(i, "titre", t, vis, st, None, v) for (i, vis, st, t), v in zip(texts, vecs)])
            [q] = await e.embed(["pénurie"])
            tilque = await store.search_chunks(corpus, q, "Tilque", 10.0, 5)
            ostrel = await store.search_chunks(corpus, q, "Ostrel", 10.0, 5)
            later = await store.search_chunks(corpus, q, "Tilque", 100.0, 5)
            return [r["id"] for r in tilque], sorted(r["id"] for r in ostrel), sorted(r["id"] for r in later)
        finally:
            await store.aclose()

    tilque, ostrel, later = asyncio.run(main())
    assert tilque == ["p0"] and ostrel == ["p0", "p1"] and later == ["p0", "p2"]


@needs_pg
def test_the_corpus_is_vectorized_once_and_its_sources_go_to_object_storage(pg_dsn, tmp_path):
    e = Counting(64)

    values = {**VALUES, "capacity": uuid.uuid4().hex[:6]}          # un lac jamais vu : un corpus rendu jamais vectorisé

    async def main():
        store = PgVectorStore(pg_dsn, e)
        await store.open()
        objects = LocalObjects(tmp_path / "objets")
        try:
            r1 = VectorRetriever(ROOT_CORPUS, values, store, e, objects)
            await r1.open()
            first = e.texts
            r2 = VectorRetriever(ROOT_CORPUS, values, store, e, objects)
            await r2.open()
            hits = await r2.asearch("pénurie lac stock", "Ostrel", 1e9, 3)
            return first, e.texts - first, hits, await objects.list("corpus/"), r1, r2
        finally:
            await store.aclose()

    first, second, hits, keys, r1, r2 = asyncio.run(main())
    assert first == len(r1.passages) and second == 1                  # la seconde partie ne calcule que sa requête
    assert r1.corpus == r2.corpus and hits and not r2.degraded
    assert keys and all(k.startswith(f"corpus/{r1.corpus}/") and k.endswith(".md") for k in keys)


@needs_pg
def test_search_falls_back_to_bm25_when_the_base_is_lost(pg_dsn, caplog):
    e = HashEmbedder(64)

    async def main():
        store = PgVectorStore(pg_dsn, e)
        await store.open()
        r = VectorRetriever(ROOT_CORPUS, VALUES, store, e)
        await r.open()
        await store.aclose()                              # la base disparaît en cours de partie
        return r, await r.asearch("pénurie lac", "Ostrel", 1e9, 3)

    r, hits = asyncio.run(main())
    assert r.degraded and hits == Retriever(ROOT_CORPUS, VALUES).search("pénurie lac", "Ostrel", 1e9, 3)
    assert "BM25" in caplog.text


# ---------------------------------------------------------------- pgvector : les souvenirs
@needs_pg
def test_a_memory_is_in_the_base_before_any_search_that_could_find_it(pg_dsn):
    e = HashEmbedder(64)
    run_id = f"mem-{uuid.uuid4().hex[:8]}"

    async def main():
        store = PgVectorStore(pg_dsn, e)
        await store.open()
        try:
            bank = MemoryBank(store, e, run_id)
            mem = VectorMemory("F01", 0.01, {"recency": 1, "importance": 1, "relevance": 1.5}, bank)
            other = VectorMemory("F02", 0.01, {"recency": 1, "importance": 1, "relevance": 1.5}, bank)
            m1 = mem.add(1.0, "promesse de pêcher deux tonnes", "promesse", 0.9)
            mem.add(2.0, "le prix du poisson monte au marché", "marché", 0.3)
            other.add(1.0, "promesse de Théo : trois tonnes", "promesse", 0.9)
            found = await mem.aretrieve("promesse tonnes", 5.0, 5)
            before = await mem.aretrieve("promesse tonnes", 0.5, 5)
            excluded = await mem.aretrieve("promesse tonnes", 5.0, 5, exclude={m1.id})
            collective = await store.run_memories(run_id, (await e.embed(["promesse"]))[0], 10)
            return m1, found, before, excluded, collective, bank
        finally:
            await store.aclose()

    m1, found, before, excluded, collective, bank = asyncio.run(main())
    assert not bank.degraded                                                  # c'est bien la base qui a cherché
    assert found[0][0] is m1 and len(found) == 2 and not bank.pending        # écrit avant la recherche, retrouvé en tête
    assert before == []                                                       # rien avant son instant simulé (C6)
    assert m1.id not in [m.id for m, _ in excluded]
    assert {r["owner"] for r in collective} == {"F01", "F02"}                 # la mémoire collective de la partie


# ---------------------------------------------------------------- une partie entière
@needs_pg
def test_a_game_keeps_its_corpus_and_memories_in_pgvector(pg_dsn, tmp_path, caplog):
    run_id = f"pgv-{uuid.uuid4().hex[:8]}"
    cfg = pg_game_cfg(tmp_path, pg_dsn)
    events = play(tmp_path, run_id=run_id, cfg=cfg)
    import asyncpg

    async def count():
        conn = await asyncpg.connect(pg_dsn)
        try:
            return await conn.fetchval("SELECT count(*) FROM rag_memories_64 WHERE run_id = $1", run_id)
        finally:
            await conn.close()

    writes = [e for e in events if e["type"] == "memory_write"]
    assert "indisponible" not in caplog.text                             # aucun repli sur BM25 : tout est passé par la base
    assert asyncio.run(count()) == len(writes) > 0                       # tous les souvenirs, aucun en double
    retrieved = [r for e in events if e["type"] == "decision" for r in e["payload"].get("retrieved", [])]
    assert {"memory", "corpus"} <= {r["source"] for r in retrieved}
    assert events[-1]["type"] == "run_end" and events[-1]["payload"]["reason"] == "completed"
    assert verify(run_id, cfg)                                            # cohérence temporelle de tout ce qui est retrouvé


@needs_pg
@needs_s3
def test_a_game_archives_its_files_in_object_storage(pg_dsn, tmp_path):
    run_id = f"obj-{uuid.uuid4().hex[:8]}"
    cfg = pg_game_cfg(tmp_path, pg_dsn, seasons=1)
    cfg["storage"]["objects"] = {"kind": "s3", "endpoint": S3_ENDPOINT, "bucket": "filets-test",
                                 "access_key": "filets", "secret_key": "filets-secret"}
    play(tmp_path, run_id=run_id, cfg=cfg)

    async def listing():
        o = S3Objects(S3_ENDPOINT, "filets-test", "filets", "filets-secret")
        try:
            return await o.list(f"runs/{run_id}/"), await o.get_bytes(f"runs/{run_id}/summary.json")
        finally:
            await o.aclose()

    keys, summary = asyncio.run(listing())
    assert {k.rsplit("/", 1)[1] for k in keys} == {"events.jsonl", "indicators.jsonl", "config.json", "summary.json"}
    assert json.loads(summary)["run_id"] == run_id


@needs_pg
def test_the_api_searches_the_collective_memory_of_a_run(pg_dsn, tmp_path):
    import httpx

    from filets.api import ApiServer, PgMemories

    run_id = f"api-{uuid.uuid4().hex[:8]}"
    cfg = pg_game_cfg(tmp_path, pg_dsn, seasons=1)
    play(tmp_path, run_id=run_id, cfg=cfg)

    async def main():
        api = ApiServer("127.0.0.1", 0, lambda c: None, memories=PgMemories(cfg))
        await api.start()
        try:
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{api.port}") as http:
                url = f"/api/runs/{run_id}/memories"
                return (await http.get(url, params={"q": "une nouvelle année commence", "k": 3}),
                        await http.get(url, params={"q": "lac", "agent": "F01", "k": 50}),
                        await http.get(url, params={"q": "lac", "agent": "F01; DROP TABLE"}),
                        await http.get(url, params={"q": "lac", "until": 0.0, "k": 100}))
        finally:
            await api.stop()

    best, one, bad, early = asyncio.run(main())
    body = best.json()
    assert best.status_code == 200 and len(body["results"]) == 3 and body["embedder"] == "hash-64"
    assert all("nouvelle année" in x["text"] for x in body["results"])
    assert one.status_code == 200 and {x["agent"] for x in one.json()["results"]} == {"F01"}
    assert bad.status_code == 422
    assert early.status_code == 200 and early.json()["results"] and all(x["t"] <= 0.0 for x in early.json()["results"])


# ---------------------------------------------------------------- l'historique dans PostgreSQL
@needs_pg
def test_the_postgres_history_holds_the_same_run_as_sqlite_and_ignores_replays(pg_dsn, tmp_path):
    run_id = f"hist-{uuid.uuid4().hex[:8]}"
    play(tmp_path, run_id=run_id, seasons=2, time__mode="sync")
    run_dir = tmp_path / "runs" / run_id
    sq = HistoryStore(tmp_path / "h.db")
    sq.ingest_run_dir(run_dir)
    by_type_sqlite = dict(sq.db.execute("SELECT type, count(*) FROM events WHERE run_id = ? GROUP BY type", (run_id,)))
    seasons_sqlite = sq.db.execute("SELECT count(*) FROM v_season_indicators WHERE run_id = ?", (run_id,)).fetchone()[0]
    sq.close()

    async def main():
        st = PgHistoryStore(pg_dsn)
        await st.open()
        try:
            n1 = await st.ingest_run_dir(run_dir)
            n2 = await st.ingest_run_dir(run_dir)                         # relu deux fois : rien en double
            rows = await st.fetch("SELECT type, count(*) AS n FROM events WHERE run_id = $1 GROUP BY type", run_id)
            seasons = await st.fetch("SELECT * FROM v_season_indicators WHERE run_id = $1 ORDER BY season", run_id)
            run = await st.fetch("SELECT end_reason, seasons_completed, llm_tiers FROM runs WHERE run_id = $1", run_id)
            catches = await st.fetch("SELECT agent, landed FROM v_catches WHERE run_id = $1", run_id)
            fallbacks = await st.fetch("SELECT count(*) AS n FROM events WHERE run_id = $1 AND payload @> '{\"fallback\": false}'",
                                       run_id)
            return n1, n2, {r["type"]: r["n"] for r in rows}, seasons, run, catches, fallbacks[0]["n"]
        finally:
            await st.close()

    n1, n2, by_type, seasons, run, catches, not_fallback = asyncio.run(main())
    assert n1 == n2 and by_type == by_type_sqlite
    assert len(seasons) == seasons_sqlite == 2 and all(0 <= s["stock_ratio"] <= 1 for s in seasons)
    assert run[0]["end_reason"] == "completed" and run[0]["seasons_completed"] == 2
    assert json.loads(run[0]["llm_tiers"]) and catches and all(isinstance(c["landed"], float) for c in catches)
    assert not_fallback > 0                                               # les charges utiles s'interrogent en JSONB


# ---------------------------------------------------------------- le service d'historique (Kafka → PostgreSQL)
def test_the_store_service_writes_to_postgres_then_commits_its_kafka_position(pg_dsn, tmp_path):
    from test_kafka_integration import BOOTSTRAP, broker_up

    if not broker_up():
        pytest.skip("aucun broker Kafka sur localhost:9092")
    from aiokafka import AIOKafkaConsumer, TopicPartition

    from filets.bus import KafkaBus, ensure_topics
    from filets.services import store as store_service

    run_id = f"svc-{uuid.uuid4().hex[:8]}"
    play(tmp_path, run_id=run_id, seasons=1, time__mode="sync")
    events = read_events(tmp_path, run_id)
    cfg = cfg_for(tmp_path)
    tag = uuid.uuid4().hex[:8]
    cfg["bus"].update(kind="kafka", bootstrap=BOOTSTRAP,
                      topics={k: f"filets.test.{tag}.{k}" for k in cfg["bus"]["topics"]})
    ensure_topics(BOOTSTRAP, cfg["bus"]["topics"])
    bus = KafkaBus(BOOTSTRAP, cfg["bus"]["topics"], consume_commands=False)
    for ev in events:
        bus.publish("events", ev, key=ev.get("actor"))
    bus.flush()
    group = f"filets-store-test-{tag}"

    async def main():
        import asyncpg

        stop = asyncio.Event()
        task = asyncio.create_task(store_service.amain(cfg, dsn=pg_dsn, stop=stop, group=group))
        conn = await asyncpg.connect(pg_dsn)
        try:
            for _ in range(200):
                n = await conn.fetchval("SELECT count(*) FROM events WHERE run_id = $1", run_id)
                if n == len(events):
                    break
                await asyncio.sleep(0.1)
        finally:
            await conn.close()
        await asyncio.sleep(0.6)                      # le temps de valider la position après l'écriture
        stop.set()
        await asyncio.wait_for(task, 10)
        probe = AIOKafkaConsumer(bootstrap_servers=BOOTSTRAP, group_id=group, enable_auto_commit=False)
        await probe.start()
        try:
            tp = TopicPartition(cfg["bus"]["topics"]["events"], 0)
            return n, await probe.committed(tp), (await probe.end_offsets([tp]))[tp]
        finally:
            await probe.stop()

    try:
        n, committed, end = asyncio.run(main())
    finally:
        from confluent_kafka.admin import AdminClient

        for fut in AdminClient({"bootstrap.servers": BOOTSTRAP}).delete_topics(list(cfg["bus"]["topics"].values())).values():
            try:
                fut.result(10)
            except Exception:
                pass
    assert n == len(events) and committed == end
