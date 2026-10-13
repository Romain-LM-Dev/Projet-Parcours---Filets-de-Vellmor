"""Historique des runs dans SQLite (F3, F5, F6).

Pourquoi SQLite : l'historique est écrit une fois et relu par des requêtes analytiques
reproductibles (comparaison de scénarios, résultats du rapport). Quelques dizaines de
runs × quelques milliers d'événements tiennent dans un seul fichier, sans serveur, et
JSON1 permet de requêter les payloads. Les vues typées (`v_catches`, `v_utterances`…)
évitent de dupliquer les données : la table `events` reste la source unique.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, label TEXT, mode TEXT, seed INTEGER, seasons INTEGER, config_hash TEXT,
  n_fishers INTEGER, rule_fraction REAL, communication TEXT, catches_visible INTEGER, capacity REAL,
  llm_tiers TEXT, started_at TEXT, end_reason TEXT, seasons_completed INTEGER
);
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY, run_id TEXT, seq INTEGER, type TEXT, sim_time REAL, season INTEGER,
  actor TEXT, processed_at REAL, wall_clock TEXT, schema_version INTEGER, payload TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_run_type ON events(run_id, type);
CREATE TABLE IF NOT EXISTS indicators (
  run_id TEXT, source_event_id TEXT, sim_time REAL, season INTEGER, trigger TEXT, lag_s REAL,
  replay INTEGER, values_json TEXT, source_event_ids TEXT,
  PRIMARY KEY (run_id, source_event_id, replay)
);
CREATE VIEW IF NOT EXISTS v_catches AS
  SELECT run_id, season, sim_time, event_id, json_extract(payload,'$.agent') AS agent,
         json_extract(payload,'$.hamlet') AS hamlet, json_extract(payload,'$.requested') AS requested,
         json_extract(payload,'$.landed') AS landed, json_extract(payload,'$.stock_observed') AS stock_observed,
         json_extract(payload,'$.stock_before') AS stock_before, json_extract(payload,'$.rationed') AS rationed
  FROM events WHERE type='catch';
CREATE VIEW IF NOT EXISTS v_utterances AS
  SELECT run_id, season, sim_time, event_id, json_extract(payload,'$.speaker') AS speaker,
         json_extract(payload,'$.to') AS to_agent, json_extract(payload,'$.scope') AS scope,
         json_extract(payload,'$.round') AS round, json_extract(payload,'$.text') AS text
  FROM events WHERE type='utterance';
CREATE VIEW IF NOT EXISTS v_promises AS
  SELECT o.run_id, o.season, json_extract(o.payload,'$.agent') AS agent, json_extract(o.payload,'$.promised') AS promised,
         json_extract(o.payload,'$.landed') AS landed, json_extract(o.payload,'$.kept') AS kept, o.event_id
  FROM events o WHERE o.type='promise_outcome';
CREATE VIEW IF NOT EXISTS v_norms AS
  SELECT run_id, season, sim_time, event_id, json_extract(payload,'$.scope') AS scope,
         json_extract(payload,'$.quota') AS quota, json_extract(payload,'$.effective_season') AS effective_season,
         json_extract(payload,'$.supporters') AS supporters
  FROM events WHERE type='norm_adopted';
CREATE VIEW IF NOT EXISTS v_incidents AS
  SELECT run_id, season, sim_time, event_id, json_extract(payload,'$.agent') AS agent,
         json_extract(payload,'$.incident_type') AS incident_type, json_extract(payload,'$.detail') AS detail
  FROM events WHERE type='incident';
CREATE VIEW IF NOT EXISTS v_llm_calls AS
  SELECT run_id, season, json_extract(payload,'$.agent') AS agent, json_extract(payload,'$.tier') AS tier,
         json_extract(payload,'$.model') AS model, json_extract(payload,'$.prompt_tokens') AS prompt_tokens,
         json_extract(payload,'$.completion_tokens') AS completion_tokens,
         json_extract(payload,'$.latency_s') AS latency_s, json_extract(payload,'$.status') AS status
  FROM events WHERE type='llm_call';
CREATE VIEW IF NOT EXISTS v_season_indicators AS
  SELECT i.run_id, r.label, r.mode, r.seed, r.communication, r.rule_fraction, i.season,
         json_extract(i.values_json,'$.stock_ratio') AS stock_ratio,
         json_extract(i.values_json,'$.total_catch') AS total_catch,
         json_extract(i.values_json,'$.norm_index') AS norm_index,
         json_extract(i.values_json,'$.norm_agreement') AS norm_agreement,
         json_extract(i.values_json,'$.norm_compliance') AS norm_compliance,
         json_extract(i.values_json,'$.catch_cv') AS catch_cv,
         json_extract(i.values_json,'$.promise_kept_rate') AS promise_kept_rate,
         json_extract(i.values_json,'$.llm_calls') AS llm_calls,
         json_extract(i.values_json,'$.llm_tokens') AS llm_tokens
  FROM indicators i JOIN runs r USING(run_id) WHERE i.trigger='season_end' AND i.replay=0;
"""


class HistoryStore:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)

    def add_event(self, ev: dict):
        if ev.get("type") == "indicator" or ev.get("replay"):
            return
        p = ev["payload"]
        self.db.execute("INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            ev["event_id"], ev["run_id"], ev["seq"], ev["type"], ev["sim_time"], ev["season"], ev.get("actor"),
            ev["processed_at"], ev["wall_clock"], ev["schema_version"], json.dumps(p, ensure_ascii=False)))
        if ev["type"] == "run_start":
            sc = p["scenario"]
            self.db.execute("INSERT OR REPLACE INTO runs (run_id,label,mode,seed,seasons,config_hash,n_fishers,"
                            "rule_fraction,communication,catches_visible,capacity,llm_tiers,started_at) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                ev["run_id"], p.get("label", ""), p["mode"], p["seed"], p["seasons"], p["config_hash"],
                p.get("population", {}).get("fishers"), p.get("population", {}).get("rule_fraction"),
                sc["communication"], int(sc["catches_visible"]), p["lake"]["capacity"],
                json.dumps(p["llm_tiers"]), ev["wall_clock"]))
        elif ev["type"] == "run_end":
            self.db.execute("UPDATE runs SET end_reason=?, seasons_completed=? WHERE run_id=?",
                            (p["reason"], p["seasons_completed"], ev["run_id"]))

    def add_indicator(self, msg: dict):
        p = msg["payload"]
        self.db.execute("INSERT OR REPLACE INTO indicators VALUES (?,?,?,?,?,?,?,?,?)", (
            msg["run_id"], p["source_event_id"], msg["sim_time"], msg["season"], p["trigger"], p["lag_s"],
            int(bool(msg.get("replay"))), json.dumps(p["values"], ensure_ascii=False),
            json.dumps(p["source_event_ids"])))

    def ingest_run_dir(self, run_dir: Path) -> int:
        n = 0
        with open(run_dir / "events.jsonl", encoding="utf-8") as f:
            for line in f:
                self.add_event(json.loads(line))
                n += 1
        ind = run_dir / "indicators.jsonl"
        if ind.exists():
            with open(ind, encoding="utf-8") as f:
                for line in f:
                    self.add_indicator(json.loads(line))
        self.commit()
        return n

    def commit(self):
        self.db.commit()

    def close(self):
        self.db.commit()
        self.db.close()
