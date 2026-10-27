"""Le climat de la vallée : les saisons de l'année, et les événements qui changent la pêche ou le repeuplement du lac.

Chaque saison de jeu est une saison de l'année, dans l'ordre (la partie commence au printemps). Chacune porte deux facteurs :
`yield` (ce que rapporte la pêche) et `growth` (le taux de repeuplement du lac, appliqué en fin de saison). Un événement
aléatoire peut s'y ajouter (sécheresse, tempête, banc de poissons…) : il dure une ou deux saisons et change l'un ou l'autre,
parfois d'un coup le stock du lac. Tout est tiré d'un hasard à part (`seed`), pour ne pas déplacer les autres tirages du monde.

Les agents connaissent la saison de l'année et les événements en cours : on ne cache pas la météo au village.
"""
from __future__ import annotations

import random

CYCLE = [
    {"name": "printemps", "growth": 1.3, "yield": 1.0, "text": "le frai a commencé, le lac se repeuple bien"},
    {"name": "été", "growth": 1.1, "yield": 1.15, "text": "le poisson remonte, la pêche rend un peu plus"},
    {"name": "automne", "growth": 0.9, "yield": 1.0, "text": "les eaux fraîchissent"},
    {"name": "hiver", "growth": 0.7, "yield": 0.75, "text": "le froid ralentit les poissons et les filets : la pêche rend moins"},
]

# weight : fréquence relative ; duration : saisons (la sienne comprise) ; growth / yield : facteurs tant qu'il dure ;
# stock : choc unique sur le stock du lac à son arrivée ; boats : rendement propre à chaque taille de bateau (remplace `yield`)
EVENTS = {
    "secheresse": {"label": "sécheresse", "weight": 2, "duration": 2, "growth": 0.6, "yield": 1.0, "stock": 0.9,
                   "text": "les eaux sont basses, les frayères à sec : le lac se repeuple mal"},
    "tempete": {"label": "tempête", "weight": 2, "duration": 1, "growth": 1.0, "yield": 0.65,
                "boats": {"barque": 0.4, "chaloupe": 0.7, "cotre": 0.85},
                "text": "le lac est dur : les petites barques sortent à peine, la pêche rend bien moins"},
    "banc": {"label": "banc de poissons", "weight": 2, "duration": 1, "growth": 1.0, "yield": 1.35,
             "text": "un gros banc est remonté : la pêche rend beaucoup plus"},
    "algues": {"label": "algues", "weight": 1, "duration": 2, "growth": 0.5, "yield": 0.9,
               "text": "les algues étouffent le lac : il se repeuple deux fois moins vite"},
    "crue": {"label": "crue", "weight": 1, "duration": 1, "growth": 1.25, "yield": 0.85,
             "text": "l'eau monte et nourrit le lac, mais les filets se prennent dans le courant"},
    "maladie": {"label": "maladie des poissons", "weight": 1, "duration": 1, "growth": 1.0, "yield": 1.0, "stock": 0.8,
                "text": "une maladie a frappé les poissons : le lac a perdu un cinquième de son stock"},
}


# La météo de chaque jour de pêche, la même pour tout le lac : son effet (avant normalisation) et sa fréquence selon la saison de
# l'année. Un jour agité ou de tempête rapporte bien moins, surtout aux petites barques (`BAD_DAY_BOATS`).
DAYS = {"calme": 1.25, "ordinaire": 1.0, "agité": 0.6, "tempête": 0.15}
DAY_WEIGHTS = {
    "printemps": {"calme": 0.25, "ordinaire": 0.50, "agité": 0.20, "tempête": 0.05},
    "été": {"calme": 0.35, "ordinaire": 0.50, "agité": 0.13, "tempête": 0.02},
    "automne": {"calme": 0.20, "ordinaire": 0.45, "agité": 0.25, "tempête": 0.10},
    "hiver": {"calme": 0.10, "ordinaire": 0.35, "agité": 0.30, "tempête": 0.25},
}
STAY = 0.45                                         # chance que le temps d'hier se prolonge aujourd'hui
BAD_DAY_BOATS = {"barque": 1.4, "chaloupe": 1.0, "cotre": 0.7}      # combien un mauvais jour pèse sur chaque bateau


class Climate:
    """La saison de l'année et les événements en cours, d'une saison de jeu à l'autre."""

    def __init__(self, cfg: dict, seed: int):
        c = cfg.get("climate") or {}
        self.seed = seed
        self.enabled = bool(c.get("enabled", True))
        self.rate = float(c.get("event_rate", 0.3))
        self.off = set(c.get("disabled_events") or ())
        self.rng = random.Random(f"{seed}|climate")
        self.active: list[dict] = []          # {kind, until} : événements en cours
        self.cycle = CYCLE[0]
        self.growth = self.yield_ = 1.0
        self.new: str | None = None           # l'événement arrivé au début de cette saison

    def begin(self, season: int) -> dict:
        """Les conditions de la saison `season` : la saison de l'année, les événements (un nouveau a pu survenir)."""
        self.new = None
        if not self.enabled:
            return self.conditions()
        self.cycle = CYCLE[(season - 1) % len(CYCLE)]
        self.active = [e for e in self.active if e["until"] >= season]
        if season >= 2 and self.rng.random() < self.rate:
            free = [k for k in EVENTS if k not in self.off and all(e["kind"] != k for e in self.active)]
            if free:
                kind = self.rng.choices(free, [EVENTS[k]["weight"] for k in free])[0]
                self.active.append({"kind": kind, "until": season + EVENTS[kind]["duration"] - 1})
                self.new = kind
        self.growth = self.cycle["growth"]
        self.yield_ = self.cycle["yield"]
        for e in self.active:
            self.growth *= EVENTS[e["kind"]].get("growth", 1.0)
            self.yield_ *= EVENTS[e["kind"]].get("yield", 1.0)
        return self.conditions()

    def yield_for(self, boat: str) -> float:
        """Ce que rapporte la pêche à ce bateau cette saison : la saison de l'année, et les événements (un événement peut
        toucher les petites barques plus que les grosses)."""
        if not self.enabled:
            return 1.0
        out = self.cycle["yield"]
        for e in self.active:
            ev = EVENTS[e["kind"]]
            out *= ev.get("boats", {}).get(boat, ev.get("yield", 1.0))
        return out

    def calendar(self, season: int, n_days: int) -> list[str]:
        """La météo de chacun des `n_days` jours de pêche de la saison : le temps d'hier se prolonge (`STAY`), sinon il est tiré selon la
        saison de l'année. Tirée d'un hasard propre à la saison : la même pour tout le lac, quel que soit l'ordre des barques."""
        if not self.enabled:
            return ["ordinaire"] * n_days
        weights = DAY_WEIGHTS[CYCLE[(season - 1) % len(CYCLE)]["name"]]
        labels = list(weights)
        rng = random.Random(f"{self.seed}|days|{season}")
        today = rng.choices(labels, [weights[k] for k in labels])[0]
        out = []
        for _ in range(n_days):
            out.append(today)
            if rng.random() >= STAY:
                today = rng.choices(labels, [weights[k] for k in labels])[0]
        return out

    def day_factor(self, label: str, season: int, boat: str) -> float:
        """Ce que rapporte un jour de cette météo à ce bateau (en moyenne 1 sur la saison : l'effet de la saison de l'année est dans
        `yield_for`). Un mauvais jour pèse plus sur une barque que sur un cotre ; un bon jour profite à tous."""
        if not self.enabled:
            return 1.0
        weights = DAY_WEIGHTS[CYCLE[(season - 1) % len(CYCLE)]["name"]]
        f = DAYS[label] / sum(weights[k] * DAYS[k] for k in weights)
        bad = 1.0 - f
        return f if bad <= 0 else max(0.0, 1.0 - bad * BAD_DAY_BOATS.get(boat, 1.0))

    def conditions(self) -> dict:
        return {"enabled": self.enabled, "climate": self.cycle["name"] if self.enabled else None,
                "growth": round(self.growth, 3), "yield": round(self.yield_, 3),
                "events": [{"kind": e["kind"], "label": EVENTS[e["kind"]]["label"], "until": e["until"]} for e in self.active],
                "new_event": self.new}

    def shock(self) -> float:
        """Le choc sur le stock du lac que l'événement arrivé en début de saison apporte (1.0 : aucun)."""
        return EVENTS[self.new].get("stock", 1.0) if self.new else 1.0

    def line(self, season: int) -> str:
        """Les conditions de la saison, dites comme un villageois les dirait (une ligne, au contexte des agents)."""
        if not self.enabled:
            return ""
        bits = [f"Saison de l'année : {self.cycle['name']} ({self.cycle['text']})."]
        for e in self.active:
            ev = EVENTS[e["kind"]]
            last = "jusqu'à la saison %d" % e["until"] if e["until"] > season else "cette saison"
            bits.append(f"En cours : {ev['label']} ({ev['text']}), {last}.")
        return " ".join(bits)
