"""Service d'indicateurs : consomme `filets.events`, publie `filets.indicators` (B2, C7, F6), en asynchrone (aiokafka).

    python -m filets.services.indicators [--bootstrap localhost:9092]

Au démarrage, le service se place sur le dernier `run_start` du topic : tous ses calculs
(capacité du lac, liste des pêcheurs, normes adoptées…) se rapportent à ce début de run. Démarré
avant, pendant ou après la simulation, il aboutit donc aux mêmes chiffres. Si le service est relancé
en cours de partie, il republie les indicateurs déjà émis ; les consommateurs les dédoublonnent.
"""
from __future__ import annotations

import asyncio

from .. import aio
from ..bus import ensure_topics
from ..pipeline import IndicatorPublisher
from ._common import base_args, kafka_cfg


async def amain(cfg):
    await asyncio.to_thread(ensure_topics, cfg["bus"]["bootstrap"], cfg["bus"]["topics"])
    prod = await aio.producer(cfg)
    bus = aio.PublisherBus(prod, cfg["bus"]["topics"])
    pub = IndicatorPublisher(bus, cfg["output"]["runs_dir"], cfg["scenario"]["quota_tolerance"])
    start = await aio.last_run_start_offset(cfg)
    consumer = await aio.assigned_consumer(cfg, {"events": start})
    print("Service d'indicateurs à l'écoute de", cfg["bus"]["topics"]["events"], f"(depuis l'offset {start})")
    warned = False
    try:
        async for _topic, ev in aio.messages(consumer):
            out = pub.on_event(ev)
            if pub.engine.skipped and not warned:
                warned = True
                print("Attention : des événements arrivent sans leur run_start ; ils sont ignorés.")
            if out and out["payload"]["trigger"] == "season_end":
                v = out["payload"]["values"]
                print(f"{out['sim_label']}  stock {v['stock_ratio'] * 100:.0f} %  norme {v['norm_index']:.2f}  "
                      f"décalage {out['payload']['lag_s'] * 1000:.0f} ms")
    finally:
        pub.close()
        await consumer.stop()
        await bus.aclose()
        await prod.stop()


def main():
    args = base_args(__doc__).parse_args()
    try:
        asyncio.run(amain(kafka_cfg(args)))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
