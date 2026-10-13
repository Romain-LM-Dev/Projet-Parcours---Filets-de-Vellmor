"""Fabrique d'événements : enveloppe commune, validation de schéma, publication et enregistrement."""
from __future__ import annotations

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


class EventFactory:
    def __init__(self, run_id: str, clock: SimClock, bus, recorder: Recorder | None):
        self.run_id = run_id
        self.clock = clock
        self.bus = bus
        self.recorder = recorder
        self.seq = 0
        self.index: dict[str, dict] = {}   # event_id -> événement (vérification de cohérence temporelle)
        self.deadletters = 0

    def emit(self, etype: str, payload: dict, actor: str | None = None, sim_time: float | None = None) -> dict:
        t = self.clock.now() if sim_time is None else sim_time
        self.seq += 1
        ev = {
            "type": etype,
            "schema_version": SCHEMA_VERSION,
            "event_id": f"{self.run_id}-{self.seq:06d}",
            "run_id": self.run_id,
            "seq": self.seq,
            "sim_time": round(t, 6),
            "sim_label": self.clock.label(t),
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
        self.index[ev["event_id"]] = ev
        self.bus.publish("events", ev, key=actor)
        if self.recorder:
            self.recorder.write(ev)
        return ev
