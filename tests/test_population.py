"""Composition de base et populations choisies par le joueur."""
from __future__ import annotations

import json
import random

import pytest

from filets.catalog import build_catalog
from filets.config import ROOT, load_config, normalize
from filets.profiles import (ARCHETYPES, HAMLETS, archetype_defaults, build_population, custom_to_profiles,
                             validate_custom)
from helpers import cfg_for, play


def spec(**kw):
    base = {"first_name": "Aldric", "hamlet": "Ostrel", "archetype": "taiseux", "experience": 20, "wealth": 500,
            "debt_payment": 0, "kind": "llm", "tier": "auto"}
    return {**base, **kw}


def test_base_population_is_unchanged():
    """La composition de base reste celle que le moteur générait avant le menu (run d'exemple fourni)."""
    run = ROOT / "runs" / "exemple-async-scripted"
    cfg_old = json.loads((run / "config.json").read_text(encoding="utf-8"))
    start = json.loads((run / "events.jsonl").read_text(encoding="utf-8").splitlines()[0])["payload"]
    cfg = load_config(None, {"population": {"fishers": cfg_old["population"]["fishers"]},
                             "run": {"seed": cfg_old["run"]["seed"]}})
    now = {p.id: p.public() for p in build_population(cfg, random.Random(cfg["run"]["seed"]))}
    assert len(now) == len(start["agents"]) == 9
    for a in start["agents"]:
        for key, value in a.items():
            if key in ("offset_days",):
                continue
            assert now[a["id"]][key] == value, (a["id"], key)


def test_catalog_offers_the_default_fishers_all_set_to_ai_auto():
    cfg = load_config(None)
    cat = build_catalog(cfg)
    json.dumps(cat)                                   # sérialisable tel quel
    assert cat["hamlets"] == HAMLETS and len(cat["archetypes"]) == 4
    base = cat["base_population"]
    generated = [p for p in build_population(cfg, random.Random(cfg["run"]["seed"])) if p.role == "pecheur"]
    assert len(base) == len(generated) == 8
    # les mêmes personnages que le moteur génère par défaut...
    for s, p in zip(base, generated):
        assert (s["first_name"], s["hamlet"], s["archetype"], s["experience"], s["wealth"]) == \
               (p.first_name, p.hamlet, p.archetype, p.experience, p.wealth)
    # ...mais tous avec le cerveau « IA auto » (le moteur en ligne de commande garde, lui, 25 % d'agents à règles)
    assert all(s["kind"] == "llm" and s["tier"] == "auto" for s in base)
    assert sum(p.kind == "rule" for p in generated) == 2
    assert validate_custom(base) == []                # la composition de base est elle-même une population valide
    assert cat["limits"]["fishers"] == [1, 24]


def test_ai_auto_picks_the_large_model_from_experience_only():
    """« IA auto » : grand modèle à partir de 15 ans de pêche, petit en dessous : l'expérience seule décide (A5)."""
    cfg = load_config(None)
    base = build_catalog(cfg)["base_population"]
    profiles = custom_to_profiles(base, cfg["population"]["large_model_min_experience"])
    for spec, p in zip(base, profiles):
        assert p.kind == "llm"
        assert p.tier == ("grand" if spec["experience"] >= 15 else "petit"), (spec["first_name"], spec["experience"])
    assert {p.tier for p in profiles} == {"grand", "petit"}     # la composition de base utilise bien les deux niveaux


def test_custom_population_is_used_as_given(tmp_path):
    fishers = [
        spec(first_name="Maëlle", hamlet="Bramois", archetype="beau_parleur", experience=30, kind="llm", tier="auto"),
        spec(first_name="Hugo", hamlet="Hennad", archetype="nouveau_venu", experience=2, debt_payment=150,
             wealth=90, kind="llm", tier="grand"),
        spec(first_name="Inès", hamlet="Hennad", archetype="ancienne_famille", experience=10, kind="rule"),
    ]
    events = play(tmp_path, seasons=1, time__mode="sync", population__custom=fishers, population__elder=False)
    start = events[0]["payload"]
    agents = start["agents"]
    assert [a["id"] for a in agents] == ["F01", "F02", "F03"]            # pas d'ancien demandé
    assert [a["name"] for a in agents] == ["Maëlle de Bramois", "Hugo de Hennad", "Inès de Hennad"]
    assert [a["hamlet"] for a in agents] == ["Bramois", "Hennad", "Hennad"]
    assert [a["experience"] for a in agents] == [30, 2, 10]
    assert [a["tier"] for a in agents] == ["grand", "grand", None]       # auto = par expérience ; choix explicite ; règles = aucun
    assert [a["kind"] for a in agents] == ["llm", "llm", "rule"]
    assert agents[1]["debt_payment"] == 150 and agents[1]["wealth"] == 90
    assert start["lake"]["capacity"] == pytest.approx(3 * 12.5)          # la capacité suit le nombre de pêcheurs
    assert start["population"] == {"fishers": 3, "rule_fraction": pytest.approx(1 / 3)}
    assert {e["payload"]["hamlet"] for e in events if e["type"] == "catch"} == {"Bramois", "Hennad"}


def test_elder_can_be_kept_and_made_a_rule_agent(tmp_path):
    fishers = [spec(), spec(first_name="Odile", hamlet="Tilque")]
    events = play(tmp_path, seasons=1, time__mode="sync", population__custom=fishers, population__elder=True,
                  population__elder_kind="rule")
    elder = [a for a in events[0]["payload"]["agents"] if a["role"] == "ancien"][0]
    assert elder["kind"] == "rule" and elder["tier"] is None
    # tous les pêcheurs à règles n'imposent plus un ancien à règles quand la liste est choisie à la main
    events = play(tmp_path, run_id="t2", seasons=1, time__mode="sync", population__custom=[spec(kind="rule")],
                  population__elder=True, population__elder_kind="llm")
    elder = [a for a in events[0]["payload"]["agents"] if a["role"] == "ancien"][0]
    assert elder["kind"] == "llm" and elder["tier"] == "grand"


def test_tier_follows_experience_threshold():
    ps = custom_to_profiles([spec(experience=14), spec(experience=15), spec(experience=40, tier="petit")], 15)
    assert [p.tier for p in ps] == ["petit", "grand", "petit"]


def test_names_use_the_right_particle():
    ps = custom_to_profiles([spec(hamlet="Ostrel"), spec(hamlet="Hennad", first_name="Rémi")], 15)
    assert [p.name for p in ps] == ["Aldric d’Ostrel", "Rémi de Hennad"]


def test_archetype_defaults_are_inside_their_ranges():
    for arch, a in ARCHETYPES.items():
        d = archetype_defaults(arch)
        assert a["experience"][0] <= d["experience"] <= a["experience"][1]
        assert a["wealth"][0] <= d["wealth"] <= a["wealth"][1]
        assert d["debt_payment"] == a["debt_payment"]


@pytest.mark.parametrize("bad, fragment", [
    ([], "au moins un"),
    ([spec(archetype="pirate")], "archétype"),
    ([spec(hamlet="Atlantis")], "hameau"),
    ([spec(kind="robot")], "type"),
    ([spec(tier="geant")], "modèle"),
    ([spec(experience=-1)], "experience"),
    ([spec(wealth="beaucoup")], "wealth"),
    ([spec(debt_payment=True)], "debt_payment"),
    (["F01"], "fiche invalide"),
])
def test_invalid_populations_are_explained(bad, fragment):
    errs = validate_custom(bad)
    assert errs and any(fragment in e for e in errs), errs


def test_normalize_derives_count_and_rule_fraction_from_the_list():
    cfg = load_config(None)
    cfg["population"]["custom"] = [spec(kind="rule"), spec(), spec(), spec(kind="rule")]
    normalize(cfg)
    assert cfg["population"]["fishers"] == 4 and cfg["population"]["rule_fraction"] == 0.5
    assert cfg["lake"]["capacity_resolved"] == pytest.approx(4 * 12.5)
    cfg["population"]["custom"] = [spec(archetype="pirate")]
    with pytest.raises(ValueError):
        normalize(cfg)


def test_many_fishers_stay_playable(tmp_path):
    fishers = [spec(first_name=f"P{i}", hamlet=HAMLETS[i % 4], archetype=list(ARCHETYPES)[i % 4], kind="rule")
               for i in range(24)]
    events = play(tmp_path, seasons=2, time__mode="async", population__custom=fishers, population__elder=False)
    assert len([e for e in events if e["type"] == "catch"]) == 48
