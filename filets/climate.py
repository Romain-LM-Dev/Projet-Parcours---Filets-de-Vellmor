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


class Climate:
    """La saison de l'année et les événements en cours, d'une saison de jeu à l'autre."""

    def __init__(self, cfg: dict, seed: int):
        c = cfg.get("climate") or {}
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
