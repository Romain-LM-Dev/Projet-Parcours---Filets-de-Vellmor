"""Contrat d'événements (exigence F4).

Chaque type d'événement a un schéma JSON versionné. La source de vérité est ce module ;
`python -m filets schemas` les exporte dans `schemas/` pour la documentation.
Un événement non conforme est isolé dans le topic de lettres mortes sans arrêter la
simulation (voir `events.EventFactory`).
"""
from __future__ import annotations

from jsonschema import Draft202012Validator

SCHEMA_VERSION = 1

NUM = {"type": "number"}
NUM_OR_NULL = {"type": ["number", "null"]}
STR = {"type": "string"}
STR_OR_NULL = {"type": ["string", "null"]}
INT = {"type": "integer"}
BOOL = {"type": "boolean"}
IDS = {"type": "array", "items": STR}


def obj(required: dict, optional: dict | None = None, extra: bool = False) -> dict:
    props = dict(required)
    props.update(optional or {})
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": extra}


RETRIEVED = {
    "type": "array",
    "items": obj({"id": STR, "source": {"enum": ["corpus", "memory", "pinned", "rumor"]}, "score": NUM, "sim_time": NUM},
                 {"text": STR}),
}

ENVELOPE = obj(
    {
        "type": STR,
        "schema_version": INT,
        "event_id": STR,
        "run_id": STR,
        "seq": INT,
        "sim_time": NUM,
        "sim_label": STR,
        "season": INT,
        "processed_at": NUM,      # secondes réelles depuis le début du run
        "wall_clock": STR,        # horodatage ISO, pour l'historique
        "payload": {"type": "object"},
    },
    {"actor": STR_OR_NULL, "replay": BOOL, "replayed_at": STR},
)

PAYLOADS: dict[str, dict] = {
    "run_start": obj({
        "mode": {"enum": ["sync", "async"]}, "seed": INT, "seasons": INT,
        "lake": obj({"capacity": NUM, "stock": NUM, "growth_rate": NUM, "collapse_ratio": NUM,
                     "sustainable_yield": NUM}),
        "agents": {"type": "array", "items": {"type": "object"}},
        "hamlets": IDS, "scenario": {"type": "object"}, "season_days": NUM, "config_hash": STR,
        "llm_tiers": {"type": "object"},
    }, {"label": STR, "population": {"type": "object"}}),
    "run_end": obj({"reason": STR, "seasons_completed": INT}),
    "season_start": obj({"stock": NUM}, {"mode": {"enum": ["sync", "async"]}}),
    "phase": obj({"name": {"enum": ["fishing", "assembly", "regrowth"]}, "state": {"enum": ["open", "close"]}}),
    "decision": obj(
        {"agent": STR, "agent_kind": {"enum": ["llm", "rule"]}, "decision_type": {"enum": ["catch", "speak"]},
         "info_horizon": NUM, "justification": STR, "retrieved": RETRIEVED, "used_event_ids": IDS,
         "fallback": BOOL},
        {"model": STR_OR_NULL, "tier": STR_OR_NULL, "rule": STR_OR_NULL, "llm_call_id": STR_OR_NULL,
         "value": {"type": ["number", "null"]}, "observed": {"type": "object"}, "out_of_role": BOOL},
    ),
    "catch": obj({"agent": STR, "hamlet": STR, "requested": NUM, "landed": NUM, "stock_observed": NUM,
                  "stock_before": NUM, "stock_after": NUM, "decision_event_id": STR, "info_horizon": NUM,
                  "rationed": BOOL, "stock_at_horizon": NUM, "stock_at_action": NUM}),
    "sale": obj({"agent": STR, "hamlet": STR, "tonnes": NUM, "price": NUM, "income": NUM, "wealth": NUM}),
    "lake_update": obj({"stock": NUM, "capacity": NUM, "cause": {"enum": ["init", "catch", "regrowth", "injection"]}},
                       {"delta": NUM}),
    "lake_collapsed": obj({"stock": NUM, "capacity": NUM}),
    "assembly_start": obj({"scope": STR, "participants": IDS}),
    "assembly_end": obj({"scope": STR, "adopted_proposal": STR_OR_NULL, "utterances": INT}),
    "utterance": obj({"speaker": STR, "to": STR, "text": STR, "scope": STR, "round": INT,
                      "info_horizon": NUM, "heard": IDS, "decision_event_id": STR}),
    "proposal": obj({"proposal_id": STR, "author": STR, "quota": NUM, "scope": STR, "utterance_id": STR}),
    "support": obj({"agent": STR, "proposal_id": STR, "utterance_id": STR}),
    "promise": obj({"agent": STR, "amount": NUM, "for_season": INT, "utterance_id": STR}),
    "promise_outcome": obj({"agent": STR, "promise_event_id": STR, "promised": NUM, "landed": NUM, "kept": BOOL,
                            "season": INT}),
    "accusation": obj({"accuser": STR, "accused": STR, "utterance_id": STR}),
    "norm_adopted": obj({"proposal_id": STR, "quota": NUM, "scope": STR, "effective_season": INT,
                         "supporters": IDS, "participants": IDS, "author": STR}),
    "memory_write": obj({"agent": STR, "memory_id": STR, "text": STR, "kind": STR, "importance": NUM,
                         "pinned": BOOL}, {"source_event_id": STR_OR_NULL}),
    "season_end": obj({"stock": NUM, "catches": {"type": "object"}, "wealth": {"type": "object"},
                       "norms_in_force": {"type": "array"}}),
    "incident": obj({"agent": STR, "incident_type": {"enum": [
        "out_of_role", "unparseable", "no_response", "quota", "invalid_value", "assistant_posture",
        "missed_window", "schema_violation", "temporal_violation"]}, "detail": STR, "handled_by": STR},
        {"llm_call_id": STR_OR_NULL}),
    "llm_call": obj({"call_id": STR, "agent": STR, "purpose": STR, "provider": STR, "model": STR, "tier": STR,
                     "prompt_tokens": INT, "completion_tokens": INT, "latency_s": NUM,
                     "status": {"enum": ["ok", "error", "timeout", "quota", "cancelled"]}}, {"retries": INT}),
    "injection": obj({"injection_type": STR, "params": {"type": "object"}, "source": STR}),
    "indicator": obj({"trigger": STR, "values": {"type": "object"}, "source_event_ids": IDS,
                      "lag_s": NUM, "computed_at": NUM}),
}

COMMAND_TYPES = [
    # injections dans la partie en cours
    "drought", "set_communication", "set_visibility", "announcement",
    # pilotage de la partie en cours
    "pause", "resume", "set_speed", "set_mode", "stop",
    # salon : lancer une partie configurée dans le menu, ou y revenir
    "start_game", "new_game",
]
COMMAND = obj({"type": {"enum": COMMAND_TYPES}},
              {"value": {}, "text": STR, "factor": NUM, "config": {"type": "object"}}, extra=True)

# Message d'état du moteur (topic `status`, hors du flux d'événements d'un run) : ce que l'interface
# affiche dans sa barre de pilotage, et ce qui lui dit si elle doit montrer le menu de démarrage.
STATUS = obj(
    {"state": {"enum": ["idle", "starting", "running", "paused", "ended"]}, "engine_id": STR, "wall_clock": STR},
    {"run_id": STR_OR_NULL, "mode": {"enum": ["sync", "async", None]}, "pending_mode": {"enum": ["sync", "async", None]},
     "speed": NUM, "fast": BOOL, "paused": BOOL, "season": INT, "seasons": INT, "sim_label": STR,
     "end_reason": STR_OR_NULL, "error": STR_OR_NULL,
     "controls": BOOL,      # l'interface peut piloter la partie (faux en rejeu)
     "lobby": BOOL,         # un salon (`serve`) peut lancer la partie suivante
     "detail": STR_OR_NULL, # ce que fait le moteur pendant la préparation (« Chargement du modèle… »)
     "ai": IDS,             # fournisseurs d'IA utilisés par les pêcheurs ([] : aucun ; ["scripted"] : faux LLM)
     # vitesse au-delà de laquelle ce moteur d'IA rate sa fenêtre en asynchrone (null : inconnue) ; l'interface la propose
     "advised_speed": NUM_OR_NULL,
     "catalog": {"type": "object"}},   # options du menu de CE moteur ; le pont le relaie à part (topic `catalog`)
)

_validators = {k: Draft202012Validator(v) for k, v in PAYLOADS.items()}
_env_validator = Draft202012Validator(ENVELOPE)
_cmd_validator = Draft202012Validator(COMMAND)
_status_validator = Draft202012Validator(STATUS)


def validate_event(event: dict) -> list[str]:
    errors = [e.message for e in _env_validator.iter_errors(event)]
    v = _validators.get(event.get("type"))
    if v is None:
        errors.append(f"type d'événement inconnu : {event.get('type')!r}")
    elif isinstance(event.get("payload"), dict):
        errors += [f"payload: {e.message}" for e in v.iter_errors(event["payload"])]
    if event.get("schema_version") not in (None, SCHEMA_VERSION):
        errors.append(f"version de schéma non supportée : {event.get('schema_version')}")
    return errors


def validate_command(cmd: dict) -> list[str]:
    return [e.message for e in _cmd_validator.iter_errors(cmd)]


def validate_status(status: dict) -> list[str]:
    return [e.message for e in _status_validator.iter_errors(status)]
