"""Le monde de FILETS et ses deux orchestrations du temps (C3, C4).

Calendrier d'une saison (jours simulés depuis le début de la saison, configurable) :

    J0 06:00   ouverture de la pêche : chaque pêcheur décide de sa prise
    J20        fermeture : une sortie décidée après est perdue (incident `missed_window`)
    J25 18:00  veillée chez l'ancien (selon le mode de communication) : tours de parole,
               propositions de quota, soutiens, promesses, accusations
    J29        fin de la veillée : adoption d'une règle si au moins la moitié des pêcheurs présents la soutient
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

from . import prompts
from .agents import Agent, _ask_llm, ballot, decide_catch, speak
from .policies import sanction_vote
from .clock import SimClock
from .config import ROOT, sustainable_yield
from .control import MODES, GameControl, StopRun
from .events import EventFactory, Recorder
from .lake import Lake
from .memory import MemoryBank, MemoryStore, VectorMemory
from .objects import archive_run, make_objects
from .profiles import HAMLETS, build_population
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

# Le lac a cinq zones : la rive de chaque hameau, où ses pêcheurs vont d'ordinaire, et le large.
ZONES = [*HAMLETS, "large"]
# Les indices et ce qu'ils pèsent dans le jugement de l'ancien (voir `World.weigh_evidence` et `scenario.detection`).
DETECTION = {"radar": 0.95, "radar_error": 0.1, "witness": 0.4, "witness_error": 0.3, "seen_leaving": 0.3, "lifestyle": 0.5,
             "lake_error": 0.03, "margin_t": 0.3, "margin_ratio": 0.25, "proof": 2.0}
EVIDENCE = {"radar": 3.0, "temoin": 1.0, "depart": 1.0, "train_de_vie": 0.5, "comptes": 0.5}
HOW = {"radar": "le radar de l'ancien a mesuré sa barque", "temoins": "des voisins l'ont vu",
       "indices": "les indices concordaient"}


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
    """Une proposition d'interdire un pêcheur de pêche (`exclure`), ou de lever son interdiction (`reautoriser`)."""
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
    sanctions: dict[str, Sanction] = field(default_factory=dict)        # propositions d'exclure ou de réautoriser
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
        for i, p in enumerate(build_population(cfg, self.rng)):
            arng = random.Random(seed * 1000 + i)
            self.agents[p.id] = Agent(p, memory_of(p.id), arng, p.wealth, offset_days=round(arng.uniform(lo, hi), 3))
        self.fishers = [a for a in self.agents.values() if a.is_fisher]
        self.elder = next((a for a in self.agents.values() if not a.is_fisher), None)
        # une sortie rapporte au plus la capacité du lac divisée par deux fois le nombre de pêcheurs (et jamais plus que la
        # barque) : à eux tous, ils ne peuvent prendre que la moitié du lac en une saison ; et au moins la prise minimale
        self.max_catch = min(self.econ["boat_capacity"], self.capacity / (2 * max(1, len(self.fishers))))
        self.min_catch = min(self.econ.get("min_catch", 0.0), self.max_catch)
        values = {"capacity": f"{self.capacity:.0f}", "half_capacity": f"{self.capacity / 2:.0f}",
                  "n_fishers": len(self.fishers), "price": self.econ["price_per_tonne"],
                  "upkeep": self.econ["upkeep_per_season"]}
        if self.vectors is not None:
            self.retriever = VectorRetriever(ROOT / cfg["rag"]["corpus_dir"], values, self.vectors, self.vectors.embedder,
                                             self.objects, float(cfg["rag"].get("min_score", 0.0)))
        else:
            self.retriever = Retriever(ROOT / cfg["rag"]["corpus_dir"], values)
        self.router = LLMRouter(cfg, self.clock, self.events, seed, self.ctl)
        self.norms: list[Norm] = []          # historique complet, dans l'ordre d'adoption
        self.promises: dict[tuple[str, int], tuple[float, str]] = {}
        self.promise_memories: dict[tuple[str, int], object] = {}   # promesse épinglée en cours
        # ce que chacun a déclaré à l'ancien (événements `report`, par (agent, saison)) : le seul chiffre que les autres
        # connaissent ; et les déclarations mensongères, par événement `report` ({agent, season, declared, landed, found_t})
        self.reports: dict[tuple[str, int], dict] = {}
        self.lies: dict[str, dict] = {}
        self.trust = {o: {s.id: TRUST_START for s in self.fishers if s.id != o} for o in self.agents}
        # la détection : sorties de chaque saison ({agent, zone, landed, secret, radar, event_id}), indices (payload de `clue`
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
        self.radar_zone: str | None = None       # où le radar de la vallée surveille le lac, et qui l'y a mis
        self.radar_by = "ancien"
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
        """`observer` revoit sa confiance envers les pêcheurs de `changes` (identifiant -> de −3 à +3, en dixièmes) : c'est son
        jugement, selon sa morale et ses intérêts, et le moteur n'y ajoute rien. Une valeur illisible, hors des pêcheurs ou sur
        soi-même est ignorée. Un événement `trust` par personne dont la confiance change."""
        if not isinstance(changes, dict):
            return
        row = self.trust[observer.id]
        for sid, raw in changes.items():
            sid, steps = str(sid).strip().upper(), to_number(raw)
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

    # ------------------------------------------------------------ indices, jugement, interdiction, radar
    def beyond_declared(self, estimate: float, said: float) -> bool:
        """L'estimation dépasse-t-elle nettement la déclaration : de plus de 25 % de celle-ci (au-delà de l'erreur du radar,
        ±10 %) et d'au moins 0,3 t ? Un plancher de 1 t laissait passer un mensonge flagrant sur une petite prise (le radar
        mesurait 1,9 t pour 1 t déclarée)."""
        det = self.detection
        return estimate - said > max(det["margin_t"], det["margin_ratio"] * said)

    def investigate(self, season: int):
        """Le soir de la veillée, les indices de la saison sont réunis. Le radar a relevé les barques de sa zone (l'ancien le dit
        à tous) ; un voisin qui pêchait dans la même zone a pu voir une barque rentrer et en estimer la charge ; la barque d'un
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

        def clue(kind: str, observer: str | None, trip: dict, estimate: float | None = None):
            subject = self.agents[trip["agent"]]
            public = observer is None or observer == elder or \
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
            if t["radar"] and rng.random() < det["radar"]:
                clue("radar", elder, t, noisy(t["landed"], det["radar_error"]))
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
                need = (self.econ["upkeep_per_season"] + a.profile.debt_payment) / self.econ["price_per_tonne"]
                if a.declared.get(season, t["landed"]) < need <= a.catches.get(season, 0.0):
                    for o in neighbours:
                        if rng.random() < det["lifestyle"]:
                            clue("train_de_vie", o.id, t)
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
        mensonge est établi quand ils pèsent `proof` (radar 3, témoin 1, départ vu 1, train de vie 0,5, comptes 0,5 s'ils ne
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
        how = "radar" if "radar" in kinds else ("temoins" if kinds & {"temoin", "depart"} else "indices")
        witnesses = sorted({c["observer"] for c in clues if c["observer"] and c["kind"] != "radar"})
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

    def place_radar(self, zone: str, by: str):
        self.radar_zone, self.radar_by = zone, by
        self.events.emit("radar_placed", {"zone": zone, "by": by})

    def move_radar(self):
        """Pour la saison suivante, l'ancien (ou la vallée, sans ancien) place le radar en secret là où il se méfie le plus : la
        rive du hameau dont il croit le moins les pêcheurs, ou le large s'il y a des interdits (c'est là qu'on pêche en
        cachette). Une fois sur quatre, ailleurs au hasard, pour que personne ne puisse compter dessus. Le joueur qui l'a placé
        lui-même garde la main jusqu'à ce qu'il la rende (« auto »)."""
        if self.radar_by == "joueur":
            return
        judge = self.elder.id if self.elder else None

        def distrust(aid: str) -> float:
            return 1.0 - (self.trust[judge].get(aid, TRUST_START) if judge else self.reputation(aid))

        score = {h: sum(distrust(a.id) for a in self.fishers if a.profile.hamlet == h and a.id not in self.banned)
                 for h in HAMLETS}
        score["large"] = 0.3 + sum(distrust(aid) for aid in self.banned)     # un hameau très suspect peut l'emporter
        rng = self.lie_rng
        zone = rng.choice(ZONES) if rng.random() < 0.25 else max(ZONES, key=lambda z: (score[z], z))
        self.place_radar(zone, "ancien" if judge else "vallee")

    def secret_zone(self, agent: Agent) -> str:
        """Où un interdit va pêcher en cachette : loin de sa rive (ses voisins le connaissent), plutôt au large."""
        others = [z for z in ZONES if z != agent.profile.hamlet]
        weights = [2.0 if z == "large" else 1.0 for z in others]
        return self.lie_rng.choices(others, weights)[0]

    def clue_text(self, c: dict, viewer: str | None = None) -> str:
        """Un indice en mots, du point de vue de `viewer` (« ta barque » s'il en est le sujet)."""
        mine = c["subject"] == viewer
        boat = "ta barque" if mine else f"la barque de {self.first_name(c['subject'])}"
        said = "" if c["declared"] is None else \
            (f" (tu as déclaré {c['declared']:g} t)" if mine else f" ({self.first_name(c['subject'])} a déclaré {c['declared']:g} t)")
        if c["kind"] == "radar":
            return f"le radar de l'ancien a mesuré environ {c['estimate']:g} t dans {boat}{said}"
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
            if c["kind"] == "radar":
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
            f["testified"] = any(c["observer"] == a.id and c["public"] and c["season"] == season and c["t"] <= horizon
                                 for c in self.clues)
            since_ban = self.banned.get(a.id)
            f["stayed_away"] = since_ban is not None and since_ban <= season and found is None and \
                not any(c["subject"] == a.id and c["public"] and c["season"] == season for c in self.clues)
            if not any(v for v in f.values() if v is not None) and f.get("over") is None:
                del out[a.id]
        return out

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
        trust = sorted(self.trust[agent.id].items(), key=lambda kv: kv[1])
        exposed = any(aid == agent.id and f["t"] <= horizon and s >= season - 2 for (aid, s), f in self.established.items())
        banned = agent.id in self.banned
        clues = self.clue_lines(agent, horizon, season)
        wealth, stock_true = agent.wealth, round(self.lake.stock, 3)
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
            "n_fishers": len(self.fishers), "_entry": entry,
            "wealth": wealth, "upkeep": self.econ["upkeep_per_season"], "debt_payment": p.debt_payment,
            "price": self.econ["price_per_tonne"], "boat_capacity": self.max_catch,
            # un interdit ne sort qu'en cachette, ou reste à quai (0 t)
            "min_catch": 0.0 if banned else self.min_catch, "carnet": carnet, "norms": norm_lines,
            "known_catches": catches_txt, "clues": clues, "banned": banned,
            "banned_others": [self.first_name(b) for b in self.banned if b != agent.id],
            "trust": [(self.first_name(s), v) for s, v in trust],
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
            "quota": norm.quota if norm else None, "boat_capacity": self.max_catch,      # limite d'une sortie
            "min_catch": 0.0 if banned else self.min_catch, "banned": banned,
            "upkeep": self.econ["upkeep_per_season"], "debt_payment": p.debt_payment,
            "price": self.econ["price_per_tonne"], "wealth": wealth,
            "growth_rate": self.lake.r, "round": rnd,
            "rumors": obs["rumors"], "rumor_targets": self.named_fishers(obs["rumors"]) if rumors else [],
            "self_id": agent.id, "names": {a.id: (a.profile.first_name or a.profile.name.split()[0]) for a in self.fishers},
            "exposed": exposed, "trust": dict(self.trust[agent.id]),     # un mensonge à lui découvert depuis peu ; sa confiance
        }
        if assembly:
            visible_u = [u for u in assembly.utterances if u["sim_time"] <= horizon]
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
            props = [pr for pr in assembly.proposals.values() if pr.t <= horizon]
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
            obs["sanctions"] = [
                f"{s.id} : {'interdire de pêche' if s.action == 'exclure' else 'laisser pêcher à nouveau'} "
                f"{self.name(s.target)} ({s.target}), proposé par {self.name(s.author)} ; pour : "
                f"{', '.join(a for a, v in s.votes.items() if v) or 'personne'}"
                for s in assembly.sanctions.values() if s.t <= horizon]
            obs["promises"] = self.promise_lines(agent, season, horizon)
            mine = [u for u in visible_u if u["payload"]["speaker"] == agent.id]
            state["facts"] = self.trust_facts(agent, season, horizon,
                                              mine[-1]["payload"]["info_horizon"] if mine else None)
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
        landed = round(self.lake.take(requested * ration), 3)
        ev = self.events.emit("catch", {
            "agent": agent.id, "hamlet": agent.profile.hamlet, "requested": requested, "landed": landed,
            "stock_observed": stock_observed, "stock_before": round(before, 3), "stock_after": round(self.lake.stock, 3),
            "decision_event_id": decision["event_id"], "info_horizon": round(horizon, 6), "rationed": ration < 1.0,
            "stock_at_horizon": obs["stock_true"],
            "stock_at_action": round(before if stock_at_action is None else stock_at_action, 3),
            "zone": zone, "secret": secret,
        }, actor=agent.id)
        # la sortie : où, combien, et si le radar surveillait cette zone à ce moment-là (lu le soir de la veillée)
        self.trips.setdefault(season, []).append({"agent": agent.id, "zone": zone, "landed": landed, "secret": secret,
                                                  "radar": zone == self.radar_zone, "event_id": ev["event_id"]})
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
        note = f"J'ai pêché {landed:g} t cette saison ; le lac m'a semblé contenir environ {stock_observed:.0f} t."
        if landed + 1e-6 < requested * ration or ration < 1:
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
        elif ctype == "place_radar":
            # le joueur place le radar où il veut (il en garde la main) ; « auto » la rend à l'ancien, qui le déplacera
            if cmd.get("value") in ZONES:
                self.place_radar(cmd["value"], "joueur")
            elif cmd.get("value") == "auto":
                self.radar_by = "ancien"
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
    def open_assemblies(self, season: int, close_t: float) -> list[Assembly]:
        # le soir de la veillée (qu'elle se tienne ou non) : les indices de la saison réunis, et ce qu'ils établissent, relaté
        # par l'ancien ; ce que chacun en pense, et ce que la vallée en décide, se dira à la veillée
        self.investigate(season)
        self.weigh_evidence(season)
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
        lo, hi = self.min_catch, self.max_catch      # proposer ou promettre hors de ce qu'une sortie rapporte, c'en est la borne
        if q is not None and 0 <= q <= self.econ["boat_capacity"]:
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
            if pv is not None and 0 <= pv <= self.econ["boat_capacity"]:
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
        acc = d.get("accuse")
        if isinstance(acc, str) and acc.strip().upper() in self.agents and acc.strip().upper() != agent.id:
            accused = self.agents[acc.strip().upper()]
            if accused.is_fisher:
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
        tid = str(raw).strip().upper()
        target = self.agents.get(tid)
        if target is None or not target.is_fisher or tid == agent.id or (action == "exclure") == (tid in self.banned):
            return
        same = next((s for s in asm.sanctions.values() if s.target == tid and s.action == action), None)
        if same is None:
            sid = f"X{next(self._xid)}"
            pe = self.events.emit("sanction_proposal", {"proposal_id": sid, "author": agent.id, "target": tid,
                                                        "action": action, "scope": asm.scope, "utterance_id": u["event_id"]},
                                  actor=agent.id)
            same = asm.sanctions[sid] = Sanction(sid, agent.id, tid, action, self.clock.now(), pe["event_id"])
            if tid in asm.participants and action == "exclure":
                self.remember(target, f"{agent.profile.name} a proposé devant tous de m'interdire de pêche.", "sanction",
                              0.95, pinned=True, expires_season=asm.season + 1, source_event_id=pe["event_id"])
        self.vote_sanction(agent, same, True)

    def vote_sanction(self, agent: Agent, s: Sanction, yes: bool):
        if agent.id == s.target or agent.id in s.votes or not agent.is_fisher:
            return
        s.votes[agent.id] = yes
        self.events.emit("sanction_vote", {"proposal_id": s.id, "agent": agent.id, "vote": yes}, actor=agent.id)

    def policy_voter(self, agent: Agent) -> bool:
        """Vote-t-il selon son caractère (agent à règles, ou faux LLM, qui ne sait pas répondre à un bulletin) ?"""
        return agent.profile.kind == "rule" or self.cfg["llm"]["tiers"]["petit"]["provider"] == "scripted"

    def close_sanctions(self, asm: Assembly):
        """À la clôture, chaque proposition d'exclure ou de réautoriser est tranchée : les pêcheurs présents (sauf celui qu'elle
        vise) qui n'ont pas encore voté le font selon leur caractère s'ils votent ainsi ; adoptée avec au moins la moitié
        d'entre eux, elle prend effet dès la saison suivante. Les IA ont voté par leur bulletin, selon leur confiance, leur
        morale et leurs intérêts."""
        for s in asm.sanctions.values():
            voters = [a for a in asm.participants if self.agents[a].is_fisher and a != s.target]
            for aid in voters:
                a = self.agents[aid]
                if aid not in s.votes and self.policy_voter(a):
                    self.vote_sanction(a, s, sanction_vote(a.archetype, self.trust[aid][s.target], s.action))
            yes = sorted(a for a, v in s.votes.items() if v)
            adopted = bool(voters) and len(yes) * 2 >= len(voters)
            res = self.events.emit("sanction_result", {
                "proposal_id": s.id, "target": s.target, "action": s.action, "adopted": adopted, "for": yes,
                "against": sorted(a for a, v in s.votes.items() if not v), "voters": len(voters)}, actor=s.target)
            name = self.agents[s.target].profile.name
            what = "l'interdire de pêche" if s.action == "exclure" else "lui rendre le droit de pêcher"
            for aid in asm.participants:
                self.remember(self.agents[aid], f"À la veillée, la vallée a {'décidé' if adopted else 'refusé'} de {what} : "
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

    def sanction_brief(self, observer: Agent, target: str, season: int) -> str:
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
        return " ; ".join(bits) or "rien de particulier cette saison"

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
                    "supporters": sorted(sups), "participants": asm.participants, "author": pr.author})
                self.norms.append(Norm(asm.scope, pr.quota, asm.season + 1, pid, self.clock.now(),
                                       ne["event_id"], sorted(sups)))
                adopted = pid
                for aid in asm.participants:
                    self.remember(self.agents[aid], f"Règle adoptée chez l'ancien ({asm.label}) : pas plus de "
                                                    f"{pr.quota:g} t par pêcheur à partir de la saison {asm.season + 1}, "
                                                    f"soutenue par {len(sups)} pêcheurs sur {len(fishers_present)}.",
                                  "regle", 0.9, source_event_id=ne["event_id"])
        self.close_sanctions(asm)
        self.events.emit("assembly_end", {"scope": asm.scope, "adopted_proposal": adopted,
                                          "utterances": len(asm.utterances)})

    # ------------------------------------------------------------ fin de saison
    def end_season(self, season: int):
        # la veillée finie, l'ancien pèse les indices et les accusations (sans veillée, il le fait seul)
        self.investigate(season)
        self.weigh_evidence(season)
        delta = self.lake.regrow()
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
            a.wealth -= self.econ["upkeep_per_season"] + a.profile.debt_payment
            self.remember(a, f"Bilan de la saison {season} : {landed:g} t pêchées, il me reste {a.wealth:.0f} écus.",
                          "bilan", 0.5)
        self.move_radar()
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
            each = ", ".join(f"{self.first_name(a)} {v:g} t" for a, v in sorted(said.items(), key=lambda kv: -kv[1]))
            facts.append(f"Prises déclarées à l'ancien : {each} (en tout {sum(said.values()):g} t).")
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
        for r in of("sanction_result"):          # ce que la vallée a voté : exclure ou réautoriser
            what = "d'interdire de pêche" if r["action"] == "exclure" else "de laisser pêcher à nouveau"
            facts.append(f"La vallée a {'voté' if r['adopted'] else 'refusé'} {what} {self.first_name(r['target'])} "
                         f"({len(r['for'])} voix sur {r['voters']}).")
        if self.banned:
            facts.append("Interdits de pêche : " + both([self.first_name(b) for b in self.banned]) + ".")
        start = next((p["stock"] for p in of("season_start")), None)
        level = prompts.lake_level(self.lake.stock, self.capacity, self.lake.collapse_ratio)
        facts.append((f"Le lac : {start:.0f} t au début de la saison, " if start is not None else "Le lac : ")
                     + f"{self.lake.stock:.0f} t après le repeuplement, sur {self.capacity:.0f} t possibles "
                       f"({100 * self.lake.stock / self.capacity:.0f} % : {level}).")
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
            facts.append(f"À la veillée, {what}{whose} : pas plus de {n['quota']:g} t par pêcheur{instead} à partir de la "
                         f"saison {n['effective_season']}, soutenue par {len(n['supporters'])} pêcheurs sur {present}.")
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
                                          prompts.narration_messages(elder.profile, facts, self.capacity), {"round": 0},
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
            "hamlets": HAMLETS, "scenario": {"communication": self.comm, "catches_visible": self.visible,
                                             "assembly_rounds": self.scn["assembly_rounds"]},
            "season_days": self.T["season_days"], "config_hash": cfg_hash, "llm_tiers": self.router.describe(),
            "label": str(self.cfg["run"].get("label", "")),
            "population": {"fishers": len(self.fishers), "rule_fraction": self.cfg["population"]["rule_fraction"]},
        })
        self.lake_update("init", 0.0)
        # le radar de la vallée commence dans une zone au hasard ; l'ancien le déplacera à la fin de chaque saison
        self.place_radar(self.lie_rng.choice(ZONES), "ancien" if self.elder else "vallee")
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
        self.events.emit("season_start", {"stock": round(self.lake.stock, 3), "mode": mode})
        self.publish_status()
        self.scheduled_injections(season)

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
        # --- veillée : tours de parole simultanés
        ta = t0 + T["assembly_day"]
        await self.goto(ta)
        asms = w.open_assemblies(season, t0 + T["assembly_close_day"])
        if asms:
            w.events.emit("phase", {"name": "assembly", "state": "open"})
            for rnd in range(1, int(w.scn["assembly_rounds"]) + 1):
                hr = ta + (rnd - 1) * self.ROUND_STEP
                await self.goto(hr)
                jobs = [(asm, w.agents[aid]) for asm in asms for aid in asm.participants
                        if w.has_reason_to_speak(w.agents[aid], asm, rnd)]
                outs = await w.ctl.guard(asyncio.gather(*(speak(w, a, asm, rnd, hr) for asm, a in jobs)))
                await self.goto(hr + self.ROUND_STEP / 2)
                for (asm, a), o in zip(jobs, outs):
                    w.post_utterance(a, asm, o, rnd, hr)
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
        asms = self.w.open_assemblies(season, close_t)
        if not asms:
            return
        self.w.events.emit("phase", {"name": "assembly", "state": "open"})
        for asm in asms:
            for aid in asm.participants:
                self.spawn(self.talk(self.w.agents[aid], asm), "talk", aid)

    async def talk(self, a: Agent, asm: Assembly):
        w = self.w
        gap = float(w.T.get("assembly_turn_gap_days", 0.05))
        for rnd in range(1, int(w.scn["assembly_rounds"]) + 1):
            if asm.closed:
                return
            if not w.has_reason_to_speak(a, asm, rnd):        # rien de neuf pour lui : il écoute ce tour
                await self.sleep_until(self.c.now() + gap)
                continue
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
            await self.sleep_until(self.c.now() + gap)

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
            self.w.close_assembly(asm)
        self.w.events.emit("phase", {"name": "assembly", "state": "close"})
        self.w.assemblies = []

    def regrowth(self, season: int):
        w = self.w
        w.events.emit("phase", {"name": "regrowth", "state": "open"})
        w.end_season(season)
        self.spawn(w.narrate(season))      # la saison attend le récit avant de finir (voir `season`)
        self.done = True        # la saison est jouée ; `World.run` choisit l'orchestration de la suivante
