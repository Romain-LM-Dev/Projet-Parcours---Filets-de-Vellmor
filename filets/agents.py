"""Agents de la vallée : décision de prise et prise de parole.

Le même chemin sert aux agents LLM et aux agents à règles, pour que leurs décisions
soient tracées de la même façon (événement `decision` avec horizon d'information,
souvenirs et documents retrouvés, justification ou règle appliquée).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import prompts
from .llm import detect_drift, extract_json, to_number
from .memory import MemoryStore
from .policies import catch_rule, speak_rule
from .profiles import Profile


@dataclass
class Agent:
    profile: Profile
    memory: MemoryStore
    rng: random.Random
    wealth: float
    offset_days: float = 0.0                       # rythme propre en mode asynchrone
    catches: dict[int, float] = field(default_factory=dict)
    last_decision: dict | None = None
    # ce que l'agent a constaté du lac, dans l'ordre : {season, phase, label, t, est, event_id}. C'est SON estimation (à l'œil,
    # donc bruitée) à chaque ouverture de pêche et à chaque veillée ; `event_id` est la décision qui l'a portée (traçabilité F6).
    stock_seen: list[dict] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.profile.id

    @property
    def is_fisher(self) -> bool:
        return self.profile.role == "pecheur"

    @property
    def archetype(self) -> str:
        return self.profile.archetype


@dataclass
class Outcome:
    value: float | None
    data: dict
    decision: dict          # événement `decision`
    ok: bool = True


def _note_observation(obs: dict, dec: dict) -> None:
    """L'estimation du lac faite pour cette décision se rattache à l'événement `decision` qui l'a portée."""
    entry = obs.get("_entry")
    if entry is not None and entry["event_id"] is None:
        entry["event_id"] = dec["event_id"]


async def _ask_llm(world, agent: Agent, purpose: str, messages: list[dict], state: dict):
    """Appelle le LLM et classe les dérives. Renvoie (données JSON ou None, llm_result, flags)."""
    brief = prompts.is_brief(world.cfg["llm"])
    hint = {"purpose": purpose, "archetype": agent.archetype, "state": state,
            "schema": prompts.answer_schema(purpose, brief, agent.is_fisher)}     # imposé aux fournisseurs qui le savent
    if brief:
        hint["max_tokens"] = prompts.BRIEF_MAX_TOKENS[purpose]       # réflexion rapide : réponse courte, appel plus court
    res = await world.router.complete(agent.id, agent.profile.tier, purpose, messages, hint)
    if res.status != "ok":
        itype = "quota" if res.status == "quota" else "no_response"
        world.incident(agent.id, itype, res.detail or res.status, "règle de repli", res.call_id)
        return None, res, {}
    data = extract_json(res.text)
    if data is None:
        world.incident(agent.id, "unparseable", (res.text or "")[:200], "règle de repli", res.call_id)
        return None, res, {}
    texts = [str(data.get(k, "")) for k in ("justification", "message")]
    oor, posture = detect_drift(*texts)
    if oor:
        world.incident(agent.id, "out_of_role", " ".join(texts)[:200], "action conservée, sortie de rôle signalée",
                       res.call_id)
    elif posture:
        world.incident(agent.id, "assistant_posture", " ".join(texts)[:200], "action conservée, posture signalée",
                       res.call_id)
    return data, res, {"out_of_role": oor}


async def decide_catch(world, agent: Agent, horizon: float) -> Outcome:
    obs, state, retrieved, used = world.observe(agent, horizon, "catch")
    p = agent.profile
    common = {"agent": agent.id, "agent_kind": p.kind, "decision_type": "catch", "info_horizon": round(horizon, 6),
              "retrieved": retrieved, "used_event_ids": used,
              "observed": {"stock_estimate": state["stock_estimate"], "stock_true": state["stock_true"],
                           "quota": state["quota"]}}
    if p.kind == "rule":
        v, rule = catch_rule(agent.archetype, state)
        dec = world.events.emit("decision", {**common, "justification": f"Règle appliquée : {rule}.", "rule": rule,
                                             "value": v, "fallback": False, "model": None, "tier": None,
                                             "llm_call_id": None}, actor=agent.id)
        _note_observation(obs, dec)
        agent.last_decision = dec
        return Outcome(v, {"prise": v}, dec)

    brief = prompts.is_brief(world.cfg["llm"])
    data, res, flags = await _ask_llm(world, agent, "catch", prompts.catch_messages(p, obs, world.capacity, brief), state)
    fallback, rule = False, None
    v = to_number(data.get("prise")) if data else None
    just = str(data.get("justification", "")).strip() if data else ""
    if data is not None and v is None:
        world.incident(agent.id, "invalid_value", f"prise absente : {str(data)[:150]}", "règle de repli", res.call_id)
    if v is not None and not (0 <= v <= state["boat_capacity"]):
        world.incident(agent.id, "invalid_value", f"prise {v} hors de [0, {state['boat_capacity']}]", "bornage",
                       res.call_id)
        v = max(0.0, min(state["boat_capacity"], v))
    if v is None:
        v, rule = catch_rule(agent.archetype, state)
        fallback = True
        just = f"(repli) Règle appliquée : {rule}."
    v = round(v, 1)
    dec = world.events.emit("decision", {**common, "justification": just or "(sans justification)", "rule": rule,
                                         "value": v, "fallback": fallback, "model": res.model, "tier": res.tier,
                                         "llm_call_id": res.call_id, "out_of_role": flags.get("out_of_role", False)},
                            actor=agent.id)
    _note_observation(obs, dec)
    agent.last_decision = dec
    return Outcome(v, {"prise": v}, dec)


async def speak(world, agent: Agent, assembly, rnd: int, horizon: float) -> Outcome:
    obs, state, retrieved, used = world.observe(agent, horizon, "speak", assembly=assembly, rnd=rnd)
    p = agent.profile
    arch = agent.archetype
    common = {"agent": agent.id, "agent_kind": p.kind, "decision_type": "speak", "info_horizon": round(horizon, 6),
              "retrieved": retrieved, "used_event_ids": used, "value": None,
              "observed": {"stock_estimate": state["stock_estimate"], "stock_true": state["stock_true"],
                           "quota": state["quota"]}}
    if p.kind == "rule":
        data, rule = speak_rule(arch, state)
        dec = world.events.emit("decision", {**common, "justification": f"Règle appliquée : {rule}.", "rule": rule,
                                             "fallback": False, "model": None, "tier": None, "llm_call_id": None},
                                actor=agent.id)
        _note_observation(obs, dec)
        agent.last_decision = dec
        return Outcome(None, data, dec)

    brief = prompts.is_brief(world.cfg["llm"])
    data, res, flags = await _ask_llm(world, agent, "speak", prompts.speak_messages(p, obs, world.capacity, brief), state)
    fallback, rule = False, None
    if data is None or not str(data.get("message", "")).strip():
        if data is not None:
            world.incident(agent.id, "invalid_value", "message vide", "règle de repli", res.call_id)
        data, rule = speak_rule(arch, state)
        fallback = True
    if fallback:
        just = f"(repli) Règle appliquée : {rule}."
    else:
        acts = []
        if to_number(data.get("proposition_quota")) is not None:
            acts.append(f"propose {to_number(data.get('proposition_quota')):g} t")
        if data.get("soutien"):
            acts.append(f"soutient {data.get('soutien')}")
        if to_number(data.get("promesse")) is not None:
            acts.append(f"promet {to_number(data.get('promesse')):g} t")
        if data.get("accuse"):
            acts.append(f"accuse {data.get('accuse')}")
        just = f"« {str(data.get('message', '')).strip()[:300]} »" + (f" ({', '.join(acts)})" if acts else "")
    dec = world.events.emit("decision", {**common, "justification": just, "rule": rule, "fallback": fallback,
                                         "model": res.model, "tier": res.tier, "llm_call_id": res.call_id,
                                         "out_of_role": flags.get("out_of_role", False)}, actor=agent.id)
    _note_observation(obs, dec)
    agent.last_decision = dec
    return Outcome(None, data, dec)
