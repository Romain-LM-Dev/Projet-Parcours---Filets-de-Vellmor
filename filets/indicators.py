"""Indicateurs calculés à partir des seuls événements (B2, B3, C6, C7, E4, F6).

Le moteur d'indicateurs ne lit que le flux d'événements : il tourne à l'identique dans le
service Kafka, en processus (bus local) et pendant un rejeu, ce qui garantit que le rejeu
reproduit les mêmes valeurs (E3).

Contexte commun observable pour FILETS (B1). Une *norme de prélèvement partagée* existe
pendant la saison s si :
  1. un quota a été adopté à une veillée (accord déclaré, `norm_agreement` = part de tous
     les pêcheurs qui ont soutenu la règle qui les concerne : hameau d'abord, vallée sinon) ;
  2. les prises de la saison le respectent (`norm_compliance` = part des pêcheurs soumis à
     une règle dont la prise est ≤ quota + tolérance).
Les effectifs derrière ces parts (`norm_supporters`, `norm_compliers`, `norm_concerned`,
`fishers`) sont publiés avec elles : chaque pourcentage se vérifie à la main.
`norm_index = norm_agreement × norm_compliance` ∈ [0, 1]. Sans accord déclaré, il vaut 0
même si tout le monde pêche par hasard la même quantité : cette « coordination sans norme »
se lit séparément dans `catch_cv` (dispersion des prises). C'est ce qui distingue une
norme d'une coïncidence (O6).
"""
from __future__ import annotations

import statistics
from collections import defaultdict


def gini(values: list[float]) -> float:
    v = sorted(max(0.0, x) for x in values)
    n, s = len(v), sum(v)
    if n == 0 or s == 0:
        return 0.0
    cum = sum((i + 1) * x for i, x in enumerate(v))
    return round((2 * cum) / (n * s) - (n + 1) / n, 4)


class IndicatorEngine:
    def __init__(self, quota_tolerance: float = 0.5):
        self.tol = quota_tolerance
        self.reset()

    def reset(self):
        self.run_id = None
        self.skipped = 0          # événements ignorés faute de `run_start` correspondant
        self.capacity = 1.0
        self.msy = 0.0
        self.fishers: dict[str, dict] = {}
        self.stock = 0.0
        self.season = 0
        self.catches: dict[int, dict[str, float]] = defaultdict(dict)
        self.catch_ids: dict[int, list[str]] = defaultdict(list)
        self.norms: list[dict] = []                 # historique des normes adoptées
        self.promise_outcomes: list[dict] = []
        self.incidents: dict[str, int] = defaultdict(int)
        self.llm = {"calls": 0, "tokens": 0, "latency_s": 0.0, "errors": 0, "cancelled": 0}
        self.events_by_id: dict[str, dict] = {}
        self.temporal_violations = 0
        self.staleness: list[float] = []
        self.utterances = 0
        self.accusations = 0
        self.history: list[dict] = []
        self.last_values: dict = {}
        self.collapsed = False

    # ------------------------------------------------------------------ ingestion
    def ingest(self, ev: dict) -> dict | None:
        """Consomme un événement ; renvoie un indicateur à publier, ou None.

        Tout se rapporte au `run_start` du run en cours (capacité du lac, liste des pêcheurs). Un événement
        qui arrive sans lui, ou d'un autre run, est ignoré : mieux vaut ne rien publier que des chiffres
        calculés sans contexte (stock en « % » d'une capacité inconnue, 0 pêcheur…).
        """
        t = ev["type"]
        p = ev["payload"]
        if t == "indicator":
            return None
        if t == "run_start":
            self.reset()
            self.run_id = ev["run_id"]
            self.capacity = p["lake"]["capacity"]
            self.msy = p["lake"]["sustainable_yield"]
            self.stock = p["lake"]["stock"]
            self.fishers = {a["id"]: dict(a) for a in p["agents"] if a.get("role") == "pecheur"}
        elif self.run_id is None or ev.get("run_id") != self.run_id:
            self.skipped += 1
            return None
        self.events_by_id[ev["event_id"]] = {"sim_time": ev["sim_time"], "type": t}
        if t == "season_start":
            self.season = ev["season"]
        elif t == "lake_update":
            self.stock = p["stock"]
            if p["cause"] in ("catch", "injection"):
                return self.snapshot(ev, "lake", [ev["event_id"]])
        elif t == "lake_collapsed":
            self.collapsed = True
        elif t == "catch":
            s = ev["season"]
            self.catches[s][p["agent"]] = self.catches[s].get(p["agent"], 0.0) + p["landed"]
            self.catch_ids[s].append(ev["event_id"])
            # obsolescence : ce qui a changé dans le lac entre l'observation et l'action (C5, C7)
            self.staleness.append(abs(p["stock_at_action"] - p["stock_at_horizon"]) / max(1e-9, self.capacity))
        elif t == "sale":
            if p["agent"] in self.fishers:
                self.fishers[p["agent"]]["wealth"] = p["wealth"]      # l'inégalité suit les ventes, pas seulement les bilans
        elif t == "decision":
            h = p["info_horizon"]
            if ev["sim_time"] + 1e-6 < h:
                self.temporal_violations += 1
            for uid in p["used_event_ids"]:
                src = self.events_by_id.get(uid)
                if src is not None and src["sim_time"] > h + 1e-6:
                    self.temporal_violations += 1
        elif t == "utterance":
            self.utterances += 1
            for uid in p["heard"]:
                src = self.events_by_id.get(uid)
                if src is not None and src["sim_time"] > p["info_horizon"] + 1e-6:
                    self.temporal_violations += 1
        elif t == "accusation":
            self.accusations += 1
        elif t == "norm_adopted":
            self.norms.append({**p, "event_id": ev["event_id"]})
            return self.snapshot(ev, "norm", [ev["event_id"]])
        elif t == "promise_outcome":
            self.promise_outcomes.append({**p, "event_id": ev["event_id"]})
        elif t == "incident":
            self.incidents[p["incident_type"]] += 1
            if p["incident_type"] == "temporal_violation":
                self.temporal_violations += 1
        elif t == "llm_call":
            self.llm["calls"] += 1
            self.llm["tokens"] += p["prompt_tokens"] + p["completion_tokens"]
            self.llm["latency_s"] += p["latency_s"]
            if p["status"] == "cancelled":
                self.llm["cancelled"] += 1             # réponse devenue inutile : du travail perdu, pas une erreur du modèle
            else:
                self.llm["errors"] += p["status"] != "ok"
        elif t == "season_end":
            return self.season_snapshot(ev)
        elif t == "run_end":
            return self.snapshot(ev, "run_end", [])
        return None

    # ------------------------------------------------------------------ calculs
    def _quota_for(self, fisher: str, season: int) -> tuple[float, dict] | None:
        hamlet = self.fishers.get(fisher, {}).get("hamlet")
        for scope in (f"hamlet:{hamlet}", "valley"):
            c = [n for n in self.norms if n["scope"] == scope and n["effective_season"] <= season]
            if c:
                return c[-1]["quota"], c[-1]
        return None

    def season_values(self, season: int) -> tuple[dict, list[str]]:
        catches = {f: self.catches[season].get(f, 0.0) for f in self.fishers}
        vals = list(catches.values())
        mean = statistics.mean(vals) if vals else 0.0
        cv = statistics.pstdev(vals) / mean if mean > 0 else 0.0
        sources = list(self.catch_ids[season])
        concerned, agree, comply = 0, 0, 0
        for f, c in catches.items():
            q = self._quota_for(f, season)
            if q is None:
                continue
            quota, norm = q
            concerned += 1
            agree += f in norm["supporters"]
            comply += c <= quota + self.tol
            if norm["event_id"] not in sources:
                sources.append(norm["event_id"])
        n = len(catches) or 1
        agreement = agree / n                       # part de TOUS les pêcheurs qui ont soutenu la règle qui les concerne
        compliance = comply / concerned if concerned else 0.0   # part des pêcheurs soumis à une règle qui la respectent
        outcomes = [o for o in self.promise_outcomes if o["season"] == season]
        sources += [o["event_id"] for o in outcomes]
        kept = [o for o in outcomes if o["kept"]]
        gap = statistics.mean(o["landed"] - o["promised"] for o in outcomes) if outcomes else 0.0
        values = {
            "season": season,
            "total_catch": round(sum(vals), 3),
            "msy": round(self.msy, 3),
            "catch_cv": round(cv, 4),
            "norm_agreement": round(agreement, 4),
            "norm_compliance": round(compliance, 4),
            "norm_index": round(agreement * compliance, 4),
            # les effectifs derrière les parts, pour pouvoir vérifier les chiffres à la main
            "fishers": len(catches),
            "norm_concerned": concerned,
            "norm_supporters": agree,
            "norm_compliers": comply,
            "promises": len(outcomes),
            "promises_kept": len(kept),
            "promise_kept_rate": round(len(kept) / len(outcomes), 4) if outcomes else None,
            "promise_gap_t": round(gap, 3),
        }
        return values, sources

    def snapshot(self, ev: dict, trigger: str, sources: list[str], extra: dict | None = None) -> dict:
        wealth = [f.get("wealth", 0) for f in self.fishers.values()]
        values = {
            "stock": round(self.stock, 3),
            "capacity": self.capacity,
            "stock_ratio": round(self.stock / self.capacity, 4) if self.capacity else 0.0,
            "collapsed": self.collapsed,
            "norms": {n["scope"]: n["quota"] for n in self.norms},
            "utterances": self.utterances,
            "accusations": self.accusations,
            "incidents": dict(self.incidents),
            "incidents_total": sum(self.incidents.values()),
            "temporal_violations": self.temporal_violations,
            "mean_staleness_ratio": round(statistics.mean(self.staleness), 4) if self.staleness else 0.0,
            "llm_calls": self.llm["calls"],
            "llm_tokens": self.llm["tokens"],
            "llm_latency_s": round(self.llm["latency_s"], 2),
            "llm_errors": self.llm["errors"],
            "llm_cancelled": self.llm["cancelled"],
            "wealth_gini": gini(wealth),
        }
        if extra:
            values.update(extra)
        out = {"trigger": trigger, "values": values, "source_event_ids": sources,
               "source_event_id": ev["event_id"], "sim_time": ev["sim_time"], "sim_label": ev["sim_label"],
               "season": ev["season"], "run_id": ev["run_id"], "source_processed_at": ev["processed_at"]}
        self.last_values = values
        return out

    def season_snapshot(self, ev: dict) -> dict:
        for f, w in ev["payload"]["wealth"].items():
            if f in self.fishers:
                self.fishers[f]["wealth"] = w
        self.stock = ev["payload"]["stock"]
        values, sources = self.season_values(ev["season"])
        out = self.snapshot(ev, "season_end", sources + [ev["event_id"]], values)
        self.history.append(out["values"])
        return out
