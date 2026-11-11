"""Déclarer à chaque retour (docs/peche.md) : chaque sortie a sa déclaration (événement `report`), un mensonge se compte sortie par
sortie, les indices visent une sortie, et chacun voit combien de mensonges la vallée tient pour établis."""
from __future__ import annotations

import asyncio
import json

import pytest

from filets.scripted import ScriptedClient
from helpers import make_world
from test_scheduler import LLM, kinds, play


def hide_on(monkeypatch, done: set | None, share: float = 0.5, agents: set | None = None):
    """Le faux LLM cache `share` de la sortie qu'il vient de faire quand c'est sa `done`-ième sortie (None : toutes), et dit vrai sinon."""
    orig = ScriptedClient.complete

    async def complete(self, model, messages, hint, tier):
        self.cfg = {**self.cfg, "incident_rates": {}}                # (ni réponse perdue ni JSON cassé : la règle de repli cacherait aussi)
        res = await orig(self, model, messages, hint, tier)
        s = hint.get("state") or {}
        if hint.get("purpose") == "catch" and res.status == "ok" and s.get("last_landed") is not None:
            hide = (done is None or s["done"] in done) and (agents is None or s["self_id"] in agents)      # (les autres disent vrai)
            try:
                res.text = json.dumps({**json.loads(res.text), "declaration": round(s["last_landed"] * (1 - share * hide), 2)})
            except ValueError:
                pass
        return res
    monkeypatch.setattr(ScriptedClient, "complete", complete)


def test_every_outing_is_declared_and_the_season_total_is_their_sum(tmp_path):
    _, events = play(tmp_path, "decl", seasons=1)
    outings, reports = kinds(events, "outing"), kinds(events, "report")
    assert len(reports) == len(outings) > 20                                             # un report par sortie
    for r in reports:
        o = next(o for o in outings if o["event_id"] == r["payload"]["outing_event_id"])
        assert o["payload"]["agent"] == r["payload"]["agent"] and r["payload"]["landed"] == pytest.approx(o["payload"]["tonnes"], abs=1e-3)
        assert r["sim_time"] == pytest.approx(o["sim_time"], abs=1e-6) and r["payload"]["declared"] <= r["payload"]["landed"] + 1e-9
    for c in kinds(events, "catch"):
        mine = [r["payload"]["declared"] for r in reports if r["payload"]["agent"] == c["payload"]["agent"]]
        assert c["payload"]["declared"] == pytest.approx(sum(mine), abs=0.011)           # le bilan de la saison porte le total déclaré
        assert [o.get("declared") for o in c["payload"]["outings"]] == mine


def test_a_lie_on_one_outing_is_not_a_lie_on_all_of_them(tmp_path, monkeypatch):
    hide_on(monkeypatch, {2})                                                            # tous cachent la moitié de leur deuxième sortie
    world, events = play(tmp_path, "une", seasons=1)
    lies = {}
    for r in kinds(events, "report"):
        p = r["payload"]
        if p["landed"] - p["declared"] >= 0.05:
            lies.setdefault(p["agent"], []).append(p["landed"] - p["declared"])
    assert lies and all(len(v) == 1 for v in lies.values())                              # une seule sortie en cause
    assert len(world.lies) == len(sum(lies.values(), [])) == sum(len(v) for v in lies.values())


def test_many_lies_are_recorded_one_by_one_with_their_size_and_date(tmp_path, monkeypatch):
    hide_on(monkeypatch, None, share=0.5, agents={"F01"})
    world, events = play(tmp_path, "toutes", seasons=1)
    mine = [e for e in kinds(events, "report") if e["payload"]["agent"] == "F01"]
    lies = [e for e in world.lies.values() if e["agent"] == "F01"]
    assert len(mine) >= 4 and len(lies) >= len(mine) - 1                                  # (la première sortie se déclare au plan : vrai)
    assert all(l["day"] is not None and l["landed"] - l["declared"] >= 0.05 for l in lies)
    assert {l["report_event_id"] for l in lies} <= {e["event_id"] for e in mine}


def test_a_witness_clue_aims_at_the_outing_it_saw(tmp_path):
    world, _, _ = make_world(tmp_path, "temoin", **LLM)
    a, b = world.fishers[:2]
    world.scn["detection"] = world.detection = {**world.detection, "witness": 1.0, "patrol": 0.0}

    def trip(agent, outs):
        landed = sum(o["landed"] for o in outs)
        return {"agent": agent.id, "zone": "large", "landed": landed, "secret": False, "patrol": 0.0, "patrol_by": None, "event_id": "c",
                "breach": [], "said": sum(o["said"] for o in outs), "outs": outs}
    o1 = {"id": "o1", "day": 1.0, "t": 1.3, "zone": "large", "landed": 2.0, "said": 1.0, "report_id": "r1"}
    o2 = {"id": "o2", "day": 5.0, "t": 5.3, "zone": "large", "landed": 1.0, "said": 1.0, "report_id": "r2"}
    ob = {"id": "o3", "day": 1.0, "t": 1.4, "zone": "large", "landed": 1.0, "said": 1.0, "report_id": "r3"}     # B pêche là le même jour
    world.trips[1] = [trip(a, [o1, o2]), trip(b, [ob])]
    world.investigate(1)
    seen = [c for c in world.clues if c["kind"] == "temoin" and c["subject"] == a.id]
    assert [c["outing_event_id"] for c in seen] == ["o1"] and seen[0]["observer"] == b.id                 # l'autre sortie n'a pas eu de témoin
    assert seen[0]["declared"] == 1.0 and 1.2 < seen[0]["estimate"] < 2.8 and seen[0]["day"] == 1.0


def test_the_others_see_how_many_lies_are_known_their_size_and_date(tmp_path):
    world, _, _ = make_world(tmp_path, "livre", **LLM)
    a, b = world.fishers[:2]
    world.established[(a.id, 1)] = {"value": 6.0, "t": 0.0, "how": "temoins", "secret": False, "breach": [], "n_outs": 6, "outs": [
        {"day": 3.0, "declared": 0.5, "estimated": 1.2, "landed": 1.0}, {"day": 9.0, "declared": 0.4, "estimated": 1.0, "landed": 1.0}]}
    lines = world.lie_lines(b, 5.0, 2)
    assert len(lines) == 1 and "2 mensonge(s) établi(s)" in lines[0] and "jour 3" in lines[0] and "jour 9" in lines[0]
    assert "déclaré 0.5 t pour environ 1.2 t" in lines[0] and "2 sorties sur 6" in lines[0]
    assert world.lie_lines(a, 5.0, 2) == [] and world.lie_lines(b, -1.0, 2) == []         # on ne le lit pas avant qu'il soit dit
    obs = asyncio.run(world.observe(b, 5.0, "catch"))[0]
    assert obs["lie_book"] == lines
    from filets import prompts
    assert "Mensonges que la vallée tient pour établis" in prompts.context_block({**obs, "stock_history": []}, False)


def test_the_scripted_declarations_are_the_same_in_two_games(tmp_path):
    def declared(run_id):
        _, events = play(tmp_path, run_id, seasons=2)
        return [(e["sim_time"], e["payload"]["agent"], e["payload"]["declared"], e["payload"]["landed"]) for e in kinds(events, "report")]
    first = declared("d1")
    assert first == declared("d2") and any(l - d >= 0.05 for _, _, d, l in first)             # et il y a des mensonges (le taiseux, le nouveau venu)
