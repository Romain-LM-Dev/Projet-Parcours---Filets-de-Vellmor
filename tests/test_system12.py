"""Système 1 (réflexe) / système 2 (réflexion) : dépenser les tokens là où la réflexion change quelque chose, et le prouver
(chaque appel porte son système, les tokens se comptent par système), sur des données fiables (réponse contrainte, graine stable).
"""
from __future__ import annotations

import pytest

from filets import prompts, routing
from filets.cli import verify
from filets.indicators import IndicatorEngine
from test_rumors import Recorder, play_with_announcement

PROVIDERS = {"fake": {"api_key_env": None, "rpm": 0, "json_schema": True, "seed": True}, "scripted": {"latency_scale": 0.0}}


def fisher(first, hamlet, arch, tier="grand"):
    return {"first_name": first, "hamlet": hamlet, "archetype": arch, "experience": 20, "wealth": 500, "debt_payment": 0,
            "kind": "llm", "tier": tier}


GRANDS = [fisher("Mathis", "Ostrel", "ancienne_famille"), fisher("Inès", "Bramois", "nouveau_venu"),
          fisher("Elwen", "Tilque", "taiseux"), fisher("Théo", "Hennad", "beau_parleur")]


def obs_routine():
    return {"label": "S3 · J0 06:00", "season": 3, "stock_estimate": 95.0, "role": "pecheur", "capacity": 100.0, "collapse_ratio": 0.05,
            "stock_history": [{"label": "S2 · J0 06:00", "est": 97.0, "phase": "pêche", "season": 2, "event_id": None}],
            "wealth": 500.0, "upkeep": 150.0, "debt_payment": 0.0, "price": 100.0, "boat_capacity": 10.0, "own_history": [],
            "norms": ["pas plus de 3 t par pêcheur"], "known_catches": [], "pinned": ["J'ai promis 3 t."], "memories": [],
            "documents": [], "rumors": []}


# ---------------------------------------------------------------- le routage
def test_a_calm_situation_is_a_reflex():
    assert routing.choose_system(obs_routine(), "catch")[0] == "S1"


@pytest.mark.parametrize("change, why", [
    ({"stock_history": []}, "première observation"),
    ({"stock_estimate": 60.0}, "sous 70 %"),
    ({"stock_estimate": 88.0}, "baisse"),                        # 97 → 88 : plus de 4 % de la capacité
    ({"rumors": ["Inès ment"]}, "rumeur"),
    ({"wealth": 100.0}, "finances"),
    ({"pinned": [], "norms": []}, "aucun engagement"),
])
def test_anything_unusual_deserves_reflection(change, why):
    system, reason = routing.choose_system({**obs_routine(), **change}, "catch")
    assert system == "S2" and why in reason, reason


def test_a_norm_or_a_promise_alone_is_enough_guidance():
    assert routing.choose_system({**obs_routine(), "pinned": []}, "catch")[0] == "S1"
    assert routing.choose_system({**obs_routine(), "norms": []}, "catch")[0] == "S1"


def test_speeches_are_always_reflection():
    assert routing.choose_system(obs_routine(), "speak")[0] == "S2"


# ---------------------------------------------------------------- le prompt du réflexe
def test_the_reflex_prompt_is_tiny_and_asks_for_a_number_only():
    p = type("P", (), {"name": "Théo de Hennad", "archetype_label": "beau parleur", "hamlet": "Hennad", "traits": "Il aime parler."})()
    msgs = prompts.reflex_messages(p, obs_routine())
    text = "".join(m["content"] for m in msgs)
    assert len(text) < 900 and "95 %" in text and "J'ai promis 3 t." in text and "pas plus de 3 t" in text
    assert '"prise"' in msgs[1]["content"] and "justification" not in text
    assert prompts.REFLEX_SCHEMA["required"] == ["prise"] and prompts.REFLEX_MAX_TOKENS <= 20


def test_the_profile_flags():
    assert prompts.is_adaptive({"reflection": "adaptive"}) and not prompts.is_adaptive({"reflection": "rapide"})
    assert prompts.is_brief({"reflection": "adaptive"}) and prompts.is_brief({"reflection": "rapide"})
    assert not prompts.is_brief({"reflection": "complete"})


# ---------------------------------------------------------------- dans une partie
def adaptive_game(tmp_path, run_id, reflection="adaptive", seasons=4, providers=PROVIDERS):
    rec = Recorder(prise=3.0)
    prov = {k: dict(v) for k, v in providers.items()}
    prov["fake"]["base_url"] = rec.url
    world, events = play_with_announcement(tmp_path, run_id, None, provider=rec, seasons=seasons, population=GRANDS,
                                           lake__capacity=400.0, llm_overrides={"reflection": reflection, "providers": prov})
    rec.close()
    return world, events, rec.requests


def test_routine_catches_become_reflexes_and_the_rest_stays_reflection(tmp_path):
    world, events, requests = adaptive_game(tmp_path, "s12a")
    calls = [e["payload"] for e in events if e["type"] == "llm_call"]
    s1 = [c for c in calls if c.get("system") == "S1"]
    s2 = [c for c in calls if c.get("system") == "S2"]
    assert s1 and s2 and len(s1) + len(s2) == len(calls)                        # tout appel porte son système
    assert all(c["purpose"] == "catch" and c["tier"] == "petit" for c in s1)     # un réflexe : une prise, par le petit modèle
    assert all(c["tier"] == "grand" for c in s2 if c["purpose"] == "catch")      # la réflexion : le modèle de l'agent
    first_season = [e for e in events if e["type"] == "decision" and e["season"] == 1 and e["payload"]["decision_type"] == "catch"]
    assert all(e["payload"]["system"] == "S2" for e in first_season)             # première saison : jamais de réflexe
    decisions = [e["payload"] for e in events if e["type"] == "decision" and e["payload"]["agent_kind"] == "llm"]
    assert all(d["system"] in ("S1", "S2") for d in decisions) and not any(d["fallback"] for d in decisions)
    reflex = [d for d in decisions if d["system"] == "S1"]
    assert reflex and all(d["justification"].startswith("Réflexe (système 1)") for d in reflex)
    assert verify("s12a", world.cfg)


def test_a_reflex_costs_a_fraction_of_a_reflection(tmp_path):
    world, events, requests = adaptive_game(tmp_path, "s12b")
    reflex = [r for r in requests if list(r["response_format"]["json_schema"]["schema"]["properties"]) == ["prise"]]
    thought = [r for r in requests if '"prise"' in r["user"] and r not in reflex]
    assert reflex and thought
    size = lambda rs: sum(len(r["system"]) + len(r["user"]) for r in rs) / len(rs)
    assert size(reflex) < 0.25 * size(thought), (size(reflex), size(thought))
    assert all(r["max_tokens"] == prompts.REFLEX_MAX_TOKENS for r in reflex)


def test_tokens_are_counted_per_system(tmp_path):
    world, events, requests = adaptive_game(tmp_path, "s12c")
    eng = IndicatorEngine(0.5)
    for e in events:
        eng.ingest(e)
    v = eng.last_values
    assert v["llm_calls_s1"] > 0 and v["llm_calls_s2"] > 0
    assert v["llm_calls_s1"] + v["llm_calls_s2"] == v["llm_calls"]
    assert v["llm_tokens_s1"] + v["llm_tokens_s2"] == v["llm_tokens"]
    usage = world.router.usage.by_system
    assert usage["S1"]["calls"] == v["llm_calls_s1"] and usage["S2"]["tokens"] == v["llm_tokens_s2"]


def test_without_the_adaptive_profile_everything_is_reflection(tmp_path):
    """Sans routage, aucune décision n'est un réflexe : tout est système 2, et le décompte permet de comparer les profils."""
    world, events, requests = adaptive_game(tmp_path, "s12d", reflection="rapide", seasons=3)
    tagged = [e["payload"]["system"] for e in events if e["type"] in ("llm_call", "decision") and "system" in e["payload"]]
    assert tagged and set(tagged) == {"S2"}
    assert set(world.router.usage.by_system) == {"S2"}
    assert all(list(r["response_format"]["json_schema"]["schema"]["properties"]) != ["prise"] for r in requests)


# ---------------------------------------------------------------- données fiables : la graine
def test_seeds_are_stable_per_decision_and_distinct_between_agents(tmp_path):
    _, _, first = adaptive_game(tmp_path, "s12e", seasons=2)
    _, _, second = adaptive_game(tmp_path, "s12f", seasons=2)
    seeds1, seeds2 = sorted(r["seed"] for r in first), sorted(r["seed"] for r in second)
    assert all(isinstance(s, int) and 0 <= s < 2 ** 31 for s in seeds1)
    assert seeds1 == seeds2                                                  # même configuration, mêmes graines
    assert len(set(seeds1)) > len(seeds1) * 0.7                              # et une par agent, saison, nature et tour


def test_the_seed_is_only_sent_to_providers_that_honour_it(tmp_path):
    prov = {"fake": {"api_key_env": None, "rpm": 0, "json_schema": True}, "scripted": {"latency_scale": 0.0}}
    _, _, requests = adaptive_game(tmp_path, "s12g", seasons=1, providers=prov)
    assert requests and all(r["seed"] is None for r in requests)
