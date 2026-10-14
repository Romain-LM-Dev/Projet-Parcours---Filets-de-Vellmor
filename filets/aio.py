"""Kafka asynchrone (aiokafka) pour les services.

Les services (pont, indicateurs, historique) vivent dans une boucle asyncio : un consommateur Kafka y est une simple boucle
`async for`, sans fil de lecture à côté, sans `call_soon_threadsafe`, et le producteur envoie sans bloquer. Le moteur, lui,
garde `bus.KafkaBus` : publier un événement y est déjà un simple dépôt dans la file de librdkafka, sans attente.

Même principe de reprise que `bus.py` : un service qui démarre ou redémarre se place explicitement sur le dernier `run_start`
du topic des événements (sans lui, il ne connaît ni la capacité du lac ni la liste des pêcheurs), et lit sans groupe de
rebalance : pas d'attente, pas de course avec le producteur, rien n'est validé côté broker (l'état se reconstruit).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.errors import KafkaError

from .bus import OFFSET_BEGINNING

__all__ = ["OFFSET_BEGINNING", "PublisherBus", "assigned_consumer", "last_run_start_offset", "messages", "producer", "send"]

_SCAN_CHUNK = 2000
log = logging.getLogger("filets.aio")


async def last_run_start_offset(cfg: dict, timeout_ms: int = 1000) -> int:
    """Offset du dernier `run_start` du topic des événements, ou du premier message s'il n'y en a pas."""
    tp = TopicPartition(cfg["bus"]["topics"]["events"], 0)
    c = AIOKafkaConsumer(bootstrap_servers=cfg["bus"]["bootstrap"], group_id=None, enable_auto_commit=False)
    await c.start()
    try:
        c.assign([tp])
        try:
            low = (await c.beginning_offsets([tp]))[tp]
            end = (await c.end_offsets([tp]))[tp]
        except KafkaError:
            return 0
        while end > low:                       # on remonte par tranches : le début du run en cours est près de la fin
            start = max(low, end - _SCAN_CHUNK)
            c.seek(tp, start)
            found, pos = None, start
            while pos < end:
                batch = (await c.getmany(tp, timeout_ms=timeout_ms, max_records=500)).get(tp, [])
                if not batch:
                    break
                for m in batch:
                    if m.offset >= end:
                        pos = end
                        break
                    pos = m.offset + 1
                    if b'"type": "run_start"' in (m.value or b"")[:80]:
                        found = m.offset
            if found is not None:
                return found
            end = start
        return low
    finally:
        await c.stop()


async def assigned_consumer(cfg: dict, positions: dict[str, int]) -> AIOKafkaConsumer:
    """Consommateur démarré, sans groupe : lit chaque topic (une partition) depuis l'offset donné.
    `positions` : clé de topic (`events`…) → offset, ou `OFFSET_BEGINNING`."""
    topics = cfg["bus"]["topics"]
    c = AIOKafkaConsumer(bootstrap_servers=cfg["bus"]["bootstrap"], group_id=None, enable_auto_commit=False,
                         auto_offset_reset="earliest")
    await c.start()
    tps = {key: TopicPartition(topics[key], 0) for key in positions}
    c.assign(list(tps.values()))
    for key, off in positions.items():
        if off == OFFSET_BEGINNING:
            await c.seek_to_beginning(tps[key])
        else:
            c.seek(tps[key], off)
    return c


async def messages(consumer: AIOKafkaConsumer) -> AsyncIterator[tuple[str, dict]]:
    """Les messages du consommateur : (nom du topic, contenu JSON). Un message qui n'est pas du JSON est ignoré."""
    async for msg in consumer:
        try:
            yield msg.topic, json.loads(msg.value)
        except (json.JSONDecodeError, TypeError):
            continue


async def producer(cfg: dict) -> AIOKafkaProducer:
    """Producteur démarré : `acks=all` et idempotent, comme celui du moteur (rien n'est écrit deux fois ni perdu en route)."""
    p = AIOKafkaProducer(bootstrap_servers=cfg["bus"]["bootstrap"], acks="all", enable_idempotence=True, linger_ms=5)
    await p.start()
    return p


async def send(p: AIOKafkaProducer, cfg: dict, topic_key: str, event: dict, key: str | None = None) -> None:
    """Envoie un message et attend l'accusé du broker."""
    await p.send_and_wait(cfg["bus"]["topics"][topic_key], json.dumps(event, ensure_ascii=False).encode("utf-8"),
                          key=key.encode() if key else None)


class PublisherBus:
    """Façade minimale (`publish`) au-dessus d'un producteur aiokafka, pour le code synchrone qui publie (les indicateurs).
    `publish` dépose le message dans une file sans attendre ; une tâche l'envoie, dans l'ordre. `aflush` attend que tout soit
    parti et accusé par le broker. À créer dans la boucle asyncio du service."""

    def __init__(self, p: AIOKafkaProducer, topics: dict[str, str]):
        self.producer, self.topics = p, topics
        self.queue: asyncio.Queue = asyncio.Queue()
        self._worker = asyncio.create_task(self._run())

    def publish(self, topic: str, event: dict, key: str | None = None) -> None:
        if topic in self.topics:
            self.queue.put_nowait((self.topics[topic], json.dumps(event, ensure_ascii=False).encode("utf-8"),
                                   key.encode() if key else None))

    def subscribe(self, topic, callback) -> None:        # l'interface du bus : sans objet ici
        pass

    async def _run(self) -> None:
        while True:
            topic, value, key = await self.queue.get()
            try:
                await self.producer.send(topic, value, key=key)
            except Exception:
                log.exception("message non envoyé sur %s", topic)
            finally:
                self.queue.task_done()

    async def aflush(self) -> None:
        await self.queue.join()
        await self.producer.flush()

    async def aclose(self) -> None:
        await self.aflush()
        self._worker.cancel()
        await asyncio.gather(self._worker, return_exceptions=True)
