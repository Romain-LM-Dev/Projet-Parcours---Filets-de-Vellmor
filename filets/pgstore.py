"""Historique des runs dans PostgreSQL (F3, F5, F6), en asynchrone (asyncpg) : le remplaçant de SQLite (`store.py`).

Mêmes tables et mêmes vues que la version SQLite, si bien que les requêtes d'analyse qui passent par les vues
(`v_catches`, `v_season_indicators`…) valent pour les deux. Les charges utiles sont en JSONB (indexées) : on peut les
interroger directement (`payload->>'agent'`, `payload @> '{"fallback": true}'`). Plusieurs services ou moteurs peuvent
écrire en même temps, et l'écriture est idempotente : un événement relu après une reprise n'est pas écrit deux fois.

L'écriture est groupée : `add_event` / `add_indicator` déposent, `commit` écrit tout ce qui attend dans une transaction.
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id text PRIMARY KEY, label text, mode text, seed integer, seasons integer, config_hash text,
  n_fishers integer, rule_fraction double precision, communication text, catches_visible integer,
  capacity double precision, llm_tiers jsonb, started_at text, end_reason text, seasons_completed integer
);
CREATE TABLE IF NOT EXISTS events (
  event_id text PRIMARY KEY, run_id text NOT NULL, seq integer, type text, sim_time double precision, season integer,
  actor text, processed_at double precision, wall_clock text, schema_version integer, payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_run_type ON events (run_id, type);
CREATE INDEX IF NOT EXISTS ix_events_payload ON events USING gin (payload jsonb_path_ops);
CREATE TABLE IF NOT EXISTS indicators (
  run_id text, source_event_id text, sim_time double precision, season integer, trigger text, lag_s double precision,
  replay integer, values_json jsonb, source_event_ids jsonb,
  PRIMARY KEY (run_id, source_event_id, replay)
);
CREATE OR REPLACE VIEW v_catches AS
  SELECT run_id, season, sim_time, event_id, payload->>'agent' AS agent, payload->>'hamlet' AS hamlet,
         (payload->>'requested')::float8 AS requested, (payload->>'landed')::float8 AS landed,
         (payload->>'stock_observed')::float8 AS stock_observed, (payload->>'stock_before')::float8 AS stock_before,
         (payload->>'rationed')::boolean AS rationed
  FROM events WHERE type = 'catch';
CREATE OR REPLACE VIEW v_utterances AS
  SELECT run_id, season, sim_time, event_id, payload->>'speaker' AS speaker, payload->>'to' AS to_agent,
         payload->>'scope' AS scope, (payload->>'round')::integer AS round, payload->>'text' AS text
  FROM events WHERE type = 'utterance';
CREATE OR REPLACE VIEW v_promises AS
  SELECT run_id, season, payload->>'agent' AS agent, (payload->>'promised')::float8 AS promised,
         (payload->>'landed')::float8 AS landed, (payload->>'kept')::boolean AS kept, event_id
  FROM events WHERE type = 'promise_outcome';
CREATE OR REPLACE VIEW v_norms AS
  SELECT run_id, season, sim_time, event_id, payload->>'scope' AS scope, (payload->>'quota')::float8 AS quota,
         (payload->>'effective_season')::integer AS effective_season, payload->'supporters' AS supporters
  FROM events WHERE type = 'norm_adopted';
CREATE OR REPLACE VIEW v_incidents AS
  SELECT run_id, season, sim_time, event_id, payload->>'agent' AS agent, payload->>'incident_type' AS incident_type,
         payload->>'detail' AS detail
  FROM events WHERE type = 'incident';
CREATE OR REPLACE VIEW v_llm_calls AS
  SELECT run_id, season, payload->>'agent' AS agent, payload->>'tier' AS tier, payload->>'model' AS model,
         payload->>'system' AS system, (payload->>'prompt_tokens')::integer AS prompt_tokens,
         (payload->>'completion_tokens')::integer AS completion_tokens, (payload->>'latency_s')::float8 AS latency_s,
         payload->>'status' AS status
  FROM events WHERE type = 'llm_call';
CREATE OR REPLACE VIEW v_season_indicators AS
  SELECT i.run_id, r.label, r.mode, r.seed, r.communication, r.rule_fraction, i.season,
         (i.values_json->>'stock_ratio')::float8 AS stock_ratio, (i.values_json->>'total_catch')::float8 AS total_catch,
         (i.values_json->>'norm_index')::float8 AS norm_index, (i.values_json->>'norm_agreement')::float8 AS norm_agreement,
         (i.values_json->>'norm_compliance')::float8 AS norm_compliance, (i.values_json->>'catch_cv')::float8 AS catch_cv,
         (i.values_json->>'promise_kept_rate')::float8 AS promise_kept_rate,
         (i.values_json->>'llm_calls')::float8 AS llm_calls, (i.values_json->>'llm_tokens')::float8 AS llm_tokens
  FROM indicators i JOIN runs r USING (run_id) WHERE i.trigger = 'season_end' AND i.replay = 0;
"""


class PgHistoryStore:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool = None
        self._events: list[tuple] = []
        self._runs: list[tuple[str, tuple]] = []      # dans l'ordre : un run_end suit toujours son run_start
        self._indicators: list[tuple] = []

    async def open(self) -> None:
        from .vectors import connect_pool

        self.pool = await connect_pool(self.dsn, vector=False)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(7312)")
                await conn.execute(SCHEMA)

    def add_event(self, ev: dict) -> None:
        if ev.get("type") == "indicator" or ev.get("replay"):
            return
        p = ev["payload"]
        self._events.append((ev["event_id"], ev["run_id"], ev["seq"], ev["type"], ev["sim_time"], ev["season"],
                             ev.get("actor"), ev["processed_at"], ev["wall_clock"], ev["schema_version"],
                             json.dumps(p, ensure_ascii=False)))
        if ev["type"] == "run_start":
            sc = p["scenario"]
            self._runs.append(("start", (
                ev["run_id"], p.get("label", ""), p["mode"], p["seed"], p["seasons"], p["config_hash"],
                p.get("population", {}).get("fishers"), p.get("population", {}).get("rule_fraction"),
                sc["communication"], int(sc["catches_visible"]), p["lake"]["capacity"],
                json.dumps(p["llm_tiers"], ensure_ascii=False), ev["wall_clock"])))
        elif ev["type"] == "run_end":
            self._runs.append(("end", (p["reason"], p["seasons_completed"], ev["run_id"])))

    def add_indicator(self, msg: dict) -> None:
        p = msg["payload"]
        self._indicators.append((msg["run_id"], p["source_event_id"], msg["sim_time"], msg["season"], p["trigger"],
                                 p["lag_s"], int(bool(msg.get("replay"))), json.dumps(p["values"], ensure_ascii=False),
                                 json.dumps(p["source_event_ids"])))

    @property
    def pending(self) -> int:
        return len(self._events) + len(self._runs) + len(self._indicators)

    async def commit(self) -> None:
        if not self.pending:
            return
        events, runs, indicators = self._events, self._runs, self._indicators
        self._events, self._runs, self._indicators = [], [], []
        try:
            await self._write(events, runs, indicators)
        except BaseException:
            # rien n'est perdu : tout reste en attente, réessayé au prochain commit (l'écriture est idempotente)
            self._events[:0], self._runs[:0], self._indicators[:0] = events, runs, indicators
            raise

    async def _write(self, events: list, runs: list, indicators: list) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if events:
                    await conn.executemany(
                        "INSERT INTO events VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb) "
                        "ON CONFLICT (event_id) DO NOTHING", events)
                for kind, args in runs:
                    if kind == "start":
                        await conn.execute(
                            "INSERT INTO runs (run_id, label, mode, seed, seasons, config_hash, n_fishers, rule_fraction, "
                            "communication, catches_visible, capacity, llm_tiers, started_at) "
                            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13) "
                            "ON CONFLICT (run_id) DO UPDATE SET label = EXCLUDED.label, mode = EXCLUDED.mode, "
                            "seed = EXCLUDED.seed, seasons = EXCLUDED.seasons, config_hash = EXCLUDED.config_hash, "
                            "n_fishers = EXCLUDED.n_fishers, rule_fraction = EXCLUDED.rule_fraction, "
                            "communication = EXCLUDED.communication, catches_visible = EXCLUDED.catches_visible, "
                            "capacity = EXCLUDED.capacity, llm_tiers = EXCLUDED.llm_tiers, started_at = EXCLUDED.started_at",
                            *args)
                    else:
                        await conn.execute("UPDATE runs SET end_reason = $1, seasons_completed = $2 WHERE run_id = $3", *args)
                if indicators:
                    await conn.executemany(
                        "INSERT INTO indicators VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb) "
                        "ON CONFLICT (run_id, source_event_id, replay) DO UPDATE SET sim_time = EXCLUDED.sim_time, "
                        "season = EXCLUDED.season, trigger = EXCLUDED.trigger, lag_s = EXCLUDED.lag_s, "
                        "values_json = EXCLUDED.values_json, source_event_ids = EXCLUDED.source_event_ids", indicators)

    async def ingest_run_dir(self, run_dir: Path) -> int:
        n = 0
        with open(Path(run_dir) / "events.jsonl", encoding="utf-8") as f:
            for line in f:
                self.add_event(json.loads(line))
                n += 1
        ind = Path(run_dir) / "indicators.jsonl"
        if ind.exists():
            with open(ind, encoding="utf-8") as f:
                for line in f:
                    self.add_indicator(json.loads(line))
        await self.commit()
        return n

    async def fetch(self, sql: str, *args):
        return await self.pool.fetch(sql, *args)

    async def close(self) -> None:
        if self.pool is not None:
            await self.commit()
            await self.pool.close()
            self.pool = None
