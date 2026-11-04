"""Le lore de partie : les moments marquants qui caractérisent un agent entrent dans le RAG de CETTE partie seulement."""
from __future__ import annotations

import pytest

import asyncio
import uuid

from helpers import make_world, play
from test_storage import pg_dsn, pg_game_cfg  # noqa: F401  (fixture : sautée sans PostgreSQL)

from filets.world import World


def started(tmp_path, run_id="w", **over):
    w, bus, _ = make_world(tmp_path, run_id=run_id, **over)
    w.start()
    return w


def lie(w, liar, season=1):
    """Fait établir par la vallée le mensonge de `liar`."""
    trip = {"agent": liar.id, "landed": 5.0, "secret": False}
    w.establish(liar, season, trip, 1.0, 5.0, [])


def seen(w, agent):
    w.clock.now = lambda: 5.0
    _, _, retrieved, _ = asyncio.run(w.observe(agent, 5.0, "catch"))
    return [r for r in retrieved if r["source"] == "lore"]


def test_an_exposed_lie_becomes_a_passage_other_agents_retrieve_next_decision(tmp_path):
    w = started(tmp_path)
    liar, other = w.fishers[0], w.fishers[1]
    lie(w, liar)
    assert [p.agent for p in w.retriever.lore] == [liar.id]
    assert liar.profile.name in w.retriever.lore[0].text and w.retriever.lore[0].visible_to == ["all"]
    got = w.retriever.search(f"{liar.profile.name} a menti", other.profile.hamlet, 99.0, 3)
    assert got and got[0][0].source == "lore"


def test_an_undiscovered_lie_stays_out_of_the_shared_corpus(tmp_path):
    events = play(tmp_path, run_id="g", seasons=3)
    lore = [e["payload"] for e in events if e["type"] == "lore_added"]
    by_id = {e["event_id"]: e for e in events}
    assert all(by_id[l["source_event_id"]]["type"] in ("lie_discovered", "ban", "accusation", "promise", "promise_outcome")
               for l in lore)                                   # chaque passage vient d'un événement public, tracé
    found = [e for e in events if e["type"] == "lie_discovered"]
    assert sum(by_id[l["source_event_id"]]["type"] == "lie_discovered" for l in lore) == len(found)    # ni plus, ni moins


def test_a_hamlet_scope_is_only_seen_from_that_hamlet(tmp_path):
    w = started(tmp_path)
    a = w.fishers[0]
    here, there = w.hamlets[0], w.hamlets[1]
    w.add_lore(a.id, "Zorglub a accusé Kriptor devant tous d'avoir trop pêché.", "e1", here, 0.5)
    assert w.retriever.search("Zorglub Kriptor accusé", here, 99.0, 3)[0][0].source == "lore"
    assert not any(p.source == "lore" for p, _ in w.retriever.search("Zorglub Kriptor accusé", there, 99.0, 3))
    with pytest.raises(AssertionError):           # la portée d'une veillée de hameau, telle quelle, n'est pas un hameau
        w.add_lore(a.id, "texte", "e2", f"hamlet:{here}", 0.5)


def test_the_next_game_does_not_find_the_lore_of_the_previous_one(tmp_path):
    w1 = started(tmp_path, run_id="a")
    lie(w1, w1.fishers[0])
    w2 = started(tmp_path, run_id="b")
    assert w2.retriever.lore == []
    assert not any(p.source == "lore" for p, _ in w2.retriever.search("a menti", w2.fishers[0].profile.hamlet, 99.0, 9))


def test_lore_per_agent_is_capped_keeping_the_most_important_then_the_latest(tmp_path):
    w = started(tmp_path)
    a = w.fishers[0]
    w.cfg["rag"]["lore_per_agent"] = 2
    w.add_lore(a.id, "Premier fait grave.", "e1", "all", 0.9)
    for i in range(2, 6):
        w.add_lore(a.id, f"Petit fait numéro {i}.", f"e{i}", "all", 0.5)
    assert sorted(p.id for p in w.retriever.lore) == ["lore:e1", "lore:e5"]
    w.add_lore(w.fishers[1].id, "Autre agent.", "x", "all", 0.5)       # le plafond est par agent
    assert len(w.retriever.lore) == 3


def test_decision_retrieved_marks_lore_with_its_own_source(tmp_path):
    w = started(tmp_path)
    a, b = w.fishers[0], w.fishers[1]
    lie(w, a)
    w.retriever.search = lambda q, h, t, k: [(w.retriever.lore[0], 1.0)]    # la requête exacte importe peu ici
    got = seen(w, b)
    assert got and got[0]["id"].startswith("lore:") and a.profile.name in got[0]["text"]


def test_pgvector_lore_is_per_run_and_deleted_at_the_end(pg_dsn, tmp_path):
    import asyncpg
    run_id = f"lore-{uuid.uuid4().hex[:8]}"
    cfg = pg_game_cfg(tmp_path, pg_dsn)

    async def main():
        w = World(cfg, __import__("filets.bus", fromlist=["LocalBus"]).LocalBus(), run_id)
        w.start()
        await w.open_storage()
        liar = w.fishers[0]
        lie(w, liar)
        got = await w.retriever.asearch(f"{liar.profile.name} a menti", liar.profile.hamlet, 99.0, 3)
        assert got and got[0][0].source == "lore"
        conn = await asyncpg.connect(pg_dsn)
        try:
            assert await conn.fetchval("SELECT count(*) FROM rag_lore_64 WHERE run_id = $1", run_id) == 1
            w2 = World(cfg, __import__("filets.bus", fromlist=["LocalBus"]).LocalBus(), run_id + "-bis")
            w2.start()
            await w2.open_storage()
            assert not any(p.source == "lore" for p, _ in
                           await w2.retriever.asearch(f"{liar.profile.name} a menti", liar.profile.hamlet, 99.0, 9))
            await w2.close_storage(archive=False)
            await w.close_storage(archive=False)
            assert await conn.fetchval("SELECT count(*) FROM rag_lore_64 WHERE run_id = $1", run_id) == 0
        finally:
            await conn.close()

    asyncio.run(main())
