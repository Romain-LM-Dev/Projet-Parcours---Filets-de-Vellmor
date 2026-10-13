"""Le monde de FILETS et ses deux orchestrations du temps (C3, C4).

Calendrier d'une saison (jours simulés depuis le début de la saison, configurable) :

    J0 06:00   ouverture de la pêche : chaque pêcheur décide de sa prise
    J20        fermeture : une sortie décidée après est perdue (incident `missed_window`)
    J25 18:00  veillée chez l'ancien (selon le mode de communication) : tours de parole,
               propositions de quota, soutiens, promesses, accusations
    J29        fin de la veillée : adoption d'une règle si une majorité des pêcheurs présents la soutient
    J29 21:36  repeuplement du lac, bilan de saison, promesses tenues ou trahies

Mode synchrone : à chaque pas, tous les agents observent le même instantané, décident
(la latence des LLM n'a aucun effet sur le temps simulé), puis leurs actions s'appliquent
au même instant. Si la somme des prises dépasse le stock, elles sont rationnées au prorata.

Mode asynchrone : l'horloge avance avec le temps réel. Chaque pêcheur se réveille à son
propre rythme, observe le lac, réfléchit (latence réelle du LLM), et sa prise s'applique
au stock *du moment où il a fini de réfléchir* : il a pu changer entre-temps (écart tracé
dans l'événement `catch` : `stock_observed` vs `stock_before`). À la veillée, chacun parle
dès qu'il a fini de réfléchir et n'entend que ce qui a été dit avant.

Chaque saison est jouée par l'un des deux orchestrateurs, choisi à son début : le joueur peut donc
passer de l'un à l'autre en cours de partie (effet à la saison suivante), mettre en pause, changer
la vitesse ou arrêter (voir `control.GameControl`).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import heapq
import itertools
import json
import logging
import random
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .agents import Agent, decide_catch, speak
from .clock import SimClock
from .config import ROOT, sustainable_yield
from .control import MODES, GameControl, StopRun
from .events import EventFactory, Recorder
from .lake import Lake
from .memory import MemoryStore
from .profiles import HAMLETS, build_population
from .rag import Retriever
from .schemas import validate_command
from .llm import LLMRouter, to_number

log = logging.getLogger("filets.world")


@dataclass
class Proposal:
    id: str
    author: str
    quota: float
    t: float
    event_id: str
    scope: str


@dataclass
class Assembly:
    scope: str                       # "valley" ou "hamlet:<nom>"
    participants: list[str]
    season: int
    close_t: float
    utterances: list[dict] = field(default_factory=list)       # événements `utterance`
    proposals: dict[str, Proposal] = field(default_factory=dict)
    support: dict[str, tuple[str, float, str]] = field(default_factory=dict)  # agent -> (proposal, t, event_id)
    closed: bool = False

    @property
    def label(self) -> str:
        return "toute la vallée" if self.scope == "valley" else f"hameau de {self.scope.split(':', 1)[1]}"


@dataclass
class Norm:
    scope: str
    quota: float
    effective_season: int
    proposal_id: str
    adopted_t: float
    event_id: str
    supporters: list[str]


class World:
    def __init__(self, cfg: dict, bus, run_id: str, record: bool = True, engine_id: str = "run", lobby: bool = False,
                 advised_speed: float | None = None):
        self.cfg = cfg
        self.bus = bus
        self.run_id = run_id
        self.engine_id = engine_id      # identifie le processus moteur dans les messages d'état
        self.lobby = lobby              # vrai si un salon (`serve`) peut lancer la partie suivante
        self.advised_speed = advised_speed   # vitesse conseillée en asynchrone avec ce moteur d'IA (voir `catalog.LLM_OPTIONS`)
        self.ended = False
        seed = int(cfg["run"]["seed"])
        self.rng = random.Random(seed)
        t = cfg["time"]
        self.T = t
        self.clock = SimClock(t["season_days"], t["sim_hours_per_second"], t["idle_speedup"], t["fast"])
        self.ctl = GameControl(self.clock, t["mode"])
        self.ctl.on_change = self.publish_status
        self.run_dir = ROOT / cfg["output"]["runs_dir"] / run_id
        self.recorder = Recorder(self.run_dir) if record else None
        if record:
            (self.run_dir / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2, default=str))
        self.events = EventFactory(run_id, self.clock, bus, self.recorder)
        L = cfg["lake"]
        self.capacity = L["capacity_resolved"]
        self.lake = Lake(self.capacity, L["initial_ratio"], L["growth_rate"], L["collapse_ratio"], L["observation_noise"])
        self.econ = cfg["economy"]
        self.scn = dict(cfg["scenario"])
        self.comm = self.scn["communication"]
        self.visible = bool(self.scn["catches_visible"])
        mcfg = cfg["memory"]
        self.agents: dict[str, Agent] = {}
        lo, hi = t["async_offset_days"]
        for i, p in enumerate(build_population(cfg, self.rng)):
            arng = random.Random(seed * 1000 + i)
            self.agents[p.id] = Agent(p, MemoryStore(p.id, mcfg["recency_decay_per_day"], mcfg["weights"]), arng,
                                      p.wealth, offset_days=round(arng.uniform(lo, hi), 3))
        self.fishers = [a for a in self.agents.values() if a.is_fisher]
        self.elder = next((a for a in self.agents.values() if not a.is_fisher), None)
        values = {"capacity": f"{self.capacity:.0f}", "half_capacity": f"{self.capacity / 2:.0f}",
                  "n_fishers": len(self.fishers), "price": self.econ["price_per_tonne"],
                  "upkeep": self.econ["upkeep_per_season"]}
        self.retriever = Retriever(ROOT / cfg["rag"]["corpus_dir"], values)
        self.router = LLMRouter(cfg, self.clock, self.events, seed, self.ctl)
        self.norms: list[Norm] = []          # historique complet, dans l'ordre d'adoption
        self.promises: dict[tuple[str, int], tuple[float, str]] = {}
        self.promise_memories: dict[tuple[str, int], object] = {}   # promesse épinglée en cours
        self.catch_log: list[dict] = []      # événements `catch`
        self.season = 0
        self.stop_requested = False
        self.stopped_reason = "completed"
        self._pid = itertools.count(1)
        self.collapse_flagged = False
        self.obs_rng = random.Random(seed + 99)
        self.assemblies: list[Assembly] = []
        self.rumors: list[dict] = []         # annonces diffusées par le joueur : {text, season, t, event_id}
        # fournisseurs d'IA réellement utilisés par la partie (pour que l'interface adapte ses conseils)
        self.ai_providers = sorted({cfg["llm"]["tiers"][a.profile.tier]["provider"] for a in self.agents.values()
                                    if a.profile.kind == "llm" and a.profile.tier})

    # ------------------------------------------------------------ utilitaires
    def incident(self, agent: str, itype: str, detail: str, handled_by: str, call_id: str | None = None):
        self.events.emit("incident", {"agent": agent, "incident_type": itype, "detail": detail[:300],
                                      "handled_by": handled_by, "llm_call_id": call_id}, actor=agent)

    def remember(self, agent: Agent, text: str, kind: str, importance: float, pinned=False,
                 expires_season=None, source_event_id=None, t: float | None = None):
        t = self.clock.now() if t is None else t
        m = agent.memory.add(t, text, kind, importance, pinned, expires_season, source_event_id)
        ev = self.events.emit("memory_write", {"agent": agent.id, "memory_id": m.id, "text": text, "kind": kind,
                                               "importance": importance, "pinned": pinned,
                                               "source_event_id": source_event_id}, actor=agent.id, sim_time=t)
        m.event_id = ev["event_id"]
        return m

    def name(self, aid: str) -> str:
        a = self.agents.get(aid)
        return a.profile.name if a else aid

    def lake_update(self, cause: str, delta: float):
        self.events.emit("lake_update", {"stock": round(self.lake.stock, 3), "capacity": self.capacity,
                                         "cause": cause, "delta": round(delta, 3)})
        if self.lake.is_collapsed() and not self.collapse_flagged:
            self.collapse_flagged = True
            self.events.emit("lake_collapsed", {"stock": round(self.lake.stock, 3), "capacity": self.capacity})
            if self.cfg["run"]["stop_on_collapse"]:
                self.stop_requested = True
                self.stopped_reason = "collapse"
        if self.lake.is_extinct() and self.cfg["run"].get("stop_on_extinction", True) and not self.ctl.stopping:
            # Plus un poisson : la logistique ne repart jamais de 0, la suite n'aurait rien à raconter. On arrête tout de suite,
            # au prochain point de passage (même en pleine saison), et non à la fin de la saison.
            self.stop_requested = True
            self.stopped_reason = "extinction"
            self.ctl.request_stop()

    def norm_for_scope(self, scope: str, season: int, horizon: float) -> Norm | None:
        """Dernière règle de ce périmètre connue à `horizon` et en vigueur à la saison `season`."""
        c = [n for n in self.norms if n.scope == scope and n.adopted_t <= horizon and n.effective_season <= season]
        return c[-1] if c else None

    def applicable_norm(self, agent: Agent, season: int, horizon: float) -> Norm | None:
        return (self.norm_for_scope(f"hamlet:{agent.profile.hamlet}", season, horizon)
                or self.norm_for_scope("valley", season, horizon))

    def active_rumors(self, horizon: float) -> list[dict]:
        """Rumeurs encore dans les esprits à l'instant `horizon` : celles de la saison en cours et de la précédente
        (jamais une rumeur d'après l'horizon : C6), les plus récentes d'abord, trois au plus."""
        season = self.clock.season_of(horizon)
        live = [r for r in self.rumors if r["t"] <= horizon and r["season"] >= season - 1]
        return sorted(live, key=lambda r: -r["t"])[:3]

    def named_fishers(self, texts: list[str]) -> list[str]:
        """Identifiants des pêcheurs dont le prénom (accents et casse ignorés) ou l'identifiant figure dans ces textes."""
        def plain(s: str) -> str:
            return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))

        blob = plain(" ".join(texts))
        out = []
        for a in self.fishers:
            first = plain(a.profile.first_name or a.profile.name.split()[0])
            if re.search(rf"\b{re.escape(first)}\b", blob) or re.search(rf"\b{a.id.lower()}\b", blob):
                out.append(a.id)
        return out

    def known_catches(self, agent: Agent, horizon: float, season: int) -> tuple[list[str], list[str], dict]:
        lines, ids, last = [], [], {}
        for ev in self.catch_log:
            p = ev["payload"]
            if ev["sim_time"] > horizon or ev["season"] < season - 2 or p["agent"] == agent.id:
                continue
            if not self.visible and p["hamlet"] != agent.profile.hamlet:
                continue
            lines.append(f"saison {ev['season']}, {self.name(p['agent'])} ({p['agent']}) : {p['landed']:g} t")
            ids.append(ev["event_id"])
            if ev["season"] == season - 1:
                last[p["agent"]] = p["landed"]
        return lines[-14:], ids[-14:], last

    # ------------------------------------------------------------ observation
    def note_lake(self, agent: Agent, season: int, horizon: float, est: float, purpose: str, rnd: int):
        """Garde ce que l'agent constate du lac (à l'ouverture de la pêche, puis à la veillée) et renvoie (l'entrée de cette
        observation, ses constats antérieurs). Sans cette suite de chiffres, un pêcheur ne voit qu'un nombre isolé : il ne
        peut ni savoir que le lac baisse de saison en saison, ni comparer à ce qu'il a vu avant."""
        phase = "pêche" if purpose == "catch" else "veillée"
        entry = None
        if (purpose == "catch" or rnd == 1) and not any(e["season"] == season and e["phase"] == phase
                                                        for e in agent.stock_seen):
            entry = {"season": season, "phase": phase, "t": horizon, "label": self.clock.label(horizon), "est": est,
                     "event_id": None}
            agent.stock_seen.append(entry)
        history = [e for e in agent.stock_seen if e is not entry and e["t"] <= horizon]
        return entry, history[-6:]

    def observe(self, agent: Agent, horizon: float, purpose: str, assembly: Assembly | None = None, rnd: int = 1):
        """Construit ce que l'agent sait à l'instant `horizon` : rien de postérieur (C6)."""
        season = self.clock.season_of(horizon)
        p = agent.profile
        used: list[str] = []
        retrieved: list[dict] = []
        est = self.lake.observe(agent.rng if agent.is_fisher else self.obs_rng)
        entry, history = self.note_lake(agent, season, horizon, est, purpose, rnd)
        used += [e["event_id"] for e in history if e["event_id"]]
        norm = self.applicable_norm(agent, season if purpose == "catch" else season + 1, horizon)
        norm_lines = []
        for key in ("valley", f"hamlet:{p.hamlet}"):
            known = [n for n in self.norms if n.scope == key and n.adopted_t <= horizon]
            if not known:
                continue
            n = known[-1]
            who = "toute la vallée" if key == "valley" else f"le hameau de {key.split(':', 1)[1]}"
            since = "depuis" if n.effective_season <= season else "à partir de"
            norm_lines.append(f"pas plus de {n.quota:g} t par pêcheur et par saison pour {who}, adoptée à la veillée "
                              f"(proposition {n.proposal_id}), en vigueur {since} la saison {n.effective_season}")
            used.append(n.event_id)
        catches_txt, catch_ids, last_catches = self.known_catches(agent, horizon, season)
        used += catch_ids
        pinned = agent.memory.pinned(horizon, season)
        for m in pinned:
            retrieved.append({"id": m.event_id or m.id, "source": "pinned", "score": 1.0, "sim_time": m.t,
                              "text": m.text[:160]})
        if purpose == "catch":
            query = f"combien pêcher prise saison lac stock repeuple moitié pénurie dette prix marché {p.hamlet}"
        else:
            query = f"veillée règle quota promesse accord trahison pénurie {p.hamlet}"
        if assembly:
            query += " " + " ".join(u["payload"]["text"] for u in assembly.utterances[-4:]
                                            if u["sim_time"] <= horizon)
        # les rumeurs ont leur propre rubrique (toujours présente) : on ne les laisse pas aussi remonter par la mémoire
        skip = {m.id for m in pinned} | {m.id for m in agent.memory.items if m.kind == "rumeur"}
        mems = agent.memory.retrieve(query, horizon, self.cfg["memory"]["top_k"], exclude=skip)
        for m, s in mems:
            retrieved.append({"id": m.event_id or m.id, "source": "memory", "score": s, "sim_time": m.t,
                              "text": m.text[:160]})
        docs = self.retriever.search(query, p.hamlet, horizon, self.cfg["rag"]["top_k"])
        for d, s in docs:
            retrieved.append({"id": f"corpus:{d.id}", "source": "corpus", "score": round(s, 3), "sim_time": d.sim_time,
                              "text": d.text[:160]})
        rumors = self.active_rumors(horizon)
        for r in rumors:
            retrieved.insert(0, {"id": r["event_id"], "source": "rumor", "score": 1.0, "sim_time": r["t"],
                                 "text": r["text"][:160]})
        used += [r["id"] for r in retrieved if r["source"] != "corpus"]
        own = [f"saison {s} : {v:g} t" for s, v in sorted(agent.catches.items())[-4:]]
        obs = {
            "label": self.clock.label(horizon), "season": season, "stock_estimate": est, "role": p.role,
            "capacity": self.capacity, "collapse_ratio": self.lake.collapse_ratio, "stock_history": history,
            "n_fishers": len(self.fishers), "_entry": entry,
            "wealth": agent.wealth, "upkeep": self.econ["upkeep_per_season"], "debt_payment": p.debt_payment,
            "price": self.econ["price_per_tonne"], "boat_capacity": self.econ["boat_capacity"],
            "own_history": own, "norms": norm_lines, "known_catches": catches_txt,
            # chaque souvenir porte sa date : une parole de la veillée d'il y a deux saisons (« le lac a l'air bien rempli »)
            # ne doit pas passer pour l'état du lac d'aujourd'hui
            "pinned": [m.text for m in pinned],
            "memories": [f"({self.clock.label(m.t)}) {m.text}" for m, _ in mems],
            "documents": [f"[{d.title}] {d.text}" for d, _ in docs],
            "rumors": [r["text"] for r in rumors],
        }
        state = {
            "stock_estimate": est, "stock_true": round(self.lake.stock, 3), "capacity": self.capacity, "n_fishers": len(self.fishers),
            "quota": norm.quota if norm else None, "boat_capacity": self.econ["boat_capacity"],
            "upkeep": self.econ["upkeep_per_season"], "debt_payment": p.debt_payment,
            "price": self.econ["price_per_tonne"], "wealth": agent.wealth,
            "growth_rate": self.lake.r, "round": rnd,
            "rumors": obs["rumors"], "rumor_targets": self.named_fishers(obs["rumors"]) if rumors else [],
            "self_id": agent.id, "names": {a.id: (a.profile.first_name or a.profile.name.split()[0]) for a in self.fishers},
        }
        if assembly:
            visible_u = [u for u in assembly.utterances if u["sim_time"] <= horizon]
            obs["transcript"] = [
                f"{self.name(u['payload']['speaker'])} ({u['payload']['speaker']})"
                + ("" if u["payload"]["to"] == "tous" else f", à {self.name(u['payload']['to'])}")
                + f" : « {u['payload']['text']} »" for u in visible_u[-12:]]
            used += [u["event_id"] for u in visible_u[-12:]]
            props = [pr for pr in assembly.proposals.values() if pr.t <= horizon]
            obs["proposals"] = []
            best = None
            for pr in props:
                sup = [a for a, (pid, t, _) in assembly.support.items() if pid == pr.id and t <= horizon]
                obs["proposals"].append(f"{pr.id} : {pr.quota:g} t par pêcheur, proposée par {self.name(pr.author)} ; "
                                        f"soutiens : {', '.join(sup) or 'aucun'}")
                used.append(pr.event_id)
                if best is None or len(sup) > best[2]:
                    best = (pr.id, pr.quota, len(sup))
            state["leading_proposal"] = (best[0], best[1]) if best else None
            obs["participants"] = [{"id": a, "name": self.name(a), "label": self.agents[a].profile.archetype_label}
                                   for a in assembly.participants]
            obs["scope_label"] = assembly.label
            obs["round"] = rnd
            state["overfisher"] = self._overfisher(agent, last_catches, season - 1)
        return obs, state, retrieved, list(dict.fromkeys(used))

    def _overfisher(self, agent: Agent, last: dict, season: int) -> str | None:
        if not last:
            return None
        norm = self.applicable_norm(agent, season, self.clock.now())
        if norm:
            limit = norm.quota + self.scn["quota_tolerance"]
        else:
            vals = sorted(last.values())
            limit = 1.5 * vals[len(vals) // 2] + 0.5
        worst = max(last.items(), key=lambda kv: kv[1])
        return worst[0] if worst[1] > limit else None

    # ------------------------------------------------------------ actions du monde
    def apply_catch(self, agent: Agent, requested: float, decision: dict, horizon: float,
                    ration: float = 1.0, stock_at_action: float | None = None) -> dict:
        """Applique une prise. `stock_at_action` : stock au moment où l'action prend effet (en synchrone,
        le même pour toutes les barques parties ensemble ; en asynchrone, le stock courant)."""
        season = self.clock.season_of()
        before = self.lake.stock
        obs = decision["payload"]["observed"]
        stock_observed = obs["stock_estimate"]
        landed = round(self.lake.take(requested * ration), 3)
        ev = self.events.emit("catch", {
            "agent": agent.id, "hamlet": agent.profile.hamlet, "requested": requested, "landed": landed,
            "stock_observed": stock_observed, "stock_before": round(before, 3), "stock_after": round(self.lake.stock, 3),
            "decision_event_id": decision["event_id"], "info_horizon": round(horizon, 6), "rationed": ration < 1.0,
            "stock_at_horizon": obs["stock_true"],
            "stock_at_action": round(before if stock_at_action is None else stock_at_action, 3),
        }, actor=agent.id)
        self.catch_log.append(ev)
        agent.catches[season] = agent.catches.get(season, 0.0) + landed
        self.lake_update("catch", -landed)
        income = landed * self.econ["price_per_tonne"]
        agent.wealth += income
        self.events.emit("sale", {"agent": agent.id, "hamlet": agent.profile.hamlet, "tonnes": landed,
                                  "price": self.econ["price_per_tonne"], "income": round(income, 2),
                                  "wealth": round(agent.wealth, 2)}, actor=agent.id)
        note = f"J'ai pêché {landed:g} t cette saison ; le lac m'a semblé contenir environ {stock_observed:.0f} t."
        if landed + 1e-6 < requested * ration or ration < 1:
            note += f" J'en voulais {requested:g}, je n'ai pas pu tout prendre."
        self.remember(agent, note, "peche", 0.6, source_event_id=ev["event_id"])
        return ev

    def handle_command(self, cmd: dict, source: str = "ui"):
        errs = validate_command(cmd)
        if errs:
            self.bus.publish("deadletter", {"command": cmd, "errors": errs})
            return
        ctype = cmd["type"]
        params = {k: v for k, v in cmd.items() if k != "type"}
        if ctype in ("start_game", "new_game"):
            return          # commandes du salon (Engine) : sans objet pendant une partie
        if ctype in ("pause", "resume", "set_speed", "set_mode", "stop"):
            self._control_command(ctype, cmd, params, source)
            return
        inj = self.events.emit("injection", {"injection_type": ctype, "params": params, "source": source})
        if ctype == "drought":
            factor = float(cmd.get("factor", 0.5))
            delta = self.lake.shock(factor)
            self.lake_update("injection", delta)
            for a in self.fishers:
                self.remember(a, "Sécheresse : le niveau du lac a brutalement baissé, les fonds sont à découvert.",
                              "evenement", 0.9, source_event_id=inj["event_id"])
        elif ctype == "set_communication":
            if cmd.get("value") in ("valley", "hamlet", "none"):
                self.comm = cmd["value"]
        elif ctype == "set_visibility":
            self.visible = bool(cmd.get("value"))
        elif ctype == "announcement":
            text = str(cmd.get("text", "")).strip()[:300]
            if text:
                # la rumeur est connue de tous : elle figure dans le contexte de chaque décision à IA (voir `observe`)
                self.rumors.append({"text": text, "season": self.clock.season_of(), "t": self.clock.now(),
                                    "event_id": inj["event_id"]})
                for a in self.agents.values():
                    self.remember(a, f"On raconte dans la vallée : « {text} »", "rumeur", 0.8,
                                  source_event_id=inj["event_id"])

    def _control_command(self, ctype: str, cmd: dict, params: dict, source: str):
        """Pilotage de la partie. Chaque commande effective est tracée par un événement `injection`."""
        ctl = self.ctl
        if ctype == "stop":
            self.stop_requested, self.stopped_reason = True, "stop"
            self.events.emit("injection", {"injection_type": ctype, "params": params, "source": source})
            ctl.request_stop()
            return
        if ctype == "pause":
            changed = ctl.pause()
        elif ctype == "resume":
            changed = ctl.resume()
        elif ctype == "set_mode":
            value = cmd.get("value")
            changed = value in MODES and value != (ctl.pending_mode or ctl.mode) and ctl.request_mode(value)
        else:   # set_speed : un facteur (×0,25 à ×16…) ou "max" (aucune attente d'affichage)
            value = cmd.get("value")
            if value == "max":
                changed = not ctl.clock.fast
                ctl.set_fast(True)
            elif isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                changed = ctl.clock.fast or abs(ctl.clock.speed - float(value)) > 1e-9
                ctl.set_fast(False)
                params = {**params, "value": ctl.set_speed(float(value))}
            else:
                changed = False
        if changed:
            self.events.emit("injection", {"injection_type": ctype, "params": params, "source": source})
        self.publish_status()

    def poll_commands(self):
        for c in self.bus.poll_commands():
            self.handle_command(c)

    async def _command_pump(self):
        """Écoute les commandes de l'interface pendant toute la partie, quoi que fassent les orchestrateurs
        (même quand ils attendent la réponse d'un LLM). Publie aussi l'état toutes les 2 s."""
        n = 0
        while True:
            try:
                self.poll_commands()
                n += 1
                if n % 40 == 0:
                    self.publish_status()
                    if self.recorder:
                        self.recorder.flush()
            except Exception:       # une commande défaillante ne doit jamais rendre le jeu sourd aux suivantes
                log.exception("commande ou état non traités")
            await asyncio.sleep(0.05)

    # ------------------------------------------------------------ état publié
    def status_payload(self, state: str | None = None, **extra) -> dict:
        ctl = self.ctl
        return {
            "state": state or ("paused" if ctl.paused else "running"),
            "engine_id": self.engine_id, "wall_clock": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
            "run_id": self.run_id, "mode": ctl.mode, "pending_mode": ctl.pending_mode, "speed": self.clock.speed,
            "fast": self.clock.fast, "paused": ctl.paused, "season": self.season, "seasons": int(self.cfg["run"]["seasons"]),
            "sim_label": self.clock.label(), "end_reason": None, "error": None, "controls": True, "lobby": self.lobby,
            "ai": self.ai_providers, "advised_speed": self.advised_speed,
            **extra,
        }

    def publish_status(self, state: str | None = None, **extra):
        self.bus.publish("status", self.status_payload(state, **extra), key="engine")

    def scheduled_injections(self, season: int):
        for inj in self.scn.get("scheduled_injections") or []:
            if int(inj.get("season", -1)) == season:
                self.handle_command({k: v for k, v in inj.items() if k != "season"}, source="scenario")

    # ------------------------------------------------------------ veillée
    def open_assemblies(self, season: int, close_t: float) -> list[Assembly]:
        if self.comm == "none":
            return []
        if self.comm == "valley":
            groups = {"valley": [a.id for a in self.agents.values()]}
        else:
            groups = {}
            for h in HAMLETS:
                members = [a.id for a in self.fishers if a.profile.hamlet == h]
                if self.elder and self.elder.profile.hamlet == h:
                    members.append(self.elder.id)
                if len([m for m in members if self.agents[m].is_fisher]) >= 1:
                    groups[f"hamlet:{h}"] = members
        out = []
        for scope, members in groups.items():
            asm = Assembly(scope, members, season, close_t)
            self.events.emit("assembly_start", {"scope": scope, "participants": members})
            out.append(asm)
        self.assemblies = out
        return out

    def post_utterance(self, agent: Agent, asm: Assembly, outcome, rnd: int, horizon: float):
        d = outcome.data
        text = str(d.get("message", "")).strip()[:400]
        to = str(d.get("destinataire") or "tous").strip()
        if to not in asm.participants:
            to = "tous"
        heard = [u["event_id"] for u in asm.utterances if u["sim_time"] <= horizon]
        u = self.events.emit("utterance", {"speaker": agent.id, "to": to, "text": text, "scope": asm.scope,
                                           "round": rnd, "info_horizon": round(horizon, 6), "heard": heard[-12:],
                                           "decision_event_id": outcome.decision["event_id"]}, actor=agent.id)
        asm.utterances.append(u)
        now = self.clock.now()
        season = asm.season
        # proposition de règle
        q = to_number(d.get("proposition_quota"))
        if q is not None and 0 <= q <= self.econ["boat_capacity"]:
            pid = f"P{next(self._pid)}"
            pe = self.events.emit("proposal", {"proposal_id": pid, "author": agent.id, "quota": round(q, 2),
                                               "scope": asm.scope, "utterance_id": u["event_id"]}, actor=agent.id)
            asm.proposals[pid] = Proposal(pid, agent.id, round(q, 2), now, pe["event_id"], asm.scope)
            self._support(agent, asm, pid, u)
        # soutien
        sup = d.get("soutien")
        if isinstance(sup, str) and sup.strip():
            pid = sup.strip().upper()
            pr = asm.proposals.get(pid)
            if pr is None:
                pass  # proposition inexistante : ignorée
            elif pr.t > horizon:
                self.incident(agent.id, "temporal_violation",
                              f"soutien à {pid}, proposée après l'horizon d'information", "soutien rejeté")
            else:
                self._support(agent, asm, pid, u)
        # promesse
        if agent.is_fisher:
            pv = to_number(d.get("promesse"))
            if pv is not None and 0 <= pv <= self.econ["boat_capacity"]:
                pe = self.events.emit("promise", {"agent": agent.id, "amount": round(pv, 2), "for_season": season + 1,
                                                  "utterance_id": u["event_id"]}, actor=agent.id)
                self.promises[(agent.id, season + 1)] = (round(pv, 2), pe["event_id"])
                old = self.promise_memories.get((agent.id, season + 1))
                if old is not None:
                    old.pinned = False      # la nouvelle promesse remplace l'ancienne pour la même saison
                self.promise_memories[(agent.id, season + 1)] = self.remember(agent, f"J'ai promis à la veillée de ne pas pêcher plus de {pv:g} t à la saison "
                                     f"{season + 1}.", "promesse", 1.0, pinned=True, expires_season=season + 1,
                              source_event_id=pe["event_id"])
        # accusation
        acc = d.get("accuse")
        if isinstance(acc, str) and acc.strip().upper() in self.agents and acc.strip().upper() != agent.id:
            accused = self.agents[acc.strip().upper()]
            if accused.is_fisher:
                self.events.emit("accusation", {"accuser": agent.id, "accused": accused.id,
                                                "utterance_id": u["event_id"]}, actor=agent.id)
                if accused.id in asm.participants:
                    self.remember(accused, f"{agent.profile.name} m'a accusé devant tous d'avoir trop pêché.",
                                  "accusation", 0.95, pinned=True, expires_season=season + 1,
                                  source_event_id=u["event_id"])
        # ce que chacun retient
        self.remember(agent, f"À la veillée, j'ai dit : « {text} »", "parole", 0.4, source_event_id=u["event_id"])
        for pid in asm.participants:
            if pid == agent.id:
                continue
            listener = self.agents[pid]
            adr = "" if to == "tous" else (" (à moi)" if to == pid else f" (à {self.name(to)})")
            self.remember(listener, f"À la veillée, {agent.profile.name}{adr} a dit : « {text} »", "parole",
                          0.8 if to == pid else 0.5, source_event_id=u["event_id"])

    def _support(self, agent: Agent, asm: Assembly, pid: str, u: dict):
        se = self.events.emit("support", {"agent": agent.id, "proposal_id": pid, "utterance_id": u["event_id"]},
                              actor=agent.id)
        asm.support[agent.id] = (pid, self.clock.now(), se["event_id"])

    def close_assembly(self, asm: Assembly):
        if asm.closed:
            return
        asm.closed = True
        fishers_present = [a for a in asm.participants if self.agents[a].is_fisher]
        tally: dict[str, list[str]] = {}
        for aid, (pid, _, _) in asm.support.items():
            if self.agents[aid].is_fisher:
                tally.setdefault(pid, []).append(aid)
        adopted = None
        if tally:
            pid, sups = max(tally.items(), key=lambda kv: (len(kv[1]), -int(kv[0][1:])))
            if len(sups) * 2 > len(fishers_present):
                pr = asm.proposals[pid]
                ne = self.events.emit("norm_adopted", {
                    "proposal_id": pid, "quota": pr.quota, "scope": asm.scope, "effective_season": asm.season + 1,
                    "supporters": sorted(sups), "participants": asm.participants, "author": pr.author})
                self.norms.append(Norm(asm.scope, pr.quota, asm.season + 1, pid, self.clock.now(),
                                       ne["event_id"], sorted(sups)))
                adopted = pid
                for aid in asm.participants:
                    self.remember(self.agents[aid], f"Règle adoptée chez l'ancien ({asm.label}) : pas plus de "
                                                    f"{pr.quota:g} t par pêcheur à partir de la saison {asm.season + 1}, "
                                                    f"soutenue par {len(sups)} pêcheurs sur {len(fishers_present)}.",
                                  "regle", 0.9, source_event_id=ne["event_id"])
        self.events.emit("assembly_end", {"scope": asm.scope, "adopted_proposal": adopted,
                                          "utterances": len(asm.utterances)})

    # ------------------------------------------------------------ fin de saison
    def end_season(self, season: int):
        delta = self.lake.regrow()
        self.lake_update("regrowth", delta)
        tol = self.scn["promise_tolerance"]
        for a in self.fishers:
            landed = a.catches.get(season, 0.0)
            key = (a.id, season)
            if key in self.promises:
                promised, pe_id = self.promises[key]
                kept = landed <= promised + tol
                self.events.emit("promise_outcome", {"agent": a.id, "promise_event_id": pe_id, "promised": promised,
                                                     "landed": round(landed, 3), "kept": kept, "season": season},
                                 actor=a.id)
                if not kept:
                    self.remember(a, f"J'avais promis {promised:g} t pour la saison {season} et j'en ai pris "
                                     f"{landed:g}. Personne ne doit le savoir." if not self.visible else
                                  f"J'avais promis {promised:g} t pour la saison {season} et j'en ai pris {landed:g}. "
                                  f"Tout le monde l'a vu au marché.", "promesse", 0.9)
            a.wealth -= self.econ["upkeep_per_season"] + a.profile.debt_payment
            self.remember(a, f"Bilan de la saison {season} : {landed:g} t pêchées, il me reste {a.wealth:.0f} écus.",
                          "bilan", 0.5)
        self.events.emit("season_end", {
            "stock": round(self.lake.stock, 3),
            "catches": {a.id: round(a.catches.get(season, 0.0), 3) for a in self.fishers},
            "wealth": {a.id: round(a.wealth, 2) for a in self.fishers},
            "norms_in_force": [{"scope": n.scope, "quota": n.quota, "proposal_id": n.proposal_id,
                                "effective_season": n.effective_season}
                               for n in (self.norm_for_scope(sc, season, self.clock.now())
                                         for sc in dict.fromkeys(x.scope for x in self.norms)) if n],
        })

    # ------------------------------------------------------------ démarrage / fin
    def start(self):
        cfg_hash = hashlib.sha1(json.dumps(self.cfg, sort_keys=True, default=str).encode()).hexdigest()[:12]
        self.events.emit("run_start", {
            "mode": self.T["mode"], "seed": int(self.cfg["run"]["seed"]), "seasons": int(self.cfg["run"]["seasons"]),
            "lake": {"capacity": self.capacity, "stock": round(self.lake.stock, 3), "growth_rate": self.lake.r,
                     "collapse_ratio": self.lake.collapse_ratio, "sustainable_yield": sustainable_yield(self.cfg)},
            "agents": [{**a.profile.public(), "wealth": a.wealth, "offset_days": a.offset_days}
                       for a in self.agents.values()],
            "hamlets": HAMLETS, "scenario": {"communication": self.comm, "catches_visible": self.visible,
                                             "assembly_rounds": self.scn["assembly_rounds"]},
            "season_days": self.T["season_days"], "config_hash": cfg_hash, "llm_tiers": self.router.describe(),
            "label": str(self.cfg["run"].get("label", "")),
            "population": {"fishers": len(self.fishers), "rule_fraction": self.cfg["population"]["rule_fraction"]},
        })
        self.lake_update("init", 0.0)
        for a in self.agents.values():
            self.remember(a, "Une nouvelle année commence sur le lac de Vellmor.", "bilan", 0.2)
        self.publish_status()

    async def finish(self):
        self.events.emit("run_end", {"reason": self.stopped_reason, "seasons_completed": self.season})
        await self.router.aclose()
        self.bus.flush()
        self.ended = True
        self.publish_status("ended", end_reason=self.stopped_reason, paused=False)
        if self.recorder:
            self.recorder.flush()
            u = self.router.usage
            (self.run_dir / "summary.json").write_text(json.dumps({
                "run_id": self.run_id, "seasons_completed": self.season, "final_stock": round(self.lake.stock, 3),
                "capacity": self.capacity, "llm_calls": u.calls, "prompt_tokens": u.prompt_tokens,
                "completion_tokens": u.completion_tokens, "llm_latency_s": round(u.latency_s, 2),
                "by_tier": u.by_tier, "wall_s": round(self.clock.wall_elapsed(), 2), "reason": self.stopped_reason,
            }, indent=2, ensure_ascii=False))
            self.recorder.close()

    def begin_season(self, season: int, mode: str):
        """Début de saison, commun aux deux orchestrations."""
        self.season = season
        self.events.emit("season_start", {"stock": round(self.lake.stock, 3), "mode": mode})
        self.publish_status()
        self.scheduled_injections(season)

    async def run(self):
        """Joue les saisons l'une après l'autre ; le mode (synchrone / asynchrone) est relu à chaque saison."""
        self.start()
        pump = asyncio.create_task(self._command_pump())
        try:
            for season in range(1, int(self.cfg["run"]["seasons"]) + 1):
                if self.stop_requested:
                    break
                await self.ctl.checkpoint()
                runner = SyncRunner(self) if self.ctl.take_mode() == "sync" else AsyncRunner(self)
                await runner.season(season)
        except StopRun:
            self.stop_requested = True
            if self.stopped_reason == "completed":       # un arrêt déjà motivé (extinction du lac…) garde sa raison
                self.stopped_reason = "stop"
        except Exception as exc:
            self.stopped_reason = f"erreur : {exc}"[:200]      # la partie est tracée comme interrompue, pas « terminée »
            raise
        finally:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
            await self.finish()


# ======================================================================== mode synchrone
class SyncRunner:
    ROUND_STEP = 0.05   # ≈ 1 h 12 simulées entre deux tours de parole

    def __init__(self, w: World):
        self.w = w
        self.c = w.clock

    async def goto(self, t: float):
        """Avance l'horloge jusqu'à `t` : attente d'affichage (vitesse et pause comprises), puis saut."""
        ctl = self.w.ctl
        await ctl.checkpoint()
        dt = t - self.c.now()
        if dt > 0 and not self.c.fast:
            await ctl.sleep(min(4.0, dt / self.c.base_rate))
        await ctl.checkpoint()          # une pause demandée pendant l'attente fige le monde avant le saut
        self.c.set(max(t, self.c.now()))

    async def season(self, season: int):
        w, T = self.w, self.w.T
        w.season = season
        t0 = self.c.season_start(season)
        await self.goto(t0)
        w.begin_season(season, "sync")
        # --- pêche : même instantané pour tous
        h = t0 + T["fishing_open_day"]
        await self.goto(h)
        w.events.emit("phase", {"name": "fishing", "state": "open"})
        outs = await w.ctl.guard(asyncio.gather(*(decide_catch(w, a, h) for a in w.fishers)))
        await self.goto(h + 1.0)        # départ en mer : toutes les barques au même instant
        total = sum(o.value for o in outs)
        s0 = w.lake.stock
        ration = min(1.0, s0 / total) if total > 0 else 1.0
        for a, o in zip(w.fishers, outs):
            w.apply_catch(a, o.value, o.decision, h, ration, stock_at_action=s0)
        await self.goto(t0 + T["fishing_close_day"])
        w.events.emit("phase", {"name": "fishing", "state": "close"})
        # --- veillée : tours de parole simultanés
        ta = t0 + T["assembly_day"]
        await self.goto(ta)
        asms = w.open_assemblies(season, t0 + T["assembly_close_day"])
        if asms:
            w.events.emit("phase", {"name": "assembly", "state": "open"})
            for rnd in range(1, int(w.scn["assembly_rounds"]) + 1):
                hr = ta + (rnd - 1) * self.ROUND_STEP
                await self.goto(hr)
                jobs = [(asm, w.agents[aid]) for asm in asms for aid in asm.participants]
                outs = await w.ctl.guard(asyncio.gather(*(speak(w, a, asm, rnd, hr) for asm, a in jobs)))
                await self.goto(hr + self.ROUND_STEP / 2)
                for (asm, a), o in zip(jobs, outs):
                    w.post_utterance(a, asm, o, rnd, hr)
            await self.goto(t0 + T["assembly_close_day"])
            for asm in asms:
                w.close_assembly(asm)
            w.events.emit("phase", {"name": "assembly", "state": "close"})
        # --- repeuplement et bilan
        await self.goto(t0 + T["regrowth_day"])
        w.events.emit("phase", {"name": "regrowth", "state": "open"})
        w.end_season(season)


# ======================================================================== mode asynchrone
class AsyncRunner:
    TICK = 0.02

    def __init__(self, w: World):
        self.w = w
        self.c = w.clock
        self.heap: list = []
        self.seq = itertools.count()
        self.tasks: set[asyncio.Task] = set()
        self.by_kind: dict[str, dict[str, asyncio.Task]] = {"fish": {}, "talk": {}}     # tâches par agent, pour les annuler
        self.thinking: dict[tuple[str, str], int] = {}     # (nature, agent) → tour de parole : qui réfléchit en ce moment
        self.done = False

    def at(self, t: float, fn, *args):
        heapq.heappush(self.heap, (t, next(self.seq), fn, args))

    def sleep_until(self, t: float) -> asyncio.Future:
        """Attente en temps simulé (et non réel) : la tâche reprend quand l'horloge atteint `t`."""
        fut = asyncio.get_running_loop().create_future()
        self.at(t, lambda: fut.done() or fut.set_result(None))
        return fut

    def spawn(self, coro, kind: str | None = None, agent: str | None = None):
        task = asyncio.create_task(self._quiet(coro))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        if kind:
            self.by_kind[kind][agent] = task
            task.add_done_callback(lambda t, k=kind, a=agent: self.by_kind[k].pop(a, None)
                                   if self.by_kind[k].get(a) is t else None)

    def expire(self, kind: str, handled_by: str, what: str):
        """Une fenêtre se ferme (pêche, veillée) : ceux qui réfléchissent encore ont raté leur tour. On le constate à cet
        instant précis, et on abandonne leur appel : leur réponse arriverait trop tard pour servir, et l'attendre ferait
        durer la saison des minutes de plus (c'était cette « queue » qui rendait le jeu asynchrone si lent)."""
        for (k, aid), rnd in list(self.thinking.items()):
            if k == kind:
                self.w.incident(aid, "missed_window", what.format(rnd=rnd), handled_by)
        for task in list(self.by_kind[kind].values()):
            if not task.done():
                task.cancel()

    @staticmethod
    async def _quiet(coro):
        try:
            await coro
        except StopRun:       # arrêt demandé pendant que cet agent réfléchissait : fin normale
            pass

    async def season(self, season: int):
        """Joue une saison : le monde avance avec le temps réel, chaque agent à son rythme."""
        w = self.w
        self.at(self.c.season_start(season), self.season_start, season)
        last = time.monotonic()
        try:
            while True:
                if await w.ctl.checkpoint():   # reprise après une pause : on ne rattrape pas le temps de la pause
                    last = time.monotonic()
                while self.heap and self.heap[0][0] <= self.c.now() + 1e-9:
                    _, _, fn, args = heapq.heappop(self.heap)
                    fn(*args)
                for _ in range(3):                # laisse les tâches réveillées avancer jusqu'à leur appel LLM
                    await asyncio.sleep(0)
                if self.done and not self.tasks:
                    break
                if not self.heap and not self.tasks:
                    break
                now_wall = time.monotonic()
                dt, last = now_wall - last, now_wall
                if self.done:                      # calendrier terminé : on laisse finir les tâches sans avancer le monde
                    await asyncio.sleep(self.TICK)
                    continue
                # tant qu'un agent réfléchit (appel LLM en cours), le temps simulé suit le temps réel ;
                # sinon personne n'est désavantagé et il peut accélérer jusqu'à la prochaine échéance
                self.c.advance_wall(dt, self.heap[0][0] if self.heap else None, busy=self.c.in_flight > 0)
                await asyncio.sleep(self.TICK)
        finally:
            for t in list(self.tasks):
                t.cancel()
            if self.tasks:
                await asyncio.gather(*self.tasks, return_exceptions=True)

    # --- calendrier
    def season_start(self, season: int):
        w, T = self.w, self.w.T
        w.begin_season(season, "async")
        t0 = self.c.season_start(season)
        self.at(t0 + T["fishing_open_day"], lambda: w.events.emit("phase", {"name": "fishing", "state": "open"}))
        for a in w.fishers:
            self.at(t0 + T["fishing_open_day"] + a.offset_days, self.spawn_fish, a, t0 + T["fishing_close_day"])
        self.at(t0 + T["fishing_close_day"], self.fishing_close)
        self.at(t0 + T["assembly_day"], self.assembly_open, season, t0 + T["assembly_close_day"])
        self.at(t0 + T["assembly_close_day"], self.assembly_close)
        self.at(t0 + T["regrowth_day"], self.regrowth, season)

    def spawn_fish(self, a: Agent, close_t: float):
        self.spawn(self.fish(a, close_t), "fish", a.id)

    def fishing_close(self):
        self.w.events.emit("phase", {"name": "fishing", "state": "close"})
        self.expire("fish", "sortie perdue",
                    "décision encore en cours à la fermeture de la pêche : l'IA réfléchissait encore")

    async def fish(self, a: Agent, close_t: float):
        w = self.w
        h = self.c.now()
        self.thinking[("fish", a.id)] = 0
        try:
            o = await decide_catch(w, a, h)
        finally:
            self.thinking.pop(("fish", a.id), None)
        if self.c.now() > close_t:
            w.incident(a.id, "missed_window", f"décision prise à {self.c.label()}, après la fermeture de la pêche",
                       "sortie perdue")
            return
        w.apply_catch(a, o.value, o.decision, h)

    def assembly_open(self, season: int, close_t: float):
        asms = self.w.open_assemblies(season, close_t)
        if not asms:
            return
        self.w.events.emit("phase", {"name": "assembly", "state": "open"})
        for asm in asms:
            for aid in asm.participants:
                self.spawn(self.talk(self.w.agents[aid], asm), "talk", aid)

    async def talk(self, a: Agent, asm: Assembly):
        w = self.w
        for rnd in range(1, int(w.scn["assembly_rounds"]) + 1):
            if asm.closed:
                return
            h = self.c.now()
            self.thinking[("talk", a.id)] = rnd
            try:
                o = await speak(w, a, asm, rnd, h)
            finally:
                self.thinking.pop(("talk", a.id), None)
            if asm.closed or self.c.now() > asm.close_t:
                w.incident(a.id, "missed_window", f"parole du tour {rnd} prête après la fin de la veillée",
                           "réplique perdue")
                return
            w.post_utterance(a, asm, o, rnd, h)
            # on écoute les autres avant de reprendre la parole
            await self.sleep_until(self.c.now() + float(w.T.get("assembly_turn_gap_days", 0.05)))

    def assembly_close(self):
        if not self.w.assemblies:
            return
        self.expire("talk", "réplique perdue",
                    "parole du tour {rnd} pas prête à la fin de la veillée : l'IA réfléchissait encore")
        for asm in self.w.assemblies:
            self.w.close_assembly(asm)
        self.w.events.emit("phase", {"name": "assembly", "state": "close"})
        self.w.assemblies = []

    def regrowth(self, season: int):
        w = self.w
        w.events.emit("phase", {"name": "regrowth", "state": "open"})
        w.end_season(season)
        self.done = True        # la saison est jouée ; `World.run` choisit l'orchestration de la suivante
