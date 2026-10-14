"""Service d'historique : archive événements et indicateurs (F3, F5), en asynchrone (aiokafka).

    python -m filets.services.store                        # la base de la configuration (`storage.history`)
    python -m filets.services.store --pg postgresql://…    # PostgreSQL
    python -m filets.services.store --db data/history.db   # SQLite

Le service lit en groupe (`filets-store`) et ne valide sa position dans Kafka qu'après avoir écrit dans la base : une
panne entre les deux fait relire quelques messages, que l'écriture idempotente ignore. Rien n'est perdu, rien n'est écrit
deux fois.
"""
from __future__ import annotations

import asyncio
import json

from aiokafka import AIOKafkaConsumer

from ..bus import ensure_topics
from ..config import ROOT
from ..pgstore import PgHistoryStore
from ..store import HistoryStore
from ..vectors import postgres_dsn
from ._common import base_args, kafka_cfg


class _SqliteAsync:
    """La base SQLite derrière la même interface que `PgHistoryStore` (écritures locales et courtes)."""

    def __init__(self, path):
        self.db = HistoryStore(path)
        self.add_event, self.add_indicator = self.db.add_event, self.db.add_indicator

    async def open(self) -> None:
        pass

    async def commit(self) -> None:
        self.db.commit()

    async def close(self) -> None:
        self.db.close()


async def amain(cfg: dict, sqlite_path=None, dsn: str | None = None, stop: asyncio.Event | None = None,
                group: str = "filets-store") -> None:
    await asyncio.to_thread(ensure_topics, cfg["bus"]["bootstrap"], cfg["bus"]["topics"])
    store = PgHistoryStore(dsn) if dsn else _SqliteAsync(sqlite_path)
    await store.open()
    topics = cfg["bus"]["topics"]
    consumer = AIOKafkaConsumer(topics["events"], topics["indicators"], bootstrap_servers=cfg["bus"]["bootstrap"],
                                group_id=group, enable_auto_commit=False, auto_offset_reset="earliest")
    await consumer.start()
    print("Archivage dans", "PostgreSQL" if dsn else sqlite_path)
    stop = stop or asyncio.Event()
    try:
        while not stop.is_set():
            batch = await consumer.getmany(timeout_ms=500, max_records=2000)
            for msgs in batch.values():
                for m in msgs:
                    try:
                        data = json.loads(m.value)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if m.topic == topics["events"]:
                        store.add_event(data)
                    else:
                        store.add_indicator(data)
            if batch:
                await store.commit()            # d'abord la base…
                await consumer.commit()         # …puis la position dans Kafka
    finally:
        try:
            await store.close()
        finally:
            await consumer.stop()


def main():
    ap = base_args(__doc__)
    ap.add_argument("--db", help="fichier SQLite (au lieu de la base de la configuration)")
    ap.add_argument("--pg", help="adresse PostgreSQL (au lieu de la base de la configuration)")
    args = ap.parse_args()
    cfg = kafka_cfg(args)
    if args.pg:
        dsn, path = args.pg, None
    elif args.db:
        dsn, path = None, ROOT / args.db
    elif cfg.get("storage", {}).get("history", "sqlite") == "postgres":
        dsn, path = postgres_dsn(cfg), None
    else:
        dsn, path = None, ROOT / cfg["output"]["history_db"]
    try:
        asyncio.run(amain(cfg, path, dsn))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
