"""Pont Kafka ↔ Godot : relaie événements, indicateurs et état du moteur vers la scène, renvoie les ordres.

    python -m filets.services.bridge [--port 8765] [--bootstrap localhost:9092]

Au démarrage, le pont relit les événements depuis le dernier `run_start` (le run en cours) : une scène
ouverte en retard, ou un pont relancé en cours de partie, reconstitue tout l'état.
"""
from __future__ import annotations

import asyncio
import threading
import uuid

from ..bus import OFFSET_BEGINNING, KafkaBus, kafka_assigned_consumer, last_run_start_offset
from ..catalog import build_catalog
from ..ws_bridge import WSBridge
from ._common import base_args, consume_forever, kafka_cfg


async def amain(cfg, port: int):
    topics = cfg["bus"]["topics"]
    producer_bus = KafkaBus(cfg["bus"]["bootstrap"], topics, consume_commands=False)
    bridge = WSBridge("0.0.0.0", port, lambda cmd: (producer_bus.send_command(cmd), producer_bus.flush()),
                      catalog=build_catalog(cfg))
    await bridge.start()
    start = await asyncio.to_thread(last_run_start_offset, cfg)
    # indicateurs et état : depuis le début des topics ; le pont écarte ce qui n'appartient pas au run en cours
    consumer = kafka_assigned_consumer(cfg, f"filets-bridge-{uuid.uuid4().hex[:8]}",
                                       {"events": start, "indicators": OFFSET_BEGINNING, "status": OFFSET_BEGINNING})
    names = {v: k for k, v in topics.items()}
    stop = threading.Event()
    th = threading.Thread(target=consume_forever, args=(consumer, lambda t, d: bridge.push(names[t], d), stop),
                          daemon=True)
    th.start()
    print(f"Pont Godot sur ws://localhost:{port}")
    try:
        while th.is_alive():
            await asyncio.sleep(0.5)
    finally:
        stop.set()
        await bridge.stop()
        producer_bus.close()


def main():
    ap = base_args(__doc__)
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    cfg = kafka_cfg(args)
    try:
        asyncio.run(amain(cfg, args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
