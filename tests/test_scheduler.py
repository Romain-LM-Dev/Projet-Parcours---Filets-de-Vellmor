"""L'ordonnanceur unique (`filets/scheduler.py`, spécification `docs/temps.md`) : réfléchir ne prend pas de temps simulé, agir en
prend. Une IA lente ne fait perdre aucune sortie et ne change pas le monde ; les décisions que rien ne sépare sont demandées en
parallèle ; une décision voit tout ce qui s'est passé avant son horizon ; rien ne part après la fermeture de la pêche."""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from filets.scripted import ScriptedClient
from helpers import make_world, read_events

LLM = dict(population__fishers=8, population__rule_fraction=0.0)


def kinds(events, kind):
    return [e for e in events if e["type"] == kind]


def slow_provider(monkeypatch, delay: float, log: list | None = None):
    """Le faux LLM dort `delay` secondes avant de répondre, et note quand chaque appel part et revient."""
    orig = ScriptedClient.complete

    async def complete(self, model, messages, hint, tier):
        start = time.monotonic()
        await asyncio.sleep(delay)
        res = await orig(self, model, messages, hint, tier)
        if log is not None:
            log.append((hint.get("purpose"), start, time.monotonic()))
        return res
    monkeypatch.setattr(ScriptedClient, "complete", complete)


def play(tmp_path, run_id, seasons=2, **over):
    world, _, _ = make_world(tmp_path, run_id, seasons=seasons, **{**LLM, **over})
    asyncio.run(world.run())
    return world, read_events(tmp_path, run_id)


def outcome(events):
    """Ce que le monde a vécu (et non l'ordre dans lequel les modèles ont répondu) : prises, ventes, déclarations, stock final."""
    keep = {"catch": ("agent", "requested", "landed", "stock_before", "stock_after", "lake"),
            "report": ("agent", "declared", "landed"), "sale": ("agent", "tonnes", "income")}
    rows = [(e["type"], e["sim_time"], *(e["payload"].get(k) for k in keep[e["type"]])) for e in events if e["type"] in keep]
    return sorted(rows, key=repr)


def test_two_games_with_the_same_seed_give_the_same_journal(tmp_path):
    def journal(run_id):
        _, events = play(tmp_path, run_id, seasons=2, **{"time__departure_spread_days": [0.0, 4.0]})
        return [{k: v for k, v in e.items() if k not in ("run_id", "event_id", "processed_at", "wall_clock", "payload")}
                | {"payload": str(e["payload"]).replace(run_id, "R")} for e in events]
    a, b = journal("zz1"), journal("zz2")
    assert len(a) > 100 and len(a) == len(b)
    assert [(x["type"], x["sim_time"]) for x in a] == [(x["type"], x["sim_time"]) for x in b]
    assert a == b


def test_a_slow_ai_loses_no_outing_and_does_not_change_the_world(tmp_path, monkeypatch):
    _, fast = play(tmp_path, "vite", seasons=1)
    slow_provider(monkeypatch, 0.05)
    world, slow = play(tmp_path, "lent", seasons=1)
    assert not [e for e in slow if e["type"] == "incident" and e["payload"]["incident_type"] == "missed_window"]
    assert len(kinds(slow, "catch")) == len(world.fishers) == len(kinds(fast, "catch"))
    assert outcome(slow) == outcome(fast)


def test_decisions_with_no_event_between_them_are_asked_in_parallel(tmp_path, monkeypatch):
    log: list = []
    slow_provider(monkeypatch, 0.15, log)
    world, events = play(tmp_path, "para", seasons=1, time__departure_spread_days=[0.0, 0.1])
    plans = sorted((s, e) for p, s, e in log if p == "plan")
    assert len(plans) == len(world.fishers)
    # les huit départs tiennent avant la fin de la plus courte sortie (3 heures) : tous les appels se chevauchent
    assert plans[-1][0] < min(e for _, e in plans), "les décisions ont été demandées l'une après l'autre"


def test_a_decision_after_an_outing_sees_its_catch(tmp_path):
    world, events = play(tmp_path, "voit", seasons=1, time__departure_spread_days=[0.0, 4.0])
    stocks = [(e["sim_time"], e["payload"]["stock"]) for e in kinds(events, "lake_update")]
    seen = [(d["payload"]["info_horizon"], d["payload"]["observed"]["stock_true"]) for d in kinds(events, "decision")
            if d["payload"]["decision_type"] in ("plan", "catch")]
    assert len(seen) > 3 * len(world.fishers)          # un plan, puis une décision à chaque retour
    for h, stock_true in seen:
        before = [s for t, s in stocks if t <= h + 1e-9]
        assert stock_true == pytest.approx(before[-1], abs=0.01), f"à J{h:.2f}, la décision ne voit pas l'état du lac"
    # les départs s'étalent sur plusieurs jours : au moins une décision tombe après la fin d'une sortie, et le lac a baissé
    assert min(s for _, s in seen) < max(s for _, s in seen) - 0.5


def test_each_outing_is_an_event_on_its_own_day_before_the_catch_balance(tmp_path):
    _, events = play(tmp_path, "sortie", seasons=1, time__departure_spread_days=[0.0, 4.0])
    for c in kinds(events, "catch"):
        a = c["payload"]["agent"]
        mine = [e for e in kinds(events, "outing") if e["payload"]["agent"] == a]
        assert [o["payload"]["day"] for o in mine] == [o["day"] for o in c["payload"]["outings"]]
        assert [o["payload"]["tonnes"] for o in mine] == pytest.approx([o["tonnes"] for o in c["payload"]["outings"]], abs=0.01)
        for o in mine:           # la sortie est émise à son retour : début de la pêche + ses heures (chez soi, pas de route)
            assert o["sim_time"] == pytest.approx(o["payload"]["day"] + o["payload"]["hours"] / 24.0, abs=1e-3)
            assert o["sim_time"] <= c["sim_time"] + 1e-9
    assert len({o["sim_time"] for o in kinds(events, "outing")}) > 1


def test_nothing_sails_after_the_fishing_close(tmp_path):
    world, events = play(tmp_path, "ferme", seasons=2, time__departure_spread_days=[3.0, 4.0], time__fishing_close_day=12.0)
    for season in (1, 2):
        start = (season - 1) * world.T["season_days"]
        close = start + world.T["fishing_close_day"]
        for e in events:       # une sortie commencée avant la fermeture rentre normalement (au plus 7 h plus tard)
            if e["season"] == season and e["type"] in ("catch", "report", "sale", "outing"):
                assert e["sim_time"] <= close + 0.3 + 1e-6, (e["type"], e["sim_time"], close)
        for e in kinds(events, "outing"):
            if e["season"] == season:
                assert e["payload"]["day"] <= world.T["fishing_close_day"] + 1e-6


def test_the_road_to_another_lake_adds_its_days_to_both_ends(tmp_path):
    lakes = [{"name": "Vellmor", "capacity": 100, "stock_ratio": 1.0, "villages": ["Ostrel", "Bramois"]},
             {"name": "Orsane", "capacity": 100, "stock_ratio": 1.0, "villages": ["Tilque", "Hennad"]}]
    world, _, _ = make_world(tmp_path, "route", population__fishers=8, lake__lakes=lakes, economy__luck=0.0)
    home, away = world.lakes["Vellmor"], world.lakes["Orsane"]
    a = next(f for f in world.fishers if world.lake_of(f) is home)
    route = world.distance(home, away)
    assert route > 0
    here = world.outings(a, 1)
    a.outings.clear()
    there = world.outings(a, 1, lake=away)
    close = world.T["fishing_close_day"]
    assert there[0]["day"] == pytest.approx(here[0]["day"] + route, abs=0.01)                    # l'aller
    assert there[-1]["day"] + 1.0 + route <= close + 1e-6 and here[-1]["day"] + 1.0 <= close + 1e-6       # le retour tient avant la fermeture
    assert there[-1]["day"] < here[-1]["day"]


def test_events_of_parallel_decisions_come_out_in_queue_order_not_in_answer_order(tmp_path, monkeypatch):
    """Le premier de la file répond le dernier : ses événements restent les premiers du journal."""
    orig = ScriptedClient.complete
    calls = {"n": 0}

    async def uneven(self, model, messages, hint, tier):
        calls["n"] += 1
        await asyncio.sleep(0.2 if calls["n"] % 8 == 1 else 0.01 * (calls["n"] % 3))     # inégal, le premier appel est le plus lent
        return await orig(self, model, messages, hint, tier)
    monkeypatch.setattr(ScriptedClient, "complete", uneven)
    _, events = play(tmp_path, "inegal", seasons=1, time__departure_spread_days=[0.0, 0.2])
    seq = [e["seq"] for e in events]
    assert seq == sorted(seq) and len(set(seq)) == len(seq)
    first = [e for e in events if e["type"] == "decision" and e["payload"]["decision_type"] == "plan"]
    assert [e["actor"] for e in first] == sorted((e["actor"] for e in first), key=lambda a: [x["actor"] for x in first].index(a))
    _, even = play(tmp_path, "egal", seasons=1, time__departure_spread_days=[0.0, 0.2])
    order = lambda evs: [(e["type"], e["actor"]) for e in evs if e["type"] in ("decision", "llm_call")]
    monkeypatch.undo()
    assert order(events) == order(even)


def test_the_evening_has_the_same_journal_in_two_games(tmp_path):
    def journal(run_id):
        _, events = play(tmp_path, run_id, seasons=2)
        return [(e["type"], e["sim_time"], e["actor"]) for e in events if e["type"] in ("utterance", "proposal", "support", "decision")]
    assert journal("v1") == journal("v2")


# ============================================================ la pêche décidée par le pêcheur (docs/peche.md)
def force(monkeypatch, purpose: str, **fields):
    """Le faux LLM répond en plus ce qu'on lui impose pour cette nature de décision (`plan`, `catch`) : le pêcheur « choisit » ainsi."""
    orig = ScriptedClient.complete

    async def complete(self, model, messages, hint, tier):
        res = await orig(self, model, messages, hint, tier)
        if hint.get("purpose") == purpose and res.status == "ok":
            try:
                res.text = json.dumps({**json.loads(res.text), **fields}, ensure_ascii=False)
            except ValueError:
                pass
        return res
    monkeypatch.setattr(ScriptedClient, "complete", complete)


def fishing_hours(o):
    """(heure du début, heure de la fin) de la pêche d'une sortie, dans sa journée."""
    h = (o["payload"]["day"] % 1.0) * 24.0
    return h, h + o["payload"]["hours"]


def test_the_fisher_chooses_his_own_days(tmp_path):
    _, events = play(tmp_path, "jours", seasons=1)
    days = {}
    for o in kinds(events, "outing"):
        days.setdefault(o["payload"]["agent"], []).append(o["payload"]["day"])
    assert len(days) >= 6 and len({tuple(d) for d in days.values()}) > 3          # chacun ses jours, ce n'est plus une grille commune
    gaps = [{round(b - a, 1) for a, b in zip(d, d[1:])} for d in days.values() if len(d) > 2]
    assert any(len(g) > 1 for g in gaps)                                         # et des écarts inégaux d'une sortie à l'autre
    assert {o["payload"]["hours"] for o in kinds(events, "outing")} == {3.0, 7.0}      # courtes et longues
    decisions = [d["payload"] for d in kinds(events, "decision") if d["payload"]["decision_type"] == "catch"]
    assert decisions and all("delay_h" in d for d in decisions)


def test_a_fisher_may_not_go_out_at_all(tmp_path, monkeypatch):
    force(monkeypatch, "plan", premiere_sortie="plus cette saison")
    world, events = play(tmp_path, "quai", seasons=1)
    assert not kinds(events, "outing")
    catches = kinds(events, "catch")
    assert len(catches) == len(world.fishers) and all(c["payload"]["landed"] == 0 and c["payload"]["outings"] == [] for c in catches)
    assert all(r["payload"]["declared"] == 0 for r in kinds(events, "report"))


def test_two_outings_the_same_day_are_possible(tmp_path, monkeypatch):
    force(monkeypatch, "plan", premiere_sortie="tout de suite")
    force(monkeypatch, "catch", quand="tout de suite", duree="courte")
    _, events = play(tmp_path, "deux", seasons=1)
    per_day = {}
    for o in kinds(events, "outing"):
        per_day.setdefault((o["payload"]["agent"], int(o["payload"]["day"])), []).append(o)
    assert max(len(v) for v in per_day.values()) >= 2
    for v in per_day.values():            # l'une après l'autre : la barque ne fait pas deux sorties à la fois
        ends = sorted(o["sim_time"] for o in v)
        starts = sorted(o["payload"]["day"] for o in v)
        assert all(s >= e - 1e-3 for s, e in zip(starts[1:], ends))


def test_nobody_fishes_at_night(tmp_path, monkeypatch):
    force(monkeypatch, "catch", quand="tout de suite", duree="longue")           # il ressort sans attendre, même le soir
    _, events = play(tmp_path, "nuit", seasons=2)
    outs = kinds(events, "outing")
    assert len(outs) > 10
    for o in outs:
        start, end = fishing_hours(o)
        assert start >= 5.0 - 1e-2 and end <= 21.0 + 1e-2, (start, end)
    assert any(abs(fishing_hours(o)[0] - 5.0) < 1e-2 for o in outs)              # une sortie reportée à l'aube


def test_no_outing_starts_after_the_close_even_if_the_fisher_wants_to(tmp_path, monkeypatch):
    force(monkeypatch, "catch", quand="tout de suite", duree="courte")
    world, events = play(tmp_path, "tard", seasons=1, time__fishing_close_day=6.0, time__departure_spread_days=[0.0, 1.0])
    outs = kinds(events, "outing")
    assert outs and max(o["payload"]["day"] for o in outs) <= 6.0 + 1e-6
    assert len(kinds(events, "catch")) == len(world.fishers)                     # et chacun a quand même rendu son bilan


def test_the_catch_of_an_outing_is_limited_by_the_hold_and_the_season_ceiling(tmp_path, monkeypatch):
    force(monkeypatch, "plan", prise_saison=50.0)
    force(monkeypatch, "catch", quand="tout de suite", duree="longue", prise=50.0)       # il demande tout, tout de suite
    world, events = play(tmp_path, "cale", seasons=1)
    for o in kinds(events, "outing"):
        a = world.agents[o["payload"]["agent"]]
        assert o["payload"]["tonnes"] <= world.cale_of(a, 7.0) + 1e-6
    for c in kinds(events, "catch"):
        a = world.agents[c["payload"]["agent"]]
        assert c["payload"]["landed"] <= world.hold_of(a, world.season_stock[world.lake_of(a).name]) + 1e-6


def test_the_routine_outing_goes_to_the_decision_model_and_a_rumor_wakes_the_big_model(tmp_path):
    from test_rumors import Recorder, play_with_announcement
    from test_system12 import GRANDS
    from test_system_one import FakeSystemOne
    s1, rec = FakeSystemOne(level=3), Recorder(prise=3.0)
    prov = {"fake": {"base_url": rec.url, "api_key_env": None, "rpm": 0, "json_schema": True, "seed": True},
            "scripted": {"latency_scale": 0.0}, "s1": {"base_url": s1.url, "kind": "systemone", "local": True, "timeout_s": 5}}
    tiers = {"grand": {"provider": "fake", "model": "m"}, "petit": {"provider": "fake", "model": "m"},
             "reflexe": {"provider": "s1", "model": "tev1:0.8b"}}
    world, events = play_with_announcement(tmp_path, "rumeur", "Le lac se vide à Ostrel", provider=rec, seasons=1, population=GRANDS,
                                           lake__capacity=400.0,
                                           announce_on=lambda ev: ev["type"] == "outing" and ev["sim_time"] > 8.0,
                                           llm_overrides={"reflection": "adaptive", "providers": prov, "tiers": tiers})
    rec.close()
    s1.close()
    t_said = next(e["sim_time"] for e in events if e["type"] == "injection")
    decs = [e for e in events if e["type"] == "decision" and e["payload"]["decision_type"] == "catch"]
    plans = [e["payload"] for e in events if e["type"] == "decision" and e["payload"]["decision_type"] == "plan"]
    assert plans and all(p["system"] == "S2" and p["tier"] == "grand" for p in plans)        # le plan est toujours une réflexion
    before = [e["payload"] for e in decs if e["sim_time"] < t_said]
    routine = [d for d in before if d["system"] == "S1"]
    assert routine and all(d["tier"] == "reflexe" and not d["fallback"] for d in routine)       # la routine : tev1
    assert all("rumeur" not in d["routing"] for d in before)           # (les autres : le lac a baissé, un plan rempli… pas de rumeur)
    later = [e["payload"] for e in decs if e["sim_time"] >= t_said]
    woken = [d for d in later if "rumeur" in d["routing"]]
    assert woken and all(d["system"] == "S2" and d["tier"] == "grand" for d in woken)       # la rumeur réveille le grand modèle
    assert {d["agent"] for d in woken} == {d["agent"] for d in later}                       # chacun y a pensé, une fois la rumeur connue
    rumor_free = [d for d in later if "rumeur" not in d["routing"]]
    assert all(d["info_horizon"] > min(w["info_horizon"] for w in woken if w["agent"] == d["agent"]) for d in rumor_free)


# ============================================================ la qualité de la parole (répétition, silence, aveu public)
def speak_log(monkeypatch, **fields):
    """Le faux LLM répond ce qu'on impose à chaque réplique ; on note le texte de chaque invite de parole."""
    prompts = []
    force(monkeypatch, "speak", **fields)
    orig = ScriptedClient.complete

    async def complete(self, model, messages, hint, tier):
        if hint.get("purpose") == "speak":
            prompts.append(messages[-1]["content"])
        return await orig(self, model, messages, hint, tier)
    monkeypatch.setattr(ScriptedClient, "complete", complete)
    return prompts


def test_the_second_speech_prompt_shows_what_the_speaker_already_said(tmp_path, monkeypatch):
    prompts = speak_log(monkeypatch, message="Le lac se vide, restons prudents.")
    _, events = play(tmp_path, "repeat", seasons=1, scenario__quiet_listeners=False)
    assert any("Ce que tu as déjà dit ce soir" in p and "Le lac se vide, restons prudents." in p for p in prompts)
    assert not any("Ce que tu as déjà dit ce soir" in p for p in prompts[:1])


def test_an_empty_message_means_the_speaker_stays_silent(tmp_path, monkeypatch):
    speak_log(monkeypatch, message="")
    _, events = play(tmp_path, "silence", seasons=1)
    assert not kinds(events, "utterance")
    assert any(e["payload"].get("justification") == "(se tait : rien de neuf à dire)" for e in kinds(events, "decision"))


def test_the_speech_prompt_says_everything_is_heard_by_all(tmp_path, monkeypatch):
    prompts = speak_log(monkeypatch)
    play(tmp_path, "heard", seasons=1)
    assert prompts and all("entendu de tous" in p and "restent privés" in p for p in prompts)
