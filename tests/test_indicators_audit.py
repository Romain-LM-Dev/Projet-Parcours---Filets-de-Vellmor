"""Audit des indicateurs : chaque chiffre du moteur est recalculé ici, à part, depuis les événements bruts.

La référence est volontairement écrite autrement que `IndicatorEngine` (autres structures, autre formule
du Gini) : si les deux s'accordent sur des parties de natures différentes (synchrone, asynchrone, veillées
par hameau, population personnalisée), c'est que les chiffres affichés sont les vrais.
"""
from __future__ import annotations

import statistics
from collections import defaultdict

import pytest

from filets.indicators import IndicatorEngine
from helpers import cfg_for, play

TOL = 0.5     # tolérance de quota et de promesse de la configuration par défaut


def engine_run(events):
    eng = IndicatorEngine(TOL)
    out = [eng.ingest(e) for e in events]
    return eng, [o for o in out if o]


def reference(events):
    """Indicateurs de fin de saison recalculés depuis le journal : {saison: valeurs}."""
    start = events[0]["payload"]
    cap = start["lake"]["capacity"]
    hamlet = {a["id"]: a["hamlet"] for a in start["agents"] if a["role"] == "pecheur"}
    fishers = list(hamlet)
    catches = defaultdict(lambda: defaultdict(float))
    norms, outcomes = [], defaultdict(list)
    broke = defaultdict(lambda: defaultdict(set))       # saison -> pêcheur -> règles de pêche enfreintes (quota : voir la prise)
    ends = {}
    for e in events:
        p = e["payload"]
        if e["type"] == "catch":
            catches[e["season"]][p["agent"]] += p["landed"]
            broke[e["season"]][p["agent"]].update(p.get("breach") or [])
        elif e["type"] == "norm_adopted":
            norms.append(p)
        elif e["type"] == "promise_outcome":
            outcomes[p["season"]].append(p)
        elif e["type"] == "season_end":
            ends[e["season"]] = p
    res = {}
    for s, end in ends.items():
        c = {f: catches[s].get(f, 0.0) for f in fishers}
        under = {}      # règles qui s'appliquent à chaque pêcheur cette saison : la dernière de chaque type et cible (hameau avant vallée)
        for f in fishers:
            now = {}
            for scope in ("valley", f"hamlet:{hamlet[f]}"):
                for i, n in enumerate(norms):
                    if n["scope"] == scope and n["effective_season"] <= s and s <= n.get("until_season", s):
                        now[(n.get("kind", "quota"), n.get("target"))] = (i, n)
            if now:
                under[f] = sorted(now.values(), key=lambda t: t[0])
        # au conseil des élus, un pêcheur soutient la règle (la dernière adoptée) si l'élu de son village l'a soutenue
        supporters = sum(f in rs[-1][1]["supporters"] or (rs[-1][1].get("delegates") or {}).get(hamlet[f]) in rs[-1][1]["supporters"]
                         for f, rs in under.items())

        def kept(f, n):
            return c[f] <= n["quota"] + TOL if n.get("kind", "quota") == "quota" else n["kind"] not in broke[s][f]
        compliers = sum(all(kept(f, n) for _, n in rs) for f, rs in under.items())
        agreement = supporters / len(fishers)
        compliance = compliers / len(under) if under else 0.0
        vals = list(c.values())
        mean = statistics.mean(vals)
        out = outcomes[s]
        res[s] = {
            "stock_ratio": end["stock"] / cap,
            "total_catch": sum(vals),
            "catch_cv": statistics.pstdev(vals) / mean if mean > 0 else 0.0,
            "norm_agreement": agreement, "norm_compliance": compliance, "norm_index": agreement * compliance,
            "norm_supporters": supporters, "norm_compliers": compliers, "norm_concerned": len(under),
            "fishers": len(fishers),
            "promises": len(out), "promises_kept": sum(o["kept"] for o in out),
            "promise_kept_rate": (sum(o["kept"] for o in out) / len(out)) if out else None,
            "promise_gap_t": statistics.mean(o["landed"] - o["promised"] for o in out) if out else 0.0,
            "wealth_gini": gini_pairs([w for w in end["wealth"].values()]),
        }
    return res


def gini_pairs(v):
    n, m = len(v), statistics.mean(v)
    if n == 0 or m <= 0:
        return 0.0
    return sum(abs(a - b) for a in v for b in v) / (2 * n * n * m)


CASES = {
    "defaut": dict(),
    "veillees_par_hameau": dict(scenario__communication="hamlet", population__fishers=9),
    "sans_communication": dict(scenario__communication="none"),
    "baseline_a_regles": dict(population__rule_fraction=1.0),
}


@pytest.mark.parametrize("name", CASES)
def test_season_indicators_match_independent_recomputation(tmp_path, name):
    events = play(tmp_path, seasons=4, **CASES[name])
    eng, outs = engine_run(events)
    ref = reference(events)
    seasons = {o["season"]: o["values"] for o in outs if o["trigger"] == "season_end"}
    assert set(seasons) == set(ref) and len(ref) == 4
    for s, want in ref.items():
        got = seasons[s]
        for key, expected in want.items():
            if expected is None:
                assert got[key] is None, f"S{s} {key}"
            else:
                assert got[key] == pytest.approx(expected, abs=2e-3), f"S{s} {key} ({name})"
        # un pourcentage de stock est un pourcentage : jamais plus de 100 % de la capacité
        assert 0.0 <= got["stock_ratio"] <= 1.0 + 1e-9


def test_live_indicators_count_what_the_log_counts(tmp_path):
    events = play(tmp_path, seasons=3)
    eng, outs = engine_run(events)
    last = outs[-1]["values"]
    by_type = defaultdict(int)
    for e in events:
        by_type[e["type"]] += 1
    assert last["llm_calls"] == by_type["llm_call"]
    assert last["llm_tokens"] == sum(e["payload"]["prompt_tokens"] + e["payload"]["completion_tokens"]
                                     for e in events if e["type"] == "llm_call")
    assert last["utterances"] == by_type["utterance"]
    assert last["accusations"] == by_type["accusation"]
    assert last["incidents_total"] == by_type["incident"]
    cap = events[0]["payload"]["lake"]["capacity"]
    final_stock = [e for e in events if e["type"] == "lake_update"][-1]["payload"]["stock"]
    assert last["stock"] == pytest.approx(final_stock, abs=1e-3)
    assert last["capacity"] == cap
    assert last["stock_ratio"] == pytest.approx(final_stock / cap, abs=1e-3)


def test_staleness_is_the_gap_between_the_decision_and_the_opening_snapshot(tmp_path):
    """Un pêcheur qui part plus tard décide sur un lac déjà entamé, mais sa cale se calcule sur l'instantané d'ouverture."""
    async_events = play(tmp_path, run_id="a", seasons=3)
    cap = async_events[0]["payload"]["lake"]["capacity"]
    gaps = [abs(e["payload"]["stock_at_action"] - e["payload"]["stock_at_horizon"]) / cap
            for e in async_events if e["type"] == "catch"]
    eng, _ = engine_run(async_events)
    assert eng.last_values["mean_staleness_ratio"] == pytest.approx(statistics.mean(gaps), abs=1e-3)


# ---------------------------------------------------------------- le bug du « 10000 % »
def test_engine_refuses_to_compute_without_run_start(tmp_path):
    """Un service qui rejoint le flux après `run_start` ne connaît ni la capacité ni les pêcheurs :
    il ne doit rien publier plutôt que des chiffres faux (stock de 76 « t sur 1 » = 7600 %)."""
    events = play(tmp_path, seasons=2)
    late = [e for e in events if e["type"] != "run_start"]
    eng, outs = engine_run(late)
    assert outs == []
    assert eng.skipped == len(late)


def test_engine_rebuilds_from_the_last_run_start(tmp_path):
    """Démarré n'importe quand, mais depuis le dernier run_start, le moteur retrouve les mêmes chiffres."""
    a = play(tmp_path, run_id="a", seasons=2)
    b = play(tmp_path, run_id="b", seasons=3, population__fishers=6)
    eng = IndicatorEngine(TOL)
    outs = [o for o in (eng.ingest(e) for e in a + b) if o]       # deux runs d'affilée, comme dans le topic Kafka
    from_b = [o for o in outs if o["run_id"] == "b" and o["trigger"] == "season_end"]
    eng_b, outs_b = engine_run(b)
    alone = [o for o in outs_b if o["trigger"] == "season_end"]
    assert [o["values"] for o in from_b] == [o["values"] for o in alone]
    assert from_b[-1]["values"]["capacity"] == 6 * 12.5


def test_engine_ignores_events_of_another_run(tmp_path):
    a = play(tmp_path, run_id="a", seasons=2)
    b = play(tmp_path, run_id="b", seasons=2)
    eng = IndicatorEngine(TOL)
    for e in a:
        eng.ingest(e)
    before = dict(eng.last_values)
    skipped = eng.skipped
    for e in b[1:]:                       # événements de b sans son run_start : ignorés, rien ne se mélange
        assert eng.ingest(e) is None
    assert eng.last_values == before and eng.skipped == skipped + len(b) - 1


def test_replay_gives_identical_indicators(tmp_path):
    """Le moteur de rejeu et le moteur en direct sont le même code : mêmes valeurs, événement par événement."""
    events = play(tmp_path, seasons=3)
    _, first = engine_run(events)
    _, second = engine_run(events)
    assert [o["values"] for o in first] == [o["values"] for o in second]
