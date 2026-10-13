"""Service d'indicateurs : consomme `filets.events`, publie `filets.indicators` (B2, C7, F6).

    python -m filets.services.indicators [--bootstrap localhost:9092]

Au démarrage, le service se place sur le dernier `run_start` du topic : tous ses calculs
(capacité du lac, liste des pêcheurs, normes adoptées…) se rapportent à ce début de run. Démarré
avant, pendant ou après la simulation, il aboutit donc aux mêmes chiffres. Si le service est relancé
en cours de partie, il republie les indicateurs déjà émis ; les consommateurs les dédoublonnent.
"""
from __future__ import annotations

from ..bus import KafkaBus, kafka_assigned_consumer, last_run_start_offset
from ..pipeline import IndicatorPublisher
from ._common import base_args, consume_forever, kafka_cfg


def main():
    args = base_args(__doc__).parse_args()
    cfg = kafka_cfg(args)
    bus = KafkaBus(cfg["bus"]["bootstrap"], cfg["bus"]["topics"], consume_commands=False)
    pub = IndicatorPublisher(bus, cfg["output"]["runs_dir"], cfg["scenario"]["quota_tolerance"])
    start = last_run_start_offset(cfg)
    consumer = kafka_assigned_consumer(cfg, "filets-indicators", {"events": start})
    print("Service d'indicateurs à l'écoute de", cfg["bus"]["topics"]["events"], f"(depuis l'offset {start})")
    warned = [False]

    def handle(_topic, ev):
        out = pub.on_event(ev)
        if pub.engine.skipped and not warned[0]:
            warned[0] = True
            print("Attention : des événements arrivent sans leur run_start ; ils sont ignorés.")
        if out and out["payload"]["trigger"] == "season_end":
            v = out["payload"]["values"]
            print(f"{out['sim_label']}  stock {v['stock_ratio'] * 100:.0f} %  norme {v['norm_index']:.2f}  "
                  f"décalage {out['payload']['lag_s'] * 1000:.0f} ms")

    try:
        consume_forever(consumer, handle, on_idle=bus.flush)
    finally:
        pub.close()
        bus.close()


if __name__ == "__main__":
    main()
