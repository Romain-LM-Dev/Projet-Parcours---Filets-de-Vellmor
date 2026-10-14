"""Ligne de commande de FILETS.

    python -m filets serve    [--config ...] [--bus local|kafka] [--no-ws]   (salon : le menu de Godot lance la partie)
    python -m filets run      [--config ...] [--agents N] [--mode sync|async] [--bus local|kafka] [--ws]
    python -m filets replay   RUN_ID [--speed 4] [--ws] [--bus local|kafka]
    python -m filets verify   RUN_ID
    python -m filets batch    --config config/default.yaml --config config/baseline.yaml --runs 5
    python -m filets ingest   [RUN_ID ...]
    python -m filets schemas
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import logging
import statistics
import sys
import time
import uuid
from pathlib import Path

from .bus import LocalBus, make_bus
from .catalog import build_catalog
from .config import ROOT, load_config, set_dotted
from .console import console_printer, print_summary
from .indicators import IndicatorEngine
from .pipeline import IndicatorPublisher
from .schemas import COMMAND, ENVELOPE, PAYLOADS, SCHEMA_VERSION, STATUS, validate_event
from .store import HistoryStore
from .vectors import postgres_dsn

log = logging.getLogger("filets")


def build_cfg(args) -> dict:
    over: dict = {}
    if getattr(args, "agents", None):
        set_dotted(over, "population.fishers", args.agents)
    if getattr(args, "mode", None):
        set_dotted(over, "time.mode", args.mode)
    if getattr(args, "seasons", None):
        set_dotted(over, "run.seasons", args.seasons)
    if getattr(args, "seed", None) is not None:
        set_dotted(over, "run.seed", args.seed)
    if getattr(args, "bus", None):
        set_dotted(over, "bus.kind", args.bus)
    if getattr(args, "fast", False):
        set_dotted(over, "time.fast", True)
    for kv in getattr(args, "set", None) or []:
        k, v = kv.split("=", 1)
        set_dotted(over, k, v)
    cfg = load_config(args.config, over)
    cfg["run"].setdefault("label", Path(args.config).stem if args.config else "default")
    return cfg


def new_run_id(cfg: dict) -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{cfg['time']['mode']}-n{cfg['population']['fishers']}-s{cfg['run']['seed']}"


def make_api(cfg: dict, port: int, on_command, catalog: dict | None):
    """L'API (REST + WebSocket) de ce processus : adresse de `api.host` (127.0.0.1 par défaut), runs lus dans `runs/`,
    mémoire collective dans pgvector si `rag.backend: pgvector`."""
    from .api import ApiServer, LocalRuns, memories_for

    return ApiServer(cfg.get("api", {}).get("host", "127.0.0.1"), port, on_command, catalog=catalog,
                     runs=LocalRuns(ROOT / cfg["output"]["runs_dir"]), memories=memories_for(cfg))


def unique_run_id(cfg: dict) -> str:
    """Comme `new_run_id`, sans jamais réutiliser le dossier d'un run existant (deux parties dans la même seconde)."""
    base = rid = new_run_id(cfg)
    runs = ROOT / cfg["output"]["runs_dir"]
    k = 1
    while (runs / rid).exists():
        k += 1
        rid = f"{base}-{k}"
    return rid


async def run_once(cfg: dict, ws: bool = False, ws_port: int = 8765, linger: bool = False,
                   run_id: str | None = None, quiet: bool = False) -> str:
    from .world import World

    bus = make_bus(cfg)
    run_id = run_id or unique_run_id(cfg)
    local = isinstance(bus, LocalBus)
    bridge = None
    if ws:
        bridge = make_api(cfg, ws_port, bus.send_command, build_catalog(cfg))
        await bridge.start()
        for topic in ("events", "indicators", "status"):
            bus.subscribe(topic, lambda e, t=topic: bridge.push(t, e))
        if not quiet:
            print(f"API FILETS : http://localhost:{bridge.port} (WebSocket /ws pour Godot, documentation /docs)")
    pub = None
    if local:
        # en bus local, les indicateurs sont calculés en processus ; avec Kafka, c'est le service dédié
        pub = IndicatorPublisher(bus, cfg["output"]["runs_dir"], cfg["scenario"]["quota_tolerance"])
        bus.subscribe("events", pub.on_event)
    if not quiet:
        bus.subscribe("events", console_printer())
    world = World(cfg, bus, run_id)
    try:
        await world.run()
    finally:
        if pub:
            pub.close()
    if not quiet:
        print_summary(world, pub)
    if bridge:
        if linger:
            print("Run terminé. La scène reste consultable ; Ctrl+C pour quitter.")
            try:
                while True:      # l'état reste publié : la scène sait que le moteur est toujours là
                    await asyncio.sleep(2)
                    bus.publish("status", world.status_payload("ended", end_reason=world.stopped_reason, paused=False),
                                key="engine")
            except asyncio.CancelledError:
                pass
        await bridge.stop()
    bus.close()
    return run_id


async def serve(cfg: dict, ws: bool = True, ws_port: int = 8765, quiet: bool = False,
                llm: str = "scripted") -> None:
    """Le salon : attend qu'une partie soit lancée depuis le menu de Godot, la joue, puis en attend une autre."""
    from .engine import Engine

    bus = make_bus(cfg, group=f"filets-engine-{uuid.uuid4().hex[:8]}")
    engine = Engine(cfg, bus, quiet=quiet, default_llm=llm)
    bridge = None
    if ws:
        bridge = make_api(cfg, ws_port, bus.send_command, engine.catalog)
        await bridge.start()
        for topic in ("events", "indicators", "status"):
            bus.subscribe(topic, lambda e, t=topic: bridge.push(t, e))
        if not quiet:
            print(f"API FILETS : http://localhost:{bridge.port} (WebSocket /ws pour Godot, documentation /docs)")
    try:
        await engine.serve()
    finally:
        engine.close()
        if bridge:
            await bridge.stop()
        bus.close()


# ------------------------------------------------------------------ rejeu
def load_events(run_id: str, runs_dir: str = "runs") -> list[dict]:
    path = ROOT / runs_dir / run_id / "events.jsonl"
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


async def replay(run_id: str, cfg: dict, speed: float, ws: bool, ws_port: int, linger: bool) -> bool:
    """Rejoue un run à partir des seules données enregistrées : aucun appel LLM (E3)."""
    events = load_events(run_id, cfg["output"]["runs_dir"])
    bus = make_bus(cfg, group="filets-replay", consume_commands=False)
    local = isinstance(bus, LocalBus)
    bridge = None
    if ws:
        bridge = make_api(cfg, ws_port, lambda c: print("(rejeu : injection ignorée)", c), None)
        await bridge.start()
        bus.subscribe("events", lambda e: bridge.push("events", e))
        bus.subscribe("indicators", lambda e: bridge.push("indicators", e))
        print(f"Rejeu sur ws://localhost:{bridge.port}")
    pub = None
    if local:
        pub = IndicatorPublisher(bus, cfg["output"]["runs_dir"], cfg["scenario"]["quota_tolerance"])
        bus.subscribe("events", pub.on_event)
    t0 = time.monotonic()
    for ev in events:
        if speed > 0:
            due = ev["processed_at"] / speed
            wait = due - (time.monotonic() - t0)
            if wait > 0:
                await asyncio.sleep(min(wait, 2.0))
        stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")
        bus.publish("events", {**ev, "replay": True, "replayed_at": stamp}, key=ev.get("actor"))
    bus.flush()
    ok = True
    if pub:
        pub.close()
        ok = compare_indicators(run_id, cfg["output"]["runs_dir"])
    if bridge:
        if linger:
            print("Rejeu terminé. Ctrl+C pour quitter.")
            try:
                while True:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                pass
        await bridge.stop()
    bus.close()
    return ok


def compare_indicators(run_id: str, runs_dir: str = "runs") -> bool:
    d = ROOT / runs_dir / run_id
    a, b = d / "indicators.jsonl", d / "indicators_replay.jsonl"
    if not a.exists() or not b.exists():
        print("Comparaison impossible : journal d'indicateurs manquant.")
        return False
    va = [json.loads(x)["payload"]["values"] for x in a.read_text(encoding="utf-8").splitlines()]
    vb = [json.loads(x)["payload"]["values"] for x in b.read_text(encoding="utf-8").splitlines()]
    same = va == vb
    print(f"Rejeu : {len(vb)} indicateurs recalculés — {'IDENTIQUES' if same else 'DIFFÉRENTS'} à l'original "
          f"({len(va)}).")
    return same


def verify(run_id: str, cfg: dict) -> bool:
    events = load_events(run_id, cfg["output"]["runs_dir"])
    bad = [(e["event_id"], validate_event(e)) for e in events]
    bad = [b for b in bad if b[1]]
    eng = IndicatorEngine(cfg["scenario"]["quota_tolerance"])
    for e in events:
        eng.ingest(e)
    seqs = [e["seq"] for e in events]
    ordered = seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    sim_mono = all(events[i]["sim_time"] <= events[i + 1]["sim_time"] + 1e-9 for i in range(len(events) - 1))
    print(f"{len(events)} événements · non conformes : {len(bad)} · séquence ordonnée : {ordered} · "
          f"temps simulé monotone : {sim_mono} · violations temporelles : {eng.temporal_violations}")
    for eid, errs in bad[:5]:
        print("  ", eid, errs[:2])
    return not bad and ordered and eng.temporal_violations == 0


# ------------------------------------------------------------------ runs répétés
def batch(configs: list[str], runs: int, base_args, db_path: str | None) -> None:
    rows = []
    for cpath in configs:
        for k in range(runs):
            args = argparse.Namespace(**{**vars(base_args), "config": cpath})
            cfg = build_cfg(args)
            cfg["run"]["seed"] = int(cfg["run"]["seed"]) + k
            cfg["time"]["fast"] = True
            cfg["bus"]["kind"] = "local"
            rid = asyncio.run(run_once(cfg, quiet=True, run_id=new_run_id(cfg) + f"-{Path(cpath).stem}"))
            summ = json.loads((ROOT / cfg["output"]["runs_dir"] / rid / "summary.json").read_text())
            last = [json.loads(x) for x in (ROOT / cfg["output"]["runs_dir"] / rid / "indicators.jsonl")
                    .read_text(encoding="utf-8").splitlines()]
            seas = [x["payload"]["values"] for x in last if x["payload"]["trigger"] == "season_end"]
            mean_norm = statistics.mean(v["norm_index"] for v in seas) if seas else 0.0
            rows.append({"config": Path(cpath).stem, "run": rid, "final_stock_ratio": summ["final_stock"] / summ["capacity"],
                         "mean_norm_index": mean_norm, "llm_calls": summ["llm_calls"],
                         "tokens": summ["prompt_tokens"] + summ["completion_tokens"]})
            print(f"  {rows[-1]['config']:<16} {rid}  stock final {rows[-1]['final_stock_ratio']:.2f}  "
                  f"norme moy. {mean_norm:.2f}  appels {summ['llm_calls']}")
            if db_path:
                st = HistoryStore(ROOT / db_path)
                st.ingest_run_dir(ROOT / cfg["output"]["runs_dir"] / rid)
                st.close()
    print("\nconfiguration       n   stock final (moy ± ét)   indice de norme (moy ± ét)   appels LLM moy.")
    for c in dict.fromkeys(r["config"] for r in rows):
        rs = [r for r in rows if r["config"] == c]
        def ms(key):
            v = [r[key] for r in rs]
            return statistics.mean(v), (statistics.stdev(v) if len(v) > 1 else 0.0)
        s, n = ms("final_stock_ratio"), ms("mean_norm_index")
        print(f"{c:<18} {len(rs):>2}   {s[0]:.2f} ± {s[1]:.2f}                {n[0]:.2f} ± {n[1]:.2f}"
              f"                   {statistics.mean(r['llm_calls'] for r in rs):.0f}")


def sql_blocks(text: str) -> list[tuple[str, str]]:
    """Les requêtes d'un fichier .sql : (titre tiré du commentaire, requête)."""
    out = []
    for block in text.split(";"):
        lines = [l for l in block.splitlines() if l.strip()]
        title = next((l.strip("- ").strip() for l in lines if l.startswith("--")), "")
        sql = "\n".join(l for l in lines if not l.strip().startswith("--"))
        if sql.strip():
            out.append((title, sql))
    return out


def print_table(title: str, columns: list[str], rows) -> None:
    print(f"\n## {title}")
    print(" | ".join(columns))
    for row in list(rows)[:30]:
        print(" | ".join("" if v is None else str(v)[:60] for v in row))


async def ingest_pg(dsn: str, runs_dir: Path, ids: list[str]) -> None:
    from .pgstore import PgHistoryStore

    st = PgHistoryStore(dsn)
    await st.open()
    try:
        for rid in ids:
            print(rid, await st.ingest_run_dir(runs_dir / rid), "événements")
    finally:
        await st.close()


async def query_pg(dsn: str, blocks: list[tuple[str, str]]) -> None:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        for title, sql in blocks:
            stmt = await conn.prepare(sql)
            print_table(title, [a.name for a in stmt.get_attributes()], [tuple(r) for r in await stmt.fetch()])
    finally:
        await conn.close()


def retrieval_sample(run_id: str, cfg: dict, n: int, seed: int = 0) -> Path:
    """F2 : échantillon de décisions LLM avec ce qui a été retrouvé, à annoter (pertinent = 1/0).
    Si le fichier annoté existe déjà, calcule la précision par source."""
    import csv
    import random
    out = ROOT / cfg["output"]["runs_dir"] / run_id / "retrieval_eval.csv"
    if out.exists():
        rows = list(csv.DictReader(open(out, encoding="utf-8")))
        done = [r for r in rows if r["pertinent"].strip() in ("0", "1")]
        if done:
            by = {}
            for r in done:
                by.setdefault(r["source"], []).append(int(r["pertinent"]))
            print(f"{len(done)}/{len(rows)} lignes annotées")
            for src, v in sorted(by.items()):
                print(f"  précision {src:<8} {sum(v) / len(v):.2f}  (n={len(v)})")
            return out
    decisions = [e for e in load_events(run_id, cfg["output"]["runs_dir"])
                 if e["type"] == "decision" and e["payload"]["agent_kind"] == "llm"]
    random.Random(seed).shuffle(decisions)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["decision_event_id", "agent", "moment", "type", "justification", "rang", "source", "score",
                    "extrait", "pertinent"])
        for d in decisions[:n]:
            p = d["payload"]
            for i, r in enumerate(p["retrieved"]):
                w.writerow([d["event_id"], p["agent"], d["sim_label"], p["decision_type"], p["justification"][:200],
                            i + 1, r["source"], r["score"], r.get("text", ""), ""])
    print(f"Échantillon écrit dans {out} : remplissez la colonne « pertinent » (1/0) puis relancez la commande.")
    return out


def export_schemas():
    out = ROOT / "schemas"
    out.mkdir(exist_ok=True)
    (out / "envelope.v1.json").write_text(json.dumps(ENVELOPE, indent=2, ensure_ascii=False))
    (out / "command.v1.json").write_text(json.dumps(COMMAND, indent=2, ensure_ascii=False))
    (out / "status.v1.json").write_text(json.dumps(STATUS, indent=2, ensure_ascii=False))
    for name, sch in PAYLOADS.items():
        (out / f"{name}.v{SCHEMA_VERSION}.json").write_text(json.dumps(sch, indent=2, ensure_ascii=False))
    print(f"{len(PAYLOADS) + 3} schémas écrits dans {out}")


def main(argv=None):
    # Sortie redirigée (fichier, tube) : Windows l'encode en cp1252, qui ignore « ✔ » ou « ⚡ ». Un caractère
    # d'affichage ne doit jamais faire échouer une partie : on le remplace plutôt que de lever une exception.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="filets")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--config", default="config/default.yaml")
        p.add_argument("--set", action="append", help="surcharge, ex. --set scenario.communication=none")
        p.add_argument("--bus", choices=["local", "kafka"])

    sv = sub.add_parser("serve", help="salon : la partie est lancée depuis le menu de Godot")
    common(sv)
    sv.add_argument("--agents", type=int, help="nombre de pêcheurs de la composition de base proposée par le menu")
    sv.add_argument("--mode", choices=["sync", "async"], help="mode proposé par défaut dans le menu")
    sv.add_argument("--seasons", type=int, help="nombre de saisons proposé par défaut dans le menu")
    sv.add_argument("--seed", type=int)
    sv.add_argument("--fast", action="store_true")
    from .catalog import LLM_OPTIONS
    sv.add_argument("--llm", choices=[o["id"] for o in LLM_OPTIONS], default="scripted",
                    help="moteur d'IA présélectionné dans le menu")
    sv.add_argument("--no-ws", action="store_true", help="ne pas ouvrir le pont WebSocket (avec Kafka, c'est le service bridge)")
    sv.add_argument("--ws-port", type=int, default=8765)

    r = sub.add_parser("run")
    common(r)
    r.add_argument("--agents", type=int)
    r.add_argument("--mode", choices=["sync", "async"])
    r.add_argument("--seasons", type=int)
    r.add_argument("--seed", type=int)
    r.add_argument("--fast", action="store_true")
    r.add_argument("--ws", action="store_true", help="démarrer le pont WebSocket pour Godot")
    r.add_argument("--ws-port", type=int, default=8765)
    r.add_argument("--no-linger", action="store_true")
    r.add_argument("--run-id")

    rp = sub.add_parser("replay")
    common(rp)
    rp.add_argument("run_id")
    rp.add_argument("--speed", type=float, default=1.0, help="facteur d'accélération (0 = sans attente)")
    rp.add_argument("--ws", action="store_true")
    rp.add_argument("--ws-port", type=int, default=8765)
    rp.add_argument("--no-linger", action="store_true")

    v = sub.add_parser("verify")
    common(v)
    v.add_argument("run_id")

    b = sub.add_parser("batch")
    b.add_argument("--config", action="append", required=True)
    b.add_argument("--runs", type=int, default=5)
    b.add_argument("--set", action="append")
    b.add_argument("--agents", type=int)
    b.add_argument("--mode", choices=["sync", "async"])
    b.add_argument("--seasons", type=int)
    b.add_argument("--db", default="data/history.db")

    ing = sub.add_parser("ingest")
    ing.add_argument("run_ids", nargs="*")
    ing.add_argument("--db", default="data/history.db")
    ing.add_argument("--pg", nargs="?", const="", default=None,
                     help="dans PostgreSQL (adresse ; sans adresse : FILETS_PG_DSN ou la configuration)")

    sub.add_parser("schemas")

    qy = sub.add_parser("query", help="exécuter les requêtes d'un fichier .sql sur l'historique")
    qy.add_argument("sql_file", nargs="?", default="analysis/queries.sql")
    qy.add_argument("--db", default="data/history.db")
    qy.add_argument("--pg", nargs="?", const="", default=None,
                    help="sur PostgreSQL (fichier conseillé : analysis/queries_pg.sql)")

    rv = sub.add_parser("retrieval", help="évaluer la qualité de la récupération (F2)")
    common(rv)
    rv.add_argument("run_id")
    rv.add_argument("--sample", type=int, default=20)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.cmd == "serve":
        cfg = build_cfg(args)
        ws = not args.no_ws and cfg["bus"]["kind"] == "local"      # avec Kafka, le pont est le service `bridge`
        try:
            asyncio.run(serve(cfg, ws=ws, ws_port=args.ws_port, llm=args.llm))
        except KeyboardInterrupt:
            print("\nSalon fermé.")
    elif args.cmd == "run":
        cfg = build_cfg(args)
        try:
            asyncio.run(run_once(cfg, ws=args.ws, ws_port=args.ws_port, linger=args.ws and not args.no_linger,
                                 run_id=args.run_id))
        except KeyboardInterrupt:
            pass
    elif args.cmd == "replay":
        cfg = build_cfg(args)
        try:
            ok = asyncio.run(replay(args.run_id, cfg, args.speed, args.ws, args.ws_port,
                                    args.ws and not args.no_linger))
        except KeyboardInterrupt:
            ok = True
        sys.exit(0 if ok else 1)
    elif args.cmd == "verify":
        sys.exit(0 if verify(args.run_id, build_cfg(args)) else 1)
    elif args.cmd == "batch":
        args.config_list = args.config
        base = argparse.Namespace(set=args.set, agents=args.agents, mode=args.mode, seasons=args.seasons,
                                  seed=None, bus=None, fast=True, config=None)
        batch(args.config, args.runs, base, args.db)
    elif args.cmd == "ingest":
        runs_dir = ROOT / "runs"
        ids = args.run_ids or sorted(p.name for p in runs_dir.iterdir() if (p / "events.jsonl").exists())
        if args.pg is not None:
            asyncio.run(ingest_pg(args.pg or postgres_dsn(load_config(None)), runs_dir, ids))
        else:
            st = HistoryStore(ROOT / args.db)
            for rid in ids:
                print(rid, st.ingest_run_dir(runs_dir / rid), "événements")
            st.close()
    elif args.cmd == "schemas":
        export_schemas()
    elif args.cmd == "query":
        blocks = sql_blocks((ROOT / args.sql_file).read_text(encoding="utf-8"))
        if args.pg is not None:
            asyncio.run(query_pg(args.pg or postgres_dsn(load_config(None)), blocks))
        else:
            import sqlite3
            db = sqlite3.connect(str(ROOT / args.db))
            for title, sql in blocks:
                cur = db.execute(sql)
                print_table(title, [d[0] for d in cur.description], cur.fetchall())
    elif args.cmd == "retrieval":
        retrieval_sample(args.run_id, build_cfg(args), args.sample)


if __name__ == "__main__":
    main()
