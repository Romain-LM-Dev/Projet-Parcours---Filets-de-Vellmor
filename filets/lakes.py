"""Les lacs de la vallée : combien, lesquels, ce que chacun contient, quels villages en vivent ; et la vallée tirée au hasard.

Un lac se décrit par son nom, sa capacité (tonnes de poisson quand il est plein), la part pleine au départ (`stock_ratio`), son taux de
repeuplement et les villages qui y pêchent. Sans description (`lake.lakes`), la configuration en fait `lake.count` (un par défaut) :
les villages se partagent en blocs qui se suivent, et la capacité de chacun est `lake.capacity_per_fisher` par pêcheur, comme avant.
"""
from __future__ import annotations

import random

LAKE_NAMES = ["Vellmor", "Orsane", "Brémol", "Ysaude"]
MAX_LAKES = len(LAKE_NAMES)


# Où sont les lacs sur la carte (centres normalisés, comme `LAKE_BOXES` de world_view.gd : un test les compare), selon leur nombre :
# la distance entre deux lacs est celle de leurs centres.
LAKE_CENTERS = {
    1: [(0.5, 0.535)],
    2: [(0.31, 0.56), (0.69, 0.56)],
    3: [(0.29, 0.42), (0.71, 0.42), (0.5, 0.69)],
    4: [(0.29, 0.42), (0.71, 0.42), (0.29, 0.72), (0.71, 0.72)],
}


def lake_distance(n_lakes: int, i: int, j: int, days_per_map: float) -> float:
    """Jours de route, à l'aller, du lac `i` au lac `j` : leur distance sur la carte, `days_per_map` jours pour la traverser."""
    (x1, y1), (x2, y2) = LAKE_CENTERS[max(1, min(n_lakes, MAX_LAKES))][i], LAKE_CENTERS[max(1, min(n_lakes, MAX_LAKES))][j]
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5 * days_per_map


def lake_label(name: str) -> str:
    return f"Lac d'{name}" if name[:1] in "AEIOUYÉÈÊ" else f"Lac de {name}"


def split_villages(hamlets: list[str], n: int) -> list[list[str]]:
    """Les villages d'un même lac se suivent dans l'ordre de la vallée : `n` blocs, à un village près."""
    size, extra = divmod(len(hamlets), n)
    out, i = [], 0
    for k in range(n):
        step = size + (1 if k < extra else 0)
        out.append(hamlets[i:i + step])
        i += step
    return out


def _number(v, what: str, lo: float, hi: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise ValueError(f"{what} doit être un nombre entre {lo:g} et {hi:g}")
    return float(v)


def resolve_lakes(L: dict, hamlets: list[str], fishers: dict[str, int]) -> list[dict]:
    """Les lacs de la partie, prêts à créer : [{name, label, capacity, initial_ratio, growth_rate, villages}]. `fishers` : combien de
    pêcheurs par village. Lève `ValueError` (en français) si la description est incohérente."""
    specs = L.get("lakes")
    if specs is not None and (not isinstance(specs, list) or not specs or not all(isinstance(s, dict) for s in specs)):
        raise ValueError("lake.lakes doit être une liste de lacs (au moins un)")
    count = len(specs) if specs else int(L.get("count", 1) or 1)
    if not 1 <= count <= MAX_LAKES:
        raise ValueError(f"le nombre de lacs doit être compris entre 1 et {MAX_LAKES}")
    if count > len(hamlets):
        raise ValueError("il faut au moins un village par lac")
    specs = specs or [{} for _ in range(count)]
    names = [str(s.get("name") or LAKE_NAMES[i]) for i, s in enumerate(specs)]
    if len(set(names)) != len(names):
        raise ValueError("deux lacs ne peuvent pas porter le même nom")
    if any("villages" in s for s in specs):
        listed = [v for s in specs for v in s.get("villages") or []]
        if sorted(listed) != sorted(hamlets):
            raise ValueError("chaque village doit être rattaché à un lac, et à un seul")
        blocks = [list(s.get("villages") or []) for s in specs]
    else:
        blocks = split_villages(hamlets, count)
    if any(not b for b in blocks):
        raise ValueError("chaque lac doit avoir au moins un village")
    out = []
    for i, (s, block) in enumerate(zip(specs, blocks)):
        n = sum(fishers.get(v, 0) for v in block)
        cap = s.get("capacity")
        if cap in (None, "auto"):
            glob = L.get("capacity")
            if glob not in (None, "auto"):                # une capacité totale choisie : partagée au prorata des pêcheurs
                total = sum(fishers.values()) or 1
                cap = float(glob) * n / total
            else:                                         # 12,5 t par pêcheur, plus ou moins riche (`richness`)
                cap = float(L["capacity_per_fisher"]) * float(s.get("richness", 1.0)) * n
        cap = _number(cap, f"la capacité de {names[i]}", 1, 100000)
        out.append({"name": names[i], "label": lake_label(names[i]), "capacity": round(cap, 3),
                    "initial_ratio": _number(s.get("stock_ratio", L["initial_ratio"]), f"le stock de départ de {names[i]}", 0.01, 1.0),
                    "growth_rate": _number(s.get("growth_rate", L["growth_rate"]), f"le repeuplement de {names[i]}", 0.05, 2.0),
                    "villages": block})
    return out


def random_valley(seed: int) -> dict:
    """Une vallée tirée de la graine seule : le nombre de villages, de pêcheurs, de lacs et leur richesse en poisson (par pêcheur,
    et part pleine au départ), leur repeuplement, la flotte (la taille des bateaux se tire ensuite pêcheur par pêcheur) et le
    nombre de patrouilles. La même graine donne toujours la même vallée."""
    from .catalog import FLEETS

    r = random.Random(f"{seed}|valley")
    villages = r.randint(3, 6)
    lakes = r.randint(1, min(3, villages))
    fishers = r.randint(2 * villages, min(24, 5 * villages))
    return {
        "villages": villages, "fishers": fishers, "fleet": r.choice([f["id"] for f in FLEETS]),
        "lakes": [{"name": LAKE_NAMES[i], "richness": round(r.uniform(0.6, 1.4), 2), "stock_ratio": round(r.uniform(0.6, 1.0), 2),
                   "growth_rate": round(r.uniform(0.6, 1.4), 2)} for i in range(lakes)],
        "patrols": r.choice([0, 1, 1, 2]),
    }
