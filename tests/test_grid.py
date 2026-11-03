"""Le monde en mailles : les lacs sont des taches de parcelles (chacune son poisson et sa chance), une barque pêche autour de sa
parcelle, le repeuplement du lac entier ne change pas, et chaque pêcheur choisit son coin d'après ce qu'il en a tiré."""
from __future__ import annotations

import asyncio
import math

import pytest

from filets.lake import Lake
from filets.lakes import GRID, LAKE_CENTERS, lake_parcels, village_positions
from helpers import make_world, read_events


def kinds(events, t):
    return [e for e in events if e["type"] == t]


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_the_lakes_are_patches_of_parcels_that_look_like_lakes(n):
    lakes = lake_parcels(n, 7)
    assert len(lakes) == n and lakes == lake_parcels(n, 7) and lakes != lake_parcels(n, 8)     # la graine, et elle seule
    seen = set()
    for k, parcels in enumerate(lakes):
        cells = {(p["i"], p["j"]) for p in parcels}
        assert len(cells) > 40 and not cells & seen                    # assez grand, et jamais sur un autre lac
        seen |= cells
        # d'un seul tenant, autour de son centre
        stack, reached = [next(iter(cells))], set()
        while stack:
            c = stack.pop()
            if c in reached or c not in cells:
                continue
            reached.add(c)
            stack += [(c[0] + 1, c[1]), (c[0] - 1, c[1]), (c[0], c[1] + 1), (c[0], c[1] - 1)]
        assert reached == cells
        cx, cy = LAKE_CENTERS[n][k]
        assert (int(cx * GRID), int(cy * GRID)) in cells
        # le poisson se partage entre les parcelles, plus au fond qu'au bord ; la chance vaut 1 en moyenne
        assert sum(p["share"] for p in parcels) == pytest.approx(1.0)
        assert sum(p["share"] * p["luck"] for p in parcels) == pytest.approx(1.0, abs=0.01)
        assert min(p["luck"] for p in parcels) < 0.95 < 1.05 < max(p["luck"] for p in parcels)
        deep = max(parcels, key=lambda p: p["depth"])
        shore = min(parcels, key=lambda p: p["depth"])
        assert deep["depth"] >= 2 and shore["depth"] == 0
    # et les villages sont sur la terre
    names = [f"V{i}" for i in range(2 * n)]
    for (x, y) in village_positions(names, {h: i % n for i, h in enumerate(names)}, n).values():
        assert (int(x * GRID), int(y * GRID)) not in seen


def test_a_boat_empties_its_own_corner_first_and_the_lake_regrows_as_a_whole():
    parcels = lake_parcels(1, 3)[0]
    lake = Lake(500.0, 0.8, 0.6, 0.1, 0.1, parcels=parcels)
    plain = Lake(500.0, 0.8, 0.6, 0.1, 0.1)                      # le même lac, d'une seule parcelle
    at = max(range(len(parcels)), key=lambda k: parcels[k]["depth"])
    far = max(range(len(parcels)), key=lambda k: (parcels[k]["i"] - parcels[at]["i"]) ** 2 + (parcels[k]["j"] - parcels[at]["j"]) ** 2)
    before = list(lake.cells)
    assert lake.take(30.0, at) == 30.0 and plain.take(30.0) == 30.0
    assert lake.stock == pytest.approx(sum(lake.cells)) == pytest.approx(370.0)
    assert lake.cells[at] < before[at] * 0.95 and lake.cells[far] == pytest.approx(before[far])     # ici, pas à l'autre bout
    assert lake.fill_near(at) == pytest.approx(1.0)              # (le rendement de la saison suit l'ouverture : voir `open_season`)
    lake.open_season()
    assert lake.fill_near(at) < 0.97 < lake.fill_near(far)
    # le repeuplement du lac entier est celui d'avant (logistique) ; une part du poisson regagne ses coins
    assert lake.regrow() == pytest.approx(plain.regrow())
    assert lake.stock == pytest.approx(sum(lake.cells)) == pytest.approx(plain.stock)
    gap = before[at] - lake.cells[at]
    lake.regrow()
    assert before[at] - lake.cells[at] < gap
    # fixer le stock (une sécheresse) : chaque parcelle dans la même proportion
    lake.stock = lake.stock / 2
    assert lake.stock == pytest.approx(sum(lake.cells))


def test_each_fisher_fishes_a_corner_of_his_own_shore_and_leaves_a_bad_one(tmp_path):
    world, bus, _ = make_world(tmp_path, "coins", seasons=4, time__mode="sync", economy__luck=0.4, climate__enabled=True)
    asyncio.run(world.run())
    events = read_events(tmp_path, "coins")
    start = kinds(events, "run_start")[0]["payload"]
    lake = world.lake
    assert len(start["lakes"][0]["cells"]) == len(lake.parcels) and set(start["map"]["hamlets"]) == set(world.hamlets)
    assert start["map"]["grid"] == GRID and kinds(events, "lake_cells")
    cell_of = {(p["i"], p["j"]): k for k, p in enumerate(lake.parcels)}
    moved = 0
    for c in kinds(events, "catch"):
        p = c["payload"]
        k = cell_of[tuple(p["cell"])]
        if p["zone"] in world.hamlets:                            # sur une rive : une parcelle de cette rive
            assert k in world.sectors[lake.name][p["zone"]]
        a = world.agents[p["agent"]]
        prev = [e["payload"] for e in kinds(events, "catch") if e["payload"]["agent"] == a.id and e["season"] == c["season"] - 1]
        if prev and prev[0]["zone"] == p["zone"] == a.profile.hamlet:
            if prev[0]["spot"] >= 0.95:
                assert p["cell"] == prev[0]["cell"]                # un bon coin, il y revient
            else:
                moved += p["cell"] != prev[0]["cell"]                # un mauvais, il en change
    assert moved >= 1
    assert any("Mon coin de pêche" in m.text for f in world.fishers for m in f.memory.items)
    # le coin de chaque rive : plus près de son village que des autres
    hx, hy = world.village_xy[world.hamlets[0]]
    for k in world.sectors[lake.name][world.hamlets[0]]:
        d = math.hypot((lake.parcels[k]["i"] + 0.5) / GRID - hx, (lake.parcels[k]["j"] + 0.5) / GRID - hy)
        assert all(d <= world._parcel_dist(lake.parcels[k], h) + 1e-9 for h in world.hamlets)
