"""Service d'historique : archive événements et indicateurs dans SQLite (F3, F5).

    python -m filets.services.store [--db data/history.db]
"""
from __future__ import annotations

import time

from ..bus import kafka_consumer
from ..config import ROOT
from ..store import HistoryStore
from ._common import base_args, consume_forever, kafka_cfg


def main():
    ap = base_args(__doc__)
    ap.add_argument("--db", default="data/history.db")
    args = ap.parse_args()
    cfg = kafka_cfg(args)
    store = HistoryStore(ROOT / args.db)
    topics = cfg["bus"]["topics"]
    consumer = kafka_consumer(cfg, "filets-store", ["events", "indicators"], from_beginning=True)
    last = [time.monotonic()]
    print("Archivage dans", ROOT / args.db)

    def handle(topic, data):
        if topic == topics["events"]:
            store.add_event(data)
        else:
            store.add_indicator(data)
        if time.monotonic() - last[0] > 1.0:
            store.commit()
            last[0] = time.monotonic()

    try:
        consume_forever(consumer, handle, on_idle=store.commit)
    finally:
        store.close()


if __name__ == "__main__":
    main()
