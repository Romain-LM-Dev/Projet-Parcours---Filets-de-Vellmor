"""Le monde de FILETS et ses deux orchestrations du temps (C3, C4).

Calendrier d'une saison (jours simulés depuis le début de la saison, configurable) :

    J0 06:00   ouverture de la pêche : chaque pêcheur décide de sa prise visée (la prise réelle dépend de la réussite du jour,
               de la saison de l'année et des événements : voir `climate.py`)
    J20        fermeture : une sortie décidée après est perdue (incident `missed_window`)
    J25 18:00  veillée chez l'ancien (selon le mode de communication) : au conseil de la vallée, un élu par village et l'ancien ;
               propositions de quota, soutiens, promesses, accusations, exclusions, patrouille du lac
    J29        fin de la veillée : adoption d'une règle si au moins la moitié des élus présents la soutient
    J29 21:36  repeuplement du lac, bilan de saison, promesses tenues ou trahies

Mode synchrone : à chaque pas, tous les agents observent le même instantané, décident
(la latence des LLM n'a aucun effet sur le temps simulé), puis leurs actions s'appliquent
au même instant. Si la somme des prises dépasse le stock, elles sont rationnées au prorata.
À la veillée, on parle à tour de rôle et chacun entend ceux qui ont parlé avant lui : les dialogues sont dépendants.

Mode asynchrone : l'horloge avance avec le temps réel. Chaque pêcheur se réveille à son
propre rythme, observe le lac, réfléchit (latence réelle du LLM), et sa prise s'applique
au stock *du moment où il a fini de réfléchir* : il a pu changer entre-temps (écart tracé
dans l'événement `catch` : `stock_observed` vs `stock_before`). À la veillée, chacun s'exprime
de son côté dès qu'il a fini de réfléchir, sans entendre les autres : les dialogues sont indépendants,
et tous votent ensuite sur ce qui a été déposé.

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
import math
import random
import re
import time
import unicodedata
import zlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import prompts
from .agents import (Agent, _ask_llm, ballot, ballot_election, debrief_villager, decide_catch, patrol_decision, speak)
from .climate import EVENTS, Climate
from .policies import patrol_vote, sanction_vote
from .clock import SimClock
from .config import ROOT, sustainable_yield
from .control import MODES, GameControl, StopRun
from .events import EventFactory, Recorder
from .lake import Lake
from .memory import MemoryBank, MemoryStore, VectorMemory
from .objects import archive_run, make_objects
from .profiles import Profile, build_population, villages_of
from .rag import Retriever, VectorRetriever
from .schemas import validate_command
from .llm import LLMRouter, to_number
from .vectors import PgVectorStore, make_embedder, postgres_dsn

log = logging.getLogger("filets.world")

# La confiance de chaque agent (pêcheurs et ancien) envers chaque pêcheur, de 0 (aucune) à 1 (totale), 0,5 au départ. Le
# moteur ne la fixe pas : chaque agent juge lui-même, à la veillée, ce que ce qu'il apprend de chacun change pour lui, selon sa
# morale et ses intérêts (une IA dans sa réplique, champ `confiance` ; un agent à règles selon son caractère,
# `policies.trust_rule`), de −3 à +3 pas de 0,1.
TRUST_START = 0.5
TRUST_STEP = 0.1
LOYAL = 0.8        # un témoin ne dénonce pas devant tous celui à qui il fait confiance à ce point

# Le lac a une zone par village (sa rive, où ses pêcheurs vont d'ordinaire) et le large : voir `World.zones`.
# Les indices et ce qu'ils pèsent dans le jugement de l'ancien (voir `World.weigh_evidence` et `scenario.detection`).
DETECTION = {"patrol": 0.9, "patrol_error": 0.12, "witness": 0.4, "witness_error": 0.3, "seen_leaving": 0.3, "lifestyle": 0.5,
             "lake_error": 0.03, "margin_t": 0.3, "margin_ratio": 0.25, "proof": 2.0}
PATROL = {"cost": 15, "legs": 3, "days": 14, "enabled": True}
EVIDENCE = {"patrouille": 3.0, "temoin": 1.0, "depart": 1.0, "train_de_vie": 0.5, "comptes": 0.5}
HOW = {"patrouille": "la patrouille du lac a mesuré sa barque", "temoins": "des voisins l'ont vu",
       "indices": "les indices concordaient"}
PATROL_ACTIONS = ("patrouille", "fin_patrouille")      # les propositions du conseil qui ne visent aucun pêcheur
LOW_LAKE = 0.3                 # sous ce niveau du lac (part de la capacité), le poisson est plus dur à prendre
SKILL_STEP = 0.005             # rendement gagné par année d'expérience au-delà de 15 ans (perdu en deçà), de 0 à 40 ans


def day_word(factor: float) -> str:
    """Ce que rapporte la pêche par rapport à la prise visée, dit comme un pêcheur : « une bonne pêche »."""
    return ("très mauvaise" if factor < 0.6 else "mauvaise" if factor < 0.85 else "ordinaire" if factor < 1.15
            else "bonne" if factor < 1.4 else "excellente")


WEATHER_WORD = {"calme": "par temps calme", "ordinaire": "par temps ordinaire", "agité": "par temps agité",
                "tempête": "dans la tempête"}


def outings_text(outs: list[dict]) -> str:
    """Les sorties d'une saison, dites par le pêcheur : le temps qu'il a fait à chacune."""
    seen = {w: sum(o["weather"] == w for o in outs) for w in WEATHER_WORD}
    return f"Sur {len(outs)} sortie{'s' if len(outs) > 1 else ''} : " + ", ".join(
        f"{k} {WEATHER_WORD[w]}" for w, k in seen.items() if k) + "."


@dataclass
class Proposal:
    id: str
    author: str
    quota: float
    t: float
    event_id: str
    scope: str


@dataclass
class Sanction:
    """Une proposition soumise au vote du conseil : interdire un pêcheur de pêche (`exclure`), lever son interdiction
    (`reautoriser`), ou installer (`patrouille`) / retirer (`fin_patrouille`) la patrouille du lac, qui ne vise personne."""
    id: str
    author: str
    target: str
    action: str
    t: float
    event_id: str
    votes: dict[str, bool] = field(default_factory=dict)       # votant -> pour (True) ou contre (False)


@dataclass
class Assembly:
    scope: str                       # "valley" ou "hamlet:<nom>"
    participants: list[str]
    season: int
    close_t: float
    utterances: list[dict] = field(default_factory=list)       # événements `utterance`
    proposals: dict[str, Proposal] = field(default_factory=dict)
    support: dict[str, tuple[str, float, str]] = field(default_factory=dict)  # agent -> (proposal, t, event_id)
    stated: dict[str, float] = field(default_factory=dict)     # agent -> dernier quota qu'il a dit vouloir (proposé ou promis)
    accused: list[tuple[float, str]] = field(default_factory=list)     # (instant, accusé) : qui a été mis en cause, et quand
    sanctions: dict[str, Sanction] = field(default_factory=dict)        # propositions soumises au vote (voir `Sanction`)
    mode: str = "sync"               # sync : on s'entend, tour à tour ; async : chacun parle de son côté, sans entendre les autres
    held: dict[str, tuple] = field(default_factory=dict)       # async : paroles prêtes (agent -> (réponse, instant)), déposées ensemble
    delegates: bool = False          # le conseil des élus (un par village), et non tous les pêcheurs
    closed: bool = False

    @property
    def label(self) -> str:
        if self.scope == "valley":
            return "conseil de la vallée" if self.delegates else "toute la vallée"
        return f"village de {self.scope.split(':', 1)[1]}"

    @property
    def independent(self) -> bool:
        """Dialogues indépendants (asynchrone) : personne n'entend les paroles des autres avant de voter."""
        return self.mode == "async"


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
        # Où vivent le corpus et les souvenirs : en mémoire (BM25, par défaut) ou dans PostgreSQL + pgvector ;
        # et où l'on archive la partie (stockage objet). Les connexions s'ouvrent au début de `run`.
        self.objects = make_objects(cfg)
        self.vectors = self.memory_bank = None
        if cfg["rag"].get("backend", "bm25") == "pgvector":
            embedder = make_embedder(cfg["rag"])
            self.vectors = PgVectorStore(postgres_dsn(cfg), embedder)
            self.memory_bank = MemoryBank(self.vectors, embedder, run_id)

        def memory_of(owner: str) -> MemoryStore:
            if self.memory_bank is not None:
                return VectorMemory(owner, mcfg["recency_decay_per_day"], mcfg["weights"], self.memory_bank)
            return MemoryStore(owner, mcfg["recency_decay_per_day"], mcfg["weights"])

        self.agents: dict[str, Agent] = {}
        lo, hi = t["async_offset_days"]
        for i, p in enumerate(build_population(cfg)):
            arng = random.Random(seed * 1000 + i)
            self.agents[p.id] = Agent(p, memory_of(p.id), arng, p.wealth, offset_days=round(arng.uniform(lo, hi), 3),
                                      temper=round(0.85 + 0.3 * arng.random(), 3))
        self.fishers = [a for a in self.agents.values() if a.is_fisher]
        self.elder = next((a for a in self.agents.values() if not a.is_fisher), None)
        # la vallée : ses villages (une zone du lac chacun, plus le large), et son conseil, un élu par village
        self.hamlets = villages_of([a.profile for a in self.fishers])
        self.zones = [*self.hamlets, "large"]
        self.delegates = self.scn.get("council", "delegates") == "delegates"
        self.reps: dict[str, str] = {}           # village -> pêcheur élu pour le représenter au conseil
        self.last_council: Assembly | None = None    # le dernier conseil de la vallée : les absents en apprennent la suite
        # les bateaux : la prise d'un pêcheur ne dépasse ni la cale de son bateau, ni sa part de la moitié du lac (proportionnelle
        # à la cale : à eux tous, ils ne peuvent prendre que la moitié du lac en une saison) ; au moins la prise minimale visée
        self.boats = self.econ["boats"]
        holds = {a.id: float(self.boats[a.profile.boat]["capacity"]) for a in self.fishers}
        total = sum(holds.values()) or 1.0
        self.hold = {aid: min(h, self.capacity / 2 * h / total) for aid, h in holds.items()}
        self.boat_max = max(float(b["capacity"]) for b in self.boats.values())       # le plus gros bateau qui existe
        self.max_catch = max(self.hold.values(), default=0.0)
        self.min_catch = min(self.econ.get("min_catch", 0.0), min(self.hold.values(), default=0.0))
        values = {"capacity": f"{self.capacity:.0f}", "half_capacity": f"{self.capacity / 2:.0f}",
                  "n_fishers": len(self.fishers), "price": self.econ["price_per_tonne"],
                  "upkeep": self.econ["upkeep_per_season"]}
        places = (tuple(self.hamlets), self.elder.profile.hamlet if self.elder else "")     # (registres des villages sans registre écrit)
        if self.vectors is not None:
            self.retriever = VectorRetriever(ROOT / cfg["rag"]["corpus_dir"], values, self.vectors, self.vectors.embedder,
                                             self.objects, float(cfg["rag"].get("min_score", 0.0)), *places)
        else:
            self.retriever = Retriever(ROOT / cfg["rag"]["corpus_dir"], values, *places)
        self.router = LLMRouter(cfg, self.clock, self.events, seed, self.ctl)
        self.norms: list[Norm] = []          # historique complet, dans l'ordre d'adoption
        self.promises: dict[tuple[str, int], tuple[float, str]] = {}
        self.promise_memories: dict[tuple[str, int], object] = {}   # promesse épinglée en cours
        # ce que chacun a déclaré à l'ancien (événements `report`, par (agent, saison)) : le seul chiffre que les autres
        # connaissent ; et les déclarations mensongères, par événement `report` ({agent, season, declared, landed, found_t})
        self.reports: dict[tuple[str, int], dict] = {}
        self.lies: dict[str, dict] = {}
        self.trust = {o: {s.id: TRUST_START for s in self.fishers if s.id != o} for o in self.agents}
        # la détection : sorties de chaque saison ({agent, zone, landed, secret, patrol, event_id}), indices (payload de `clue`
        # + saison, instant), comptes du lac, accusations ((instant, accusé, accusateur)), et ce que la vallée tient pour établi
        # ((agent, saison) -> {value, t, how, secret}) ; ses propres tirages, pour ne pas déplacer les autres hasards
        self.detection = {**DETECTION, **(self.scn.get("detection") or {})}
        self.trips: dict[int, list[dict]] = {}
        self.clues: list[dict] = []
        self.audits: dict[int, dict] = {}
        self.accusations: dict[int, list[tuple[float, str, str]]] = {}
        self.established: dict[tuple[str, int], dict] = {}
        self.lie_rng = random.Random(seed + 7)
        self._investigated_season = self._weighed_season = 0
        self.banned: dict[str, int] = {}         # pêcheur interdit de pêche -> saison où l'interdiction a pris effet
        # la patrouille du lac, si le conseil en a voté une ({since, proposal_id}) ; ses étapes de la saison ({zone, from_day,
        # to_day}, en jours depuis le début de la saison) ; le climat de la saison (saison de l'année, événements)
        self.patrol: dict | None = None
        self.patrol_cfg = {**PATROL, **(self.scn.get("patrol") or {})}
        self.patrol_on = bool(self.patrol_cfg.get("enabled", True))        # la patrouille fait-elle partie de cette partie ? (menu)
        if self.patrol_on and self.patrol_cfg.get("from_season"):   # patrouille installée d'emblée, sans vote (expériences de comparaison)
            self.patrol = {"since": int(self.patrol_cfg["from_season"]), "proposal_id": "config"}
        self.patrol_legs: dict[int, list[dict]] = {}
        self.patrol_log: dict[int, list[str]] = {}       # ce que la patrouille a relevé, saison par saison
        # son capitaine est un agent à part entière (il réfléchit comme l'ancien : une IA, ou des règles) ; il n'est ni pêcheur ni
        # de l'ancien : il ne siège pas, ne vote pas, ne juge pas
        self.patrol_agent: Agent | None = None
        if self.patrol_on:
            kind = self.elder.profile.kind if self.elder else cfg["population"].get("elder_kind", "llm")
            self.patrol_agent = Agent(Profile(
                id="PAT", name="Capitaine Aubry, la patrouille", hamlet=self.elder.profile.hamlet if self.elder else self.hamlets[0],
                archetype="patrouille", archetype_label="la patrouille du lac", experience=30, debt_payment=0, wealth=0,
                traits="", voice="bref, précis, sans illusion", kind=kind, tier="grand" if kind == "llm" else None,
                role="patrouille", first_name="Aubry", boat=""), memory_of("PAT"), random.Random(seed * 1000 + 999), 0.0)
        self.climate = Climate(cfg, seed)
        self.conditions = self.climate.conditions()
        self.season = 0
        self.stop_requested = False
        self.stopped_reason = "completed"
        self._pid = itertools.count(1)
        self._xid = itertools.count(1)       # propositions d'exclure ou de réautoriser : X1, X2…
        self.collapse_flagged = False
        self.obs_rng = random.Random(seed + 99)
        self.assemblies: list[Assembly] = []
        self.rumors: list[dict] = []         # annonces diffusées par le joueur : {text, season, t, event_id}
        self.waiting_note: str | None = None  # « le monde attend N IA » (asynchrone), repris dans l'état du moteur
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

    def fisher_ref(self, raw) -> str | None:
        """Le pêcheur que désigne `raw` : son identifiant, ou son nom (un petit modèle écrit souvent « Odile de Bramois » là où
        l'on attend F02, et son jugement ou sa proposition se perdait) ; None s'il n'en désigne aucun, ou plusieurs."""
        sid = str(raw).strip().upper()
        if sid in self.agents:
            return sid if self.agents[sid].is_fisher else None
        found = self.named_fishers([str(raw)])
        return found[0] if len(found) == 1 else None

    # ------------------------------------------------------------ déclarations, mensonges, confiance
    def can_see(self, observer: Agent, subject: Agent) -> bool:
        """L'observateur connaît-il la déclaration de `subject` ? Toute la vallée si les déclarations sont lues à tous, sinon le
        seul hameau ; l'ancien, qui les reçoit, toujours."""
        return self.visible or not observer.is_fisher or observer.profile.hamlet == subject.profile.hamlet

    def known_catch(self, aid: str, season: int, horizon: float) -> float | None:
        """Ce que la vallée sait de la prise de `aid` à cette saison : sa déclaration, ou, si l'ancien a établi qu'il mentait, ce
        que les indices en disent (une estimation, pas la vérité)."""
        found = self.established.get((aid, season))
        if found is not None and found["t"] <= horizon and found["value"] is not None:
            return found["value"]
        rep = self.reports.get((aid, season))
        if rep is None or rep["sim_time"] > horizon:
            return None
        return rep["payload"]["declared"]

    def lied(self, aid: str, season: int) -> bool:
        return any(lie["agent"] == aid and lie["season"] == season for lie in self.lies.values())

    def cheated(self, aid: str, season: int) -> bool:
        """A-t-il triché cette saison (déclaration mensongère, ou sortie en cachette d'un interdit) ? La vérité, que lui seul
        connaît : c'est elle qui le fait se taire quand il a vu quelque chose."""
        return self.lied(aid, season) or any(t["agent"] == aid and t["secret"] for t in self.trips.get(season, []))

    def reputation(self, subject: str) -> float:
        vals = [row[subject] for row in self.trust.values() if subject in row]
        return round(sum(vals) / len(vals), 3) if vals else TRUST_START

    def judge(self, observer: Agent, changes, source_event_id: str | None = None):
        """`observer` revoit sa confiance envers les pêcheurs de `changes` (identifiant ou nom -> de −3 à +3, en dixièmes) : c'est
        son jugement, selon sa morale et ses intérêts, et le moteur n'y ajoute rien. Une valeur illisible, hors des pêcheurs ou
        sur soi-même est ignorée. Un événement `trust` par personne dont la confiance change."""
        if not isinstance(changes, dict):
            return
        row = self.trust[observer.id]
        for key, raw in changes.items():
            sid, steps = self.fisher_ref(key), to_number(raw)
            if sid not in row or steps is None:
                continue
            old = row[sid]
            new = round(min(1.0, max(0.0, old + TRUST_STEP * round(max(-3.0, min(3.0, steps))))), 3)
            if new == old:
                continue
            row[sid] = new
            self.events.emit("trust", {
                "subject": sid, "cause": f"jugement de {self.first_name(observer.id)}", "values": {observer.id: new},
                "reputation": self.reputation(sid), "by": observer.id, "delta": round(new - old, 3),
                "source_event_id": source_event_id}, actor=observer.id)

    # ------------------------------------------------------------ indices, jugement, interdiction, patrouille
    def beyond_declared(self, estimate: float, said: float) -> bool:
        """L'estimation dépasse-t-elle nettement la déclaration : de plus de 25 % de celle-ci (au-delà de l'erreur de la
        patrouille, ±12 %) et d'au moins 0,3 t ? Un plancher de 1 t laissait passer un mensonge flagrant sur une petite prise
        (1,9 t mesurées pour 1 t déclarée)."""
        det = self.detection
        return estimate - said > max(det["margin_t"], det["margin_ratio"] * said)

    def investigate(self, season: int):
        """Le soir de la veillée, les indices de la saison sont réunis. La patrouille a relevé les barques qu'elle a croisées
        (l'ancien le dit à tous) ; un voisin qui pêchait dans la même zone a pu voir une barque rentrer et en estimer la charge ; la barque d'un
        interdit a pu être vue partant à l'aube ; un train de vie peut ne pas coller avec une déclaration ; l'ancien fait les
        comptes du lac. Qui n'a rien à se reprocher dit ce qu'il a vu ; qui a triché se tait (pour ne pas attirer l'attention),
        et l'on ne dénonce pas un ami (confiance d'au moins `LOYAL`). Tout part des vraies sorties : un indice dit vrai, à l'erreur
        d'estimation près. Une fois par saison."""
        if self._investigated_season >= season:
            return
        self._investigated_season = season
        det, rng, now = self.detection, self.lie_rng, self.clock.now()
        trips = self.trips.get(season, [])
        by_agent = {t["agent"]: t for t in trips}
        elder = self.elder.id if self.elder else None
        patrol_id = self.patrol_agent.id if self.patrol_agent else None

        def clue(kind: str, observer: str | None, trip: dict, estimate: float | None = None):
            subject = self.agents[trip["agent"]]
            public = observer is None or observer in (elder, patrol_id) or \
                (not self.cheated(observer, season) and self.trust[observer].get(subject.id, TRUST_START) < LOYAL)
            p = {"kind": kind, "observer": observer, "subject": subject.id, "zone": trip["zone"],
                 "estimate": None if estimate is None else round(max(0.0, estimate), 1), "public": public,
                 "declared": None if trip["secret"] else subject.declared.get(season)}
            ev = self.events.emit("clue", p, actor=observer or subject.id)
            self.clues.append({**p, "season": season, "t": now, "event_id": ev["event_id"]})
            if not public:                         # il l'a vu, et le garde pour lui
                self.remember(self.agents[observer], f"J'ai vu {self.clue_text(p, observer)} ; je ne l'ai dit à personne.",
                              "indice", 0.7, source_event_id=ev["event_id"])

        def noisy(v: float, err: float) -> float:
            return v * (1 + rng.uniform(-err, err))

        for t in trips:
            if t["patrol"] and patrol_id and rng.random() < det["patrol"] * t["patrol"]:
                clue("patrouille", patrol_id, t, noisy(t["landed"], det["patrol_error"]))
            for o in self.fishers:                 # les barques qui pêchaient dans la même zone
                mine = by_agent.get(o.id)
                if o.id != t["agent"] and mine is not None and mine["zone"] == t["zone"] and rng.random() < det["witness"]:
                    clue("temoin", o.id, t, noisy(t["landed"], det["witness_error"]))
            home = self.agents[t["agent"]].profile.hamlet
            neighbours = [o for o in self.fishers if o.id != t["agent"] and o.profile.hamlet == home]
            if t["secret"]:
                for o in neighbours:
                    if rng.random() < det["seen_leaving"]:
                        clue("depart", o.id, t)
            else:
                # déclarer moins qu'il ne faut pour vivre, et pourtant vivre comme avant (payer sa dette, son entretien)
                a = self.agents[t["agent"]]
                need = (self.upkeep(a) + a.profile.debt_payment) / self.econ["price_per_tonne"]
                if a.declared.get(season, t["landed"]) < need <= a.catches.get(season, 0.0):
                    for o in neighbours:
                        if rng.random() < det["lifestyle"]:
                            clue("train_de_vie", o.id, t)
        self.patrol_report(season)
        # les comptes du lac : ce que la pêche lui a fait perdre (mesuré à lake_error × capacité près), ce que les déclarations
        # en expliquent
        err = det["lake_error"] * self.capacity
        drop = max(0.0, sum(t["landed"] for t in trips) + rng.uniform(-err, err))
        declared = sum(self.agents[t["agent"]].declared.get(season, 0.0) for t in trips if not t["secret"])
        audit = {"drop": round(drop, 1), "declared": round(declared, 1), "gap": round(drop - declared, 1),
                 "significant": drop - declared > 2 * err}
        self.audits[season] = {**audit, "t": now}
        self.events.emit("lake_audit", audit, actor=elder)

    def weigh_evidence(self, season: int):
        """À l'ouverture de la veillée, l'ancien dit ce que les indices dits devant tous établissent, pêcheur par pêcheur. Un
        mensonge est établi quand ils pèsent `proof` (patrouille 3, témoin 1, départ vu 1, train de vie 0,5, comptes 0,5 s'ils ne
        tombent pas juste) et que la charge estimée dépasse nettement la déclaration ; pour un interdit, toute sortie prouvée est
        une faute. Il relate, il ne sanctionne pas : ce que chacun en pense, et ce que la vallée décide, appartient aux pêcheurs.
        Seuls les indices comptent, jamais la vérité : l'ancien peut se tromper (`wrongful`)."""
        if self._weighed_season >= season:
            return
        self._weighed_season = season
        det = self.detection
        books = EVIDENCE["comptes"] if self.audits.get(season, {}).get("significant") else 0.0
        for trip in self.trips.get(season, []):
            a = self.agents[trip["agent"]]
            clues = [c for c in self.clues if c["season"] == season and c["subject"] == a.id and c["public"]]
            if not clues:
                continue
            nums = [(EVIDENCE[c["kind"]], c["estimate"]) for c in clues if c["estimate"] is not None]
            est = sum(w * e for w, e in nums) / sum(w for w, _ in nums) if nums else None
            weight = sum(EVIDENCE[c["kind"]] for c in clues)
            said = 0.0 if trip["secret"] else a.declared.get(season, trip["landed"])
            if trip["secret"]:
                caught = weight >= det["proof"]
            else:
                caught = est is not None and self.beyond_declared(est, said) and weight + books >= det["proof"]
            if caught:
                self.establish(a, season, trip, said, est, clues)

    def establish(self, a: Agent, season: int, trip: dict, said: float, est: float | None, clues: list[dict]):
        """L'ancien tient pour établi que `a` a menti (ou est sorti en cachette) : il le dit à tous, et chacun s'en souvient. La
        vallée retient l'estimation des indices, pas la vérité."""
        kinds = {c["kind"] for c in clues}
        how = "patrouille" if "patrouille" in kinds else ("temoins" if kinds & {"temoin", "depart"} else "indices")
        witnesses = sorted({c["observer"] for c in clues if c["observer"] and c["kind"] != "patrouille"})
        value = None if est is None else round(est, 1)
        self.established[(a.id, season)] = {"value": value, "t": self.clock.now(), "how": how, "secret": trip["secret"]}
        rep = self.reports.get((a.id, season))
        ev = self.events.emit("lie_discovered", {
            "agent": a.id, "lie_season": season, "declared": said, "landed": trip["landed"], "how": how,
            "secret": trip["secret"], "wrongful": not self.cheated(a.id, season), "estimated": value,
            "witnesses": witnesses, "report_event_id": rep["event_id"] if rep else None}, actor=a.id)
        about = f"environ {value:g} t" if value is not None else "une quantité inconnue"
        for o in self.agents.values():
            if o.id == a.id:
                fault = "suis sorti pêcher en cachette" if trip["secret"] else f"avais menti en déclarant {said:g} t"
                text = (f"La vallée a établi que je {fault} à la saison {season} ({HOW[how]}) : "
                        f"elle croit que j'ai pris {about}.")
            elif trip["secret"]:
                text = (f"{a.profile.name}, interdit de pêche, est sorti pêcher en cachette à la saison {season} "
                        f"({HOW[how]}) : {about}.")
            else:
                text = (f"{a.profile.name} a menti à l'ancien à la saison {season} : il a déclaré {said:g} t, les indices "
                        f"disent {about} ({HOW[how]}).")
            self.remember(o, text, "mensonge", 0.9, source_event_id=ev["event_id"])

    def upkeep(self, agent: Agent, season: int | None = None) -> float:
        """Ce que coûte une saison à ce pêcheur, hors dette : la vie, l'entretien de son bateau, et la patrouille du lac si le
        conseil en a voté une (chacun y contribue)."""
        patrol = self.patrol_cfg["cost"] if self.patrol_active(season or self.season or 1) else 0
        return self.econ["upkeep_per_season"] + self.boats[agent.profile.boat]["upkeep"] + patrol

    def patrol_active(self, season: int) -> bool:
        """La patrouille du lac sort-elle cette saison ? (`since` : sa première saison ; `until` : sa dernière, si le conseil l'a retirée.)"""
        p = self.patrol
        return self.patrol_on and p is not None and p["since"] <= season <= p.get("until", math.inf)

    def patrol_exists(self) -> bool:
        """Y a-t-il une patrouille, installée ou votée, que le conseil n'a pas retirée ?"""
        return self.patrol_on and self.patrol is not None and "until" not in self.patrol

    def set_patrol(self, s: Sanction, season: int, yes: list[str], voters: int):
        """Le conseil installe la patrouille du lac (dès la saison suivante), ou la retire (elle sort encore cette saison)."""
        installed = s.action == "patrouille"
        if installed:
            self.patrol = {"since": season + 1, "proposal_id": s.id}
        elif self.patrol is not None:
            self.patrol["until"] = season
        self.events.emit("patrol", {"state": "installed" if installed else "lifted", "effective_season": season + 1,
                                    "proposal_id": s.id, "for": yes, "voters": voters, "cost": self.patrol_cfg["cost"]})

    def patrolled(self, season: int, zone: str, days: list[float], aid: str = "") -> float:
        """La part de ces jours (depuis le début de la saison) où la patrouille se trouvait dans cette zone, ou sur les talons de ce
        pêcheur (`aid`) : qu'elle suive une barque, elle la croise où qu'elle aille."""
        legs = [leg for leg in self.patrol_legs.get(season, []) if leg["zone"] == zone or (aid and leg.get("follow") == aid)]
        return sum(any(leg["from_day"] <= d < leg["to_day"] for leg in legs) for d in days) / len(days)

    def weather(self, season: int) -> list[str]:
        """Le temps de chaque jour de la fenêtre de pêche de la saison, le même pour tout le lac (voir `Climate.calendar`)."""
        return self.climate.calendar(season, int(self.T["fishing_close_day"]))

    def outings(self, agent: Agent, season: int, stock: float | None = None) -> list[dict]:
        """Les sorties de ce pêcheur cette saison, étalées sur la fenêtre de pêche (la première part un jour propre à chacun) : pour
        chacune, le jour, le temps qu'il faisait (le même pour tout le lac, voir `weather`), la chance du pêcheur et ce que la
        sortie rapporte par rapport à ce qu'il visait. Sa chance mêle sa forme de la saison (elle se prolonge d'une saison à l'autre,
        `economy.luck_streak`) et sa forme du jour (de sortie en sortie) ; s'y ajoutent la saison de l'année, les événements, la
        tenue de son bateau par gros temps, son expérience et le lac bas (le poisson est plus dur à prendre sous `LOW_LAKE`).
        Tout est tiré pour ce pêcheur et cette saison : les mêmes quel que soit l'ordre dans lequel les barques rentrent.
        `economy.luck: 0` : ni chance ni malchance, ni expérience ni lac bas, seulement le temps."""
        if season in agent.outings:
            return agent.outings[season]
        seed, boat = self.cfg["run"]["seed"], agent.profile.boat
        amp, keep = float(self.econ.get("luck", 0.0)), float(self.econ.get("luck_streak", 0.5))
        n, (lo, hi) = max(1, int(self.econ.get("outings", 6))), (self.T["fishing_open_day"], self.T["fishing_close_day"])
        first = (zlib.crc32(f"{seed}|day|{agent.id}|{season}".encode()) % 10000) / 10000
        base, weather = self.climate.yield_for(boat), self.weather(season)
        if amp > 0:
            ratio = (self.lake.stock if stock is None else stock) / self.capacity
            base *= (1 + SKILL_STEP * (min(max(agent.profile.experience, 0), 40) - 15)) * \
                (1.0 if ratio >= LOW_LAKE else 0.55 + 1.5 * ratio)
        rng, fresh = random.Random(f"{seed}|luck|{agent.id}|{season}"), math.sqrt(max(0.0, 1 - keep * keep))
        agent.form = max(-2.5, min(2.5, keep * agent.form + fresh * rng.gauss(0, 1)))
        mood = rng.gauss(0, 1)
        outs = []
        for k in range(n):
            day = round(lo + (k + first) / n * (hi - lo - 0.01), 2)
            label = weather[min(int(day), len(weather) - 1)]
            mood = max(-2.5, min(2.5, keep * mood + fresh * rng.gauss(0, 1)))
            luck = max(0.1, 1 + amp * (0.6 * agent.form + 0.8 * mood))
            outs.append({"day": day, "weather": label, "luck": round(luck, 3),
                         "yield": round(luck * base * self.climate.day_factor(label, season, boat), 3)})
        agent.outings[season] = outs
        return outs

    def secret_zone(self, agent: Agent) -> str:
        """Où un interdit va pêcher en cachette : loin de sa rive (ses voisins le connaissent), plutôt au large."""
        others = [z for z in self.zones if z != agent.profile.hamlet] or ["large"]
        weights = [2.0 if z == "large" else 1.0 for z in others]
        return self.lie_rng.choices(others, weights)[0]

    def clue_text(self, c: dict, viewer: str | None = None) -> str:
        """Un indice en mots, du point de vue de `viewer` (« ta barque » s'il en est le sujet)."""
        mine = c["subject"] == viewer
        boat = "ta barque" if mine else f"la barque de {self.first_name(c['subject'])}"
        said = "" if c["declared"] is None else \
            (f" (tu as déclaré {c['declared']:g} t)" if mine else f" ({self.first_name(c['subject'])} a déclaré {c['declared']:g} t)")
        if c["kind"] == "patrouille":
            return f"la patrouille du lac a mesuré environ {c['estimate']:g} t dans {boat}{said}"
        if c["kind"] == "temoin":
            return f"{boat} rentrer avec environ {c['estimate']:g} t{said}"
        if c["kind"] == "depart":
            return f"{boat}, interdite de pêche, partir à l'aube"
        return f"que {'tu vis' if mine else self.first_name(c['subject']) + ' vit'} bien pour {c['declared']:g} t déclarées"

    def clue_lines(self, agent: Agent, horizon: float, season: int) -> list[str]:
        """Les indices que l'agent connaît (dits devant tous, ou vus par lui et gardés), et les comptes du lac, de cette saison et
        de la précédente : la matière de ses soupçons."""
        lines = []
        for c in self.clues:
            if c["t"] > horizon or c["season"] < season - 1 or not (c["public"] or c["observer"] == agent.id):
                continue
            if c["kind"] == "patrouille":
                text = self.clue_text(c, agent.id)
            elif c["observer"] == agent.id:
                text = f"tu as vu {self.clue_text(c, agent.id)}" + ("" if c["public"] else " ; tu ne l'as dit à personne")
            else:
                verb = "trouve" if c["kind"] == "train_de_vie" else "a vu"
                text = f"{self.first_name(c['observer'])} {verb} {self.clue_text(c, agent.id)}"
            lines.append(f"saison {c['season']} : {text}.")
        for s in (season - 1, season):
            au = self.audits.get(s)
            if au and au["t"] <= horizon:
                lines.append(f"saison {s} : comptes de l'ancien, la pêche a fait perdre environ {au['drop']:g} t au lac, les "
                             f"déclarations en expliquent {au['declared']:g} t.")
        return lines[-7:]

    def trust_facts(self, agent: Agent, season: int, horizon: float, since: float | None) -> dict[str, dict]:
        """Ce que l'agent vient d'apprendre de chaque pêcheur, la matière de son jugement (`policies.trust_rule` pour un agent à
        règles ; une IA lit les mêmes faits dans son contexte). `since` None (sa première parole de la veillée) : les faits de
        la saison (déclaration et règle, mensonge établi, sortie en cachette prouvée, promesse, témoignage, interdit resté à
        l'écart) ; sinon, seulement les accusations portées contre lui depuis sa dernière parole."""
        out: dict[str, dict] = {}
        for t, accused, accuser in self.accusations.get(season, []):
            if accused == agent.id and accuser != agent.id and t <= horizon and (since is None or t > since):
                out.setdefault(accuser, {})["accused_me"] = True
        if since is not None:
            return out
        tol, ptol = self.scn["quota_tolerance"], self.scn["promise_tolerance"]
        for a in self.fishers:
            if a.id == agent.id or not self.can_see(agent, a):
                continue
            f = out.setdefault(a.id, {})
            known, norm = self.known_catch(a.id, season, horizon), self.applicable_norm(a, season, horizon)
            if known is not None and norm is not None:
                f["over"] = 0.0 if known <= norm.quota + tol else (known - norm.quota) / max(norm.quota, 0.1)
            found = self.established.get((a.id, season))
            if found is not None and found["t"] <= horizon:
                f["secret" if found["secret"] else "lie"] = True
            promise = self.promises.get((a.id, season))
            if promise is not None and known is not None:
                f["promise"] = known <= promise[0] + ptol
            # a témoigné : contre quelqu'un (un relevé qui confirme sa déclaration ne dénonce personne)
            f["testified"] = any(c["observer"] == a.id and c["public"] and c["season"] == season and c["t"] <= horizon
                                 and self.discordant(c) for c in self.clues)
            since_ban = self.banned.get(a.id)
            f["stayed_away"] = since_ban is not None and since_ban <= season and found is None and \
                not any(c["subject"] == a.id and c["public"] and c["season"] == season for c in self.clues)
            if f.get("over") is None and f.get("promise") is None and not any(
                    f.get(k) for k in ("lie", "secret", "accused_me", "testified", "stayed_away")):
                del out[a.id]
                continue
            # ce qui, hors de la nouvelle, pèse sur le jugement : le voisinage, ce qu'on en dit dans la vallée, ce qu'on en pensait,
            # et la gravité d'un mensonge établi (l'écart entre l'estimation des indices et la déclaration)
            f["kin"] = a.profile.hamlet == agent.profile.hamlet
            f["rep"] = self.reputation(a.id)
            f["old"] = self.trust[agent.id].get(a.id, TRUST_START)
            said = self.reports.get((a.id, season))
            if found is not None and found["t"] <= horizon and not found["secret"] and found["value"] is not None and said:
                f["gap"] = max(0.0, (found["value"] - said["payload"]["declared"]) / max(said["payload"]["declared"], 0.5))
        return out

    def trust_context(self, agent: Agent, season: int) -> dict:
        """Ce qui, en dehors de ce qu'il apprend de chacun, pèse sur le jugement d'un agent à règles (voir `policies.trust_rule`) : la
        chance de la saison (saison de l'année et événements), ses dettes, s'il a lui-même triché, sa sévérité et son hasard."""
        return {"yield": float(self.conditions.get("yield", 1.0)), "luck": float(self.econ.get("luck", 0.0)),
                "debt": agent.profile.debt_payment,
                "cheated": self.cheated(agent.id, season), "harsh": agent.temper, "rng": agent.rng}

    def trust_obs(self, agent: Agent) -> dict:
        """Ce que l'agent sait de la confiance, pour son contexte : la sienne envers chacun, ses voisins, et ce que la vallée pense des
        autres (la confiance moyenne de tous, pour ceux qui s'écartent de la moyenne)."""
        others = [a for a in self.fishers if a.id != agent.id]
        return {"trust": sorted(((self.first_name(s), v) for s, v in self.trust[agent.id].items()), key=lambda kv: kv[1]),
                "neighbors": [self.first_name(a.id) for a in others if a.profile.hamlet == agent.profile.hamlet],
                "valley": [(self.first_name(a.id), self.reputation(a.id)) for a in others
                           if not 0.4 <= self.reputation(a.id) < 0.6]}

    def sky_phrase(self, days: list[str]) -> str:
        """Le temps des jours de pêche, en mots : « 3 jours calmes, 8 jours ordinaires, 2 jours de tempête »."""
        return ", ".join(f"{days.count(k)} jour{'s' if days.count(k) > 1 else ''} {w + 's' if w[0] != 'd' and days.count(k) > 1 else w}"
                         for k, w in (("calme", "calme"), ("ordinaire", "ordinaire"), ("agité", "agité"), ("tempête", "de tempête"))
                         if days.count(k))

    def sky_line(self, season: int) -> str:
        """Ce que tout le monde sait du temps de la saison, une fois la pêche faite (rien sans climat)."""
        line = f"Le temps de la pêche cette saison : {self.sky_phrase(self.weather(season))}." if self.climate.enabled else ""
        luck = float(self.econ.get("luck", 0.0))
        if luck > 0:        # chacun le sait : la prise d'un pêcheur n'est pas celle qu'il visait
            line += (f" La chance fait varier la prise de chacun d'environ ±{100 * luck:.0f} % : dépasser un peu la règle n'est "
                     "pas forcément tricher.")
        return line.strip()

    def promise_lines(self, agent: Agent, season: int, horizon: float) -> list[str]:
        """Les promesses faites à la dernière veillée pour cette saison, et ce que la vallée sait de leur sort."""
        lines = []
        for (aid, s), (promised, _) in self.promises.items():
            if s != season or aid == agent.id or not self.can_see(agent, self.agents[aid]):
                continue
            known = self.known_catch(aid, season, horizon)
            if known is None:
                continue
            kept = known <= promised + self.scn["promise_tolerance"]
            lines.append(f"{self.first_name(aid)} avait promis {promised:g} t au plus : {known:g} t "
                         + ("(promesse tenue)" if kept else "(promesse trahie)"))
        return lines

    def known_catches(self, agent: Agent, horizon: float, season: int) -> tuple[list[str], list[str], dict]:
        """Les déclarations des autres que l'agent connaît (une ligne par saison, les trois dernières), et la vérité de ceux dont
        le mensonge a éclaté ; `last` : ce qu'il sait de la saison passée, par pêcheur."""
        by_season: dict[int, list[str]] = {}
        ids, last = [], {}
        for (aid, s), rep in self.reports.items():
            if rep["sim_time"] > horizon or s < season - 2 or aid == agent.id or not self.can_see(agent, self.agents[aid]):
                continue
            p, val = rep["payload"], self.known_catch(aid, s, horizon)
            txt = f"{self.first_name(aid)} {val:g} t"
            if val != p["declared"]:
                txt += f" (en avait déclaré {p['declared']:g} : mensonge établi)"
            by_season.setdefault(s, []).append(txt)
            ids.append(rep["event_id"])
            if s == season - 1:
                last[aid] = val
        for (aid, s), found in self.established.items():      # les interdits pris à pêcher en cachette
            if found["secret"] and found["t"] <= horizon and s >= season - 2 and aid != agent.id:
                about = f"environ {found['value']:g} t" if found["value"] is not None else "on ne sait combien"
                by_season.setdefault(s, []).append(f"{self.first_name(aid)}, interdit, pris à pêcher en cachette ({about})")
        lines = [f"saison {s} : " + ", ".join(v) for s, v in sorted(by_season.items())]
        return lines, ids, last

    def carnet(self, agent: Agent, horizon: float) -> list[str]:
        """Ce que l'agent est seul à savoir de ses trois dernières prises : la vraie, ce qu'il en a déclaré, et si son mensonge a
        éclaté. Sans cela, un pêcheur qui a menti l'oublie et se défend mal (ou se dénonce lui-même)."""
        honest, out = [], []
        if agent.is_fisher:      # ce que la vallée pense de lui : de quoi peser un dépassement, un mensonge
            rep = self.reputation(agent.id)
            out.append(f"ta réputation dans la vallée : {prompts.trust_word(rep)} ({100 * rep:.0f} %) ; ceux qui ne te font "
                       "plus confiance peuvent proposer de t'interdire de pêche.")
        if agent.id in self.banned:
            out.append(f"la vallée t'a interdit de pêche (depuis la saison {self.banned[agent.id]}) tant que tu n'as pas "
                       "regagné sa confiance : ta seule prise possible est en cachette.")
        for s in sorted(agent.catches)[-3:]:
            landed, said = agent.catches[s], agent.declared.get(s, agent.catches[s])
            found = self.established.get((agent.id, s))
            known = found is not None and found["t"] <= horizon
            secret = any(t["agent"] == agent.id and t["secret"] for t in self.trips.get(s, []))
            if secret:
                out.append(f"saison {s} : tu as pêché {landed:g} t en cachette ; "
                           + ("on t'a pris, tout le monde le sait." if known else "personne ne t'a pris, pour l'instant."))
            elif landed - said > 0.05:
                out.append(f"saison {s} : tu as pêché {landed:g} t et déclaré {said:g} t à l'ancien ; "
                           + ("la vallée a établi ce mensonge." if known else "personne ne le sait, pour l'instant."))
            elif known:
                out.append(f"saison {s} : tu as pêché {landed:g} t, déclarées telles quelles, mais la vallée croit que tu as "
                           f"menti (environ {found['value']:g} t) : c'est faux.")
            else:
                honest.append(f"saison {s} : {landed:g} t")
        if honest:
            out.insert(0, "tes prises, déclarées telles quelles à l'ancien : " + ", ".join(honest) + ".")
        return out

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

    async def observe(self, agent: Agent, horizon: float, purpose: str, assembly: Assembly | None = None, rnd: int = 1):
        """Construit ce que l'agent sait à l'instant `horizon` : rien de postérieur (C6). Asynchrone : la mémoire et le corpus
        peuvent être dans PostgreSQL (`rag.backend: pgvector`)."""
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
        rumors = self.active_rumors(horizon)
        carnet = self.carnet(agent, horizon)
        exposed = any(aid == agent.id and f["t"] <= horizon and s >= season - 2 for (aid, s), f in self.established.items())
        banned = agent.id in self.banned
        clues = self.clue_lines(agent, horizon, season)
        wealth, stock_true = agent.wealth, round(self.lake.stock, 3)
        # son bateau : ce qu'il peut porter, ce que la saison lui coûte (vie, entretien, patrouille)
        hold = self.hold.get(agent.id, self.max_catch)
        min_catch = 0.0 if banned else min(self.min_catch, hold)
        upkeep = self.upkeep(agent, season) if agent.is_fisher else self.econ["upkeep_per_season"]
        patrol = self.patrol_active(season)
        lies_recent = sum(1 for (_, s), f in self.established.items() if s >= season - 1 and f["t"] <= horizon)
        if self.vectors is None:
            # en mémoire : aucune attente, le monde ne bouge pas pendant l'observation
            mems = agent.memory.retrieve(query, horizon, self.cfg["memory"]["top_k"], exclude=skip)
            docs = self.retriever.search(query, p.hamlet, horizon, self.cfg["rag"]["top_k"])
        else:
            # dans la base : pendant l'attente, d'autres agents peuvent agir ; ce que l'agent sait de l'instant `horizon`
            # (ses prises, son avoir, le stock) a été relevé avant
            mems, docs = await asyncio.gather(
                agent.memory.aretrieve(query, horizon, self.cfg["memory"]["top_k"], exclude=skip),
                self.retriever.asearch(query, p.hamlet, horizon, self.cfg["rag"]["top_k"]))
        for m, s in mems:
            retrieved.append({"id": m.event_id or m.id, "source": "memory", "score": s, "sim_time": m.t,
                              "text": m.text[:160]})
        for d, s in docs:
            retrieved.append({"id": f"corpus:{d.id}", "source": "corpus", "score": round(s, 3), "sim_time": d.sim_time,
                              "text": d.text[:160]})
        for r in rumors:
            retrieved.insert(0, {"id": r["event_id"], "source": "rumor", "score": 1.0, "sim_time": r["t"],
                                 "text": r["text"][:160]})
        used += [r["id"] for r in retrieved if r["source"] != "corpus"]
        obs = {
            "label": self.clock.label(horizon), "season": season, "stock_estimate": est, "role": p.role,
            "capacity": self.capacity, "collapse_ratio": self.lake.collapse_ratio, "stock_history": history,
            "n_fishers": len(self.fishers), "_entry": entry, "villages": self.hamlets,
            "wealth": wealth, "upkeep": upkeep, "debt_payment": p.debt_payment,
            "price": self.econ["price_per_tonne"], "boat_capacity": hold, "boat": p.boat,
            "growth": self.lake.r * self.conditions.get("growth", 1.0),
            "conditions": self.climate.line(season), "events": [e["label"] for e in self.conditions.get("events", [])],
            "patrol": patrol, "patrol_enabled": self.patrol_on,
            # un interdit ne sort qu'en cachette, ou reste à quai (0 t)
            "min_catch": min_catch, "carnet": carnet, "norms": norm_lines,
            "known_catches": catches_txt, "clues": clues, "banned": banned,
            "banned_others": [self.first_name(b) for b in self.banned if b != agent.id],
            **self.trust_obs(agent),
            "last_season_catches": sorted(last_catches.values()),
            # la règle votée qui s'applique à ce pêcheur, et s'il l'a soutenue (rappelée juste avant la question de prise)
            "rule": ({"quota": norm.quota, "supported": agent.id in norm.supporters, "visible": self.visible}
                     if norm else None),
            # chaque souvenir porte sa date : une parole de la veillée d'il y a deux saisons (« le lac a l'air bien rempli »)
            # ne doit pas passer pour l'état du lac d'aujourd'hui
            "pinned": [m.text for m in pinned],
            "memories": [f"({self.clock.label(m.t)}) {m.text}" for m, _ in mems],
            "documents": [f"[{d.title}] {d.text}" for d, _ in docs],
            "rumors": [r["text"] for r in rumors],
        }
        state = {
            "stock_estimate": est, "stock_true": stock_true, "capacity": self.capacity, "n_fishers": len(self.fishers),
            "quota": norm.quota if norm else None, "boat_capacity": hold,      # limite d'une sortie
            "min_catch": min_catch, "banned": banned,
            "upkeep": upkeep, "debt_payment": p.debt_payment,
            "price": self.econ["price_per_tonne"], "wealth": wealth,
            "growth_rate": self.lake.r * self.conditions.get("growth", 1.0), "round": rnd,
            "has_patrol": patrol, "patrol_enabled": self.patrol_on, "lies_recent": lies_recent,
            "patrol_cost": self.patrol_cfg["cost"],
            "rumors": obs["rumors"], "rumor_targets": self.named_fishers(obs["rumors"]) if rumors else [],
            "self_id": agent.id, "names": {a.id: (a.profile.first_name or a.profile.name.split()[0]) for a in self.fishers},
            "exposed": exposed, "trust": dict(self.trust[agent.id]),     # un mensonge à lui découvert depuis peu ; sa confiance
        }
        if assembly:
            # synchrone : on entend ceux qui ont parlé avant soi (dialogues dépendants) ; asynchrone : chacun s'exprime de son
            # côté, sans rien entendre ni voir des propositions des autres avant le vote (dialogues indépendants)
            visible_u = [] if assembly.independent else [u for u in assembly.utterances if u["sim_time"] <= horizon]
            row = self.trust[agent.id]

            def speaker(aid: str) -> str:      # chaque parole se pèse à la confiance qu'on fait à celui qui la dit
                if aid == agent.id:
                    return "toi"
                trusted = f", ta confiance : {prompts.trust_word(row[aid])}" if aid in row else ""
                return f"{self.name(aid)} ({aid}{trusted})"

            obs["transcript"] = [
                speaker(u["payload"]["speaker"])
                + ("" if u["payload"]["to"] == "tous" else f", à {self.name(u['payload']['to'])}")
                + f" : « {u['payload']['text']} »" for u in visible_u[-12:]]
            used += [u["event_id"] for u in visible_u[-12:]]
            obs["addressed"] = [f"{self.name(u['payload']['speaker'])} : « {u['payload']['text']} »"
                                for u in visible_u[-12:] if u["payload"]["to"] == agent.id and u["payload"]["speaker"] != agent.id]
            props = [] if assembly.independent else [pr for pr in assembly.proposals.values() if pr.t <= horizon]
            obs["proposals"] = []
            best = None
            for pr in props:
                sup = [a for a, (pid, t, _) in assembly.support.items() if pid == pr.id and t <= horizon]
                obs["proposals"].append(f"{pr.id} : {pr.quota:g} t par pêcheur, proposée par {self.name(pr.author)} ; "
                                        f"soutiens : {', '.join(sup) or 'aucun'}")
                used.append(pr.event_id)
                if best is None or len(sup) > best[2]:
                    best = (pr.id, pr.quota, len(sup), pr.author)
            state["leading_proposal"] = (best[0], best[1]) if best else None
            state["leading_trust"] = row.get(best[3], 1.0) if best else 1.0
            obs["sanctions"] = [] if assembly.independent else [
                f"{s.id} : {self.motion_text(s)}, proposé par {self.name(s.author)} ; pour : "
                f"{', '.join(a for a, v in s.votes.items() if v) or 'personne'}"
                for s in assembly.sanctions.values() if s.t <= horizon]
            obs["independent"] = assembly.independent
            obs["delegate"] = self.delegate_line(agent) if assembly.delegates and agent.is_fisher else ""
            obs["patrol_line"] = self.patrol_line(season) if agent.is_fisher else ""
            obs["promises"] = self.promise_lines(agent, season, horizon)
            mine = [u for u in visible_u if u["payload"]["speaker"] == agent.id]
            state["facts"] = self.trust_facts(agent, season, horizon,
                                              mine[-1]["payload"]["info_horizon"] if mine else None)
            state["trust_ctx"] = self.trust_context(agent, season)
            obs["conditions"] = " ".join(x for x in (obs["conditions"], self.sky_line(season)) if x)     # la pêche est faite : on l'a vue
            state["present"] = [a for a in assembly.participants if self.agents[a].is_fisher and a != agent.id]
            state["banned_ids"] = list(self.banned)
            obs["participants"] = [{"id": a, "name": self.name(a), "label": self.agents[a].profile.archetype_label}
                                   for a in assembly.participants]
            obs["scope_label"] = assembly.label
            obs["round"] = rnd
            # celui qu'un agent à règles accuserait : d'abord celui que les indices de la saison désignent, sinon le plus gros
            # pêcheur connu de la saison passée
            state["overfisher"] = self._clue_suspect(agent, season, horizon) or \
                self._overfisher(agent, last_catches, season - 1)
        return obs, state, retrieved, list(dict.fromkeys(used))

    def _clue_suspect(self, agent: Agent, season: int, horizon: float) -> str | None:
        """Le pêcheur que les indices connus de l'agent désignent le plus nettement cette saison (charge estimée bien au-delà
        de sa déclaration, ou interdit vu dehors)."""
        best, worst = None, 0.0
        for c in self.clues:
            if c["season"] != season or c["t"] > horizon or c["subject"] == agent.id or \
                    not (c["public"] or c["observer"] == agent.id):
                continue
            if c["declared"] is not None and not self.beyond_declared(c["estimate"] or 0.0, c["declared"]):
                continue
            excess = 5.0 if c["declared"] is None else c["estimate"] - c["declared"]
            if excess > worst:
                best, worst = c["subject"], excess
        return best

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
                    ration: float = 1.0, stock_at_action: float | None = None, declared: float | None = None) -> dict:
        """Applique une prise, puis la déclaration du pêcheur à l'ancien. `stock_at_action` : stock au moment où l'action prend
        effet (en synchrone, le même pour toutes les barques parties ensemble ; en asynchrone, le stock courant). `declared` :
        ce qu'il comptait déclarer (None : la vérité). Un interdit de pêche reste à quai (0 t) ou sort en cachette : il ne
        déclare rien, et va plutôt pêcher loin de sa rive. Renvoie l'événement `catch` (None : resté à quai)."""
        season = self.clock.season_of()
        secret = agent.id in self.banned
        if secret and requested <= 0:
            self.remember(agent, "Interdit de pêche, je suis resté à quai cette saison.", "peche", 0.5)
            return None
        zone = self.secret_zone(agent) if secret else agent.profile.hamlet
        before = self.lake.stock
        obs = decision["payload"]["observed"]
        stock_observed = obs["stock_estimate"]
        # la pêche n'est pas toujours bonne : la prise visée est étalée sur les sorties, et chacune rapporte selon sa journée (le
        # temps, la chance, la saison de l'année, les événements) sans jamais dépasser sa part de la cale ; puis, en synchrone, le
        # rationnement si la flotte demande plus que le lac
        outs = self.outings(agent, season, stock_at_action)
        wanted = [min(requested * o["yield"], self.hold[agent.id]) / len(outs) * ration for o in outs]
        landed = round(self.lake.take(sum(wanted)), 3)
        tonnes = [round(landed * w / sum(wanted), 3) if landed else 0.0 for w in wanted]
        tonnes[-1] = round(landed - sum(tonnes[:-1]), 3)
        factor, luck = (sum(o[k] for o in outs) / len(outs) for k in ("yield", "luck"))
        ev = self.events.emit("catch", {
            "agent": agent.id, "hamlet": agent.profile.hamlet, "requested": requested, "landed": landed,
            "stock_observed": stock_observed, "stock_before": round(before, 3), "stock_after": round(self.lake.stock, 3),
            "decision_event_id": decision["event_id"], "info_horizon": round(horizon, 6), "rationed": ration < 1.0,
            "stock_at_horizon": obs["stock_true"],
            "stock_at_action": round(before if stock_at_action is None else stock_at_action, 3),
            "zone": zone, "secret": secret, "yield": round(factor, 3), "luck": round(luck, 3),
            "outings": [{**o, "tonnes": t} for o, t in zip(outs, tonnes)],
        }, actor=agent.id)
        # la saison de pêche : où, combien, et la part des sorties où la patrouille du lac était dans cette zone (lu le soir de la veillée)
        self.trips.setdefault(season, []).append({"agent": agent.id, "zone": zone, "landed": landed, "secret": secret,
                                                  "patrol": self.patrolled(season, zone, [o["day"] for o in outs], agent.id),
                                                  "event_id": ev["event_id"]})
        agent.catches[season] = agent.catches.get(season, 0.0) + landed
        self.lake_update("catch", -landed)
        income = landed * self.econ["price_per_tonne"]
        agent.wealth += income
        self.events.emit("sale", {"agent": agent.id, "hamlet": agent.profile.hamlet, "tonnes": landed,
                                  "price": self.econ["price_per_tonne"], "income": round(income, 2),
                                  "wealth": round(agent.wealth, 2)}, actor=agent.id)
        if secret:
            self.remember(agent, f"Interdit de pêche, je suis sorti en cachette ({'au large' if zone == 'large' else 'du côté de ' + zone}) "
                                 f"et j'ai pris {landed:g} t. Personne ne doit le savoir.", "peche", 0.8,
                          source_event_id=ev["event_id"])
            return ev
        # en rentrant, il déclare sa prise à l'ancien : la part qu'il comptait avouer (une prise rationnée, dans la même proportion)
        said = landed if declared is None or requested <= 0 else round(landed * min(1.0, max(0.0, declared) / requested), 2)
        rep = self.events.emit("report", {"agent": agent.id, "hamlet": agent.profile.hamlet, "declared": said,
                                          "landed": landed, "catch_event_id": ev["event_id"]}, actor=agent.id)
        self.reports[(agent.id, season)] = rep
        agent.declared[season] = said
        if landed - said > 0.05:
            self.lies[rep["event_id"]] = {"agent": agent.id, "season": season, "declared": said, "landed": landed,
                                          "found_t": None, "report_event_id": rep["event_id"]}
        note = f"J'ai pêché {landed:g} t cette saison ; le lac m'a semblé contenir environ {stock_observed:.0f} t. {outings_text(outs)}"
        if abs(factor - 1.0) >= 0.15 and requested > 0:
            note += f" J'en visais {requested:g} : {day_word(factor)} pêche."
        elif landed + 1e-6 < requested * ration or ration < 1:
            note += f" J'en voulais {requested:g}, je n'ai pas pu tout prendre."
        if landed - said > 0.05:
            note += f" J'ai déclaré {said:g} t à l'ancien."
        self.remember(agent, note, "peche", 0.6, source_event_id=ev["event_id"])
        return ev

    def handle_command(self, cmd: dict, source: str = "ui"):
        errs = validate_command(cmd)
        if errs:
            self.bus.publish("deadletter", {"command": cmd, "errors": errs})
            return
        ctype = cmd["type"]
        params = {k: v for k, v in cmd.items() if k != "type"}
        if ctype in ("start_game", "new_game", "generate_world"):
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
            **({"detail": self.waiting_note} if self.waiting_note else {}),
            **extra,
        }

    def publish_status(self, state: str | None = None, **extra):
        self.bus.publish("status", self.status_payload(state, **extra), key="engine")

    def scheduled_injections(self, season: int):
        for inj in self.scn.get("scheduled_injections") or []:
            if int(inj.get("season", -1)) == season:
                self.handle_command({k: v for k, v in inj.items() if k != "season"}, source="scenario")

    # ------------------------------------------------------------ veillée
    async def elect(self, season: int):
        """Au conseil de la vallée, chaque village est représenté par un élu, choisi à chaque saison par ses pêcheurs. Chacun vote
        pour le pêcheur de son village qu'il juge le plus apte à parler pour lui, selon sa confiance, son caractère et ses
        intérêts (une IA par son bulletin, un agent à règles selon sa règle : `policies.elect_rule`). Le moteur ne fait que
        compter les voix ; à égalité, le plus de confiance moyenne, l'élu sortant, le plus d'expérience. Un interdit de pêche
        ne peut pas être élu : un menteur démasqué ne garde pas le siège de son village."""
        if not (self.delegates and self.comm == "valley"):
            self.reps = {}
            return
        for h in self.hamlets:
            villagers = [a for a in self.fishers if a.profile.hamlet == h]
            candidates = [a for a in villagers if a.id not in self.banned]
            if not candidates:
                self.reps.pop(h, None)
                continue
            incumbent = self.reps.get(h)
            if len(candidates) == 1:
                ballots = {v.id: candidates[0].id for v in villagers}
            else:
                picks = await asyncio.gather(*(ballot_election(self, v, candidates, season) for v in villagers))
                ballots = {v.id: pick for v, pick in zip(villagers, picks) if pick is not None}
            votes = Counter(ballots.values())

            def mean_trust(c: Agent) -> float:
                others = [self.trust[v.id].get(c.id, TRUST_START) for v in villagers if v.id != c.id]
                return sum(others) / len(others) if others else TRUST_START

            winner = max(candidates, key=lambda c: (votes[c.id], mean_trust(c), c.id == incumbent, c.profile.experience,
                                                    -self.fishers.index(c)))
            self.reps[h] = winner.id
            ev = self.events.emit("election", {"season": season, "hamlet": h, "representative": winner.id,
                                               "votes": dict(votes), "voters": len(villagers), "incumbent": incumbent,
                                               "ballots": ballots}, actor=winner.id)
            if winner.id != incumbent:
                self.remember(winner, f"Mon village m'a élu pour le représenter au conseil de la vallée "
                                      f"({votes[winner.id]} voix sur {len(villagers)}).", "conseil", 0.7,
                              source_event_id=ev["event_id"])

    async def debrief(self, season: int):
        """Les villageois qui n'étaient pas au conseil de la saison `season` en apprennent par l'ancien les décisions et les faits
        établis, et en jugent chacun pour soi : leur confiance envers chaque pêcheur bouge selon leur caractère et leurs intérêts
        (une IA dans sa réflexion, un agent à règles selon `policies.trust_rule`). C'est ce qui fait ensuite leur vote."""
        asm = self.last_council
        if asm is None or asm.season != season:
            return
        absent = [a for a in self.fishers if a.id not in asm.participants]
        await asyncio.gather(*(debrief_villager(self, a, asm) for a in absent))

    async def plan_patrol(self, season: int):
        """Avant la saison, la patrouille du lac (si le conseil en a voté une) prend la mer. Son capitaine décide seul où aller et
        combien de jours y rester (au plus `patrol.days` jours de mer, `patrol.legs` étapes) : une zone du lac, ou les talons d'un
        pêcheur qu'il soupçonne. Il lit ce qui a été partagé (`patrol_dossier`) ; un capitaine à règles va là où l'on se méfie le
        plus (`patrol_rule`). Les pêcheurs savent qu'elle existe, pas où elle sera."""
        if not self.patrol_active(season):
            return
        agent = self.patrol_agent
        days = max(1, min(int(self.patrol_cfg["days"]), int(self.T["fishing_close_day"] - self.T["fishing_open_day"])))
        legs_n = max(1, min(int(self.patrol_cfg["legs"]), len(self.zones)))
        got = None if self.policy_voter(agent) else await patrol_decision(self, season, legs_n, days, self.patrol_dossier(season))
        by = "patrouille"
        if got is None:
            got, by = self.patrol_rule(season, legs_n, days), "patrouille (règle)"
        plan, why = got
        legs = self.patrol_schedule(plan)
        self.patrol_legs[season] = legs
        self.remember(agent, f"Saison {season} : je fais route vers {', puis '.join(self.leg_text(leg) for leg in legs)}. {why}",
                      "patrouille", 0.6)
        self.events.emit("patrol_route", {"season": season, "legs": legs, "by": by, "why": why}, actor=agent.id)

    def leg_text(self, leg: dict) -> str:
        """Une étape de la patrouille, en mots : « Hennad (8 jours) », « le large (4 jours) », « la suite de Mathis (3 jours) »."""
        where = f"la suite de {self.first_name(leg['follow'])}" if leg.get("follow") else \
            ("le large" if leg["zone"] == "large" else leg["zone"])
        return f"{where} ({leg['days']} jour{'s' if leg['days'] > 1 else ''})"

    def patrol_schedule(self, plan: list[tuple[str, int]]) -> list[dict]:
        """Les étapes du plan, dans l'ordre, réparties sur la fenêtre de pêche (le même écart entre chacune). Une étape à la suite d'un
        pêcheur se tient où il pêche ; sur la carte, du côté de son village (ou au large s'il est interdit de pêche)."""
        lo, hi = self.T["fishing_open_day"], self.T["fishing_close_day"]
        gap = max(0.0, (hi - lo - sum(d for _, d in plan)) / (len(plan) + 1))
        t, legs = lo + gap, []
        for target, d in plan:
            follow = target if target in self.agents else None
            zone = target if follow is None else ("large" if target in self.banned else self.agents[target].profile.hamlet)
            legs.append({"zone": zone, "follow": follow, "days": d, "from_day": round(t, 2), "to_day": round(t + d, 2)})
            t += d + gap
        return legs

    def discordant(self, c: dict) -> bool:
        """Cet indice dit-il autre chose que ce que le pêcheur a déclaré ? Un voisin qui a vu rentrer la charge déclarée ne soupçonne
        personne ; un train de vie qui ne colle pas, ou une barque d'interdit vue partir, si."""
        if c["kind"] == "temoin":
            return c["declared"] is not None and self.beyond_declared(c["estimate"], c["declared"])
        return c["kind"] in ("train_de_vie", "depart")

    def heard_text(self, c: dict) -> str:
        """Un indice dit devant tous, pour le dossier de la patrouille : « on a vu la barque de X rentrer avec environ 4 t »."""
        return f"{'on a remarqué ' if c['kind'] == 'train_de_vie' else 'on a vu '}{self.clue_text(c)} (saison {c['season']})"

    def patrol_dossier(self, season: int) -> list[str]:
        """Ce que la patrouille sait avant de prendre la mer, zone par zone : ce qui s'est dit devant tous (accusations, indices relatés
        par l'ancien, mensonges établis, comptes du lac), ce que la vallée pense de chacun, et ce qu'elle a elle-même relevé. Un
        indice que quelqu'un garde pour lui (on ne dénonce pas un ami) ne lui parvient pas ; la vérité des sorties non plus."""
        def recent(s: int) -> bool:
            return s >= season - 2

        def passage(zone: str) -> str:       # là où il est déjà allé, il le sait : ce qu'il n'a pas vu depuis longtemps, il peut y retourner
            seen = [s for s, legs in self.patrol_legs.items() if s < season and any(leg["zone"] == zone for leg in legs)]
            return f"ton dernier passage : saison {max(seen)}" if seen else "tu n'y es encore jamais allé"

        accused = [(e["payload"]["accuser"], e["payload"]["accused"], e["season"]) for e in self.events.index.values()
                   if e["type"] == "accusation" and recent(e["season"])]
        heard = [c for c in self.clues if c["public"] and recent(c["season"]) and c["kind"] != "patrouille"]
        out = []
        for h in self.hamlets:
            here = [a for a in self.fishers if a.profile.hamlet == h and a.id not in self.banned]
            ids = {a.id for a in here}
            facts = [f"{self.first_name(aid)} a été pris en défaut à la saison {s}" for (aid, s), f in self.established.items()
                     if aid in ids and recent(s) and not f["secret"]]
            facts += [f"{self.first_name(x)} a accusé {self.first_name(y)} de trop pêcher (saison {s})"
                      for x, y, s in accused if y in ids]
            said = [c for c in heard if c["subject"] in ids and c["kind"] != "depart"]
            facts += [self.heard_text(c) + " : cela ne colle pas" for c in said if self.discordant(c)][-3:]
            fine = sum(1 for c in said if not self.discordant(c))
            if fine:
                facts.append(f"{fine} témoignage{'s' if fine > 1 else ''} concordant{'s' if fine > 1 else ''} avec ce qu'ils ont déclaré")
            names = ", ".join(f"{self.first_name(a.id)} ({a.id}, confiance de la vallée : {prompts.trust_word(self.reputation(a.id))})"
                              for a in here)
            out.append(f"{h} : {names} ; " + (" ; ".join(facts) if facts else "rien de particulier") + f" ; {passage(h)}")
        banned = [a for a in self.fishers if a.id in self.banned]
        if banned:
            seen = [self.heard_text(c) for c in heard if c["kind"] == "depart"][-3:]
            caught = [f"{self.first_name(aid)} a été pris à pêcher en cachette (saison {s})"
                      for (aid, s), f in self.established.items() if f["secret"] and recent(s)]
            out.append("large : les interdits de pêche (" + ", ".join(f"{self.first_name(a.id)} {a.id}" for a in banned)
                       + ") peuvent y sortir en cachette" + "".join(" ; " + x for x in seen + caught) + f" ; {passage('large')}")
        else:
            out.append(f"large : personne n'y pêche d'ordinaire ; {passage('large')}")
        audit = self.audits.get(season - 1)
        if audit and audit["significant"]:
            out.append(f"Les comptes du lac de la saison dernière ne tombaient pas juste : il a perdu environ {audit['drop']:g} t, "
                       f"les déclarations n'en expliquent que {audit['declared']:g}.")
        mine = [x for s in sorted(self.patrol_log) if recent(s) for x in self.patrol_log[s]]
        out.append("Ce que tu as relevé toi-même ces deux dernières saisons : " + (" ".join(mine) if mine else "rien encore."))
        return out

    def patrol_suspicion(self, season: int) -> dict[str, float]:
        """Où se méfie-t-on le plus, d'après ce qui s'est dit devant tous (de moins en moins avec l'ancienneté) : la décision d'un
        capitaine à règles. Une zone où il est passé sans rien trouver inspire moins de méfiance."""
        home = {a.id: a.profile.hamlet for a in self.fishers}
        score = {z: 0.0 for z in self.zones}

        def place(aid: str) -> str:
            return "large" if aid in self.banned else home[aid]

        def fade(s: int) -> float:
            return 1.0 if s >= season - 1 else 0.5 if s == season - 2 else 0.0

        for h in self.hamlets:
            here = [a.id for a in self.fishers if a.profile.hamlet == h and a.id not in self.banned]
            score[h] += sum(1.0 - self.reputation(i) for i in here) / max(len(here), 1)
        score["large"] += sum(1.0 - self.reputation(b) for b in self.banned) + (0.3 if self.banned else 0.0)
        for (aid, s), f in self.established.items():
            score["large" if f["secret"] else place(aid)] += 2.0 * fade(s)
        for e in self.events.index.values():
            if e["type"] == "accusation" and e["payload"]["accused"] in home:
                score[place(e["payload"]["accused"])] += fade(e["season"])
        for c in self.clues:
            if c["public"] and c["kind"] != "patrouille" and c["subject"] in home and self.discordant(c):
                score["large" if c["kind"] == "depart" else c["zone"] if c["zone"] in score else place(c["subject"])] += fade(c["season"])
        for leg in self.patrol_legs.get(season - 1, []):
            if not any(s == season - 1 and (place(aid) == leg["zone"] or (f["secret"] and leg["zone"] == "large"))
                       for (aid, s), f in self.established.items()):
                score[leg["zone"]] *= 0.6
        return score

    def patrol_suspects(self, season: int) -> dict[str, float]:
        """Qui soupçonne-t-on, d'après ce qui s'est dit devant tous (accusations, mensonges établis, indices relatés par l'ancien ; de
        moins en moins avec l'ancienneté) ? Sans rien de dit sur lui, un pêcheur n'est pas soupçonné."""
        home = {a.id for a in self.fishers}
        score: dict[str, float] = {}

        def fade(s: int) -> float:
            return 1.0 if s >= season - 1 else 0.5 if s == season - 2 else 0.0

        for (aid, s), _f in self.established.items():
            score[aid] = score.get(aid, 0.0) + 2.0 * fade(s)
        for e in self.events.index.values():
            if e["type"] == "accusation" and e["payload"]["accused"] in home:
                score[e["payload"]["accused"]] = score.get(e["payload"]["accused"], 0.0) + fade(e["season"])
        for c in self.clues:
            if c["public"] and c["kind"] != "patrouille" and c["subject"] in home and self.discordant(c):
                score[c["subject"]] = score.get(c["subject"], 0.0) + fade(c["season"])
        return {aid: v for aid, v in score.items() if v > 0}

    def patrol_rule(self, season: int, legs_n: int, days: int) -> tuple[list[tuple[str, int]], str]:
        """Le plan d'un capitaine à règles (ou le repli d'un capitaine dont l'IA n'a pas répondu) : il suit de près le pêcheur le plus
        soupçonné s'il y en a un, puis va là où l'on se méfie le plus ; les jours en proportion, un coup d'œil ailleurs une fois sur
        cinq pour qu'on ne le devine pas."""
        score, suspects = self.patrol_suspicion(season), self.patrol_suspects(season)
        steps: list[tuple[str, float]] = []
        if suspects:
            top = max(suspects, key=lambda a: (suspects[a], a))
            steps.append((top, suspects[top]))
        order = sorted(self.zones, key=lambda z: (-score[z], z))
        chosen = order[:legs_n - len(steps)]
        if len(order) > len(chosen) and chosen and self.lie_rng.random() < 0.2:
            chosen[-1] = self.lie_rng.choice(order[len(chosen):])
        steps += [(z, score[z]) for z in chosen]
        weights = [w + 0.5 for _, w in steps]
        split = [max(1, round(days * w / sum(weights))) for w in weights]
        while sum(split) > days:
            split[split.index(max(split))] -= 1
        why = (f"Je suis de près {self.first_name(steps[0][0])}, dont on parle, puis je vais là où l'on se méfie le plus."
               if suspects else "Je vais d'abord là où l'on se méfie le plus.")
        return list(zip([t for t, _ in steps], split)), why

    def patrol_report(self, season: int):
        """Ce que la patrouille retient de sa saison : où elle est passée, qui elle a mesuré, et si ce qu'elle a mesuré collait à ce qui
        était déclaré (elle ne saura le fin mot qu'à la veillée). C'est ce qu'elle relira avant de choisir sa route."""
        legs = self.patrol_legs.get(season)
        if not self.patrol_agent or not legs:
            return
        mine = [c for c in self.clues if c["season"] == season and c["kind"] == "patrouille"]
        lines = [f"Saison {season} : je suis allé vers {', puis '.join(self.leg_text(leg) for leg in legs)}"
                 + ("." if mine else " et je n'ai croisé aucune barque à mesurer.")]
        for c in mine:
            gap = c["declared"] is not None and self.beyond_declared(c["estimate"], c["declared"])
            lines.append(f"J'ai mesuré la barque de {self.first_name(c['subject'])} ({c['zone']}) : environ {c['estimate']:g} t"
                         + ("" if c["declared"] is None else f", {c['declared']:g} t déclarées : "
                            + ("ça ne colle pas." if gap else "ça colle.")))
        self.patrol_log[season] = lines
        for text in lines:
            self.remember(self.patrol_agent, text, "patrouille", 0.7)

    def council_members(self, season: int) -> list[str]:
        """Qui siège au conseil de la vallée : l'ancien, qui ouvre la séance, puis un élu par village (le tour de parole commence
        chaque saison par un village différent) ; ou tous, si `scenario.council` vaut `all`."""
        elder = [self.elder.id] if self.elder else []
        if not self.delegates or not self.reps:         # (sans élus, par exemple si la communication vient d'être rouverte : tous)
            return elder + [a.id for a in self.fishers]
        reps = [self.reps[h] for h in self.hamlets if h in self.reps]
        k = season % len(reps) if reps else 0
        return elder + reps[k:] + reps[:k]

    def open_assemblies(self, season: int, close_t: float, mode: str = "sync") -> list[Assembly]:
        # le soir de la veillée (qu'elle se tienne ou non) : les indices de la saison réunis, et ce qu'ils établissent, relaté
        # par l'ancien ; ce que chacun en pense, et ce que la vallée en décide, se dira à la veillée
        self.investigate(season)
        self.weigh_evidence(season)
        if self.comm == "none":
            return []
        if self.comm == "valley":
            groups = {"valley": self.council_members(season)}
        else:
            groups = {}
            for h in self.hamlets:
                members = [a.id for a in self.fishers if a.profile.hamlet == h]
                if self.elder and self.elder.profile.hamlet == h:
                    members.insert(0, self.elder.id)
                if len([m for m in members if self.agents[m].is_fisher]) >= 1:
                    groups[f"hamlet:{h}"] = members
        out = []
        for scope, members in groups.items():
            council = scope == "valley" and self.delegates and bool(self.reps)
            asm = Assembly(scope, members, season, close_t, mode=mode, delegates=council)
            self.events.emit("assembly_start", {"scope": scope, "participants": members, "mode": mode,
                                                **({"delegates": dict(self.reps)} if council else {})})
            out.append(asm)
        self.assemblies = out
        return out

    def post_utterance(self, agent: Agent, asm: Assembly, outcome, rnd: int, horizon: float):
        d = outcome.data
        text = str(d.get("message", "")).strip()[:400]
        to = str(d.get("destinataire") or "tous").strip()
        if to not in asm.participants:
            to = "tous"
        heard = [] if asm.independent else [u["event_id"] for u in asm.utterances if u["sim_time"] <= horizon]
        u = self.events.emit("utterance", {"speaker": agent.id, "to": to, "text": text, "scope": asm.scope,
                                           "round": rnd, "info_horizon": round(horizon, 6), "heard": heard[-12:],
                                           "decision_event_id": outcome.decision["event_id"]}, actor=agent.id)
        asm.utterances.append(u)
        now = self.clock.now()
        season = asm.season
        # proposition de règle
        q = to_number(d.get("proposition_quota"))
        lo, hi = self.min_catch, self.max_catch      # proposer ou promettre hors de ce qu'une sortie rapporte, c'en est la borne
        if q is not None and 0 <= q <= self.boat_max:
            q = round(min(max(q, lo), hi), 2)
            asm.stated[agent.id] = q
            twin = self._similar_proposal(asm, q)
            if twin is not None:
                # huit pêcheurs qui proposent 7,0 ; 7,3 ; 7,4 ; 7,5 ne font pas huit règles : une seule, soutenue par tous. Sans
                # cela les voix se dispersaient sur des dizaines de propositions et aucune règle n'était jamais adoptée.
                self._support(agent, asm, twin.id, u)
            else:
                pid = f"P{next(self._pid)}"
                pe = self.events.emit("proposal", {"proposal_id": pid, "author": agent.id, "quota": q,
                                                   "scope": asm.scope, "utterance_id": u["event_id"]}, actor=agent.id)
                asm.proposals[pid] = Proposal(pid, agent.id, q, now, pe["event_id"], asm.scope)
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
            if pv is not None and 0 <= pv <= self.boat_max:
                pv = min(max(pv, lo), hi)
                asm.stated.setdefault(agent.id, round(pv, 2))     # une proposition de quota, si elle existe, prime sur la promesse
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
        acc = self.fisher_ref(d["accuse"]) if d.get("accuse") else None
        if acc is not None and acc != agent.id:
            accused = self.agents[acc]
            ae = self.events.emit("accusation", {"accuser": agent.id, "accused": accused.id,
                                                 "utterance_id": u["event_id"]}, actor=agent.id)
            asm.accused.append((now, accused.id))
            self.accusations.setdefault(season, []).append((now, accused.id, agent.id))
            if accused.id in asm.participants:
                self.remember(accused, f"{agent.profile.name} m'a accusé devant tous d'avoir trop pêché.",
                              "accusation", 0.95, pinned=True, expires_season=season + 1,
                              source_event_id=u["event_id"])
        # ce qu'il pense désormais de chacun (son jugement), et ce qu'il propose à la vallée : exclure ou réautoriser
        self.judge(agent, d.get("confiance"), u["event_id"])
        if agent.is_fisher:
            for action in ("exclure", "reautoriser"):
                if d.get(action):
                    self.propose_sanction(agent, asm, d[action], action, u)
            if d.get("patrouille") and asm.scope == "valley":      # la patrouille du lac se décide au conseil de la vallée
                self.propose_patrol(agent, asm, d["patrouille"], u)
        # ce que chacun retient
        self.remember(agent, f"À la veillée, j'ai dit : « {text} »", "parole", 0.4, source_event_id=u["event_id"])
        for pid in asm.participants:
            if pid == agent.id:
                continue
            listener = self.agents[pid]
            adr = "" if to == "tous" else (" (à moi)" if to == pid else f" (à {self.name(to)})")
            self.remember(listener, f"À la veillée, {agent.profile.name}{adr} a dit : « {text} »", "parole",
                          0.8 if to == pid else 0.5, source_event_id=u["event_id"])

    def has_reason_to_speak(self, agent: Agent, asm: Assembly, rnd: int) -> bool:
        """Dès le 2e tour (`scenario.quiet_listeners`), un agent à IA ne reprend la parole que s'il a une raison, apparue depuis
        sa dernière parole : on s'adresse à lui, on le nomme ou l'accuse, ou une autre proposition concurrence la sienne. Les
        autres écoutent, et leur position se recueille au bulletin de vote (quelques tokens) : la parole coûtait 80 % des
        tokens d'une partie, souvent pour redire « je suis d'accord »."""
        if rnd == 1 or agent.profile.kind != "llm" or not self.scn.get("quiet_listeners", False):
            return True
        mine = [u for u in asm.utterances if u["payload"]["speaker"] == agent.id]
        if not mine:
            return True
        heard = mine[-1]["payload"]["info_horizon"]          # ce qu'il avait entendu quand il a parlé
        new = [u for u in asm.utterances if u["sim_time"] > heard and u["payload"]["speaker"] != agent.id]
        if any(u["payload"]["to"] == agent.id for u in new) or any(t > heard and a == agent.id for t, a in asm.accused):
            return True
        if agent.id in self.named_fishers([u["payload"]["text"] for u in new]):
            return True
        return any(p.author == agent.id for p in asm.proposals.values()) and \
            any(p.author != agent.id and p.t > heard for p in asm.proposals.values())

    def propose_sanction(self, agent: Agent, asm: Assembly, raw, action: str, u: dict):
        """`agent` propose d'interdire de pêche (`exclure`) un pêcheur, ou de le laisser pêcher à nouveau (`reautoriser`) ; si la
        même proposition est déjà sur la table, il la soutient. On n'exclut pas un exclu, on ne réautorise pas un libre, et l'on
        ne se vise pas soi-même. L'auteur vote pour."""
        tid = self.fisher_ref(raw)
        if tid is None or tid == agent.id or (action == "exclure") == (tid in self.banned):
            return
        target = self.agents[tid]
        same = self._motion(agent, asm, action, tid, u)
        if same.author == agent.id and len(same.votes) == 0 and tid in asm.participants and action == "exclure":
            self.remember(target, f"{agent.profile.name} a proposé devant tous de m'interdire de pêche.", "sanction",
                          0.95, pinned=True, expires_season=asm.season + 1, source_event_id=same.event_id)
        self.vote_sanction(agent, same, True)

    def propose_patrol(self, agent: Agent, asm: Assembly, raw, u: dict):
        """Un élu propose d'installer la patrouille du lac (« installer ») ou de la retirer (« retirer ») : la première s'il n'y en
        a pas, la seconde s'il y en a une. Une proposition déjà sur la table est soutenue plutôt que doublée. L'auteur vote pour."""
        if not self.patrol_on:
            return
        word = str(raw).strip().lower()
        if word.startswith(("inst", "mett", "cré", "cre", "voter", "cr")):
            action = "patrouille"
        elif word.startswith(("ret", "lev", "fin", "supp", "arr", "abol")):
            action = "fin_patrouille"
        else:
            return
        if (action == "patrouille") == self.patrol_exists():
            return
        self.vote_sanction(agent, self._motion(agent, asm, action, "", u), True)

    def _motion(self, agent: Agent, asm: Assembly, action: str, target: str, u: dict) -> Sanction:
        """La motion `action` visant `target` ("" : aucun pêcheur) : celle qui est déjà sur la table, ou une nouvelle."""
        same = next((s for s in asm.sanctions.values() if s.target == target and s.action == action), None)
        if same is None:
            sid = f"X{next(self._xid)}"
            pe = self.events.emit("sanction_proposal", {"proposal_id": sid, "author": agent.id, "target": target,
                                                        "action": action, "scope": asm.scope, "utterance_id": u["event_id"]},
                                  actor=agent.id)
            same = asm.sanctions[sid] = Sanction(sid, agent.id, target, action, self.clock.now(), pe["event_id"])
        return same

    def vote_sanction(self, agent: Agent, s: Sanction, yes: bool):
        if agent.id == s.target or agent.id in s.votes or not agent.is_fisher:
            return
        s.votes[agent.id] = yes
        self.events.emit("sanction_vote", {"proposal_id": s.id, "agent": agent.id, "vote": yes}, actor=agent.id)

    def policy_voter(self, agent: Agent) -> bool:
        """Vote-t-il selon son caractère (agent à règles, ou faux LLM, qui ne sait pas répondre à un bulletin) ?"""
        return agent.profile.kind == "rule" or self.cfg["llm"]["tiers"]["petit"]["provider"] == "scripted"

    def close_sanctions(self, asm: Assembly):
        """À la clôture, chaque proposition du conseil (exclure ou réautoriser un pêcheur, installer ou retirer la patrouille) est
        tranchée : les pêcheurs présents (sauf celui qu'elle vise) qui n'ont pas encore voté le font selon leur caractère s'ils
        votent ainsi ; adoptée avec au moins la moitié d'entre eux, elle prend effet dès la saison suivante. Les IA ont voté par
        leur bulletin, selon leur confiance, leur morale et leurs intérêts. Tout le monde en apprend la décision, même les
        villageois qui n'étaient pas au conseil."""
        for s in asm.sanctions.values():
            voters = [a for a in asm.participants if self.agents[a].is_fisher and a != s.target]
            for aid in voters:
                a = self.agents[aid]
                if aid in s.votes or not self.policy_voter(a):
                    continue
                if s.action in PATROL_ACTIONS:
                    lies = sum(1 for (_, ls), f in self.established.items() if ls >= asm.season - 1)
                    self.vote_sanction(a, s, patrol_vote(a.archetype, lies, s.action))
                else:
                    self.vote_sanction(a, s, sanction_vote(a.archetype, self.trust[aid][s.target], s.action))
            yes = sorted(a for a, v in s.votes.items() if v)
            adopted = bool(voters) and len(yes) * 2 >= len(voters)
            res = self.events.emit("sanction_result", {
                "proposal_id": s.id, "target": s.target, "action": s.action, "adopted": adopted, "for": yes,
                "against": sorted(a for a, v in s.votes.items() if not v), "voters": len(voters)}, actor=s.target or None)
            if s.action in PATROL_ACTIONS:
                what = "installer la patrouille du lac" if s.action == "patrouille" else "retirer la patrouille du lac"
                for agent in self.agents.values():
                    self.remember(agent, f"Au conseil, la vallée a {'décidé' if adopted else 'refusé'} de {what} "
                                         f"({len(yes)} voix sur {len(voters)}).", "sanction", 0.9, source_event_id=res["event_id"])
                if adopted:
                    self.set_patrol(s, asm.season, yes, len(voters))
                continue
            name = self.agents[s.target].profile.name
            what = "l'interdire de pêche" if s.action == "exclure" else "lui rendre le droit de pêcher"
            for agent in self.agents.values():
                self.remember(agent, f"Au conseil, la vallée a {'décidé' if adopted else 'refusé'} de {what} : "
                                     f"{name} ({len(yes)} voix sur {len(voters)}).", "sanction", 0.9,
                              source_event_id=res["event_id"])
            if not adopted:
                continue
            target = self.agents[s.target]
            if s.action == "exclure":
                self.banned[s.target] = asm.season + 1
            else:
                self.banned.pop(s.target, None)
            self.events.emit("ban", {"agent": s.target, "banned": s.action == "exclure",
                                     "reputation": self.reputation(s.target), "proposal_id": s.id, "for": yes,
                                     "voters": len(voters)}, actor=s.target)
            self.remember(target, "La vallée m'a interdit de pêche : tant qu'elle ne me fera pas de nouveau confiance, je ne "
                                  "pourrai pêcher qu'en cachette." if s.action == "exclure" else
                          "La vallée m'a rendu le droit de pêcher.", "interdiction", 1.0, source_event_id=res["event_id"])

    def _support(self, agent: Agent, asm: Assembly, pid: str, u: dict):
        se = self.events.emit("support", {"agent": agent.id, "proposal_id": pid, "utterance_id": u["event_id"]},
                              actor=agent.id)
        asm.support[agent.id] = (pid, self.clock.now(), se["event_id"])

    def _similar_proposal(self, asm: Assembly, q: float) -> Proposal | None:
        """La proposition déjà sur la table dont le quota est à moins de `scenario.proposal_merge_tolerance` t de `q` (la plus proche)."""
        tol = float(self.scn.get("proposal_merge_tolerance", 0.75))
        near = [p for p in asm.proposals.values() if abs(p.quota - q) <= tol + 1e-9]
        return min(near, key=lambda p: (abs(p.quota - q), p.id), default=None)

    def motion_text(self, s: Sanction) -> str:
        """Ce que propose une motion du conseil, en mots."""
        if s.action == "patrouille":
            return (f"installer une patrouille du lac (chaque pêcheur y contribuerait de {self.patrol_cfg['cost']:g} écus par "
                    "saison)")
        if s.action == "fin_patrouille":
            return "retirer la patrouille du lac"
        return f"{'interdire de pêche' if s.action == 'exclure' else 'laisser pêcher à nouveau'} {self.name(s.target)} ({s.target})"

    def patrol_line(self, season: int) -> str:
        """L'état de la patrouille du lac, pour les élus qui doivent décider d'en voter une ou de la retirer : ce qu'elle coûte, ce
        qu'elle fait, et ce que la vallée a établi depuis deux saisons (de quoi juger si elle est nécessaire, sans qu'aucun seuil ne
        le dise)."""
        if not self.patrol_on:
            return ""
        lies = sum(1 for (_, s), _f in self.established.items() if s >= season - 1)
        seen = f" Mensonges ou sorties en cachette établis depuis deux saisons : {lies}."
        how = ("Son capitaine décide seul où aller, d'après les soupçons et les indices que les villageois et les pêcheurs ont "
               "partagés (accusations, indices dits à la veillée) : ce qui n'est pas dit ne lui parvient pas. Il mesure les barques "
               "qu'il croise ; nul ne sait où il passera.")
        if self.patrol_active(season):
            return (f"Une patrouille surveille le lac depuis la saison {self.patrol['since']} : chaque pêcheur y contribue de "
                    f"{self.patrol_cfg['cost']:g} écus par saison. {how}{seen}")
        return ("Il n'y a pas de patrouille sur le lac. Le conseil peut en voter une, aux frais de chaque pêcheur "
                f"({self.patrol_cfg['cost']:g} écus par saison), s'il juge qu'il faut démasquer des fraudes. {how}{seen}")

    def delegate_line(self, agent: Agent) -> str:
        """Pour qui parle un élu : il est le rapporteur de son village, et connaît les siens (leur caractère, leur bateau, ce qu'il
        leur faut pour vivre). Il reste lui-même : sa façon d'être colore ce qu'il en dit, et c'est voulu."""
        village = agent.profile.hamlet
        mates = [a for a in self.fishers if a.profile.hamlet == village and a.id != agent.id]
        if not mates:
            return f"Tu es le seul pêcheur de {village}, et son élu au conseil de la vallée."

        def mate(a: Agent) -> str:
            need = (self.upkeep(a) + a.profile.debt_payment) / self.econ["price_per_tonne"]
            return (f"{self.first_name(a.id)} ({a.profile.archetype_label}, {a.profile.boat} ; il lui faut {need:.1f} t par saison "
                    "pour vivre)")

        return (f"Tu es l'élu de {village} au conseil de la vallée, le porte-parole de ton village : tu rapportes ce que veulent les "
                f"tiens, qui n'y {'viennent' if len(mates) > 1 else 'vient'} pas et subiront la décision : "
                + " ; ".join(mate(a) for a in mates) + ". Tu restes toi-même : ta façon de voir colore ce que tu en dis.")

    def motion_item(self, observer: Agent, s: Sanction, season: int) -> str:
        """Une motion au bulletin d'un élu, en une ligne : ce qu'on propose, par qui, et ce qu'il sait pour en juger."""
        if s.action in PATROL_ACTIONS:
            return f"{self.motion_text(s)}, proposé par {self.name(s.author)}. {self.patrol_line(season)}"
        first, trust = self.first_name(s.target), self.trust[observer.id].get(s.target, TRUST_START)
        return (f"{self.motion_text(s)}, proposé par {self.name(s.author)}. Ta confiance envers {first} : "
                f"{prompts.trust_word(trust)} ({100 * trust:.0f} %). Ce que tu sais de lui : "
                f"{self.sanction_brief(observer, s.target, season)}.")

    def ballot_candidates(self, asm: Assembly) -> list[Agent]:
        """Les pêcheurs à IA qui ont encore un bulletin à remplir : aucune proposition de règle soutenue, ou une proposition
        d'exclure ou de réautoriser sur laquelle ils n'ont pas voté. Pas avec le faux LLM : il ne sait pas répondre à un
        bulletin, la clôture compte alors ce que chacun a dit (et le fait voter selon son caractère sur les sanctions)."""
        if asm.closed or self.cfg["llm"]["tiers"]["petit"]["provider"] == "scripted":
            return []
        out = []
        for aid in asm.participants:
            a = self.agents[aid]
            if not a.is_fisher or a.profile.kind != "llm":
                continue
            if (asm.proposals and aid not in asm.support) or \
                    any(s.target != aid and aid not in s.votes for s in asm.sanctions.values()):
                out.append(a)
        return out

    def candidate_line(self, voter: Agent, cand: Agent, season: int) -> str:
        """Un candidat à l'élection de son village, vu par un électeur : qui il est, ce que celui-ci en pense et en sait."""
        if cand.id == voter.id:
            return f"toi-même ({cand.profile.experience} ans de pêche, {cand.profile.boat})"
        trust = self.trust[voter.id].get(cand.id, TRUST_START)
        known = self.sanction_brief(voter, cand.id, season - 1, "rien de particulier") if season > 1 else "rien de particulier"
        return (f"{self.first_name(cand.id)}, {cand.profile.archetype_label}, {cand.profile.experience} ans de pêche, "
                f"{cand.profile.boat}. Ta confiance : {prompts.trust_word(trust)} ({100 * trust:.0f} %). Ce que tu sais de "
                f"lui : {known}.")

    def debrief_lines(self, agent: Agent, asm: Assembly, facts: dict[str, dict]) -> list[str]:
        """Ce que l'ancien rapporte à un villageois absent du conseil : les décisions prises, les accusations portées, et ce que
        la vallée sait de chaque pêcheur (seuls ceux sur qui il y a quelque chose à dire)."""
        evs = [e for e in self.events.index.values() if e["season"] == asm.season]
        sky = self.sky_line(asm.season)
        lines = [sky] if sky else []
        adopted = [e["payload"] for e in evs if e["type"] == "norm_adopted" and e["payload"]["scope"] == "valley"]
        lines.append(f"le conseil a adopté une règle : pas plus de {adopted[-1]['quota']:g} t par pêcheur dès la saison "
                     f"{adopted[-1]['effective_season']}" if adopted else "le conseil n'a adopté aucune règle")
        for e in evs:
            p = e["payload"]
            if e["type"] == "sanction_result":
                verdict = "voté" if p["adopted"] else "refusé"
                if p["action"] in PATROL_ACTIONS:
                    what = "d'installer la patrouille du lac" if p["action"] == "patrouille" else "de retirer la patrouille du lac"
                else:
                    what = ("d'interdire de pêche " if p["action"] == "exclure" else "de laisser pêcher à nouveau ") \
                        + self.first_name(p["target"])
                lines.append(f"le conseil a {verdict} {what} ({len(p['for'])} voix sur {p['voters']})")
            elif e["type"] == "accusation":
                lines.append(f"{self.first_name(p['accuser'])} a accusé {self.first_name(p['accused'])} de trop pêcher")
        for cid, f in facts.items():
            if f.get("over", 0.0) > 0 or f.get("lie") or f.get("secret") or f.get("accused_me") or f.get("testified") \
                    or f.get("stayed_away") or f.get("promise") is not None:
                bits = [self.sanction_brief(agent, cid, asm.season)]
                if f.get("testified"):
                    bits.append("a témoigné devant tous")
                if f.get("accused_me"):
                    bits.append("t'a accusé devant le conseil")
                lines.append(f"{self.first_name(cid)} ({cid}) : " + " ; ".join(bits))
        return lines

    def sanction_brief(self, observer: Agent, target: str, season: int, none: str = "rien de particulier cette saison") -> str:
        """Ce que `observer` sait de `target` cette saison, en une ligne : de quoi voter sur son exclusion."""
        now, bits = self.clock.now(), []
        known, norm = self.known_catch(target, season, now), self.applicable_norm(self.agents[target], season, now)
        if known is not None:
            bits.append(f"déclare {known:g} t" + (f" pour une règle de {norm.quota:g} t" if norm else ""))
        found = self.established.get((target, season))
        if found is not None:
            bits.append("pris à pêcher en cachette" if found["secret"] else "mensonge établi par l'ancien")
        if target in self.banned:
            bits.append(f"interdit de pêche depuis la saison {self.banned[target]}")
        promise = self.promises.get((target, season))
        if promise is not None and known is not None:
            bits.append("promesse tenue" if known <= promise[0] + self.scn["promise_tolerance"] else "promesse trahie")
        return " ; ".join(bits) or none

    async def ballots(self, asms: list[Assembly]) -> None:
        """Le bulletin de chacun, en même temps (synchrone : juste avant la clôture)."""
        await asyncio.gather(*(ballot(self, a, asm) for asm in asms for a in self.ballot_candidates(asm)))

    def closing_vote(self, asm: Assembly):
        """Le vote de clôture : chaque pêcheur qui n'a soutenu aucune proposition vote pour celle dont le quota est le plus proche
        de ce qu'il a lui-même dit vouloir (quota proposé ou promesse), pourvu qu'elle soit à moins de `scenario.vote_tolerance` t.
        Qui n'a rien dit de chiffré s'abstient. C'est le dépouillement de ce que chacun a déjà exprimé, sans appel à l'IA : chaque
        voix est un événement `support`, rattaché à la dernière parole du votant."""
        tol = float(self.scn.get("vote_tolerance", 1.5))
        for aid in asm.participants:
            agent = self.agents[aid]
            if not agent.is_fisher or aid in asm.support or aid not in asm.stated or not asm.proposals:
                continue
            best = min(asm.proposals.values(), key=lambda p: (abs(p.quota - asm.stated[aid]), p.id))
            if abs(best.quota - asm.stated[aid]) > tol + 1e-9:
                continue
            last = next((u for u in reversed(asm.utterances) if u["payload"]["speaker"] == aid), None)
            if last is not None:
                self._support(agent, asm, best.id, last)

    def close_assembly(self, asm: Assembly):
        if asm.closed:
            return
        asm.closed = True
        self.closing_vote(asm)
        fishers_present = [a for a in asm.participants if self.agents[a].is_fisher]
        tally: dict[str, list[str]] = {}
        for aid, (pid, _, _) in asm.support.items():
            if self.agents[aid].is_fisher:
                tally.setdefault(pid, []).append(aid)
        adopted = None
        if tally:
            pid, sups = max(tally.items(), key=lambda kv: (len(kv[1]), -int(kv[0][1:])))
            if len(sups) * 2 >= len(fishers_present):      # au moins la moitié des pêcheurs présents
                pr = asm.proposals[pid]
                ne = self.events.emit("norm_adopted", {
                    "proposal_id": pid, "quota": pr.quota, "scope": asm.scope, "effective_season": asm.season + 1,
                    "supporters": sorted(sups), "participants": asm.participants, "author": pr.author,
                    **({"delegates": dict(self.reps)} if asm.delegates else {})})
                self.norms.append(Norm(asm.scope, pr.quota, asm.season + 1, pid, self.clock.now(),
                                       ne["event_id"], sorted(sups)))
                adopted = pid
                # la règle vaut pour tous : les villageois qui n'étaient pas au conseil l'apprennent aussi
                everyone = list(self.agents) if asm.delegates else asm.participants
                for aid in everyone:
                    self.remember(self.agents[aid], f"Règle adoptée chez l'ancien ({asm.label}) : pas plus de "
                                                    f"{pr.quota:g} t par pêcheur à partir de la saison {asm.season + 1}, "
                                                    f"soutenue par {len(sups)} {'élus' if asm.delegates else 'pêcheurs'} "
                                                    f"sur {len(fishers_present)}.",
                                  "regle", 0.9, source_event_id=ne["event_id"])
        self.close_sanctions(asm)
        if asm.delegates:
            self.last_council = asm          # les villageois absents en jugeront avant la saison suivante (voir `debrief`)
        self.events.emit("assembly_end", {"scope": asm.scope, "adopted_proposal": adopted,
                                          "utterances": len(asm.utterances)})

    # ------------------------------------------------------------ fin de saison
    def end_season(self, season: int):
        # la veillée finie, l'ancien pèse les indices et les accusations (sans veillée, il le fait seul)
        self.investigate(season)
        self.weigh_evidence(season)
        delta = self.lake.regrow(self.conditions.get("growth", 1.0))       # la saison de l'année et les événements
        self.lake_update("regrowth", delta)
        tol = self.scn["promise_tolerance"]
        now = self.clock.now()
        for a in self.fishers:
            landed = a.catches.get(season, 0.0)
            key = (a.id, season)
            if key in self.promises:
                promised, pe_id = self.promises[key]
                kept = landed <= promised + tol
                # la vallée juge sur ce qu'elle sait : une déclaration mensongère couvre une promesse trahie, jusqu'à ce
                # qu'elle éclate
                known = self.known_catch(a.id, season, now)
                known_kept = (landed if known is None else known) <= promised + tol
                self.events.emit("promise_outcome", {
                    "agent": a.id, "promise_event_id": pe_id, "promised": promised, "landed": round(landed, 3),
                    "kept": kept, "season": season, "declared": round(a.declared.get(season, landed), 3),
                    "known_kept": known_kept}, actor=a.id)
                if not kept:
                    self.remember(a, f"J'avais promis {promised:g} t pour la saison {season} et j'en ai pris "
                                     f"{landed:g}. " + ("Personne ne le sait." if known_kept else "Tout le monde le sait."),
                                  "promesse", 0.9)
            a.wealth -= self.upkeep(a, season) + a.profile.debt_payment
            self.remember(a, f"Bilan de la saison {season} : {landed:g} t pêchées, il me reste {a.wealth:.0f} écus.",
                          "bilan", 0.5)
        self.events.emit("season_end", {
            "stock": round(self.lake.stock, 3),
            "catches": {a.id: round(a.catches.get(season, 0.0), 3) for a in self.fishers},
            "declared": {a.id: round(a.declared.get(season, 0.0), 3) for a in self.fishers},
            "reputation": {a.id: self.reputation(a.id) for a in self.fishers},
            "wealth": {a.id: round(a.wealth, 2) for a in self.fishers},
            "norms_in_force": [{"scope": n.scope, "quota": n.quota, "proposal_id": n.proposal_id,
                                "effective_season": n.effective_season}
                               for n in (self.norm_for_scope(sc, season, self.clock.now())
                                         for sc in dict.fromkeys(x.scope for x in self.norms)) if n],
        })

    # ------------------------------------------------------------ le récit de l'ancien
    def first_name(self, aid: str) -> str:
        a = self.agents.get(aid)
        return (a.profile.first_name or a.profile.name) if a else aid

    def season_facts(self, season: int) -> list[str]:
        """Ce que l'ancien sait de la saison, relevé dans le journal de la partie : la matière de son récit. Il ne connaît que
        les déclarations, et la vérité des mensonges qui ont éclaté ; le joueur, lui, voit tout dans l'interface."""
        evs = [e for e in self.events.index.values() if e["season"] == season]
        now = self.clock.now()

        def of(etype: str) -> list[dict]:
            return [e["payload"] for e in evs if e["type"] == etype]

        def both(names: list[str]) -> str:
            return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " et " + names[-1]

        facts: list[str] = []
        said: dict[str, float] = {}
        for r in of("report"):
            said[r["agent"]] = round(said.get(r["agent"], 0.0) + r["declared"], 2)
        landed = {a: self.known_catch(a, season, now) for a in said}       # ce que l'ancien en sait
        if said:
            # (huit noms et huit chiffres, un petit modèle les mélange : le récit n'a besoin que des extrêmes et du total)
            low, high = min(said.items(), key=lambda kv: kv[1]), max(said.items(), key=lambda kv: kv[1])
            facts.append(f"Prises déclarées à l'ancien : de {self.first_name(low[0])} {low[1]:g} t à {self.first_name(high[0])} "
                         f"{high[1]:g} t (en tout {sum(said.values()):g} t).")
        for d in of("lie_discovered"):          # ce que l'ancien a établi : l'estimation des indices, pas la vérité
            about = f"environ {d['estimated']:g} t" if d.get("estimated") is not None else "on ne sait combien"
            if d["secret"]:
                facts.append(f"{self.first_name(d['agent'])}, interdit de pêche, a été pris à pêcher en cachette "
                             f"({about} ; {HOW[d['how']]}).")
            else:
                facts.append(f"Mensonge établi : {self.first_name(d['agent'])} a déclaré {d['declared']:g} t, les indices "
                             f"disent {about} ({HOW[d['how']]}).")
        audit = of("lake_audit")
        if audit and audit[0]["significant"]:
            facts.append(f"Les comptes du lac ne tombent pas juste : il a perdu environ {audit[0]['drop']:g} t, les "
                         f"déclarations n'en expliquent que {audit[0]['declared']:g}.")
        for r in of("sanction_result"):          # ce que la vallée a voté : exclure ou réautoriser, la patrouille du lac
            verdict = 'voté' if r["adopted"] else 'refusé'
            if r["action"] in PATROL_ACTIONS:
                what = "d'installer" if r["action"] == "patrouille" else "de retirer"
                facts.append(f"Le conseil a {verdict} {what} la patrouille du lac, dès la saison {season + 1} "
                             f"({len(r['for'])} voix sur {r['voters']}).")
                continue
            what = "d'interdire de pêche" if r["action"] == "exclure" else "de laisser pêcher à nouveau"
            facts.append(f"La vallée a {verdict} {what} {self.first_name(r['target'])} "
                         f"({len(r['for'])} voix sur {r['voters']}).")
        if self.banned:
            facts.append("Interdits de pêche : " + both([self.first_name(b) for b in self.banned]) + ".")
        start = next((p["stock"] for p in of("season_start")), None)
        level = prompts.lake_level(self.lake.stock, self.capacity, self.lake.collapse_ratio)
        facts.append((f"Le lac : {start:.0f} t au début de la saison, " if start is not None else "Le lac : ")
                     + f"{self.lake.stock:.0f} t après le repeuplement, sur {self.capacity:.0f} t possibles "
                       f"({100 * self.lake.stock / self.capacity:.0f} % : {level}).")
        cond = next((p.get("conditions") for p in of("season_start")), None) or {}
        if cond.get("climate"):
            facts.append(f"Saison de l'année : {cond['climate']}.")
            sky = self.sky_phrase(cond.get("days") or [])                 # le temps de la pêche : tout le monde l'a vu
            if sky:
                facts.append("Temps de la pêche : " + sky + " (les petites barques souffrent le plus des mauvais jours).")
        for ev in of("world_event"):
            facts.append(f"Événement : {ev['label']} ({ev['text']}).")
        route = next((p["legs"] for p in of("patrol_route")), None)         # la vallée l'a vue passer : l'ancien le sait
        if route:
            facts.append("La patrouille du lac a fait route vers " + ", puis ".join(self.leg_text(leg) for leg in route) + ".")
        elif self.patrol_active(season):
            facts.append("Une patrouille surveille le lac cette saison.")
        council = next((p.get("delegates") for p in of("assembly_start") if p.get("delegates")), None)
        if council:
            facts.append("Au conseil de la vallée siégeaient : "
                         + ", ".join(f"{self.first_name(a)} ({h})" for h, a in council.items()) + ".")
        for inj in of("injection"):
            if inj["injection_type"] == "drought":
                facts.append("Une sécheresse a frappé le lac : son stock a baissé d'un coup.")
            elif inj["injection_type"] == "announcement":
                facts.append(f"Une rumeur a couru dans la vallée : « {inj['params'].get('text', '')} ».")
        tol = self.scn["quota_tolerance"]
        rules: dict[tuple[str, float], list[str]] = {}
        for a in self.fishers:
            norm = self.applicable_norm(a, season, self.clock.now())
            if norm is not None:
                over = rules.setdefault((norm.scope, norm.quota), [])
                if landed.get(a.id, 0.0) > norm.quota + tol:
                    over.append(f"{self.first_name(a.id)} ({landed[a.id]:g} t)")
        for (scope, quota), over in rules.items():
            whose = "de la vallée" if scope == "valley" else f"du hameau de {scope.split(':', 1)[1]}"
            facts.append(f"Règle {whose} : pas plus de {quota:g} t par pêcheur ; "
                         + ("tous l'ont tenue." if not over else f"dépassée par {both(over)}."))
        adopted = of("norm_adopted")
        for n in adopted:
            present = sum(1 for p in n["participants"] if p in self.agents and self.agents[p].is_fisher)
            whose = "" if n["scope"] == "valley" else f" pour le hameau de {n['scope'].split(':', 1)[1]}"
            # la règle qu'elle remplace, pour que l'ancien ne dise pas « on augmente la limite » à la toute première
            before = self.norm_for_scope(n["scope"], season, self.clock.now())
            if before is None:
                what, instead = "première règle adoptée", ""
            elif n["quota"] == before.quota:
                what, instead = "règle reconduite", ""
            else:
                what = "règle plus stricte adoptée" if n["quota"] < before.quota else "règle assouplie"
                instead = f" (au lieu de {before.quota:g} t)"
            who = "élus" if n.get("delegates") else "pêcheurs"           # au conseil, ce sont les élus qui soutiennent
            facts.append(f"À la veillée, {what}{whose} : pas plus de {n['quota']:g} t par pêcheur{instead} à partir de la "
                         f"saison {n['effective_season']}, soutenue par {len(n['supporters'])} {who} sur {present}.")
        if of("assembly_start") and not adopted:
            facts.append(f"À la veillée, {len(of('proposal'))} proposition(s), mais aucune règle n'a réuni la moitié des pêcheurs.")
        outcomes = of("promise_outcome")
        kept = [self.first_name(o["agent"]) for o in outcomes if o.get("known_kept", o["kept"])]
        broken = [f"{self.first_name(o['agent'])} ({o['promised']:g} t promises, "
                  f"{landed.get(o['agent']) if landed.get(o['agent']) is not None else o['landed']:g} t pêchées)"
                  for o in outcomes if not o.get("known_kept", o["kept"])]
        if kept:
            facts.append(f"Promesses tenues : {both(kept)}.")
        if broken:
            facts.append(f"Promesses trahies : {both(broken)}.")
        for acc in of("accusation"):
            facts.append(f"{self.first_name(acc['accuser'])} a accusé {self.first_name(acc['accused'])} de trop pêcher.")
        return facts

    async def narrate(self, season: int) -> None:
        """À la fin de la saison, l'ancien raconte au joueur ce que la vallée a vécu (onglet « Récit de l'ancien » de Godot).
        Son IA le rédige à partir des seuls faits relevés ; sans IA, ou si elle ne répond pas, le récit reprend les faits."""
        facts = self.season_facts(season)
        elder = self.elder
        text, source, call_id = "", "faits", None
        if elder is not None and elder.profile.kind == "llm" and elder.profile.tier and \
                self.cfg["llm"]["tiers"][elder.profile.tier]["provider"] != "scripted":
            data, res, _ = await _ask_llm(self, elder, "narration",
                                          prompts.narration_messages(elder.profile, facts, self.capacity, self.hamlets),
                                          {"round": 0},
                                          schema=prompts.NARRATION_SCHEMA, max_tokens=prompts.NARRATION_MAX_TOKENS,
                                          temperature=prompts.NARRATION_TEMPERATURE)
            text = str((data or {}).get("recit", "")).strip()[:600]
            if text:
                source, call_id = "ancien", res.call_id
        if not text:
            text = f"Ce que j'ai vu à la saison {season}. " + " ".join(facts)
        self.events.emit("narration", {"season": season, "text": text, "source": source, "facts": facts,
                                       "llm_call_id": call_id}, actor=elder.id if elder else None)

    # ------------------------------------------------------------ démarrage / fin
    def start(self):
        cfg_hash = hashlib.sha1(json.dumps(self.cfg, sort_keys=True, default=str).encode()).hexdigest()[:12]
        self.events.emit("run_start", {
            "mode": self.T["mode"], "seed": int(self.cfg["run"]["seed"]), "seasons": int(self.cfg["run"]["seasons"]),
            "lake": {"capacity": self.capacity, "stock": round(self.lake.stock, 3), "growth_rate": self.lake.r,
                     "collapse_ratio": self.lake.collapse_ratio, "sustainable_yield": sustainable_yield(self.cfg)},
            "agents": [{**a.profile.public(), "wealth": a.wealth, "offset_days": a.offset_days}
                       for a in self.agents.values()],
            "hamlets": self.hamlets, "boats": {k: dict(v) for k, v in self.boats.items()},
            "scenario": {"communication": self.comm, "catches_visible": self.visible,
                         "assembly_rounds": self.scn["assembly_rounds"], "council": "delegates" if self.delegates else "all",
                         "patrol": self.patrol_on},
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
                "by_tier": u.by_tier, "by_system": u.by_system, "wall_s": round(self.clock.wall_elapsed(), 2), "reason": self.stopped_reason,
            }, indent=2, ensure_ascii=False))
            self.recorder.close()
        await self.close_storage()

    async def open_storage(self) -> None:
        """Ouvre la base (pgvector) et le stockage objet, et vectorise le corpus s'il ne l'est pas encore."""
        if self.objects is not None:
            await self.objects.open()
        if self.vectors is not None:
            await self.vectors.open()
            await self.retriever.open()

    async def close_storage(self, archive: bool = True) -> None:
        """Archive la partie dans le stockage objet, écrit les derniers souvenirs, ferme les connexions. Une panne ici ne
        change rien à la partie, déjà tracée dans `runs/` : elle est signalée, pas propagée."""
        if archive and self.objects is not None and self.recorder:
            try:
                keys = await archive_run(self.objects, self.run_dir, self.run_id)
                log.info("partie archivée dans %s (%d fichiers)", self.objects.where, len(keys))
            except Exception as exc:
                log.warning("archivage de la partie impossible : %s", exc)
        if self.memory_bank is not None and not self.memory_bank.degraded and self.vectors.pool is not None:
            try:
                await self.memory_bank.flush()
            except Exception as exc:
                log.warning("derniers souvenirs non écrits dans la base : %s", exc)
        for closing in (self.vectors, self.objects, getattr(self.vectors, "embedder", None)):
            if closing is not None:
                try:
                    await closing.aclose()
                except Exception as exc:
                    log.warning("fermeture du stockage : %s", exc)

    def begin_season(self, season: int, mode: str):
        """Début de saison, commun aux deux orchestrations."""
        self.season = season
        self.conditions = cond = self.climate.begin(season)
        cond["days"] = self.weather(season)                    # le temps de chaque jour de pêche, connu de l'interface
        self.events.emit("season_start", {"stock": round(self.lake.stock, 3), "mode": mode, "conditions": cond})
        if self.climate.new:
            ev = self.climate.new
            info = EVENTS[ev]
            self.events.emit("world_event", {"kind": ev, "label": info["label"], "text": info["text"], "season": season,
                                             "until": season + info["duration"] - 1, "stock_factor": info.get("stock", 1.0)})
            if self.climate.shock() != 1.0:
                self.lake_update("event", self.lake.shock(self.climate.shock()))
        self.publish_status()
        self.scheduled_injections(season)

    async def prepare_season(self, season: int):
        """Entre deux saisons, avant que la suivante ne s'ouvre (le même pas pour les deux orchestrations) : les villageois qui
        n'étaient pas au conseil en jugent ce que l'ancien leur en a rapporté, puis chaque village choisit son élu, et l'ancien
        envoie la patrouille du lac (si le conseil en a voté une). Chacun y réfléchit selon son caractère et ce qu'il sait."""
        self.clock.set(max(self.clock.now(), self.clock.season_start(season)))
        await self.debrief(season - 1)
        await asyncio.gather(self.elect(season), self.plan_patrol(season))

    async def run(self):
        """Joue les saisons l'une après l'autre ; le mode (synchrone / asynchrone) est relu à chaque saison."""
        try:
            await self.open_storage()
        except BaseException:
            await self.close_storage(archive=False)
            await self.router.aclose()
            if self.recorder:
                self.recorder.close()
            raise
        self.start()
        pump = asyncio.create_task(self._command_pump())
        try:
            for season in range(1, int(self.cfg["run"]["seasons"]) + 1):
                if self.stop_requested:
                    break
                await self.ctl.checkpoint()
                await self.ctl.guard(self.prepare_season(season))
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
            w.apply_catch(a, o.value, o.decision, h, ration, stock_at_action=s0, declared=o.data.get("declaration"))
        await self.goto(t0 + T["fishing_close_day"])
        w.events.emit("phase", {"name": "fishing", "state": "close"})
        # --- veillée : on parle à tour de rôle, chacun entend ceux qui ont parlé avant lui (dialogues dépendants)
        ta = t0 + T["assembly_day"]
        await self.goto(ta)
        asms = w.open_assemblies(season, t0 + T["assembly_close_day"], "sync")
        if asms:
            w.events.emit("phase", {"name": "assembly", "state": "open"})
            for rnd in range(1, int(w.scn["assembly_rounds"]) + 1):
                hr = ta + (rnd - 1) * self.ROUND_STEP
                turns = [(asm, w.agents[aid]) for asm in asms for aid in asm.participants]
                step = self.ROUND_STEP / (len(turns) + 1)
                for k, (asm, a) in enumerate(turns):
                    h = hr + k * step                          # l'horloge avance d'un tour à l'autre : la parole précédente est entendue
                    await self.goto(h)
                    if w.has_reason_to_speak(a, asm, rnd):
                        w.post_utterance(a, asm, await w.ctl.guard(speak(w, a, asm, rnd, h)), rnd, h)
            await w.ctl.guard(w.ballots(asms))               # le bulletin de ceux qui n'ont rien soutenu
            await self.goto(t0 + T["assembly_close_day"])
            for asm in asms:
                w.close_assembly(asm)
            w.events.emit("phase", {"name": "assembly", "state": "close"})
        # --- repeuplement et bilan
        await self.goto(t0 + T["regrowth_day"])
        w.events.emit("phase", {"name": "regrowth", "state": "open"})
        w.end_season(season)
        await w.ctl.guard(w.narrate(season))


# ======================================================================== mode asynchrone
class AsyncRunner:
    TICK = 0.02

    def __init__(self, w: World):
        self.w = w
        self.c = w.clock
        self.heap: list = []
        self.seq = itertools.count()
        self.tasks: set[asyncio.Task] = set()
        self.by_kind: dict[str, dict[str, asyncio.Task]] = {"fish": {}, "talk": {}, "vote": {}}     # tâches par agent, pour les annuler
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
                waiting = 0
                while self.heap and self.heap[0][0] <= self.c.now() + 1e-9:
                    waiting = self.waiting_for(self.heap[0][2])
                    if waiting:                    # une fenêtre se ferme : on attend ceux qui réfléchissent encore
                        break
                    _, _, fn, args = heapq.heappop(self.heap)
                    fn(*args)
                self.show_waiting(waiting)
                for _ in range(3):                # laisse les tâches réveillées avancer jusqu'à leur appel LLM
                    await asyncio.sleep(0)
                if self.done and not self.tasks:
                    break
                if not self.heap and not self.tasks:
                    break
                now_wall = time.monotonic()
                dt, last = now_wall - last, now_wall
                if self.done or waiting:           # calendrier terminé, ou fenêtre retenue : le monde n'avance pas
                    await asyncio.sleep(self.TICK)
                    continue
                # tant qu'un agent réfléchit (recherche dans sa mémoire comprise, avant même son appel LLM), le temps simulé
                # suit le temps réel ; sinon personne n'est désavantagé et il peut accélérer jusqu'à la prochaine échéance
                busy = self.c.in_flight > 0 or bool(self.thinking)
                self.c.advance_wall(dt, self.heap[0][0] if self.heap else None, busy=busy)
                await asyncio.sleep(self.TICK)
        finally:
            for t in list(self.tasks):
                t.cancel()
            if self.tasks:
                await asyncio.gather(*self.tasks, return_exceptions=True)

    def waiting_for(self, fn) -> int:
        """Combien d'IA réfléchissent encore à la fermeture que `fn` déclencherait (0 : rien à attendre). Avec
        `time.wait_for_ai`, le monde les attend, temps suspendu, plutôt que de leur faire rater leur tour : la partie
        ralentit avec une IA lente, mais aucune sortie, réplique ni bulletin n'est perdu."""
        if not self.w.T.get("wait_for_ai", True):
            return 0
        if fn == self.fishing_close:
            return sum(1 for kind, _ in self.thinking if kind == "fish")
        if fn == self.assembly_close:
            return sum(1 for kind, _ in self.thinking if kind == "talk") + \
                sum(1 for t in self.by_kind["vote"].values() if not t.done())
        return 0

    def show_waiting(self, n: int):
        """Dit au joueur (état du moteur) que le monde attend des IA, et combien ; à chaque changement seulement."""
        note = f"le monde attend {n} IA qui réfléchi{'ssent' if n > 1 else 't'} encore" if n else None
        if note != self.w.waiting_note:
            self.w.waiting_note = note
            self.w.publish_status()

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
        self.at(t0 + T["assembly_close_day"] - float(T.get("ballot_lead_days", 0.25)), self.assembly_vote)
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
        w.apply_catch(a, o.value, o.decision, h, declared=o.data.get("declaration"))

    def assembly_open(self, season: int, close_t: float):
        asms = self.w.open_assemblies(season, close_t, "async")
        if not asms:
            return
        self.w.events.emit("phase", {"name": "assembly", "state": "open"})
        for asm in asms:
            for aid in asm.participants:
                self.thinking[("talk", aid)] = 1
                self.spawn(self.talk(self.w.agents[aid], asm), "talk", aid)

    async def talk(self, a: Agent, asm: Assembly):
        """Asynchrone : chacun s'exprime une fois, à son rythme, sans entendre les autres (dialogues indépendants) ; tous votent
        ensuite sur ce qui a été déposé (voir `assembly_vote`)."""
        w = self.w
        h = self.c.now()
        self.thinking[("talk", a.id)] = 1
        try:
            if asm.closed:
                return
            o = await speak(w, a, asm, 1, h)
        finally:
            self.thinking.pop(("talk", a.id), None)
        if asm.closed or self.c.now() > asm.close_t:
            w.incident(a.id, "missed_window", "parole prête après la fin de la veillée", "réplique perdue")
            return
        asm.held[a.id] = (o, h)
        self.release(asm)

    def release(self, asm: Assembly, force: bool = False):
        """Les paroles étant indépendantes, personne n'a entendu personne : on les dépose toutes ensemble, quand la dernière est prête
        (ou à la clôture), dans l'ordre du conseil, et non l'une après l'autre au gré de la vitesse de chaque IA."""
        if not force and any(k == "talk" and aid in asm.participants for k, aid in self.thinking):
            return
        for aid in [x for x in asm.participants if x in asm.held]:
            o, h = asm.held.pop(aid)
            self.w.post_utterance(self.w.agents[aid], asm, o, 1, h)

    def assembly_vote(self):
        """Quelques heures avant la fin de la veillée, chaque pêcheur qui n'a rien soutenu remplit son bulletin. Une IA trop lente
        perd sa voix, comme elle perd sa réplique : à la clôture, on compte alors ce qu'elle avait dit."""
        for asm in self.w.assemblies:
            for a in self.w.ballot_candidates(asm):
                self.spawn(ballot(self.w, a, asm), "vote", a.id)

    def assembly_close(self):
        if not self.w.assemblies:
            return
        for task in list(self.by_kind["vote"].values()):
            if not task.done():
                task.cancel()                            # un bulletin pas rempli à temps est abandonné, sans incident
        self.expire("talk", "réplique perdue",
                    "parole du tour {rnd} pas prête à la fin de la veillée : l'IA réfléchissait encore")
        for asm in self.w.assemblies:
            self.release(asm, force=True)
            self.w.close_assembly(asm)
        self.w.events.emit("phase", {"name": "assembly", "state": "close"})
        self.w.assemblies = []

    def regrowth(self, season: int):
        w = self.w
        w.events.emit("phase", {"name": "regrowth", "state": "open"})
        w.end_season(season)
        self.spawn(w.narrate(season))      # la saison attend le récit avant de finir (voir `season`)
        self.done = True        # la saison est jouée ; `World.run` choisit l'orchestration de la suivante
