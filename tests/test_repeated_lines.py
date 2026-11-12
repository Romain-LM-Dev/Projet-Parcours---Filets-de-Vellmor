"""Les répliques redites, les règles déjà en vigueur reproposées, et le récit du narrateur (nombres vérifiés)."""
from __future__ import annotations

import asyncio

from filets.bus import LocalBus
from filets.world import World
from helpers import cfg_for, read_events
from test_narration import elder_game, kinds
from test_rumors import FOUR, Recorder

SAID = "La saison à venir, je déclencherais une patrouille du lac pour contrôler la préservation de la faune et de la flore."


def world_with(tmp_path, *lines):
    world = World(cfg_for(tmp_path, seasons=1, population__custom=FOUR), LocalBus(), "redite")
    for i, text in enumerate(lines):
        world.events.index[f"u{i}"] = {"type": "utterance", "season": 2, "payload": {"text": text, "speaker": "F01"}}
    return world


def test_repeated_line_cases(tmp_path):
    w = world_with(tmp_path, SAID, "Proposons une règle de quota : 3 tonnes par pêcheur et par saison.",
                   "Je prendrai 2.1 tonnes.", "Je soutiendrai la proposition de quota à 4 tonnes par pêcheur.")
    hit = w.repeated_line(SAID + " Ce n'est pas la première fois que")
    assert hit == {"text": SAID, "speaker": "F01", "season": 2}
    assert w.repeated_line("Proposons une règle de quota : 3 tonnes par pêcheur par saison.")
    assert w.repeated_line("Je prendrai 1.8 tonnes.") is None
    assert w.repeated_line("Je soutiens la proposition de quota à 4 t par pêcheur.") is None


def play_fake(tmp_path, run_id, rec, seasons):
    """Une partie de quatre pêcheurs, tous au conseil, contre un faux fournisseur ; (événements, demandes reçues)."""
    cfg = cfg_for(tmp_path, seasons=seasons, population__custom=FOUR, population__elder=True, population__elder_kind="llm",
                  scenario__council="all")
    cfg["llm"]["providers"]["fake"] = {"base_url": rec.url, "api_key_env": None, "rpm": 0}
    cfg["llm"]["tiers"] = {"grand": {"provider": "fake", "model": "m"}, "petit": {"provider": "fake", "model": "m"}}
    asyncio.run(World(cfg, LocalBus(), run_id).run())
    rec.close()
    return read_events(tmp_path, run_id), rec.requests


def test_a_repeated_line_is_asked_again_then_silence(tmp_path):
    events, requests = play_fake(tmp_path, "redite-ia", Recorder(vary=False), 2)
    asked = [r for r in requests if "a déjà été dit (par" in r["user"]]
    assert asked and "Ne le répète pas" in asked[0]["user"]
    told = [e["payload"] for e in kinds(events, "incident")]
    assert any("réplique déjà dite" in i["detail"] and i["handled_by"] == "nouvelle réplique demandée" for i in told)
    assert any(i["incident_type"] == "invalid_value" and i["handled_by"] == "silence" for i in told)
    # (les répliques d'un même tour se préparent en même temps : seules celles des saisons suivantes peuvent en redire une)
    thought = {e["event_id"] for e in kinds(events, "decision") if e["payload"]["llm_call_id"]}
    told = [e for e in kinds(events, "utterance") if e["payload"]["decision_event_id"] in thought and e["payload"]["text"]]
    assert {e["payload"]["text"] for e in told if e["season"] == 1}
    assert not [e for e in told if e["season"] == 2]            # redites de la saison 1 : redemandées, puis silence


def test_a_rule_already_in_force_is_not_proposed_again(tmp_path):
    events, _ = play_fake(tmp_path, "en-vigueur", Recorder(speech={"proposition_quota": 2.0}), 3)     # chaque réplique propose 2 t
    adopted = [e for e in kinds(events, "norm_adopted") if e["payload"]["scope"] == "valley"]
    assert adopted and adopted[0]["season"] == 1
    proposed = [e["season"] for e in kinds(events, "proposal") if e["payload"]["scope"] == "valley" and abs(e["payload"]["value"] - 2.0) < 0.05]
    assert proposed and set(proposed) == {1}                   # la règle vaut déjà : rien de nouveau aux saisons 2 et 3


def test_a_sentence_with_an_invented_number_is_removed(tmp_path):
    rec = "Le lac a donné 109.2 t cette saison. La parole n'a pas tenu."
    events, _ = elder_game(tmp_path, "recit-nombre", rec)
    [n] = kinds(events, "narration")
    story = n["payload"]["text"].split("\n\n")[0]
    assert story == "La parole n'a pas tenu." and n["payload"]["source"] == "narrateur"
    assert any(e["payload"]["handled_by"] == "phrases retirées" for e in kinds(events, "incident"))


def test_the_story_is_cut_at_a_whole_sentence():
    assert World._whole_sentences("Le lac est bas. Hugo a menti. Isaure a dé") == "Le lac est bas. Hugo a menti."
