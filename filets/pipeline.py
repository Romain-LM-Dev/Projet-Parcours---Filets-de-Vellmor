"""Publication des indicateurs : enveloppe, mesure du décalage (C7), journal par run."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .config import ROOT
from .indicators import IndicatorEngine


def _parse(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts)


class IndicatorPublisher:
    def __init__(self, bus, runs_dir: str = "runs", quota_tolerance: float = 0.5, journal: bool = True,
                 journal_name: str = "indicators.jsonl"):
        self.engine = IndicatorEngine(quota_tolerance)
        self.bus = bus
        self.runs_dir = ROOT / runs_dir
        self.journal = journal
        self.journal_name = journal_name
        self._f = None
        self._run = None
        self.lags: list[float] = []

    def on_event(self, ev: dict) -> dict | None:
        if ev.get("type") == "run_start":
            self._open(ev["run_id"], "indicators_replay.jsonl" if ev.get("replay") else self.journal_name)
        out = self.engine.ingest(ev)
        if out is None:
            return None
        now = dt.datetime.now(dt.timezone.utc)
        published = ev.get("replayed_at") or ev.get("wall_clock")
        lag = (now - _parse(published)).total_seconds() if published else 0.0
        self.lags.append(lag)
        msg = {
            "type": "indicator", "run_id": out["run_id"], "sim_time": out["sim_time"], "sim_label": out["sim_label"],
            "season": out["season"], "replay": bool(ev.get("replay")),
            "payload": {"trigger": out["trigger"], "values": out["values"],
                        "source_event_ids": out["source_event_ids"], "source_event_id": out["source_event_id"],
                        "lag_s": round(lag, 4), "computed_at": now.isoformat(timespec="milliseconds")},
        }
        self.bus.publish("indicators", msg, key=out["run_id"])
        if self._f:
            self._f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            self._f.flush()
        return msg

    def _open(self, run_id: str, name: str):
        if self._f:
            self._f.close()
            self._f = None
        if self.journal:
            d = self.runs_dir / run_id
            d.mkdir(parents=True, exist_ok=True)
            self._f = open(d / name, "w", encoding="utf-8")
        self._run = run_id

    def close(self):
        if self._f:
            self._f.close()
            self._f = None
