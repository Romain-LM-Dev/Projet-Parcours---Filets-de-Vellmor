"""Pont Kafka ↔ Godot : l'API FastAPI (REST + WebSocket), alimentée par Kafka en asynchrone.

    python -m filets.services.bridge [--port 8765] [--host 127.0.0.1] [--bootstrap localhost:9092]

Relaie événements, indicateurs et état du moteur vers la scène Godot (WebSocket `/ws`) et vers l'API REST (`/api`, `/docs`),
et renvoie les ordres dans `filets.commands`. Au démarrage, le pont relit les événements depuis le dernier `run_start` (le run
en cours) : une scène ouverte en retard, ou un pont relancé en cours de partie, reconstitue tout l'état.

Tout se passe dans une seule boucle asyncio (aiokafka pour lire et écrire, uvicorn pour servir) : pas de fil de lecture.
"""
from __future__ import annotations

import asyncio

from .. import aio
from ..api import ApiServer, LocalRuns, memories_for
from ..bus import ensure_topics
from ..catalog import build_catalog
from ..config import ROOT
from ._common import base_args, kafka_cfg


async def amain(cfg, host: str, port: int):
    topics = cfg["bus"]["topics"]
    await asyncio.to_thread(ensure_topics, cfg["bus"]["bootstrap"], topics)
    prod = await aio.producer(cfg)

    async def on_command(cmd: dict):
        await aio.send(prod, cfg, "commands", cmd)

    api = ApiServer(host, port, on_command, catalog=build_catalog(cfg), runs=LocalRuns(ROOT / cfg["output"]["runs_dir"]),
                    memories=memories_for(cfg))
    await api.start()
    start = await aio.last_run_start_offset(cfg)
    # indicateurs et état : depuis le début des topics ; le pont écarte ce qui n'appartient pas au run en cours
    consumer = await aio.assigned_consumer(cfg, {"events": start, "indicators": aio.OFFSET_BEGINNING,
                                                 "status": aio.OFFSET_BEGINNING})
    names = {v: k for k, v in topics.items()}
    print(f"API FILETS sur http://localhost:{api.port} (WebSocket /ws pour Godot, documentation /docs)")
    try:
        async for topic, data in aio.messages(consumer):
            api.push(names[topic], data)
    finally:
        await consumer.stop()
        await api.stop()
        await prod.stop()


def main():
    ap = base_args(__doc__)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default=None, help="adresse d'écoute (défaut : api.host de la configuration, 127.0.0.1)")
    args = ap.parse_args()
    cfg = kafka_cfg(args)
    try:
        asyncio.run(amain(cfg, args.host or cfg.get("api", {}).get("host", "127.0.0.1"), args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
