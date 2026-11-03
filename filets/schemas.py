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
    {"actor": STR_OR_NULL, "replay": BOOL, "replayed_at": STR,
     "sim_text": STR},      # le temps en toutes lettres (« saison 2 (été), jour 25, le soir (18 h) »)
)

PAYLOADS: dict[str, dict] = {
    "run_start": obj({
        "mode": {"enum": ["sync", "async"]}, "seed": INT, "seasons": INT,
        "lake": obj({"capacity": NUM, "stock": NUM, "growth_rate": NUM, "collapse_ratio": NUM,
                     "sustainable_yield": NUM}),
        "agents": {"type": "array", "items": {"type": "object"}},
        "hamlets": IDS, "scenario": {"type": "object"}, "season_days": NUM, "config_hash": STR,
        "llm_tiers": {"type": "object"},
    }, {"label": STR, "population": {"type": "object"}, "boats": {"type": "object"},
        # les lacs de la vallée : nom, capacité, stock de départ, repeuplement, villages et pêcheurs
        "lakes": {"type": "array", "items": {"type": "object"}},     # (chacun avec ses parcelles `cells` : [i, j, profondeur, chance])
        "map": {"type": "object"}}),     # la maille des lacs (`grid`) et la place de chaque village dans le sol (`hamlets`)
    # le remplissage de chaque parcelle de chaque lac (dans l'ordre de `cells`), après le repeuplement
    "lake_cells": obj({"lakes": {"type": "object"}}),
    "run_end": obj({"reason": STR, "seasons_completed": INT}),
    # `conditions` : la saison de l'année, ses facteurs (pêche, repeuplement) et les événements en cours (voir `climate.py`)
    "season_start": obj({"stock": NUM}, {"mode": {"enum": ["sync", "async"]}, "conditions": {"type": "object"},
                                        "lakes": {"type": "object"}}),      # (plusieurs lacs) le stock de chacun
    "phase": obj({"name": {"enum": ["fishing", "assembly", "regrowth"]}, "state": {"enum": ["open", "close"]}}),
    "decision": obj(
        {"agent": STR, "agent_kind": {"enum": ["llm", "rule"]}, "decision_type": {"enum": ["catch", "speak"]},
         "info_horizon": NUM, "justification": STR, "retrieved": RETRIEVED, "used_event_ids": IDS,
         "fallback": BOOL},
        {"model": STR_OR_NULL, "tier": STR_OR_NULL, "rule": STR_OR_NULL, "llm_call_id": STR_OR_NULL,
         "value": {"type": ["number", "null"]}, "observed": {"type": "object"}, "out_of_role": BOOL,
         "system": {"enum": ["S1", "S2"]},
         "declared": NUM_OR_NULL,       # prise : ce que le pêcheur compte déclarer à l'ancien
         "lake": STR_OR_NULL},          # prise, plusieurs lacs : le lac où il a choisi de pêcher, s'il n'est pas le sien
    ),
    "catch": obj({"agent": STR, "hamlet": STR, "requested": NUM, "landed": NUM, "stock_observed": NUM,
                  "stock_before": NUM, "stock_after": NUM, "decision_event_id": STR, "info_horizon": NUM,
                  "rationed": BOOL, "stock_at_horizon": NUM, "stock_at_action": NUM},
                 {"zone": STR, "secret": BOOL,        # où il a pêché ; en cachette (interdit de pêche)
                  "lake": STR,         # (plusieurs lacs) le lac où il a pêché
                  # ailleurs que dans le lac de son village : la route (jours, aller), ce qu'elle a coûté (écus), le lac de son village
                  "away": BOOL, "home_lake": STR, "travel_days": NUM, "travel_cost": NUM,
                  "yield": NUM,        # ce que la pêche a rapporté par rapport à la prise visée (`requested`), tout compris
                  "luck": NUM,         # dont la chance du pêcheur (moyenne de ses sorties)
                  # ses sorties : le jour, le temps (calme, ordinaire, agité, tempête), la chance, le rendement et les tonnes rapportées
                  "outings": {"type": "array", "items": {"type": "object"}},
                  "cell": {"type": "array", "items": INT},     # la parcelle du lac où il a pêché (i, j sur la maille des lacs)
                  "spot": NUM}),       # ce que ce coin a rendu : sa chance, et le poisson qu'y ont laissé les autres barques
    # ce que le pêcheur déclare à l'ancien en rentrant : les autres ne connaissent que `declared` ; la vraie prise (`landed`)
    # n'est connue que de lui et du joueur
    "report": obj({"agent": STR, "hamlet": STR, "declared": NUM, "landed": NUM, "catch_event_id": STR}),
    # un indice sur la prise de `subject` : relevé de la patrouille, barque vue rentrer (estimation de sa charge), barque d'un interdit vue
    # partant, train de vie ; `public` : dit devant tous à la veillée (sinon, gardé par celui qui l'a vu)
    "clue": obj({"kind": {"enum": ["patrouille", "temoin", "depart", "train_de_vie"]}, "observer": STR_OR_NULL, "subject": STR,
                 "zone": STR, "estimate": NUM_OR_NULL, "public": BOOL}, {"declared": NUM_OR_NULL}),
    # les comptes du lac par l'ancien : ce que la pêche lui a fait perdre, ce que les déclarations en expliquent
    "lake_audit": obj({"drop": NUM, "declared": NUM, "gap": NUM, "significant": BOOL}),
    # un mensonge (ou une sortie en cachette) tenu pour établi par l'ancien sur des indices ; `landed` : la vérité (pour le
    # joueur), `estimated` : ce que la vallée en croit ; `wrongful` : il n'avait pas menti (erreur de jugement)
    "lie_discovered": obj({"agent": STR, "lie_season": INT, "declared": NUM, "landed": NUM,
                           "how": {"enum": ["patrouille", "temoins", "indices"]}, "secret": BOOL, "wrongful": BOOL},
                          {"estimated": NUM_OR_NULL, "witnesses": IDS, "report_event_id": STR_OR_NULL}),
    # interdit de pêche, ou levée de l'interdiction, par un vote de la vallée (`proposal_id`, ses voix `for` sur `voters`)
    "ban": obj({"agent": STR, "banned": BOOL, "reputation": NUM}, {"proposal_id": STR, "for": IDS, "voters": INT}),
    # la patrouille du lac, si le conseil en a voté une : sa route de la saison (étapes : zone = un village ou « large », jours
    # depuis le début de la saison), décidée par son capitaine (un agent) ; puis son installation ou son retrait par un vote du conseil
    "patrol_route": obj({"season": INT, "legs": {"type": "array", "items": obj({"zone": STR, "from_day": NUM, "to_day": NUM},
                                                                                {"follow": STR_OR_NULL, "days": NUM, "by": STR})},
                         "by": STR}, {"why": STR, "captain": STR}),      # captain : laquelle des patrouilles (PAT, PAT2…)
    "patrol": obj({"state": {"enum": ["installed", "lifted"]}, "effective_season": INT, "proposal_id": STR, "for": IDS,
                   "voters": INT, "cost": NUM}),
    # l'élection de l'élu d'un village pour la saison (`ballots` : électeur → candidat choisi, `votes` : voix par candidat)
    "election": obj({"season": INT, "hamlet": STR, "representative": STR, "votes": {"type": "object"}, "voters": INT},
                    {"incumbent": STR_OR_NULL, "ballots": {"type": "object"}}),
    # un événement du climat (voir `climate.py`) arrivé au début de la saison
    "world_event": obj({"kind": STR, "label": STR, "text": STR, "season": INT, "until": INT}, {"stock_factor": NUM}),
    # la confiance que les autres (`values` : observateur → 0..1) accordent à `subject` vient de changer ; `reputation` :
    # la moyenne de la confiance de tous les autres envers lui
    "trust": obj({"subject": STR, "cause": STR, "values": {"type": "object"}, "reputation": NUM},
                 {"source_event_id": STR_OR_NULL, "by": STR, "delta": NUM}),     # `by` : celui qui a jugé, de `delta`
    # une proposition soumise au vote du conseil : interdire de pêche un pêcheur (`exclure`), lever son interdiction (`reautoriser`),
    # installer (`patrouille`) ou retirer (`fin_patrouille`) la patrouille du lac (`target` vide : elle ne vise personne) ; les
    # votes, l'issue
    "sanction_proposal": obj({"proposal_id": STR, "author": STR, "target": STR,
                              "action": {"enum": ["exclure", "reautoriser", "patrouille", "fin_patrouille"]}, "scope": STR,
                              "utterance_id": STR}),
    "sanction_vote": obj({"proposal_id": STR, "agent": STR, "vote": BOOL}),
    "sanction_result": obj({"proposal_id": STR, "target": STR,
                            "action": {"enum": ["exclure", "reautoriser", "patrouille", "fin_patrouille"]},
                            "adopted": BOOL, "for": IDS, "against": IDS, "voters": INT}),
    "sale": obj({"agent": STR, "hamlet": STR, "tonnes": NUM, "price": NUM, "income": NUM, "wealth": NUM}),
    "lake_update": obj({"stock": NUM, "capacity": NUM, "cause": {"enum": ["init", "catch", "regrowth", "injection", "event"]}},
                       # (plusieurs lacs) `stock` et `capacity` sont ceux de tous les lacs ; `lakes` : le stock de chacun ; `lake` :
                       # celui qui change
                       {"delta": NUM, "lakes": {"type": "object"}, "lake": STR}),
    "lake_collapsed": obj({"stock": NUM, "capacity": NUM}, {"lake": STR}),
    # `delegates` : au conseil de la vallée, l'élu de chaque village ; `mode` : sync (on s'entend, à tour de rôle) ou async
    # (chacun s'exprime de son côté)
    "assembly_start": obj({"scope": STR, "participants": IDS},
                          {"mode": {"enum": ["sync", "async"]}, "delegates": {"type": "object"}}),
    "assembly_end": obj({"scope": STR, "adopted_proposal": STR_OR_NULL, "utterances": INT}),
    "utterance": obj({"speaker": STR, "to": STR, "text": STR, "scope": STR, "round": INT,
                      "info_horizon": NUM, "heard": IDS, "decision_event_id": STR}),
    "proposal": obj({"proposal_id": STR, "author": STR, "quota": NUM, "scope": STR, "utterance_id": STR}),
    "support": obj({"agent": STR, "proposal_id": STR, "utterance_id": STR}),
    "promise": obj({"agent": STR, "amount": NUM, "for_season": INT, "utterance_id": STR}),
    # `kept` : d'après la vraie prise ; `known_kept` : d'après ce que la vallée en sait (déclaration, ou mensonge découvert)
    "promise_outcome": obj({"agent": STR, "promise_event_id": STR, "promised": NUM, "landed": NUM, "kept": BOOL,
                            "season": INT}, {"declared": NUM, "known_kept": BOOL}),
    "accusation": obj({"accuser": STR, "accused": STR, "utterance_id": STR}),
    "norm_adopted": obj({"proposal_id": STR, "quota": NUM, "scope": STR, "effective_season": INT,
                         "supporters": IDS, "participants": IDS, "author": STR},
                        {"delegates": {"type": "object"}}),      # au conseil des élus : l'élu de chaque village à cet instant
    "memory_write": obj({"agent": STR, "memory_id": STR, "text": STR, "kind": STR, "importance": NUM,
                         "pinned": BOOL}, {"source_event_id": STR_OR_NULL}),
    "season_end": obj({"stock": NUM, "catches": {"type": "object"}, "wealth": {"type": "object"},
                       "norms_in_force": {"type": "array"}},
                      {"declared": {"type": "object"}, "reputation": {"type": "object"}, "lakes": {"type": "object"}}),
    "incident": obj({"agent": STR, "incident_type": {"enum": [
        "out_of_role", "unparseable", "no_response", "quota", "invalid_value", "assistant_posture",
        "missed_window", "schema_violation", "temporal_violation"]}, "detail": STR, "handled_by": STR},
        {"llm_call_id": STR_OR_NULL}),
    "llm_call": obj({"call_id": STR, "agent": STR, "purpose": STR, "provider": STR, "model": STR, "tier": STR,
                     "prompt_tokens": INT, "completion_tokens": INT, "latency_s": NUM,
                     "status": {"enum": ["ok", "error", "timeout", "quota", "cancelled"]}},
        {"retries": INT, "system": {"enum": ["S1", "S2"]}}),
    "injection": obj({"injection_type": STR, "params": {"type": "object"}, "source": STR}),
    # le récit de la saison par l'ancien, pour le joueur : rédigé par son IA (« ancien ») ou tiré des faits (« faits »)
    "narration": obj({"season": INT, "text": STR, "source": {"enum": ["ancien", "faits"]}, "facts": IDS},
                     {"llm_call_id": STR_OR_NULL}),
    "indicator": obj({"trigger": STR, "values": {"type": "object"}, "source_event_ids": IDS,
                      "lag_s": NUM, "computed_at": NUM}),
}

COMMAND_TYPES = [
    # injections dans la partie en cours
    "drought", "set_communication", "set_visibility", "announcement",
    # pilotage de la partie en cours
    "pause", "resume", "set_speed", "set_mode", "stop",
    # salon : lancer une partie configurée dans le menu, ou y revenir ; faire générer une vallée (villages, pêcheurs, bateaux)
    "start_game", "new_game", "generate_world",
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
