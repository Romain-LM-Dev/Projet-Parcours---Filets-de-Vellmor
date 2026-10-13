"""Chargement de la configuration : fichier YAML, héritage (`extends`) et surcharges en ligne de commande."""
from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: str | Path | None = None, overrides: dict | None = None) -> dict:
    path = Path(path) if path else ROOT / "config" / "default.yaml"
    if not path.is_absolute() and not path.exists():
        path = ROOT / path
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    parent = cfg.pop("extends", None)
    if parent:
        cfg = deep_merge(load_config(path.parent / parent), cfg)
    if overrides:
        cfg = deep_merge(cfg, overrides)
    return normalize(cfg)


def set_dotted(d: dict, dotted: str, value: Any) -> None:
    """`--set time.mode=sync` → d['time']['mode'] = 'sync' (valeur interprétée en YAML)."""
    keys = dotted.split(".")
    cur = d
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = yaml.safe_load(value) if isinstance(value, str) else value


def normalize(cfg: dict) -> dict:
    lake = cfg["lake"]
    pop = cfg["population"]
    if pop.get("custom"):
        # population choisie par le joueur : le nombre de pêcheurs est celui de la liste
        from .profiles import validate_custom
        errs = validate_custom(pop["custom"])
        if errs:
            raise ValueError("population.custom invalide : " + " ; ".join(errs[:3]))
        pop["fishers"] = len(pop["custom"])
        pop["rule_fraction"] = sum(f.get("kind", "llm") == "rule" for f in pop["custom"]) / len(pop["custom"])
    n = int(pop["fishers"])
    if n < 1:
        raise ValueError("population.fishers doit être >= 1")
    if lake.get("capacity") in (None, "auto"):
        lake["capacity_resolved"] = float(lake["capacity_per_fisher"]) * n
    else:
        lake["capacity_resolved"] = float(lake["capacity"])
    t = cfg["time"]
    if t["mode"] not in ("sync", "async"):
        raise ValueError("time.mode doit valoir sync ou async")
    sp = t.get("idle_speedup", 20)
    t["idle_speedup"] = math.inf if str(sp).lower() in ("inf", ".inf", "infinity") else float(sp)
    if cfg["scenario"]["communication"] not in ("valley", "hamlet", "none"):
        raise ValueError("scenario.communication doit valoir valley, hamlet ou none")
    return cfg


def sustainable_yield(cfg: dict) -> float:
    """Rendement maximal durable de la croissance logistique : r·K/4 par saison."""
    return cfg["lake"]["growth_rate"] * cfg["lake"]["capacity_resolved"] / 4.0
