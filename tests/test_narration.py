"""Le récit de l'ancien : à la fin de chaque saison, il raconte au joueur ce que la vallée a vécu (onglet « Récit de l'ancien »
de Godot). Son IA rédige à partir des seuls faits relevés dans le journal ; sans IA, ou sans réponse, le récit reprend les faits."""
from __future__ import annotations

import asyncio

import pytest

from filets.bus import LocalBus
from filets.cli import verify
from filets.world import World
from helpers import cfg_for, play, read_events
from test_rumors import FOUR, Recorder


def kinds(events, kind):
    return [e for e in events if e["type"] == kind]


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_each_finished_season_is_told_once_after_its_end(tmp_path, mode):
    over = {"time__fast": False, "time__sim_hours_per_second": 7200} if mode == "async" else {}
    events = play(tmp_path, run_id=f"recit-{mode}", seasons=3, time__mode=mode, **over)
    told = kinds(events, "narration")
    assert [n["payload"]["season"] for n in told] == [1, 2, 3]
    for n in told:
        end = next(e for e in kinds(events, "season_end") if e["season"] == n["payload"]["season"])
        assert n["seq"] > end["seq"] and n["payload"]["source"] == "faits" and n["payload"]["facts"]
        assert n["payload"]["text"].startswith(f"Ce que j'ai vu à la saison {n['payload']['season']}.")
    assert verify(f"recit-{mode}", cfg_for(tmp_path))          # schéma du nouvel événement, ordre, cohérence temporelle


def test_the_story_only_tells_what_the_journal_holds(tmp_path):
    events = play(tmp_path, run_id="faits", seasons=2, time__mode="sync")
    for n in kinds(events, "narration"):
        season = n["payload"]["season"]
        total = round(sum(e["payload"]["landed"] for e in kinds(events, "catch") if e["season"] == season), 2)
        catches = next(f for f in n["payload"]["facts"] if f.startswith("Prises :"))
        assert f"(en tout {total:g} t)" in catches
        stock = next(e for e in kinds(events, "season_end") if e["season"] == season)["payload"]["stock"]
        assert any(f"{stock:.0f} t après le repeuplement" in f for f in n["payload"]["facts"])


def elder_game(tmp_path, run_id, recit):
    rec = Recorder(recit=recit)
    cfg = cfg_for(tmp_path, seasons=1, time__mode="sync", population__custom=FOUR, population__elder=True,
                  population__elder_kind="llm")
    cfg["llm"]["providers"]["fake"] = {"base_url": rec.url, "api_key_env": None, "rpm": 0}
    cfg["llm"]["tiers"] = {"grand": {"provider": "fake", "model": "m"}, "petit": {"provider": "fake", "model": "m"}}
    world = World(cfg, LocalBus(), run_id)
    asyncio.run(world.run())
    rec.close()
    return read_events(tmp_path, run_id), rec.requests


def test_an_ai_elder_tells_the_season_in_its_own_voice_from_the_facts(tmp_path):
    events, requests = elder_game(tmp_path, "ancien-ia", "Le lac a donné, mais la parole n'a pas tenu.")
    [n] = kinds(events, "narration")
    assert n["payload"]["source"] == "ancien" and n["payload"]["text"] == "Le lac a donné, mais la parole n'a pas tenu."
    asked = next(r for r in requests if '"recit"' in r["user"])
    assert all(f in asked["user"] for f in n["payload"]["facts"]) and "N'invente rien" in asked["user"]
    call = next(e["payload"] for e in kinds(events, "llm_call") if e["payload"]["purpose"] == "narration")
    assert call["call_id"] == n["payload"]["llm_call_id"] and n["actor"] == call["agent"]


def test_without_an_answer_the_elder_falls_back_to_the_facts(tmp_path):
    events, _ = elder_game(tmp_path, "ancien-muet", None)
    [n] = kinds(events, "narration")
    assert n["payload"]["source"] == "faits" and n["payload"]["text"].startswith("Ce que j'ai vu à la saison 1.")
