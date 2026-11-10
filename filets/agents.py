"""Agents de la vallée : décision de prise et prise de parole.

Le même chemin sert aux agents LLM et aux agents à règles, pour que leurs décisions
soient tracées de la même façon (événement `decision` avec horizon d'information,
souvenirs et documents retrouvés, justification ou règle appliquée).
"""
from __future__ import annotations

import logging
import random
import unicodedata
import zlib
from dataclasses import dataclass, field

from . import prompts, routing
from .llm import detect_drift, extract_json, to_number
from .memory import MemoryStore
from .policies import at_lake, catch_rule, declare_rule, elect_rule, lake_choice_rule, outing_rule, rule_choices, speak_rule, trust_rule
from .rules import DUREES, LONG_H, quand_hours
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
    declared: dict[int, float] = field(default_factory=dict)       # ce qu'il a déclaré à l'ancien, par saison
    outings: dict[int, list[dict]] = field(default_factory=dict)   # ses sorties de chaque saison (voir `World.outings`)
    form: float = 0.0                                              # sa chance de la saison (elle se prolonge d'une saison à l'autre)
    form_season: int = 0                                           # la saison pour laquelle `form` a été tirée
    plans: dict[int, dict] = field(default_factory=dict)           # son plan de chaque saison (voir `decide_plan`)
    prev: dict | None = None                                       # ce qu'il observait à sa décision de sortie précédente (voir `routing.outing_reasons`)
    temper: float = 1.0                                            # sa sévérité : plus de 1, il pardonne moins (tirée une fois)
    lake_choice: dict[int, str] = field(default_factory=dict)      # le lac où il a pêché à chaque saison (le sien, ou un autre)
    spot: int | None = None                                        # son coin de pêche : une parcelle de sa rive (voir `World.spot_of`)
    spots: dict[int, float] = field(default_factory=dict)          # ce que chaque coin de sa rive lui a rendu (1 : comme le lac)

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
    key = f"{world.cfg['run']['seed']}|{agent.id}|{world.season}|{purpose}|{state.get('round', 1)}|{state.get('done', 0)}"
    return zlib.crc32(key.encode()) & 0x7FFFFFFF


async def _ask_llm(world, agent: Agent, purpose: str, messages: list[dict], state: dict, system: str = "S2",
                   schema: dict | None = None, max_tokens: int | None = None, system_one: dict | None = None,
                   temperature: float | None = None, handled: str = "règle de repli"):
    """Appelle le LLM et classe les dérives. Renvoie (données JSON ou None, llm_result, flags). `handled` : ce que devient
    l'action si la réponse manque (texte de l'incident ; l'appelant qui a un rattrapage le dit ici).
    `system` : « S1 » (réflexe : un nombre, le petit modèle) ou « S2 » (réflexion : le modèle de l'agent), voir `routing.py`."""
    brief = prompts.is_brief(world.cfg["llm"])
    reflex = system == "S1"
    hint = {"purpose": purpose, "archetype": agent.archetype, "state": state, "system": system,
            "schema": schema or (prompts.REFLEX_SCHEMA if reflex else prompts.answer_schema(
                purpose, brief, agent.is_fisher, [world.first_name(a.id) for a in world.fishers if a.id != agent.id],
                state.get("lake_labels") if purpose in ("catch", "plan") else None,
                state.get("catch_extras") if purpose in ("catch", "plan") else None)),
            "seed": _seed(world, agent, purpose, state)}                  # le schéma est imposé aux fournisseurs qui le savent
    if max_tokens:
        hint["max_tokens"] = max_tokens
    elif reflex:
        hint["max_tokens"] = prompts.REFLEX_MAX_TOKENS
    elif brief:
        hint["max_tokens"] = prompts.BRIEF_MAX_TOKENS[purpose]       # réflexion rapide : réponse courte, appel plus court
    if temperature is not None:
        hint["temperature"] = temperature
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
        world.incident(agent.id, itype, res.detail or res.status, handled, res.call_id)
        return None, res, {}
    data = extract_json(res.text)
    if data is None:
        world.incident(agent.id, "unparseable", (res.text or "")[:200], handled, res.call_id)
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


def reflex_usable(world) -> bool:
    """Le modèle de décision (palier `reflexe`, ex. tev1) est-il là et encore en état de répondre ?"""
    return "reflexe" in world.router.tiers and not getattr(world, "_reflex_down", False)


PLACES = {"rive": "rive", "large": "large", "rive voisine": "voisine"}       # « lieu » dit en mots -> `place` du moteur


def _place(data: dict | None) -> str | None:
    """Où il pêche, d'après sa réponse (« rive », « large », « rive voisine ») ; None : rien dit de lisible."""
    return PLACES.get(str((data or {}).get("lieu", "")).strip().lower())


def _chosen_lake(data: dict | None, state: dict):
    """Le lac que l'IA a choisi parmi ceux à portée, s'il n'est pas le sien."""
    label = str((data or {}).get("lac", "")).strip()
    return next((o for o in state.get("lake_options", []) if o["label"] == label), None) if data else None


def _bound(world, agent, v: float, lo: float, hi: float, res, label: str = "prise") -> float:
    """La valeur ramenée dans [lo, hi] ; un arrondi de quelques kilos n'est pas une valeur invalide (un nombre absurde, si)."""
    if not (lo <= v <= hi):
        if not (lo - 0.05 <= v <= hi + 0.05):          # un arrondi de quelques kilos n'est pas une valeur invalide
            world.incident(agent.id, "invalid_value", f"{label} {v} hors de [{lo:g}, {hi:g}]", "bornage", res.call_id)
        v = max(lo, min(hi, v))
    return v


async def decide_plan(world, agent: Agent, horizon: float) -> Outcome:
    """Le plan de la saison, à l'ouverture de la pêche (docs/peche.md) : combien il compte prendre en tout, où, ce qu'il compte
    déclarer, et sa première sortie (quand). Toujours une réflexion du grand modèle ; un agent à règles suit la règle de son archétype.
    Le plan n'engage pas le moteur : il guide les décisions de sortie suivantes (`agent.plans`, la mémoire)."""
    obs, state, retrieved, used = await world.observe(agent, horizon, "catch")
    p, season = agent.profile, world.clock.season_of(horizon)
    n_default = int(state.get("outings_n") or 6)
    common = {"agent": agent.id, "agent_kind": p.kind, "decision_type": "plan", "info_horizon": round(horizon, 6),
              "retrieved": retrieved, "used_event_ids": used,
              "observed": {"stock_estimate": state["stock_estimate"], "stock_true": state["stock_true"],
                           "quota": state["quota"],
                           **({k: state[k] for k in ("lake_estimates", "lake_stocks") if k in state})}}
    agent.prev = routing.snapshot(obs)
    if p.kind == "rule":
        where, why_lake = lake_choice_rule(agent.archetype, state)         # son lac, ou un autre s'il y gagne nettement
        there = next((o for o in state.get("lake_options", []) if o["name"] == where), None)
        s_here = at_lake(state, there)
        v, rule = catch_rule(agent.archetype, s_here)
        said, drule = declare_rule(agent.archetype, s_here, v)
        extras, xrule = rule_choices(agent.archetype, s_here)          # où il pêche et combien de sorties, face aux règles
        plan = {"total": v, "declared": said, "lake": where, "place": extras.get("place"),
                "outings": extras.get("outings", n_default), "hold": round(s_here["boat_capacity"], 3)}
        nxt, _ = outing_rule(agent.archetype, {**s_here, "plan": plan, "taken": 0.0, "done": 0}, first=True)
        nxt = {**nxt, "lake": where, "place": extras.get("place")}
        lake_text = f" ; il pêche dans {prompts.lake_ref(there['label'])} : {why_lake}" if there else ""
        dec = world.events.emit("decision", {**common, "justification": f"Règle appliquée : {rule} ; {drule}{xrule}{lake_text}.",
                                             "rule": rule, "value": v, "declared": said, "fallback": False, "model": None,
                                             "tier": None, "llm_call_id": None, "delay_h": nxt["delay_h"], "hours": nxt["hours"],
                                             **({"place": extras["place"]} if "place" in extras else {}),
                                             **({"outings": extras["outings"]} if "outings" in extras else {}),
                                             **({"lake": where} if where else {})}, actor=agent.id)
        _note_observation(obs, dec)
        agent.last_decision = dec
        agent.plans[season] = plan
        return Outcome(v, {"declaration": said, "next": nxt, "plan": plan}, dec)

    brief = prompts.is_brief(world.cfg["llm"])

    def ask_reflex():
        return _ask_llm(world, agent, "plan", prompts.reflex_messages(p, obs), state, "S1", system_one=prompts.reflex_system_one(p, obs))
    data, res, flags = await _ask_llm(world, agent, "plan", prompts.catch_messages(p, obs, world.capacity, brief, plan=True), state,
                                      handled="repris par le réflexe" if reflex_usable(world) else "règle de repli")
    system, why = "S2", ""
    if (data is None or to_number(data.get("prise_saison")) is None) and reflex_usable(world):
        data, res, flags = await ask_reflex()
        system, why = "S1", "reprise : la réponse du grand modèle manquait ou était illisible"
        if data is not None and "prise_saison" not in data:
            data = {**data, "prise_saison": data.get("prise")}
    fallback, rule = False, None
    v = to_number(data.get("prise_saison")) if data else None
    just = str(data.get("justification", "")).strip() if data else ""
    if system == "S1" and data is not None:
        just = f"Réflexe (système 1, {res.model}) : {why}."
    if data is not None and v is None:
        world.incident(agent.id, "invalid_value", f"prise_saison absente : {str(data)[:150]}", "règle de repli", res.call_id)
    chosen = _chosen_lake(data, state) if system == "S2" else None
    lo, hi = state.get("min_catch", 0.0), (chosen["hold"] if chosen else state["boat_capacity"])    # la saison rapporte au moins la prise minimale
    if v is not None:
        v = _bound(world, agent, v, lo, hi, res, "prise_saison")
    else:
        v, rule = catch_rule(agent.archetype, state)
        fallback = True
        just = f"(repli) Règle appliquée : {rule}."
    v = round(v, 1)
    # ce qu'il déclarera de la saison : la vérité par défaut (réflexe, repli, champ absent) ; jamais plus que la prise
    said = to_number(data.get("declaration")) if data and system == "S2" and not fallback else None
    said = v if said is None else round(min(max(said, 0.0), v), 1)
    where = chosen["name"] if chosen and not fallback else None
    extras: dict = {}
    if fallback:
        extras, _ = rule_choices(agent.archetype, at_lake(state, None))
    elif data and system == "S2":
        if _place(data):
            extras["place"] = _place(data)
        n_out = to_number(data.get("sorties"))
        if n_out is not None and state.get("outings_cap"):
            extras["outings"] = int(max(1, min(n_default, round(n_out))))
    n_plan = extras.get("outings", n_default)
    delay = quand_hours(data.get("premiere_sortie"), horizon) if data and system == "S2" and not fallback else 0.0
    plan = {"total": v, "declared": said, "lake": where, "place": extras.get("place"), "outings": n_plan, "hold": round(hi, 3)}
    nxt = {"delay_h": delay, "hours": LONG_H, "target": round(v / max(1, n_plan), 2), "lake": where, "place": extras.get("place")}
    if v < 0.05:
        nxt["delay_h"] = None                       # pas de prise prévue : il ne sort pas
    dec = world.events.emit("decision", {**common, "justification": just or "(sans justification)", "rule": rule,
                                         "value": v, "declared": said, "fallback": fallback, "model": res.model, "system": system,
                                         "tier": res.tier, "llm_call_id": res.call_id, "delay_h": nxt["delay_h"], "hours": LONG_H,
                                         "out_of_role": flags.get("out_of_role", False), **extras,
                                         **({"lake": where} if where else {})}, actor=agent.id)
    _note_observation(obs, dec)
    agent.last_decision = dec
    agent.plans[season] = plan
    return Outcome(v, {"declaration": said, "next": nxt, "plan": plan}, dec)


async def decide_catch(world, agent: Agent, horizon: float, rescue: bool = False) -> Outcome:
    """Sa prochaine sortie (docs/peche.md), à l'ouverture puis à chaque retour : quand (un délai, ou « plus cette saison »), où (lac,
    zone), pour combien de temps (courte ou longue) et combien de tonnes il vise. Le réflexe (système 1) la décide quand rien n'a changé
    depuis sa décision précédente (`routing.outing_reasons`), le grand modèle sinon ; un agent à règles suit son plan.
    `rescue` : le grand modèle n'a pas répondu à temps : la sortie est décidée par le modèle de décision."""
    obs, state, retrieved, used = await world.observe(agent, horizon, "catch")
    p = agent.profile
    plan = state.get("plan") or {}
    common = {"agent": agent.id, "agent_kind": p.kind, "decision_type": "catch", "info_horizon": round(horizon, 6),
              "retrieved": retrieved, "used_event_ids": used,
              "observed": {"stock_estimate": state["stock_estimate"], "stock_true": state["stock_true"],
                           "quota": state["quota"],
                           **({k: state[k] for k in ("lake_estimates", "lake_stocks") if k in state})}}
    prev, agent.prev = agent.prev, routing.snapshot(obs)

    def decided(nxt: dict, v: float) -> dict:
        return {"delay_h": nxt["delay_h"], "hours": nxt["hours"], "value": v,
                **({"lake": nxt["lake"]} if nxt.get("lake") else {}), **({"place": nxt["place"]} if nxt.get("place") else {})}
    if p.kind == "rule":
        where = plan.get("lake")                         # il suit son plan : le même lac, la même zone
        there = next((o for o in state.get("lake_options", []) if o["name"] == where), None)
        nxt, why = outing_rule(agent.archetype, at_lake(state, there))
        nxt = {**nxt, "lake": where, **({"place": plan["place"]} if plan.get("place") else {})}
        dec = world.events.emit("decision", {**common, "justification": f"Règle appliquée : {why}.", "rule": why, "fallback": False,
                                             "model": None, "tier": None, "llm_call_id": None, **decided(nxt, nxt["target"])},
                                actor=agent.id)
        _note_observation(obs, dec)
        agent.last_decision = dec
        return Outcome(nxt["target"], {"next": nxt}, dec)

    brief = prompts.is_brief(world.cfg["llm"])
    system, why = routing.choose_outing_system(obs, prev) if prompts.is_adaptive(world.cfg["llm"]) else ("S2", "")

    def ask_reflex():
        return _ask_llm(world, agent, "catch", prompts.reflex_messages(p, obs), state, "S1", schema=prompts.REFLEX_OUTING_SCHEMA,
                        system_one=prompts.reflex_system_one(p, obs))
    if rescue:
        system, why = "S1", "reprise : le grand modèle n'a pas répondu à temps"
    if system == "S1":
        data, res, flags = await ask_reflex()
    else:
        # pas de réponse lisible du grand modèle : le modèle de décision tranche (mieux que la règle de repli)
        data, res, flags = await _ask_llm(world, agent, "catch", prompts.catch_messages(p, obs, world.capacity, brief), state,
                                          handled="repris par le réflexe" if reflex_usable(world) else "règle de repli")
        if (data is None or to_number(data.get("prise")) is None) and reflex_usable(world):
            data, res, flags = await ask_reflex()
            system, why = "S1", "reprise : la réponse du grand modèle manquait ou était illisible"
    fallback, rule = False, None
    v = to_number(data.get("prise")) if data else None
    just = str(data.get("justification", "")).strip() if data else ""
    if system == "S1" and data is not None:
        conf = (data.get("_confiance") or {}).get("prise")
        just = f"Réflexe (système 1, {res.model}) : {why}." + (f" Confiance {conf:.2f}." if conf is not None else "")
    common = {**common, "system": system, **({"routing": why} if why else {})}      # sans routage adaptatif, tout est système 2
    if data is not None and v is None:
        world.incident(agent.id, "invalid_value", f"prise absente : {str(data)[:150]}", "règle de repli", res.call_id)
    chosen = _chosen_lake(data, state) if system == "S2" else None       # le lac que l'IA a choisi, s'il n'est pas le sien
    if system == "S1" or not data:
        where, place = plan.get("lake"), plan.get("place")          # le réflexe garde le lieu de son plan
    else:
        where, place = (chosen["name"] if chosen else None), _place(data) or plan.get("place")
    there = next((o for o in state.get("lake_options", []) if o["name"] == where), chosen)
    lo, hi = state.get("min_catch", 0.0), min(state["cale"], there["hold"] if there else state["boat_capacity"], state["boat_capacity"])
    if v is not None:
        v = _bound(world, agent, v, lo, hi, res)
        label = str(data.get("quand", "")).strip().lower()
        delay = quand_hours(label, horizon) if label else 0.0
        nxt = {"delay_h": delay, "hours": DUREES.get(str(data.get("duree", "")).strip().lower(), LONG_H), "target": round(v, 2),
               "lake": where, "place": place}
    else:
        nxt, rule = outing_rule(agent.archetype, at_lake(state, there))
        nxt = {**nxt, "lake": where, "place": place or nxt.get("place")}
        v, fallback = nxt["target"], True
        just = f"(repli) Règle appliquée : {rule}."
    if v < 0.05:
        nxt["delay_h"] = None                    # rien à prendre : il ne ressort plus cette saison
    v = round(v, 2)
    dec = world.events.emit("decision", {**common, "justification": just or "(sans justification)", "rule": rule,
                                         "fallback": fallback, "model": res.model, "tier": res.tier, "llm_call_id": res.call_id,
                                         "out_of_role": flags.get("out_of_role", False), **decided(nxt, v)}, actor=agent.id)
    _note_observation(obs, dec)
    agent.last_decision = dec
    return Outcome(v, {"next": nxt}, dec)


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
        proposed = world.read_proposal(data, agent)
        if proposed is not None:
            acts.append("propose : " + world.rule_words(*proposed))
        if data.get("soutien"):
            acts.append(f"soutient {data.get('soutien')}")
        if to_number(data.get("promesse")) is not None:
            acts.append(f"promet {to_number(data.get('promesse')):g} t")
        if data.get("accuse"):
            acts.append(f"accuse {data.get('accuse')}")
        for action, verb in (("exclure", "propose d'exclure"), ("reautoriser", "propose de réautoriser"),
                             ("patrouille", "propose de patrouille :")):
            if data.get(action):
                acts.append(f"{verb} {data.get(action)}")
        judged = data.get("confiance")
        if isinstance(judged, dict):
            steps = [f"{k} {to_number(v):+g}" for k, v in judged.items() if to_number(v)]
            if steps:
                acts.append("confiance " + ", ".join(steps))
        just = f"« {str(data.get('message', '')).strip()[:300]} »" + (f" ({', '.join(acts)})" if acts else "")
    dec = world.events.emit("decision", {**common, "justification": just, "rule": rule, "fallback": fallback,
                                         "model": res.model, "tier": res.tier, "llm_call_id": res.call_id,
                                         "out_of_role": flags.get("out_of_role", False)}, actor=agent.id)
    _note_observation(obs, dec)
    agent.last_decision = dec
    return Outcome(None, data, dec)


async def ballot(world, agent: Agent, asm) -> None:
    """Le bulletin d'un pêcheur à IA avant la clôture de la veillée : la proposition de règle qu'il soutient, s'il n'en a
    soutenu aucune ; puis son vote sur chaque proposition d'exclure ou de réautoriser un pêcheur, selon sa confiance, sa morale
    et ses intérêts."""
    if asm.closed:
        return
    if agent.id not in asm.support and asm.proposals:
        await _quota_ballot(world, agent, asm)
    pending = [s for s in asm.sanctions.values() if s.target != agent.id and agent.id not in s.votes]
    if pending and not asm.closed:
        await _sanction_ballot(world, agent, asm, pending)


async def _sanction_ballot(world, agent: Agent, asm, pending: list) -> None:
    """Pour ou contre chaque proposition d'exclure (ou de réautoriser) : quelques lignes (sa confiance envers le pêcheur visé, ce
    qu'il sait de lui, sa propre situation), une réponse « oui » ou « non » par proposition (système 1). Sans réponse lisible,
    il ne vote pas."""
    items = {s.id: world.motion_item(agent, s, asm.season) for s in pending}
    situation = (f"Tes finances : {agent.wealth:.0f} écus" + (" ; tu es toi-même interdit de pêche." if agent.id in world.banned
                                                                  else "."))
    data, res, _ = await _ask_llm(world, agent, "vote", prompts.sanction_messages(agent.profile, items, situation),
                                  {"round": 98}, "S1", schema=prompts.sanction_schema(list(items)),
                                  max_tokens=prompts.SANCTION_MAX_TOKENS,
                                  system_one=prompts.sanction_system_one(agent.profile, items, situation))
    for s in pending:
        v = (data or {}).get(s.id)
        if isinstance(v, (int, float)) and not isinstance(v, bool):        # un modèle de décision : la probabilité du oui
            yes = v >= 0.5
        elif str(v).strip().lower() in ("oui", "non", "true", "false"):
            yes = str(v).strip().lower() in ("oui", "true")
        else:
            continue
        if not asm.closed:
            world.vote_sanction(agent, s, yes)


def _plain(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c)).strip()


async def ballot_election(world, voter: Agent, candidates: list[Agent], season: int) -> str | None:
    """Le bulletin d'un pêcheur pour l'élu de son village : celui des candidats (lui-même compris) qu'il juge le plus apte à
    parler et voter au conseil au nom du village, d'après sa confiance, sa morale et ses intérêts. Une question de quelques lignes
    (système 1) ; un agent à règles vote selon sa règle (`policies.elect_rule`). None : pas de bulletin lisible, il s'abstient."""
    ids = [c.id for c in candidates]
    row = world.trust[voter.id]
    if world.policy_voter(voter):
        return elect_rule({c.id: row.get(c.id, 0.5) for c in candidates if c.id != voter.id},
                          {c.id: c.profile.experience for c in candidates}, voter.id)
    items = {c.id: world.candidate_line(voter, c, season) for c in candidates}
    situation = f"Tes finances : {voter.wealth:.0f} écus" + \
        (f", une dette de {voter.profile.debt_payment:.0f} écus par saison." if voter.profile.debt_payment else ".")
    data, _, _ = await _ask_llm(world, voter, "vote", prompts.election_messages(voter.profile, items, situation),
                                {"round": 97}, "S1", schema=prompts.election_schema(ids),
                                max_tokens=prompts.ELECTION_MAX_TOKENS,
                                system_one=prompts.election_system_one(voter.profile, items, situation))
    vote = str((data or {}).get("vote", "")).strip().upper()
    return vote if vote in ids else None


async def debrief_villager(world, agent: Agent, asm) -> None:
    """Un villageois qui n'était pas au conseil en apprend la suite par l'ancien, et en juge : sa confiance envers chaque pêcheur
    bouge (de −3 à +3 dixièmes) selon ce qu'il apprend, sa morale et ses intérêts. Un agent à règles juge selon son caractère
    (`policies.trust_rule`) ; une IA qui ne répond pas ne juge pas (sa confiance reste ce qu'elle était)."""
    facts = world.trust_facts(agent, asm.season, world.clock.now(), None)
    if world.policy_voter(agent):
        world.judge(agent, trust_rule(agent.archetype, facts, world.trust_context(agent, asm.season)))
        return
    lines = world.debrief_lines(agent, asm, facts)
    names = [world.first_name(a.id) for a in world.fishers if a.id != agent.id]
    trust = prompts.trust_line(world.trust_obs(agent))
    situation = f"Tes finances : {agent.wealth:.0f} écus."
    messages = prompts.debrief_messages(agent.profile, lines, trust, situation)
    kw = dict(schema=prompts.debrief_schema(names), max_tokens=max(prompts.DEBRIEF_MAX_TOKENS, 12 + 9 * len(names)))
    data = None
    if reflex_usable(world):
        # un jugement de confiance est une décision structurée courte : le modèle de décision y répond (une échelle par pêcheur)
        data, res, _ = await _ask_llm(world, agent, "debrief", messages, {"round": 96}, "S1", **kw,
                                      system_one=prompts.debrief_system_one(agent.profile, lines, trust, situation, names))
        if data is not None and res.tier == "reflexe":
            data = {"confiance": {k: v for k, v in data.items() if not k.startswith("_")}}
    if data is None:                                   # pas de modèle de décision, ou rien de lisible : le grand modèle
        data, _, _ = await _ask_llm(world, agent, "debrief", messages, {"round": 96}, "S2", **kw)
    if data is not None:
        world.judge(agent, data.get("confiance"))


async def patrol_decision(world, season: int, legs: int, days: int, lines: list[str],
                          agent: Agent | None = None) -> tuple[list[tuple[str, int]], str] | None:
    """Le capitaine de la patrouille décide où aller : jusqu'à `legs` étapes (une zone du lac, ou un pêcheur qu'il suit), et combien de
    jours à chacune (`days` jours de mer en tout), d'après ce qu'on lui a dit et ce qu'il a relevé. Renvoie (étapes, raison), ou None si
    la réponse est illisible (le plan sera celui d'un capitaine à règles)."""
    agent = agent or world.patrol_agent
    targets = [*world.zones, *(a.id for a in world.fishers)]
    data, _, _ = await _ask_llm(world, agent, "route", prompts.patrol_messages(
        agent.profile, world.capacity, world.hamlets, lines, legs, days, world.world_text(agent) if world.multi else None),
        {"round": 95}, "S2",
        schema=prompts.patrol_schema(targets, legs, days), max_tokens=prompts.PATROL_MAX_TOKENS)
    steps = (data or {}).get("etapes")
    if not isinstance(steps, list):
        return None
    known = {_plain(t): t for t in targets}
    plan: list[tuple[str, int]] = []
    left = days
    for step in steps:
        target = known.get(_plain(str(step.get("cible", "")))) if isinstance(step, dict) else None
        n = to_number(step.get("jours")) if isinstance(step, dict) else None
        if target is None or n is None or left <= 0 or any(target == t for t, _ in plan):
            continue
        n = int(max(1, min(n, left)))
        plan.append((target, n))
        left -= n
    return (plan[:legs], str((data or {}).get("raison", "")).strip()[:200]) if plan else None


async def _quota_ballot(world, agent: Agent, asm) -> None:
    """Pour quelle proposition de règle vote-t-il ? Une question de quelques lignes au petit modèle (système 1), réponse
    contrainte à l'identifiant d'une proposition ou « aucune ». Sans cela, ceux qui ne disent aucun chiffre s'abstenaient et
    aucune proposition n'atteignait la majorité. Une réponse inutilisable n'est pas une erreur : le pêcheur reste sans voix
    ici, et la clôture compte ce qu'il a dit (`World.closing_vote`)."""
    lake = world.lake_of(agent)
    est = lake.observe(agent.rng)
    table = [f"- {pr.id} : {world.proposal_words(pr)}, proposée par {world.name(pr.author)}, "
             f"{sum(1 for v in asm.support.values() if v[0] == pr.id)} soutien(s)" for pr in asm.proposals.values()]
    messages = prompts.ballot_messages(agent.profile, table, est, lake.capacity, lake.collapse_ratio)
    described = {pr.id: f"{world.proposal_words(pr)}, proposée par {world.name(pr.author)}, "
                        f"{sum(1 for v in asm.support.values() if v[0] == pr.id)} soutien(s)" for pr in asm.proposals.values()}
    data, res, _ = await _ask_llm(world, agent, "vote", messages, {"round": 99}, "S1",
                                  schema=prompts.ballot_schema(list(asm.proposals)), max_tokens=prompts.BALLOT_MAX_TOKENS,
                                  system_one=prompts.ballot_system_one(agent.profile, described, est, lake.capacity,
                                                                       lake.collapse_ratio))
    vote = str((data or {}).get("vote", "")).strip().upper()
    last = next((u for u in reversed(asm.utterances) if u["payload"]["speaker"] == agent.id), None)
    if vote in asm.proposals and last is not None and not asm.closed:
        world._support(agent, asm, vote, last)
