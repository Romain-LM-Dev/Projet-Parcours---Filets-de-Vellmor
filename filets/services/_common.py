from __future__ import annotations

import argparse
import json
import signal
import threading

from ..config import load_config


def base_args(desc: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=desc)
    ap.add_argument("--config", default="config/default.yaml")
    ap.add_argument("--bootstrap", help="adresse Kafka (sinon celle de la configuration)")
    return ap


def kafka_cfg(args) -> dict:
    cfg = load_config(args.config)
    cfg["bus"]["kind"] = "kafka"
    if args.bootstrap:
        cfg["bus"]["bootstrap"] = args.bootstrap
    return cfg


def consume_forever(consumer, handle, stop: threading.Event | None = None, on_idle=None):
    """Boucle de consommation : `handle(topic_name, message_dict)`."""
    stop = stop or threading.Event()
    if threading.current_thread() is threading.main_thread():   # signal.signal() est interdit ailleurs (pont : thread)
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        while not stop.is_set():
            msg = consumer.poll(0.5)
            if msg is None:
                if on_idle:
                    on_idle()
                continue
            if msg.error():
                continue
            try:
                data = json.loads(msg.value())
            except json.JSONDecodeError:
                continue
            handle(msg.topic(), data)
    finally:
        consumer.close()
