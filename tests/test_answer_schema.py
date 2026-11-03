"""Réponse des IA contrainte par un schéma JSON (Ollama).

Constat : avec la justification placée avant la prise (pour que le nombre s'écrive APRÈS le raisonnement), les petits modèles
oubliaient souvent le champ « prise » : la décision retombait sur la règle de repli, qui tient compte du stock, et masquait
justement ce qu'on voulait mesurer. Un schéma imposé au fournisseur garantit tous les champs, dans l'ordre voulu, et borne les
textes.
"""
from __future__ import annotations

import asyncio
import re

import pytest

from filets.config import load_config
from filets.llm import OpenAICompatClient
from filets.prompts import answer_schema
from test_rumors import FOUR, Recorder, play_with_announcement

LLM_CFG = {"temperature": 0.7, "max_tokens": 50, "json_mode": True, "timeout_s": 5, "max_retries": 0}
MSGS = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


# ---------------------------------------------------------------- le schéma
def test_catch_schema_puts_the_reasoning_before_the_number():
    schema = answer_schema("catch", brief=True)
    # puis ce qu'il déclarera à l'ancien, une fois sa prise décidée
    assert list(schema["properties"]) == ["justification", "prise", "declaration"]
    assert schema["required"] == ["justification", "prise", "declaration"] and schema["additionalProperties"] is False
    assert schema["properties"]["justification"]["maxLength"] == 160
    assert answer_schema("catch", brief=False)["properties"]["justification"]["maxLength"] == 400


def test_speak_schema_asks_every_field_and_lets_the_optional_ones_be_null():
    fisher = answer_schema("speak", brief=True, fisher=True)
    assert list(fisher["properties"]) == ["message", "destinataire", "proposition_type", "proposition_valeur", "proposition_cible", "soutien", "promesse", "accuse",
                                          "confiance", "exclure", "reautoriser", "patrouille"]
    assert fisher["required"] == list(fisher["properties"])
    # son jugement de confiance : identifiant -> de −3 à +3, rien de plus
    assert fisher["properties"]["confiance"]["additionalProperties"] == {"type": "integer", "minimum": -3, "maximum": 3}
    assert fisher["properties"]["proposition_type"]["enum"] == ["quota", "reserve", "repos", "sorties", "bateau", None]
    for k in ("proposition_valeur", "promesse"):
        assert fisher["properties"][k]["type"] == ["number", "null"]
    for k in ("soutien", "accuse"):
        assert fisher["properties"][k]["type"] == ["string", "null"] and fisher["properties"][k]["maxLength"] == 8
    elder = answer_schema("speak", fisher=False)
    assert "promesse" not in elder["properties"] and "accuse" in elder["properties"]      # l'ancien ne promet pas de pêche
    assert "confiance" in elder["properties"] and "exclure" not in elder["properties"]   # il juge, mais ne sanctionne pas


# ---------------------------------------------------------------- le client
def request_formats(recorder):
    return [r["response_format"] for r in recorder.requests]


def complete(rec, schema=True, json_schema=True, hint_extra=None):
    async def run():
        client = OpenAICompatClient("ollama", rec.url, None, 0, LLM_CFG, timeout_s=5, json_schema=json_schema)
        try:
            hint = {"purpose": "catch", **({"schema": answer_schema("catch", True)} if schema else {}), **(hint_extra or {})}
            return await client.complete("m", MSGS, hint, "petit")
        finally:
            await client.http.aclose()

    return asyncio.run(run())


def test_a_schema_capable_provider_gets_the_schema():
    rec = Recorder()
    res = complete(rec)
    rec.close()
    assert res.status == "ok"
    fmt = request_formats(rec)[0]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["name"] == "catch" and fmt["json_schema"]["strict"] is True
    assert list(fmt["json_schema"]["schema"]["properties"]) == ["justification", "prise", "declaration"]


def test_other_providers_keep_the_free_json_mode():
    for kwargs in ({"json_schema": False}, {"schema": False}):
        rec = Recorder()
        complete(rec, **kwargs)
        rec.close()
        assert request_formats(rec)[0] == {"type": "json_object"}, kwargs


def test_a_refused_schema_falls_back_to_free_json_then_to_nothing():
    rec = Recorder(reject=("json_schema",))
    res = complete(rec)
    rec.close()
    assert res.status == "ok"
    assert [f["type"] for f in request_formats(rec)] == ["json_schema", "json_object"]
    rec = Recorder(reject=("json_schema", "json_object"))
    res = complete(rec)
    rec.close()
    assert res.status == "ok" and [f and f["type"] for f in request_formats(rec)] == ["json_schema", "json_object", None]


def test_ollama_gets_schemas_by_default_and_other_providers_do_not():
    providers = load_config(None)["llm"]["providers"]
    assert providers["ollama"]["json_schema"] is True
    assert all(not p.get("json_schema") for name, p in providers.items() if name != "ollama")


# ---------------------------------------------------------------- dans une partie
def test_every_ai_decision_of_a_game_asks_for_its_schema(tmp_path):
    rec = Recorder()
    world, events = play_with_announcement(tmp_path, "sch1", None, provider=rec, seasons=2,
                                           llm_overrides={"providers": {"fake": {"base_url": rec.url, "api_key_env": None, "rpm": 0,
                                                                                  "json_schema": True},
                                                                         "scripted": {"latency_scale": 0.0}}})
    rec.close()
    assert rec.requests
    for r in rec.requests:
        fmt = r["response_format"]
        assert fmt["type"] == "json_schema"
        props = list(fmt["json_schema"]["schema"]["properties"])
        assert props == (["justification", "prise", "declaration"] if '"prise"' in r["user"] else
                         ["message", "destinataire", "proposition_type", "proposition_valeur", "proposition_cible", "soutien", "promesse", "accuse", "confiance",
                          "exclure", "reautoriser", "patrouille"]), props
    decisions = [e for e in events if e["type"] == "decision" and e["payload"]["agent_kind"] == "llm"]
    assert decisions and not any(e["payload"]["fallback"] for e in decisions)


def test_the_catch_question_names_the_two_fields_in_the_schema_order(tmp_path):
    rec = Recorder()
    play_with_announcement(tmp_path, "sch2", None, provider=rec, seasons=1)
    rec.close()
    asks = [r["user"].split("Réponds en JSON")[1] for r in rec.requests if '"prise"' in r["user"]]
    assert asks and all(a.index('"justification"') < a.index('"prise"') for a in asks)


def test_a_displayed_limit_is_never_above_the_real_one():
    """Une partie réelle a signalé « prise 3.64 hors de [1, 3.63636] » : la limite affichée était arrondie vers le haut."""
    from filets import prompts

    for cap in (3.63636, 6.25, 3.65, 7.0, 10.999):
        obs = {"boat_capacity": cap, "min_catch": 1.0, "boat": "chaloupe"}
        shown = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", prompts.catch_range(obs))]
        assert max(shown) <= cap and cap - max(shown) < 0.011, (cap, shown)
        assert all(v <= cap for v in prompts.catch_levels(cap, lo=1.0))
        assert f"à {prompts.cap_text(cap)} t" in prompts.boat_line(obs)


def test_the_trust_judgment_of_an_ai_is_closed_on_the_known_fishers():
    """Sans cela, un petit modèle répétait les mêmes clés jusqu'à épuiser sa réponse (« unparseable » en pleine partie)."""
    trust = answer_schema("speak", ids=["F01", "F02"])["properties"]["confiance"]
    assert set(trust["properties"]) == {"F01", "F02"} and trust["additionalProperties"] is False
    assert trust["properties"]["F01"]["maximum"] == 3
    from filets import prompts
    assert prompts.debrief_schema(["F03"])["properties"]["confiance"]["properties"].keys() == {"F03"}
    assert answer_schema("speak")["properties"]["confiance"]["additionalProperties"]["maximum"] == 3      # sans identifiants : comme avant


def test_a_rule_in_force_is_kept_by_proposing_nothing_and_its_record_is_given():
    """Un petit modèle recopiait le quota en vigueur d'une veillée à l'autre (7 réponses sur 12 à l'identique, avec 2,1 t)."""
    from filets import prompts

    obs = {"rule": {"quota": 2.1, "supported": True}, "last_season_catches": [3.0, 3.0, 2.0, 2.1]}
    assert "Bilan de la règle de 2.1 t : parmi les 4 pêcheurs dont tu connais la prise, 2 l'ont dépassée et 2 l'ont respectée" \
        in prompts.rule_review(obs)
    assert prompts.rule_review({"rule": None, "last_season_catches": [3.0]}) == "" and prompts.rule_review({"rule": obs["rule"]}) == ""


def test_the_declaration_is_the_catch_unless_one_chooses_to_hide_some():
    from filets import prompts
    from test_reflection_profile import Profile, long_obs

    text = prompts.catch_messages(Profile(), long_obs(), 100.0)[1]["content"]
    assert "exactement ta prise" in text and "Tu la déclares telle quelle" in text
