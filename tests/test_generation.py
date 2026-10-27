"""La génération procédurale de la vallée : déterministe, stable (ajouter un pêcheur ou un village ne rebat pas les fiches),
différente d'une graine à l'autre, équilibrée, avec une flotte réglable."""
from __future__ import annotations

import collections

from filets.bus import LocalBus
from filets.catalog import FLEETS, build_catalog, generate_world
from filets.config import load_config
from filets.engine import Engine
from filets.profiles import FIRST_NAMES, VILLAGE_NAMES
from helpers import cfg_for


def valley(villages, fishers, seed, fleet="mixte"):
    return generate_world(load_config(None), villages, fishers, seed, fleet)["base_population"]


def card(s):
    return (s["first_name"], s["archetype"], s["experience"], s["wealth"], s["boat"])


def test_the_same_parameters_make_the_same_valley():
    assert valley(5, 11, 3) == valley(5, 11, 3)
    assert valley(5, 11, 3) != valley(5, 11, 4)


def test_adding_a_fisher_changes_no_other_card():
    for seed in range(1, 21):
        for n in (3, 8, 13, 19, 23):
            before, after = valley(min(3, n), n, seed), valley(min(3, n), n + 1, seed)
            assert before == after[:n], (seed, n)


def test_changing_the_number_of_villages_only_moves_people():
    for seed in range(1, 11):
        a, b = valley(4, 12, seed), valley(5, 12, seed)
        assert [card(s) for s in a] == [card(s) for s in b]
        assert len({s["hamlet"] for s in b}) == 5


def test_the_seed_changes_who_lives_where():
    layouts = {tuple(sorted((s["hamlet"], s["archetype"]) for s in valley(4, 8, seed))) for seed in range(1, 11)}
    assert len(layouts) >= 5                           # (et pas seulement les prénoms, l'expérience et les bateaux)


def test_villages_and_characters_stay_balanced():
    for v in range(1, 9):
        for n in range(v, 25, 3):
            pop = valley(v, n, 7)
            per, arch = collections.Counter(s["hamlet"] for s in pop), collections.Counter(s["archetype"] for s in pop)
            assert len(per) == v and max(per.values()) - min(per.values()) <= 1, (v, n)
            assert max(arch.values()) - (min(arch.values()) if len(arch) == 4 else 0) <= 1, (v, n)


def test_there_are_enough_different_first_names():
    assert len(set(FIRST_NAMES)) == len(FIRST_NAMES) >= 48
    assert len({s["first_name"] for s in valley(8, 24, 5)}) == 24
    assert len({tuple(s["first_name"] for s in valley(4, 8, seed)) for seed in range(1, 8)}) > 4


def test_the_fleet_sets_the_size_of_the_boats():
    share = {}
    for fleet in ("petits", "mixte", "gros"):
        boats = [s["boat"] for seed in range(40) for s in valley(4, 24, seed, fleet)]
        share[fleet] = {b: boats.count(b) / len(boats) for b in ("barque", "cotre")}
    assert share["petits"]["barque"] > share["mixte"]["barque"] > share["gros"]["barque"]
    assert share["petits"]["cotre"] < share["mixte"]["cotre"] < share["gros"]["cotre"]


def test_the_catalog_offers_the_fleets_and_the_engine_refuses_an_unknown_one(tmp_path):
    cat = build_catalog(load_config(None))
    assert [f["id"] for f in cat["fleets"]] == [f["id"] for f in FLEETS] and cat["defaults"]["fleet"] == "mixte"
    assert cat["fleets"][1]["mix"] == cat["defaults"]["boat_mix"]                 # « mixte » : celle de la configuration
    bus, statuses = LocalBus(), []
    bus.subscribe("status", statuses.append)
    engine = Engine(cfg_for(tmp_path), bus, quiet=True)
    engine.generate({"villages": 4, "fishers": 24, "seed": 3, "fleet": "gros", "id": "g1"})
    assert engine.catalog["generation"]["fleet"] == "gros" and {s["boat"] for s in engine.catalog["base_population"]} >= {"cotre"}
    engine.generate({"villages": 4, "fishers": 8, "seed": 3, "fleet": "pirogues", "id": "g2"})
    assert "flotte" in statuses[-1]["error"] and engine.catalog["generation"]["id"] == "g1"


def test_every_village_of_the_valley_has_a_market_register():
    from filets.config import ROOT
    from filets.rag import Retriever

    values = {"capacity": "100", "price": "100", "upkeep": "150", "half_capacity": "50"}
    four = Retriever(ROOT / "corpus", values)
    assert [p.id for p in Retriever(ROOT / "corpus", values, tuple(VILLAGE_NAMES[:4]), "Bramois").passages] == [p.id for p in four.passages]
    six = Retriever(ROOT / "corpus", values, tuple(VILLAGE_NAMES[:6]), "Bramois")
    for village in ("Varenne", "Corbel"):                      # les deux villages que le corpus écrit à la main ne connaît pas
        mine = [p for p in six.passages if p.visible_to == [village]]
        assert mine and village in mine[0].text and "100 écus" in mine[0].text and "{{" not in "".join(p.text for p in mine)
        assert not [p for p in four.passages if p.visible_to == [village]]
        assert [p.text for p, _ in six.search("registre du marché ventes", village, 0.0, 3) if village in p.text]
