"""Chargement de la configuration : fichier YAML, héritage (`extends`) et surcharges en ligne de commande."""
from __future__ import annotations

import copy
import logging
import math
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)
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


def apply_random_valley(cfg: dict) -> None:
    """`population.random` : la vallée est tirée de la graine seule (voir `lakes.random_valley`). Sans effet sur une composition
    choisie à la main. Appliquée deux fois, elle donne la même vallée."""
    from .catalog import fleet_mix
    from .lakes import random_valley

    pop, lake = cfg["population"], cfg["lake"]
    v = random_valley(int(cfg["run"]["seed"]))
    pop["villages"], pop["fishers"], pop["boat_mix"] = v["villages"], v["fishers"], fleet_mix(cfg, v["fleet"])
    lake["lakes"] = v["lakes"]
    patrol = cfg["scenario"].setdefault("patrol", {})
    patrol["count"], patrol["enabled"] = v["patrols"], v["patrols"] > 0
    cfg.setdefault("climate", {})["event_rate"] = v["event_rate"]


def normalize(cfg: dict) -> dict:
    lake = cfg["lake"]
    pop = cfg["population"]
    if pop.get("random") and not pop.get("custom"):
        apply_random_valley(cfg)
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
    if not pop.get("custom") and not 1 <= int(pop.get("villages", 4)) <= 8:
        raise ValueError("population.villages doit être compris entre 1 et 8 (la carte n'en place pas davantage)")
    count = len(lake["lakes"]) if lake.get("lakes") else int(lake.get("count") or 1)
    if not 1 <= count <= 4:
        raise ValueError("le nombre de lacs doit être compris entre 1 et 4")
    if lake.get("lakes"):
        # (le total exact vient de `lakes.resolve_lakes`, une fois les villages connus ; ceci en est l'estimation)
        share = n / len(lake["lakes"])
        lake["capacity_resolved"] = sum(
            float(s["capacity"]) if s.get("capacity") not in (None, "auto")
            else float(lake["capacity_per_fisher"]) * float(s.get("richness", 1.0)) * share for s in lake["lakes"])
    elif lake.get("capacity") in (None, "auto"):
        lake["capacity_resolved"] = float(lake["capacity_per_fisher"]) * n
    else:
        lake["capacity_resolved"] = float(lake["capacity"])
    patrol = cfg["scenario"].get("patrol") or {}
    if not isinstance(patrol.get("count", 1), int) or isinstance(patrol.get("count", 1), bool) or not 0 <= patrol.get("count", 1) <= 4:
        raise ValueError("le nombre de patrouilles doit être un entier entre 0 et 4")
    for key, hi in (("travel_days", 10.0), ("travel_cost", 1000.0)):
        v = cfg["economy"].get(key, 0.0)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= hi:
            raise ValueError(f"economy.{key} doit être un nombre entre 0 et {hi:g}")
    hold = cfg["economy"].get("hold_fraction", 0.5)
    if isinstance(hold, bool) or not isinstance(hold, (int, float)) or not 0.05 <= hold <= 1.0:
        raise ValueError("economy.hold_fraction doit être un nombre entre 0,05 et 1")
    t = cfg["time"]
    if "mode" in t:        # l'ancien choix synchrone / asynchrone : il n'y a plus qu'un mode de temps (docs/temps.md)
        log.warning("time.mode (%s) est ignoré : il n'y a plus qu'un seul mode de temps", t.pop("mode"))
    if "async_offset_days" in t:      # ancien nom de time.departure_spread_days
        t["departure_spread_days"] = t.pop("async_offset_days")
    for gone in ("wait_for_ai", "ballot_lead_days", "assembly_turn_gap_days"):
        t.pop(gone, None)
    lo, hi = t.get("departure_spread_days", [0.0, 4.0])
    if not 0 <= lo <= hi:
        raise ValueError("time.departure_spread_days doit être [min, max] avec 0 <= min <= max")
    sp = t.get("idle_speedup", 20)
    t["idle_speedup"] = math.inf if str(sp).lower() in ("inf", ".inf", "infinity") else float(sp)
    if cfg["scenario"]["communication"] not in ("valley", "hamlet", "none"):
        raise ValueError("scenario.communication doit valoir valley, hamlet ou none")
    if cfg["scenario"].get("council", "delegates") not in ("delegates", "all"):
        raise ValueError("scenario.council doit valoir delegates ou all")
    return cfg


def sustainable_yield(cfg: dict) -> float:
    """Rendement maximal durable de la croissance logistique : r·K/4 par saison."""
    return cfg["lake"]["growth_rate"] * cfg["lake"]["capacity_resolved"] / 4.0
