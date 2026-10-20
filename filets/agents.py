"""Agents de la vallée : décision de prise et prise de parole.

Le même chemin sert aux agents LLM et aux agents à règles, pour que leurs décisions
soient tracées de la même façon (événement `decision` avec horizon d'information,
souvenirs et documents retrouvés, justification ou règle appliquée).
"""
from __future__ import annotations

import logging
import random
import zlib
from dataclasses import dataclass, field

from . import prompts, routing
from .llm import detect_drift, extract_json, to_number
from .memory import MemoryStore
from .policies import catch_rule, speak_rule
from .profiles import Profile

log = logging.getLogger("filets.agents")


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


def _seed(world, agent: Agent, purpose: str, state: dict) -> int:
    """Une graine stable par (partie, agent, saison, nature, tour) : le fournisseur qui la respecte (Ollama) redonne la même
    réponse au même prompt, donc une partie rejouée avec la même configuration se déroule de la même façon."""
    key = f"{world.cfg['run']['seed']}|{agent.id}|{world.season}|{purpose}|{state.get('round', 1)}"
    return zlib.crc32(key.encode()) & 0x7FFFFFFF


async def _ask_llm(world, agent: Agent, purpose: str, messages: list[dict], state: dict, system: str = "S2",
                   schema: dict | None = None, max_tokens: int | None = None, system_one: dict | None = None):
    """Appelle le LLM et classe les dérives. Renvoie (données JSON ou None, llm_result, flags).
    `system` : « S1 » (réflexe : un nombre, le petit modèle) ou « S2 » (réflexion : le modèle de l'agent), voir `routing.py`."""
    brief = prompts.is_brief(world.cfg["llm"])
    reflex = system == "S1"
    hint = {"purpose": purpose, "archetype": agent.archetype, "state": state, "system": system,
            "schema": schema or (prompts.REFLEX_SCHEMA if reflex else prompts.answer_schema(purpose, brief, agent.is_fisher)),
            "seed": _seed(world, agent, purpose, state)}                  # le schéma est imposé aux fournisseurs qui le savent
    if max_tokens:
        hint["max_tokens"] = max_tokens
    elif reflex:
        hint["max_tokens"] = prompts.REFLEX_MAX_TOKENS
    elif brief:
        hint["max_tokens"] = prompts.BRIEF_MAX_TOKENS[purpose]       # réflexion rapide : réponse courte, appel plus court
    tier = agent.profile.tier
    if reflex:
        # le réflexe va au modèle de décision s'il y en a un (niveau `reflexe`, ex. tev1), sinon au petit modèle de langage
        usable = "reflexe" in world.router.tiers and system_one and not getattr(world, "_reflex_down", False)
        tier = "reflexe" if usable else "petit"
        if tier == "reflexe":
            hint["system_one"] = system_one
    res = await world.router.complete(agent.id, tier, purpose, messages, hint)
    if res.status != "ok" and tier == "reflexe":
        # modèle de décision indisponible (Ollama trop ancien, modèle absent…) : le petit modèle de langage prend le relais,
        # pour cet appel et, si l'erreur n'est pas un simple délai dépassé, pour le reste de la partie
        if res.status == "error":
            world._reflex_down = True
        if not getattr(world, "_reflex_warned", False):
            world._reflex_warned = True
            log.warning("modèle de décision indisponible (%s) : le petit modèle répond à sa place",
                        (res.detail or res.status)[:160])
        hint = {k: v for k, v in hint.items() if k not in ("_started", "system_one")}
        res = await world.router.complete(agent.id, "petit", purpose, messages, hint)
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
    obs, state, retrieved, used = await world.observe(agent, horizon, "catch")
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
    system, why = routing.choose_system(obs, "catch") if prompts.is_adaptive(world.cfg["llm"]) else ("S2", "")
    if system == "S1":
        data, res, flags = await _ask_llm(world, agent, "catch", prompts.reflex_messages(p, obs), state, "S1",
                                          system_one=prompts.reflex_system_one(p, obs))
    else:
        data, res, flags = await _ask_llm(world, agent, "catch", prompts.catch_messages(p, obs, world.capacity, brief), state)
    fallback, rule = False, None
    v = to_number(data.get("prise")) if data else None
    just = str(data.get("justification", "")).strip() if data else ""
    if system == "S1" and data is not None:
        conf = (data.get("_confiance") or {}).get("prise")
        just = f"Réflexe (système 1, {res.model}) : {why}." + (f" Confiance {conf:.2f}." if conf is not None else "")
    common = {**common, "system": system}                        # sans routage adaptatif, tout est système 2
    if data is not None and v is None:
        world.incident(agent.id, "invalid_value", f"prise absente : {str(data)[:150]}", "règle de repli", res.call_id)
    lo, hi = state.get("min_catch", 0.0), state["boat_capacity"]      # une sortie rapporte au moins la prise minimale
    if v is not None and not (lo <= v <= hi):
        world.incident(agent.id, "invalid_value", f"prise {v} hors de [{lo:g}, {hi:g}]", "bornage", res.call_id)
        v = max(lo, min(hi, v))
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
    obs, state, retrieved, used = await world.observe(agent, horizon, "speak", assembly=assembly, rnd=rnd)
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
    common = {**common, "system": "S2"}                          # la parole est toujours de la réflexion (voir `routing.py`)
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


async def ballot(world, agent: Agent, asm) -> None:
    """Le bulletin d'un pêcheur à IA qui n'a soutenu aucune proposition à la veillée : pour laquelle vote-t-il ? Une question de
    quelques lignes au petit modèle (système 1), réponse contrainte à l'identifiant d'une proposition ou « aucune ». Sans cela,
    ceux qui ne disent aucun chiffre s'abstenaient et aucune proposition n'atteignait la majorité. Une réponse inutilisable n'est
    pas une erreur : le pêcheur reste sans voix ici, et la clôture compte ce qu'il a dit (`World.closing_vote`)."""
    if asm.closed or agent.id in asm.support or not asm.proposals:
        return
    est = world.lake.observe(agent.rng)
    table = [f"- {pr.id} : {pr.quota:g} t par pêcheur, proposée par {world.name(pr.author)}, "
             f"{sum(1 for v in asm.support.values() if v[0] == pr.id)} soutien(s)" for pr in asm.proposals.values()]
    messages = prompts.ballot_messages(agent.profile, table, est, world.capacity, world.lake.collapse_ratio)
    described = {pr.id: f"{pr.quota:g} t par pêcheur, proposée par {world.name(pr.author)}, "
                        f"{sum(1 for v in asm.support.values() if v[0] == pr.id)} soutien(s)" for pr in asm.proposals.values()}
    data, res, _ = await _ask_llm(world, agent, "vote", messages, {"round": 99}, "S1",
                                  schema=prompts.ballot_schema(list(asm.proposals)), max_tokens=prompts.BALLOT_MAX_TOKENS,
                                  system_one=prompts.ballot_system_one(agent.profile, described, est, world.capacity,
                                                                       world.lake.collapse_ratio))
    vote = str((data or {}).get("vote", "")).strip().upper()
    last = next((u for u in reversed(asm.utterances) if u["payload"]["speaker"] == agent.id), None)
    if vote in asm.proposals and last is not None and not asm.closed:
        world._support(agent, asm, vote, last)
