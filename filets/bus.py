"""Transport des événements.

* `KafkaBus` : le transport de référence (exigence C1). Un topic par nature de flux :
  - `filets.events`     : tous les faits du monde, une partition (ordre total garanti,
                          indispensable au rejeu et au calcul d'indicateurs), clé = acteur ;
  - `filets.indicators` : indicateurs calculés par le service d'indicateurs ;
  - `filets.commands`   : injections envoyées depuis Godot ;
  - `filets.deadletter` : événements non conformes, isolés.
  - `filets.status`     : état du moteur (salon, en cours, pause, vitesse), hors du flux d'un run ;
                          conservé une heure seulement, car seul le dernier message compte.
* `LocalBus` : même interface en mémoire, pour les tests et les runs répétés sans broker.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from collections import defaultdict
from typing import Callable

TOPIC_KEYS = ("events", "indicators", "commands", "deadletter", "status")
RETENTION_MS = {"status": 3600 * 1000}          # les autres topics : 7 jours
DEFAULT_RETENTION_MS = 7 * 24 * 3600 * 1000


log = logging.getLogger("filets.bus")


def _notify(subscribers: list, event: dict, topic: str) -> None:
    """Prévient les abonnés en processus (affichage console, pont Godot, indicateurs locaux). L'un d'eux qui échoue
    ne doit jamais interrompre la partie qui publie : l'erreur est journalisée, les autres abonnés sont prévenus."""
    for cb in list(subscribers):
        try:
            cb(event)
        except Exception:
            log.exception("abonné défaillant sur le topic %s", topic)


class Bus:
    def publish(self, topic: str, event: dict, key: str | None = None) -> None: ...
    def subscribe(self, topic: str, callback: Callable[[dict], None]) -> None: ...
    def send_command(self, cmd: dict) -> None: ...
    def poll_commands(self) -> list[dict]: ...
    def wait_ready(self, timeout: float = 30.0) -> bool: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...


class LocalBus(Bus):
    def __init__(self):
        self._subs: dict[str, list[Callable]] = defaultdict(list)
        self._commands: "queue.Queue[dict]" = queue.Queue()
        self.counts: dict[str, int] = defaultdict(int)

    def publish(self, topic, event, key=None):
        self.counts[topic] += 1
        if topic == "commands":
            self._commands.put(event)
        _notify(self._subs[topic], event, topic)

    def subscribe(self, topic, callback):
        self._subs[topic].append(callback)

    def send_command(self, cmd):
        self.publish("commands", cmd)

    def poll_commands(self):
        out = []
        while True:
            try:
                out.append(self._commands.get_nowait())
            except queue.Empty:
                return out

    def wait_ready(self, timeout=30.0):
        return True

    def flush(self):
        pass

    def close(self):
        pass


def ensure_topics(bootstrap: str, topics: dict[str, str]) -> None:
    from confluent_kafka.admin import AdminClient, NewTopic

    admin = AdminClient({"bootstrap.servers": bootstrap})
    existing = set(admin.list_topics(timeout=10).topics)
    new = []
    for key, name in topics.items():
        if name in existing:
            continue
        conf = {"retention.ms": str(RETENTION_MS.get(key, DEFAULT_RETENTION_MS))}
        new.append(NewTopic(name, num_partitions=1, replication_factor=1, config=conf))
    if new:
        for _, fut in admin.create_topics(new).items():
            try:
                fut.result()
            except Exception as exc:  # topic créé entre-temps
                if "TOPIC_ALREADY_EXISTS" not in str(exc):
                    raise


class KafkaBus(Bus):
    def __init__(self, bootstrap: str, topics: dict[str, str], group: str = "filets-engine",
                 consume_commands: bool = True):
        from confluent_kafka import Consumer, Producer

        ensure_topics(bootstrap, topics)
        self.topics = topics
        self.producer = Producer({"bootstrap.servers": bootstrap, "linger.ms": 5, "acks": "all",
                                  "enable.idempotence": True})
        self._subs: dict[str, list[Callable]] = defaultdict(list)
        self._commands: "queue.Queue[dict]" = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        # levé quand le consommateur de commandes a reçu sa partition : avant, une commande envoyée
        # serait perdue (lecture « latest »). Le moteur n'annonce son salon qu'à ce moment-là.
        self.commands_ready = threading.Event()
        if consume_commands:
            self.consumer = Consumer({"bootstrap.servers": bootstrap, "group.id": group,
                                      "auto.offset.reset": "latest", "enable.auto.commit": True})
            self.consumer.subscribe([topics["commands"]], on_assign=lambda _c, _parts: self.commands_ready.set())
            self._thread = threading.Thread(target=self._consume, daemon=True)
            self._thread.start()
        else:
            self.commands_ready.set()

    def wait_ready(self, timeout: float = 30.0) -> bool:
        return self.commands_ready.wait(timeout)

    def _consume(self):
        while not self._stop.is_set():
            msg = self.consumer.poll(0.2)
            if msg is None or msg.error():
                continue
            try:
                self._commands.put(json.loads(msg.value()))
            except json.JSONDecodeError:
                pass

    def publish(self, topic, event, key=None):
        if topic in self.topics:        # un topic absent d'une configuration ancienne n'arrête pas la partie
            self.producer.produce(self.topics[topic], json.dumps(event, ensure_ascii=False).encode("utf-8"),
                                  key=key.encode() if key else None)
            self.producer.poll(0)
        _notify(self._subs[topic], event, topic)

    def subscribe(self, topic, callback):
        # abonnement en processus (ex. calcul local) ; les autres services consomment Kafka directement
        self._subs[topic].append(callback)

    def send_command(self, cmd):
        self.publish("commands", cmd)

    def poll_commands(self):
        out = []
        while True:
            try:
                out.append(self._commands.get_nowait())
            except queue.Empty:
                return out

    def flush(self):
        self.producer.flush(10)

    def close(self):
        self._stop.set()
        self.flush()
        if self._thread:
            self._thread.join(timeout=2)
            self.consumer.close()


def make_bus(cfg: dict, group: str = "filets-engine", consume_commands: bool = True) -> Bus:
    b = cfg["bus"]
    if b["kind"] == "kafka":
        return KafkaBus(b["bootstrap"], b["topics"], group=group, consume_commands=consume_commands)
    return LocalBus()


def kafka_consumer(cfg: dict, group: str, topics: list[str], from_beginning: bool = False):
    from confluent_kafka import Consumer

    c = Consumer({"bootstrap.servers": cfg["bus"]["bootstrap"], "group.id": group,
                  "auto.offset.reset": "earliest" if from_beginning else "latest"})
    c.subscribe([cfg["bus"]["topics"][t] for t in topics])
    return c


# ------------------------------------------------------------------ reprise au début du run en cours
# Un service qui démarre (ou redémarre) en cours de route doit retrouver le début du run en cours :
# sans l'événement `run_start`, il ne connaît ni la capacité du lac ni la liste des pêcheurs, et
# tous ses calculs seraient faux. On ne s'abonne donc pas « au dernier message » (course contre le
# démarrage de la simulation) : on se place explicitement au `run_start` le plus récent du topic.
_SCAN_CHUNK = 2000


def last_run_start_offset(cfg: dict, timeout: float = 10.0) -> int:
    """Offset du dernier `run_start` du topic des événements, ou du premier message s'il n'y en a pas."""
    import uuid

    from confluent_kafka import Consumer, KafkaException, TopicPartition

    topic = cfg["bus"]["topics"]["events"]
    c = Consumer({"bootstrap.servers": cfg["bus"]["bootstrap"], "group.id": f"filets-scan-{uuid.uuid4().hex[:8]}",
                  "enable.auto.commit": False, "auto.offset.reset": "earliest"})
    try:
        try:
            low, high = c.get_watermark_offsets(TopicPartition(topic, 0), timeout=timeout)
        except KafkaException:
            return 0
        end = high
        while end > low:
            start = max(low, end - _SCAN_CHUNK)
            c.assign([TopicPartition(topic, 0, start)])
            found, pos, silent = None, start, 0
            while pos < end and silent < 5:
                msg = c.poll(1.0)
                if msg is None:
                    silent += 1
                    continue
                silent = 0
                if msg.error():
                    continue
                if msg.offset() >= end:
                    break
                pos = msg.offset() + 1
                raw = msg.value() or b""
                if b"run_start" in raw[:80] and b'"type": "run_start"' in raw[:80]:
                    found = msg.offset()
            if found is not None:
                return found
            end = start
        return low
    finally:
        c.close()


def kafka_assigned_consumer(cfg: dict, group: str, positions: dict[str, int]):
    """Consommateur sans groupe de rebalance : lit chaque topic (une partition) depuis l'offset donné.

    `positions` : clé de topic (`events`…) → offset, ou `OFFSET_BEGINNING` (-2). Aucune attente de
    rebalance, aucune course avec le producteur ; rien n'est validé côté broker (l'état se reconstruit).
    """
    from confluent_kafka import Consumer, TopicPartition

    c = Consumer({"bootstrap.servers": cfg["bus"]["bootstrap"], "group.id": group, "enable.auto.commit": False,
                  "auto.offset.reset": "earliest"})
    c.assign([TopicPartition(cfg["bus"]["topics"][key], 0, off) for key, off in positions.items()])
    return c


OFFSET_BEGINNING = -2
