"""Fabrique d'événements : enveloppe commune, validation de schéma, publication et enregistrement."""
from __future__ import annotations

import contextlib
import contextvars
import datetime as dt
import json
from pathlib import Path

from .clock import SimClock
from .schemas import SCHEMA_VERSION, validate_event


class Recorder:
    """Écrit tous les événements d'un run dans `runs/<run_id>/events.jsonl` (source du rejeu, E3)."""

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        self._f = open(run_dir / "events.jsonl", "a", encoding="utf-8")

    def write(self, event: dict) -> None:
        self._f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def flush(self):
        self._f.flush()

    def close(self):
        self._f.close()


_pending: contextvars.ContextVar[list | None] = contextvars.ContextVar("pending_events", default=None)


class EventFactory:
    def __init__(self, run_id: str, clock: SimClock, bus, recorder: Recorder | None):
        self.run_id = run_id
        self.clock = clock
        self.bus = bus
        self.recorder = recorder
        self.seq = 0
        self.index: dict[str, dict] = {}   # event_id -> événement (vérification de cohérence temporelle)
        self.when = None                   # le moment en toutes lettres (`World.when`) ; à défaut, celui de l'horloge
        self.deadletters = 0
        self.renamed: dict[str, str] = {}  # identifiant provisoire -> identifiant définitif (événements mis en attente, voir `defer`)
        self._tmp = 0

    @staticmethod
    @contextlib.contextmanager
    def defer(buf: list):
        """Dans ce bloc (et cette tâche), les événements sont mis en attente dans `buf` (avec un identifiant provisoire) : l'ordonnanceur
        les émet ensuite avec `flush`, dans l'ordre de la file et non dans celui où les modèles ont répondu."""
        token = _pending.set(buf)
        try:
            yield
        finally:
            _pending.reset(token)

    def flush(self, buf: list) -> None:
        """Émet les événements mis en attente : numéro de suite et identifiant définitifs, puis publication et trace."""
        for ev in buf:
            self.seq += 1
            old, ev["seq"], ev["event_id"] = ev["event_id"], self.seq, f"{self.run_id}-{self.seq:06d}"
            self.renamed[old] = ev["event_id"]
            self.index[ev["event_id"]] = ev
            self.bus.publish("events", ev, key=ev["actor"])
            if self.recorder:
                self.recorder.write(ev)
        buf.clear()

    def emit(self, etype: str, payload: dict, actor: str | None = None, sim_time: float | None = None) -> dict:
        t = self.clock.now() if sim_time is None else sim_time
        buf = _pending.get()
        if buf is None:
            self.seq += 1
            seq, eid = self.seq, f"{self.run_id}-{self.seq:06d}"
        else:
            self._tmp += 1
            seq, eid = 0, f"{self.run_id}-p{self._tmp}"
        ev = {
            "type": etype,
            "schema_version": SCHEMA_VERSION,
            "event_id": eid,
            "run_id": self.run_id,
            "seq": seq,
            "sim_time": round(t, 6),
            "sim_label": self.clock.label(t),
            "sim_text": (self.when or self.clock.text)(round(t, 6)),      # lu sur le même instant que `sim_time`
            "season": self.clock.season_of(t),
            "processed_at": round(self.clock.wall_elapsed(), 4),
            "wall_clock": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
            "actor": actor,
            "payload": payload,
        }
        errors = validate_event(ev)
        if errors:
            self.deadletters += 1
            self.bus.publish("deadletter", {"event": ev, "errors": errors}, key=actor)
            if etype != "incident":
                self.emit("incident", {"agent": actor or "system", "incident_type": "schema_violation",
                                       "detail": f"{etype}: {errors[0]}"[:300], "handled_by": "deadletter"},
                          actor=actor, sim_time=t)
            return ev
        if buf is not None:
            buf.append(ev)
            return ev
        self.index[ev["event_id"]] = ev
        self.bus.publish("events", ev, key=actor)
        if self.recorder:
            self.recorder.write(ev)
        return ev
