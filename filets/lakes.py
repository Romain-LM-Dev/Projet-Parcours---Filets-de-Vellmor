"""Les lacs de la vallée : combien, lesquels, ce que chacun contient, quels villages en vivent ; et la vallée tirée au hasard.

Un lac se décrit par son nom, sa capacité (tonnes de poisson quand il est plein), la part pleine au départ (`stock_ratio`), son taux de
repeuplement et les villages qui y pêchent. Sans description (`lake.lakes`), la configuration en fait `lake.count` (un par défaut) :
les villages se partagent en blocs qui se suivent, et la capacité de chacun est `lake.capacity_per_fisher` par pêcheur, comme avant.
"""
from __future__ import annotations

import math
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


# Les rayons des lacs dans le sol (ceux de `LAKE_BOXES` × `ISO_LAKE_K` dans world_view.gd) : le gabarit autour duquel la maille
# du lac se dessine.
LAKE_RADII = {
    1: [(0.348, 0.294)],
    2: [(0.168, 0.2352), (0.168, 0.2352)],
    3: [(0.165, 0.143), (0.165, 0.143), (0.209, 0.1265)],
    4: [(0.165, 0.1265)] * 4,
}
ISO_LAKE_K = {1: 1.2, 2: 1.12, 3: 1.1, 4: 1.1}
# Où sont les villages (comme `SLOTS`, `LAYOUTS` et `layout` de world_view.gd) : un seul lac, selon le nombre de villages ; plusieurs,
# sur la rive extérieure de leur lac.
SLOTS = {"NW": (0.14, 0.25), "NE": (0.86, 0.25), "SE": (0.86, 0.84), "SW": (0.14, 0.84), "W": (0.08, 0.52), "E": (0.92, 0.52),
         "BL": (0.30, 0.89), "BR": (0.70, 0.89)}
LAYOUTS = {1: ["SW"], 2: ["NW", "SE"], 3: ["NW", "E", "SW"], 4: ["NW", "NE", "SE", "SW"], 5: ["NW", "NE", "SE", "SW", "W"],
           6: ["NW", "NE", "SE", "SW", "W", "E"], 7: ["NW", "NE", "SE", "SW", "W", "E", "BL"],
           8: ["NW", "NE", "SE", "SW", "W", "E", "BL", "BR"]}
_PLAN_BOXES = {2: (0.15, 0.21), 3: [(0.15, 0.13), (0.15, 0.13), (0.19, 0.115)], 4: (0.15, 0.115)}

# La maille des lacs : la vallée (le carré [0,1]² du sol) en GRID × GRID parcelles, à la taille 1 (voir `grid_of` : une vallée plus
# grande a plus de parcelles, de la même taille à l'écran). Celle des maisons (40) et celle des
# personnages (120) ne vivent que dans la carte (world_view.gd) : elles ne changent rien au poisson.
GRID = 30


def grid_of(size: float) -> int:
    """La maille des lacs d'une vallée de cette taille : les parcelles gardent leur taille à l'écran."""
    return max(GRID, round(GRID * size))


def world_size(villages: int, lakes: int) -> float:
    """La taille de la vallée, en largeurs de carte : au zoom 1, on en voit une largeur (il faut la parcourir) ; elle grandit avec
    les villages et les lacs, pour garder de l'espace entre eux. Maisons et personnages, eux, gardent leur taille."""
    return round(min(2.6, 1.5 + 0.1 * max(0, villages - 4) + 0.15 * (max(1, lakes) - 1)), 2)


def village_positions(hamlets: list[str], lake_index: dict[str, int], n_lakes: int,
                      size: float = 1.0) -> dict[str, tuple[float, float]]:
    """Où est chaque village dans le sol (normalisé) : `layout` de world_view.gd à la taille 1, que la carte reprend telle quelle.
    Dans une vallée plus grande (`size`), les lacs gardent leur taille à l'écran : ils sont plus petits dans le sol, et les villages
    s'en rapprochent un peu, avec plus de terre entre eux."""
    if n_lakes <= 1:
        slots = LAYOUTS[max(1, min(len(hamlets), 8))]
        (cx, cy), k = LAKE_CENTERS[1][0], 0.45 + 0.55 / size
        return {h: (round(cx + (SLOTS[slots[min(i, len(slots) - 1)]][0] - cx) * k, 4),
                    round(cy + (SLOTS[slots[min(i, len(slots) - 1)]][1] - cy) * k, 4)) for i, h in enumerate(hamlets)}
    out, by_lake = {}, {}
    for h in hamlets:
        by_lake.setdefault(max(0, min(lake_index.get(h, 0), n_lakes - 1)), []).append(h)
    n = max(1, min(n_lakes, MAX_LAKES))

    def free(x: float, y: float) -> bool:
        """Sur le sol, loin de la maison de l'ancien, des lacs (leur gabarit, rive ondulée comprise) et des autres villages."""
        if not (0.1 <= x <= 0.9 and 0.2 <= y <= 0.9) or math.hypot(x - 0.5, y - 0.115) < 0.24 / size:
            return False
        if any(math.hypot((x - c[0]) * size / r[0], (y - c[1]) * size / r[1]) < 1.4 for c, r in zip(LAKE_CENTERS[n], LAKE_RADII[n])):
            return False
        return all(math.hypot(x - u, y - v) > 0.13 for u, v in out.values())

    for k, hs in by_lake.items():
        cx, cy = LAKE_CENTERS[n][k]
        rb = _PLAN_BOXES[n][k] if isinstance(_PLAN_BOXES[n], list) else _PLAN_BOXES[n]
        rx, ry = rb[0] * ISO_LAKE_K[n] / size, rb[1] * ISO_LAKE_K[n] / size
        outward = math.atan2(cy - 0.55, cx - 0.5) if abs(cx - 0.5) + abs(cy - 0.55) > 0.05 else math.pi / 2
        step = min(2 * math.pi / len(hs), 2.0 if len(hs) == 2 else 1.65 if len(hs) == 3 else 1.3)
        for i, h in enumerate(hs):
            want = outward + (i - (len(hs) - 1) / 2) * step
            # la place voulue sur sa rive, ou la plus proche qui soit libre (un village ne se pose jamais dans l'eau)
            spots = [(abs(d), cx + math.cos(want + d) * rx * f, cy + math.sin(want + d) * ry * f)
                     for f in (1.55, 1.75, 1.95) for d in (0.1 * j * s for j in range(32) for s in (1, -1))]
            ok = [sp for sp in spots if free(sp[1], sp[2])]
            _, x, y = min(ok) if ok else spots[0]
            out[h] = (round(x, 4), round(y, 4))
    return out


def _value_noise(rng: random.Random, every: int, grid: int = GRID):
    """Un bruit doux sur la maille : des valeurs tirées tous les `every` parcelles, interpolées entre elles (des coins plus
    poissonneux que d'autres, pas une parcelle au hasard de sa voisine)."""
    n = grid // every + 2
    lattice = [[rng.random() for _ in range(n)] for _ in range(n)]

    def at(i: int, j: int) -> float:
        x, y = i / every, j / every
        x0, y0 = int(x), int(y)
        fx, fy = x - x0, y - y0
        fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        a = lattice[x0][y0] + (lattice[x0 + 1][y0] - lattice[x0][y0]) * fx
        b = lattice[x0][y0 + 1] + (lattice[x0 + 1][y0 + 1] - lattice[x0][y0 + 1]) * fx
        return a + (b - a) * fy
    return at


def lake_parcels(n_lakes: int, seed: int, size: float = 1.0) -> list[list[dict]]:
    """Les parcelles de chaque lac, tirées de la graine : [{i, j, depth, share, luck}] par lac. Un lac est la tache de la maille
    autour de son centre, au bord ondulé (quelques harmoniques tirées au hasard : il a l'air d'un lac, jamais d'une ellipse) ;
    `depth` : à combien de parcelles de la rive ; `share` : la part du poisson du lac qui y vit quand il est plein (plus au fond,
    plus de poisson) ; `luck` : la chance d'y pêcher (des coins plus ou moins bons, en moyenne 1 sur le lac)."""
    n = max(1, min(n_lakes, MAX_LAKES))
    taken: set[tuple[int, int]] = set()
    out = []
    G = grid_of(size)                      # (`size` : une vallée plus grande, des lacs de la même taille à l'écran)
    for k, ((cx, cy), (rx, ry)) in enumerate(zip(LAKE_CENTERS[n], LAKE_RADII[n])):
        rx, ry = rx / size, ry / size
        rng = random.Random(f"{seed}|lake-shape|{n}|{k}")
        waves = [(m, rng.uniform(0.02, 0.055), rng.uniform(0, 2 * math.pi)) for m in (2, 3, 4, 5)]
        cells = set()
        for i in range(G):
            for j in range(G):
                dx, dy = ((i + 0.5) / G - cx) / rx, ((j + 0.5) / G - cy) / ry
                th = math.atan2(dy, dx)
                if math.hypot(dx, dy) < 1 + sum(a * math.sin(m * th + ph) for m, a, ph in waves) and (i, j) not in taken:
                    cells.add((i, j))
        cells = _largest_patch(cells)
        taken |= cells
        # la profondeur : à combien de parcelles de la terre (parcours en largeur depuis la rive)
        depth = {c: 0 for c in cells if any((c[0] + di, c[1] + dj) not in cells for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)))}
        frontier = list(depth)
        while frontier:
            nxt = []
            for (i, j) in frontier:
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    c = (i + di, j + dj)
                    if c in cells and c not in depth:
                        depth[c] = depth[(i, j)] + 1
                        nxt.append(c)
            frontier = nxt
        fish_noise, luck_noise = _value_noise(rng, 5, G), _value_noise(rng, 4, G)
        parcels = [{"i": i, "j": j, "depth": depth[(i, j)], "share": (1.0 + depth[(i, j)]) * (0.75 + 0.5 * fish_noise(i, j)),
                    "luck": 0.7 + 0.6 * luck_noise(i, j)} for (i, j) in sorted(cells)]
        total = sum(p["share"] for p in parcels)
        for p in parcels:
            p["share"] /= total
        mean_luck = sum(p["share"] * p["luck"] for p in parcels)
        for p in parcels:
            p["luck"] = round(p["luck"] / mean_luck, 3)
        out.append(parcels)
    return out


def _largest_patch(cells: set) -> set:
    """La plus grande tache d'un seul tenant (les parcelles isolées au bord ne font pas un lac)."""
    best, seen = set(), set()
    for c in cells:
        if c in seen:
            continue
        patch, stack = set(), [c]
        while stack:
            q = stack.pop()
            if q in seen or q not in cells:
                continue
            seen.add(q)
            patch.add(q)
            stack += [(q[0] + 1, q[1]), (q[0] - 1, q[1]), (q[0], q[1] + 1), (q[0], q[1] - 1)]
        if len(patch) > len(best):
            best = patch
    return best


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
    nombre de patrouilles, plus la fréquence des événements du climat. La même graine donne toujours la même vallée.
    Cohérence : 2 à 8 villages, 2 à 5 pêcheurs par village (24 au plus), au plus un lac par village (donc chacun a des villages) ;
    la capacité d'un lac suit ses pêcheurs (`resolve_lakes`, 12,5 t × richesse × pêcheurs) et la richesse reste >= 0,5 ; pas plus
    de patrouilles que de lacs + 1."""
    from .catalog import FLEETS

    r = random.Random(f"{seed}|valley")
    villages = r.randint(2, 8)
    lakes = r.randint(1, min(4, villages, MAX_LAKES))
    fishers = r.randint(2 * villages, min(24, 5 * villages))
    return {
        "villages": villages, "fishers": fishers, "fleet": r.choice([f["id"] for f in FLEETS]),
        "lakes": [{"name": LAKE_NAMES[i], "richness": round(r.uniform(0.5, 1.6), 2), "stock_ratio": round(r.uniform(0.4, 1.0), 2),
                   "growth_rate": round(r.uniform(0.3, 1.6), 2)} for i in range(lakes)],
        "patrols": r.randint(0, min(3, lakes + 1)), "event_rate": round(r.uniform(0.1, 0.5), 2),
    }
