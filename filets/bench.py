"""Banc de comparaison du modèle de décision (tev1) et du grand modèle de langage, sur des invites réelles.

`python -m filets bench-reflexe <run_id>` rejoue les appels « système 1 » d'une partie passée (`runs/<id>/s1_calls.jsonl`, écrit par
le routeur quand le palier `reflexe` répond) sur tev1 (question typée) et sur le grand modèle (même état, même schéma), puis mesure
l'accord des décisions, les réponses illisibles et le temps. Il appelle de VRAIS modèles : il refuse de tourner si une partie est
en cours (le port du salon répond), pour ne pas disputer la carte graphique.
"""
from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

from .llm import OpenAICompatClient, SystemOneClient, extract_json, to_number


def server_running(port: int = 8765, host: str = "127.0.0.1") -> bool:
    """Une partie tourne-t-elle (le salon répond sur son port) ?"""
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def norm(purpose: str, key: str, v):
    """Une décision ramenée à une forme comparable : prise en tonnes, oui/non, identifiant de choix, pas de confiance."""
    n = to_number(v)
    if purpose == "catch" or purpose == "debrief":
        return n
    if n is not None:                                  # tev1 donne la probabilité du oui ; le langage, « oui » / « non »
        return "oui" if n >= 0.5 else "non"
    return str(v).strip().lower() if v is not None else None


def same(purpose: str, a, b) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= 0.5 if purpose == "catch" else a == b


def load_calls(path: Path, limit: int = 0) -> list[dict]:
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return rows[:limit] if limit else rows


async def bench(cfg: dict, rows: list[dict]) -> dict:
    tiers, provs = cfg["llm"]["tiers"], cfg["llm"]["providers"]
    t1, big = tiers["reflexe"], tiers["grand"]
    p1, pb = provs[t1["provider"]], provs[big["provider"]]
    c1 = SystemOneClient(t1["provider"], p1["base_url"], cfg["llm"], p1.get("timeout_s"))
    cb = OpenAICompatClient(big["provider"], pb["base_url"], pb.get("api_key_env"), pb.get("rpm", 0), cfg["llm"],
                            pb.get("timeout_s"), 0, bool(pb.get("json_schema", False)), bool(pb.get("seed", False)))
    out = {"decisions": 0, "agree": 0, "unreadable": {"reflexe": 0, "grand": 0}, "seconds": {"reflexe": 0.0, "grand": 0.0}}
    try:
        for r in rows:
            r1 = await c1.complete(t1["model"], [], {"system_one": r["system_one"]}, "reflexe")
            hint = {"purpose": r["purpose"], "schema": r["schema"], "max_tokens": r["max_tokens"]}
            rb = await cb.complete(big["model"], r["messages"], hint, "grand")
            d1, db = (extract_json(x.text) if x.status == "ok" else None for x in (r1, rb))
            out["seconds"]["reflexe"] += r1.latency_s
            out["seconds"]["grand"] += rb.latency_s
            for who, d in (("reflexe", d1), ("grand", db)):
                out["unreadable"][who] += d is None
            for key in (d1 or {}):
                if key.startswith("_") or db is None:
                    continue
                out["decisions"] += 1
                out["agree"] += same(r["purpose"], norm(r["purpose"], key, d1[key]), norm(r["purpose"], key, db.get(key)))
    finally:
        await c1.http.aclose()
        await cb.http.aclose()
    return out


def run(run_id: str, cfg: dict, runs_dir: Path, limit: int = 0, port: int = 8765) -> int:
    if server_running(port):
        print(f"Une partie tourne (le port {port} répond) : le banc attend qu'elle soit finie pour ne pas disputer la carte graphique.")
        return 2
    path = runs_dir / run_id / "s1_calls.jsonl"
    if not path.exists():
        print(f"{path} n'existe pas : seules les parties lancées avec un palier `reflexe` (ollama_open) l'écrivent.")
        return 1
    rows = load_calls(path, limit)
    res = asyncio.run(bench(cfg, rows))
    n = max(1, res["decisions"])
    print(f"{len(rows)} appels rejoués, {res['decisions']} décisions comparées : accord {100 * res['agree'] / n:.0f} %")
    print(f"réponses illisibles : tev1 {res['unreadable']['reflexe']}, grand modèle {res['unreadable']['grand']}")
    print(f"temps total : tev1 {res['seconds']['reflexe']:.1f} s, grand modèle {res['seconds']['grand']:.1f} s")
    return 0
