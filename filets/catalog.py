"""Catalogue envoyé à l'interface : tout ce dont le menu de démarrage a besoin pour se construire.

Une seule source de vérité (le code Python et la configuration) : le menu Godot n'en recopie rien.
Il est envoyé par le pont à chaque connexion (voir `api.ApiServer`).
"""
from __future__ import annotations

import random

from .profiles import ARCHETYPES, FIRST_NAMES, HAMLETS, ORDER, archetype_defaults, build_population, profile_to_spec

LIMITS = {
    "fishers": [1, 24],
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

MODES = [
    {"id": "sync", "label": "Synchrone",
     "detail": "Tous les pêcheurs observent le même instant, décident, puis agissent ensemble. "
               "La lenteur d'une IA n'a aucun effet sur le temps du monde."},
    {"id": "async", "label": "Asynchrone",
     "detail": "Chacun va à son rythme et le temps du monde suit le temps réel : un pêcheur qui réfléchit "
               "longtemps agit plus tard, sur un lac qui a changé."},
]

COMMUNICATIONS = [
    {"id": "valley", "label": "Toute la vallée"},
    {"id": "hamlet", "label": "Par hameau"},
    {"id": "none", "label": "Interdite"},
]


def base_population(cfg: dict) -> list[dict]:
    """La composition de base du menu : les mêmes pêcheurs que la composition par défaut du moteur (mêmes graines, mêmes
    tirages : prénoms, hameaux, archétypes, expérience, avoir), mais tous réglés sur « IA auto ». Le moteur lancé en
    ligne de commande, lui, garde sa part d'agents à règles (`population.rule_fraction`, 25 % par défaut, A6) ; dans le
    menu, c'est au joueur de passer un pêcheur en « Règles »."""
    base_cfg = {**cfg, "population": {**cfg["population"], "custom": None, "elder": False}}
    rng = random.Random(int(cfg["run"]["seed"]))
    specs = [profile_to_spec(p) for p in build_population(base_cfg, rng)]
    for spec in specs:
        spec["kind"], spec["tier"] = "llm", "auto"
    return specs


def build_catalog(cfg: dict, llm: str = "scripted") -> dict:
    """`llm` : moteur d'IA présélectionné dans le menu."""
    pop, scn = cfg["population"], cfg["scenario"]
    option = next((o for o in LLM_OPTIONS if o["id"] == llm), LLM_OPTIONS[0])
    return {
        "version": 1,
        "hamlets": list(HAMLETS),
        "first_names": list(FIRST_NAMES),
        "archetypes": [
            {"id": a, "label": ARCHETYPES[a]["label"], "summary": ARCHETYPES[a]["summary"],
             "experience_range": list(ARCHETYPES[a]["experience"]), "wealth_range": list(ARCHETYPES[a]["wealth"]),
             **archetype_defaults(a)}
            for a in ORDER
        ],
        "base_population": base_population(cfg),
        "defaults": {
            "mode": cfg["time"]["mode"], "seasons": int(cfg["run"]["seasons"]), "seed": int(cfg["run"]["seed"]),
            "communication": scn["communication"], "catches_visible": bool(scn["catches_visible"]),
            "speed": 1.0, "llm": option["id"],
            "reflection": option["reflection"], "assembly_rounds": int(scn["assembly_rounds"]), "capacity": None,
            "stop_on_extinction": bool(cfg["run"].get("stop_on_extinction", True)),
            "elder": bool(pop.get("elder", True)), "elder_kind": pop.get("elder_kind", "llm"),
            "large_model_min_experience": int(pop["large_model_min_experience"]),
            "capacity_per_fisher": float(cfg["lake"]["capacity_per_fisher"]),
            "growth_rate": float(cfg["lake"]["growth_rate"]),
            "boat_capacity": float(cfg["economy"]["boat_capacity"]),
        },
        "limits": LIMITS,
        "speeds": SPEEDS,
        "modes": MODES,
        "communications": COMMUNICATIONS,
        "reflections": REFLECTIONS,
        "llm_options": [{k: v for k, v in o.items() if k != "config"} for o in LLM_OPTIONS],
    }
