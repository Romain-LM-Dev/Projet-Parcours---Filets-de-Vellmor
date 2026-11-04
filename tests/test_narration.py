"""Le récit du narrateur : à la fin de chaque saison, un narrateur externe et omniscient raconte au joueur ce que la vallée a vécu
(onglet « Récit du narrateur » de Godot). Son IA rédige à partir des seuls faits relevés dans le journal (la vérité de la saison) ;
sans IA, ou sans réponse, le récit reprend les faits."""
from __future__ import annotations

import asyncio

import pytest

from filets.bus import LocalBus
from filets.cli import verify
from filets.world import World
from helpers import cfg_for, play, read_events
from test_rumors import FOUR, Recorder
from test_trust import QUIET, elwen_of, game


def kinds(events, kind):
    return [e for e in events if e["type"] == kind]


def test_each_finished_season_is_told_once_after_its_end(tmp_path):
    events = play(tmp_path, run_id="recit", seasons=3)
    told = kinds(events, "narration")
    assert [n["payload"]["season"] for n in told] == [1, 2, 3]
    for n in told:
        end = next(e for e in kinds(events, "season_end") if e["season"] == n["payload"]["season"])
        assert n["seq"] > end["seq"] and n["payload"]["source"] == "faits" and n["payload"]["facts"]
        assert n["payload"]["text"].startswith(f"Saison {n['payload']['season']}.")
    assert verify("recit", cfg_for(tmp_path))          # schéma du nouvel événement, ordre, cohérence temporelle


def test_the_story_tells_the_true_catches_and_the_lake_stock(tmp_path):
    events = play(tmp_path, run_id="faits", seasons=2)
    for n in kinds(events, "narration"):
        season = n["payload"]["season"]
        # le narrateur sait la vérité : les vraies prises, à côté des déclarations
        real = round(sum(e["payload"]["landed"] for e in kinds(events, "catch") if e["season"] == season), 3)
        said = round(sum(e["payload"]["declared"] for e in kinds(events, "report") if e["season"] == season), 2)
        assert f"Prises réelles : {real:g} t ; prises déclarées : {said:g} t." in n["payload"]["facts"]
        stock = next(e for e in kinds(events, "season_end") if e["season"] == season)["payload"]["stock"]
        assert any(f"{stock:.0f} t après le repeuplement" in f for f in n["payload"]["facts"])
        assert len(n["payload"]["facts"]) <= 14


def test_the_narrator_knows_a_lie_nobody_discovered(tmp_path):
    world, events, _ = game(tmp_path, "menteur", QUIET)
    elwen = elwen_of(world)
    lie = next(e["payload"] for e in kinds(events, "report")
               if e["payload"]["agent"] == elwen.id and e["payload"]["landed"] - e["payload"]["declared"] > 0.05)
    assert not kinds(events, "lie_discovered")
    facts = " ".join(f for n in kinds(events, "narration") for f in n["payload"]["facts"])
    assert (f"Elwen a déclaré {lie['declared']:g} t mais a pêché {lie['landed']:g} t (sans que personne ne le sache)." in facts)


def test_the_story_tells_the_weather_event_and_the_patrol(tmp_path):
    events = play(tmp_path, run_id="conseil", seasons=2, climate__enabled=True,
                  scenario__patrol={"cost": 15, "from_season": 1})
    facts = [f for n in kinds(events, "narration") for f in n["payload"]["facts"]]
    assert any(f.startswith("La patrouille a fait route vers ") for f in facts)
    assert any(f.startswith("Saison de l'année : ") for f in facts)
    assert any(f.startswith("À la veillée, ") for f in facts)


def elder_game(tmp_path, run_id, recit):
    rec = Recorder(recit=recit)
    cfg = cfg_for(tmp_path, seasons=1, population__custom=FOUR, population__elder=True,
                  population__elder_kind="llm")
    cfg["llm"]["providers"]["fake"] = {"base_url": rec.url, "api_key_env": None, "rpm": 0}
    cfg["llm"]["tiers"] = {"grand": {"provider": "fake", "model": "m"}, "petit": {"provider": "fake", "model": "m"}}
    world = World(cfg, LocalBus(), run_id)
    asyncio.run(world.run())
    rec.close()
    return read_events(tmp_path, run_id), rec.requests + rec.narrations


def test_an_external_narrator_tells_the_season_from_the_facts(tmp_path):
    events, requests = elder_game(tmp_path, "narrateur-ia", "Le lac a donné, mais la parole n'a pas tenu.")
    [n] = kinds(events, "narration")
    assert n["payload"]["source"] == "narrateur" and n["payload"]["text"] == "Le lac a donné, mais la parole n'a pas tenu."
    asked = next(r for r in requests if '"recit"' in r["user"])
    assert all(f in asked["user"] for f in n["payload"]["facts"]) and "n'invente rien" in asked["user"]
    assert asked["temperature"] == 0.3 != next(r for r in requests if '"prise"' in r["user"])["temperature"]
    call = next(e["payload"] for e in kinds(events, "llm_call") if e["payload"]["purpose"] == "narration")
    assert call["call_id"] == n["payload"]["llm_call_id"] and call["agent"] == "narrateur" and call["tier"] == "grand"
    assert not n["actor"]


def test_without_an_answer_the_narrator_falls_back_to_the_facts(tmp_path):
    events, _ = elder_game(tmp_path, "narrateur-muet", None)
    [n] = kinds(events, "narration")
    assert n["payload"]["source"] == "faits" and n["payload"]["text"].startswith("Saison 1.")
