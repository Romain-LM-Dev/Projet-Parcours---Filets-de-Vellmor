"""Indicateurs à plusieurs lacs : le détail par lac se recalcule depuis les événements bruts, la vallée n'est effondrée que si tous ses
lacs le sont, et l'obsolescence se rapporte à la capacité du lac où l'on a pêché."""
from __future__ import annotations

import statistics
from collections import defaultdict

import pytest

from filets.indicators import IndicatorEngine
from helpers import play
from test_lakes import TWO_LAKES


def run_engine(events):
    eng = IndicatorEngine(0.5)
    return eng, [o for o in (eng.ingest(e) for e in events) if o]


def test_per_lake_detail_matches_the_raw_events(tmp_path):
    ev = play(tmp_path, "il", seasons=3, population__fishers=8, lake__lakes=TWO_LAKES)
    eng, out = run_engine(ev)
    caps = {lk["name"]: lk["capacity"] for lk in ev[0]["payload"]["lakes"]}
    ends = {e["season"]: e["payload"] for e in ev if e["type"] == "season_end"}
    caught = defaultdict(lambda: defaultdict(float))
    for e in ev:
        if e["type"] == "catch":
            caught[e["season"]][e["payload"]["lake"]] += e["payload"]["landed"]
    snaps = [o for o in out if o["trigger"] == "season_end"]
    assert len(snaps) == 3
    for o in snaps:
        v, s = o["values"], o["season"]
        assert set(v["lakes"]) == set(caps)
        for n, d in v["lakes"].items():
            assert d["stock"] == pytest.approx(ends[s]["lakes"][n], abs=1e-3)
            assert d["stock_ratio"] == pytest.approx(ends[s]["lakes"][n] / caps[n], abs=1e-3)      # sa propre capacité
            assert d["catch"] == pytest.approx(caught[s][n], abs=1e-3)
        assert sum(d["catch"] for d in v["lakes"].values()) == pytest.approx(v["total_catch"], abs=1e-2)
        assert v["stock"] == pytest.approx(sum(d["stock"] for d in v["lakes"].values()), abs=1e-2)   # les totaux restent
    assert sum(caught[1].values()) > 0 and len([n for n in caught[1] if caught[1][n] > 0]) == 2
    gaps = [abs(e["payload"]["stock_at_action"] - e["payload"]["stock_at_horizon"]) / caps[e["payload"]["lake"]]
            for e in ev if e["type"] == "catch"]
    assert eng.last_values["mean_staleness_ratio"] == pytest.approx(statistics.mean(gaps), abs=1e-3)


def test_valley_collapses_only_when_every_lake_has(tmp_path):
    ev = play(tmp_path, "ic", seasons=1, population__fishers=8, lake__lakes=TWO_LAKES)
    eng = IndicatorEngine(0.5)
    for e in ev[:1]:
        eng.ingest(e)
    base = dict(ev[1], type="lake_collapsed", payload={"stock": 1.0, "capacity": 100, "lake": "Vellmor"})
    eng.ingest(base)
    assert eng.collapsed is False and eng.lakes["Vellmor"]["collapsed"] and not eng.lakes["Orsane"]["collapsed"]
    eng.ingest(dict(base, payload={**base["payload"], "lake": "Orsane"}))
    assert eng.collapsed is True
    snap = eng.snapshot(ev[1], "run_end", [])
    assert snap["values"]["lakes_collapsed"] == 2 and snap["values"]["lakes"]["Orsane"]["collapsed"]


def test_single_lake_has_no_lake_detail(tmp_path):
    ev = play(tmp_path, "i1", seasons=1, population__fishers=8)
    _, out = run_engine(ev)
    assert all("lakes" not in o["values"] for o in out)
