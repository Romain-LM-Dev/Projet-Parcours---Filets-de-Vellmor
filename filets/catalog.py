"""Catalogue envoyé à l'interface : tout ce dont le menu de démarrage a besoin pour se construire.

Une seule source de vérité (le code Python et la configuration) : le menu Godot n'en recopie rien.
Il est envoyé par le pont à chaque connexion (voir `api.ApiServer`).
"""
from __future__ import annotations

import collections

from .lakes import LAKE_NAMES, MAX_LAKES, random_valley, resolve_lakes
from .profiles import (ARCHETYPES, BOAT_NAMES, DEFAULT_BOAT_MIX, FIRST_NAMES, ORDER, VILLAGE_NAMES, archetype_defaults,
                       build_population, profile_to_spec)

LIMITS = {
    "villages": [1, 8],              # villages autour du lac (la génération de la vallée)
    "fishers": [1, 24],
    "lakes": [1, MAX_LAKES],         # lacs de la vallée (au plus un par village)
    "patrols": [0, 4],               # patrouilles du lac (0 : aucune)
    "stock_ratio": [0.05, 1.0],      # part pleine d'un lac au départ
    "seasons": [1, 50],
    "experience": [0, 60],
    "wealth": [0, 5000],
    "debt_payment": [0, 500],
    "seed": [0, 999999],
    "capacity": [10, 1000],          # limite du stock du lac, en tonnes
    "growth_rate": [0.1, 2.0],       # taux de repeuplement r du lac, par saison (au-delà de 2, la croissance logistique oscille)
    "assembly_rounds": [1, 3],       # tours de parole par veillée
}

# Les vitesses lentes comptent : en asynchrone, le temps du monde suit le temps réel, et une IA locale qui réfléchit
# 30 s agit alors 30 s plus tard dans le monde. Ralentir le monde laisse à l'IA le temps de répondre.
SPEEDS = [0.0625, 0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0]

# Moteurs d'IA proposés dans le menu : chacun renvoie à un fichier de `config/` qui définit les niveaux de modèle.
# `async_speed` : vitesse de départ conseillée en mode asynchrone avec ce moteur (voir `SPEEDS`).
# `reflection` : réflexion proposée avec ce moteur, tant que le joueur n'a pas choisi la sienne (voir `REFLECTIONS`).
LLM_OPTIONS = [
    {"id": "scripted", "label": "Faux LLM (test)", "config": None, "async_speed": 1.0, "reflection": "rapide",
     "detail": "Réponses à règles bruitées, sans IA : pour essayer le jeu. Aucun résultat scientifique. "
               "Il réagit aux annonces par des phrases toutes faites."},
    {"id": "ollama_fast", "label": "Ollama · rapide (3B + 1,5B)", "config": "config/ollama_fast.yaml", "async_speed": 0.25,
     "reflection": "rapide",
     "detail": "Qwen 2.5 sur votre machine, réglé pour la vitesse : grand modèle 3B, petit 1,5B. Les deux tiennent "
               "ensemble dans 6 Go de mémoire graphique, sans échange. Recommandé."},
    {"id": "ollama_open", "label": "Ollama · rapide + réflexes open", "config": "config/ollama_open.yaml",
     "async_speed": 0.25, "reflection": "adaptive",
     "detail": "Qwen 2.5 (3B + 1,5B) réfléchit et parle ; les prises de routine et les bulletins de vote vont à un modèle "
               "de décision open de 0,8B (tev1, Ollama 0.40.4 ou plus) qui choisit parmi des options en un ou deux tokens. "
               "Moins de calcul pour les choix simples, Qwen garde ce qui demande de réfléchir."},
    {"id": "ollama", "label": "Ollama · qualité (7B + 1,5B)", "config": "config/ollama.yaml", "async_speed": 0.125,
     "reflection": "rapide",
     "detail": "Qwen 2.5 sur votre machine : grand modèle 7B, petit 1,5B. Sur une carte de 6 Go ils ne tiennent pas "
               "ensemble : chaque passage de l'un à l'autre coûte une trentaine de secondes. Lent."},
    {"id": "groq", "label": "Groq (API gratuite)", "config": "config/groq.yaml", "async_speed": 0.5, "reflection": "rapide",
     "detail": "Grand modèle sur Groq (clé GROQ_API_KEY requise), petit modèle sur Ollama."},
]

REFLECTIONS = [
    {"id": "rapide", "label": "Rapide",
     "detail": "Les IA répondent en une phrase courte, avec un contexte allégé : environ deux fois plus rapide."},
    {"id": "adaptive", "label": "Adaptative (système 1 / 2)",
     "detail": "Système 1 : un réflexe de quelques tokens pour les prises de routine (lac sain et stable, engagement à "
               "suivre), par le petit modèle ou par un modèle de décision open s'il y en a un. Système 2 : la réflexion, "
               "seulement quand la situation l'exige. Moins de tokens, plus de temps pour ce qui compte."},
    {"id": "complete", "label": "Complète",
     "detail": "Réponses libres et contexte complet (profil de référence des expériences) : plus lent."},
]

# Un seul mode de temps (docs/temps.md) : la liste ne sert plus qu'à valider la demande (« sync » et « async » : anciennes
# demandes, ignorées) ; le catalogue ne la publie plus.
MODES = [{"id": "unique", "label": "Unique"}, {"id": "sync", "label": "Synchrone"}, {"id": "async", "label": "Asynchrone"}]

COMMUNICATIONS = [
    {"id": "valley", "label": "Conseil de la vallée"},
    {"id": "hamlet", "label": "Par village"},
    {"id": "none", "label": "Interdite"},
]

COUNCILS = [
    {"id": "delegates", "label": "Un élu par village",
     "detail": "Chaque village choisit à chaque saison un élu, selon la confiance de ses pêcheurs. Seuls les élus (et l'ancien) "
               "vont au conseil de la vallée ; les autres villageois en apprennent les décisions."},
    {"id": "all", "label": "Tous les pêcheurs", "detail": "Tous les pêcheurs vont au conseil de la vallée."},
]


# La flotte de la vallée générée : la répartition des tailles de bateaux (le caractère l'infléchit encore, voir
# `profiles.BOAT_TILT`). La flotte « mixte » est celle de la configuration (`population.boat_mix`).
FLEETS = [
    {"id": "petits", "label": "Petits bateaux", "mix": {"barque": 0.6, "chaloupe": 0.3, "cotre": 0.1}},
    {"id": "mixte", "label": "Flotte mixte", "mix": None},
    {"id": "gros", "label": "Gros bateaux", "mix": {"barque": 0.1, "chaloupe": 0.3, "cotre": 0.6}},
]


def fleet_mix(cfg: dict, fleet: str) -> dict:
    mix = next((f["mix"] for f in FLEETS if f["id"] == fleet), None)
    return mix or cfg["population"].get("boat_mix") or DEFAULT_BOAT_MIX


def boats_catalog(cfg: dict) -> list[dict]:
    """Les tailles de bateaux, de la plus petite à la plus grande : capacité (t par saison) et entretien (écus par saison)."""
    return [{"id": b, "label": b, **{k: v for k, v in cfg["economy"]["boats"][b].items()}} for b in BOAT_NAMES]


def base_population(cfg: dict) -> list[dict]:
    """La composition de base du menu : les mêmes pêcheurs que la composition par défaut du moteur (mêmes graines, mêmes
    tirages : prénoms, villages, archétypes, expérience, avoir, bateau), mais tous réglés sur « IA auto ». Le moteur lancé en
    ligne de commande, lui, garde sa part d'agents à règles (`population.rule_fraction`, 25 % par défaut, A6) ; dans le
    menu, c'est au joueur de passer un pêcheur en « Règles »."""
    base_cfg = {**cfg, "population": {**cfg["population"], "custom": None, "elder": False}}
    profiles = build_population(base_cfg)
    specs = [profile_to_spec(p) for p in profiles]
    for spec in specs:
        spec["kind"], spec["tier"] = "llm", "auto"
    return specs


def generate_world(cfg: dict, villages: int, fishers: int, seed: int, fleet: str = "mixte", lakes: int = 1, patrols: int = 1,
                   mode: str = "params") -> dict:
    """La vallée que génèrent ces paramètres (génération procédurale, la même pour la même graine) : ses villages et ses pêcheurs,
    avec la flotte demandée (`FLEETS`), ses lacs (chacun son poisson : 12,5 t par pêcheur du lac) et ses patrouilles. En mode
    `random`, la graine seule décide de tout (`lakes.random_valley`) et les autres paramètres sont ignorés. Le menu l'affiche, le
    joueur la retouche, puis la lance."""
    if mode == "random":
        drawn = random_valley(seed)
        villages, fishers, fleet, patrols, specs_lakes = drawn["villages"], drawn["fishers"], drawn["fleet"], drawn["patrols"], \
            drawn["lakes"]
    else:
        specs_lakes = [{"name": LAKE_NAMES[i]} for i in range(lakes)]
    over = {"population": {**cfg["population"], "villages": villages, "fishers": fishers, "boat_mix": fleet_mix(cfg, fleet),
                           "random": False},
            "run": {**cfg["run"], "seed": seed}}
    specs = base_population({**cfg, **over})
    hamlets = villages_of_specs(specs)
    resolved = resolve_lakes({**cfg["lake"], "lakes": specs_lakes}, hamlets, collections.Counter(s["hamlet"] for s in specs))
    return {"villages": villages, "fishers": fishers, "seed": seed, "fleet": fleet, "hamlets": hamlets, "base_population": specs,
            "lakes": resolved, "patrols": patrols, "mode": mode}


def villages_of_specs(specs: list[dict]) -> list[str]:
    return sorted({s["hamlet"] for s in specs}, key=VILLAGE_NAMES.index)


def build_catalog(cfg: dict, llm: str = "scripted") -> dict:
    """`llm` : moteur d'IA présélectionné dans le menu."""
    pop, scn = cfg["population"], cfg["scenario"]
    option = next((o for o in LLM_OPTIONS if o["id"] == llm), LLM_OPTIONS[0])
    base = base_population(cfg)
    hamlets = villages_of_specs(base)
    lakes = resolve_lakes(cfg["lake"], hamlets, collections.Counter(s["hamlet"] for s in base))
    patrol = cfg["scenario"].get("patrol") or {}
    return {
        "version": 1,
        "hamlets": hamlets,                             # les villages de la composition de base
        "lakes": lakes,                                 # les lacs de la composition de base : nom, capacité, stock, villages
        "lake_names": list(LAKE_NAMES),
        "village_names": list(VILLAGE_NAMES),           # tous ceux que la génération peut poser autour du lac
        "boats": boats_catalog(cfg),
        "fleets": [{"id": f["id"], "label": f["label"], "mix": fleet_mix(cfg, f["id"])} for f in FLEETS],
        "councils": COUNCILS,
        "first_names": list(FIRST_NAMES),
        "archetypes": [
            {"id": a, "label": ARCHETYPES[a]["label"], "summary": ARCHETYPES[a]["summary"],
             "experience_range": list(ARCHETYPES[a]["experience"]), "wealth_range": list(ARCHETYPES[a]["wealth"]),
             **archetype_defaults(a)}
            for a in ORDER
        ],
        "base_population": base,
        "defaults": {
            "mode": "unique", "seasons": int(cfg["run"]["seasons"]), "seed": int(cfg["run"]["seed"]),
            "communication": scn["communication"], "catches_visible": bool(scn["catches_visible"]),
            "council": scn.get("council", "delegates"), "patrol": bool((scn.get("patrol") or {}).get("enabled", True)),
            "speed": 1.0, "llm": option["id"],
            "reflection": option["reflection"], "assembly_rounds": int(scn["assembly_rounds"]), "capacity": None,
            "stop_on_extinction": bool(cfg["run"].get("stop_on_extinction", True)),
            "elder": bool(pop.get("elder", True)), "elder_kind": pop.get("elder_kind", "llm"),
            "large_model_min_experience": int(pop["large_model_min_experience"]),
            "capacity_per_fisher": float(cfg["lake"]["capacity_per_fisher"]),
            "growth_rate": float(cfg["lake"]["growth_rate"]),
            "villages": len(hamlets), "fishers": len(base), "lakes": len(lakes), "mode_generation": "params",
            "patrols": int(patrol.get("count", 1)) if patrol.get("enabled", True) else 0,
            "hold_fraction": float(cfg["economy"].get("hold_fraction", 0.5)),
            "travel_days": float(cfg["economy"].get("travel_days", 1.5)), "travel_cost": float(cfg["economy"].get("travel_cost", 10.0)),
            "climate": bool((cfg.get("climate") or {}).get("enabled", True)),
            "event_rate": float((cfg.get("climate") or {}).get("event_rate", 0.3)),
            "luck": float(cfg["economy"].get("luck", 0.0)),
            "boat_mix": {**DEFAULT_BOAT_MIX, **(pop.get("boat_mix") or {})}, "fleet": "mixte",
        },
        "limits": LIMITS,
        "speeds": SPEEDS,
        "communications": COMMUNICATIONS,
        "reflections": REFLECTIONS,
        "llm_options": [{k: v for k, v in o.items() if k != "config"} for o in LLM_OPTIONS],
    }
