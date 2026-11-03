"""Les types de règle que le conseil peut voter, et les mots pour les dire.

Une règle = un type + une valeur + une portée (la vallée ou un village) + la saison d'effet (+ une cible, + une durée pour
`reserve` et `repos`). Le moteur applique la physique (voir `World.rules_for`, `apply_catch`) ; respecter ou non reste la
décision de chaque pêcheur.

  quota    valeur = tonnes par pêcheur et par saison                        (pas de cible)
  reserve  valeur = durée en saisons ; cible = une zone (rive d'un village, ou le large)
  repos    valeur = durée en saisons ; cible = un lac, fermé à la pêche
  sorties  valeur = nombre maximal de sorties en mer par pêcheur et par saison  (pas de cible)
  bateau   valeur = rang de la taille maximale (1 = la plus petite classe de bateau, 2 = la suivante…) (pas de cible)
"""
from __future__ import annotations

KINDS = ("quota", "reserve", "repos", "sorties", "bateau")
TIMED = ("reserve", "repos")          # règles à durée : elles s'éteignent d'elles-mêmes
TARGETED = ("reserve", "repos")       # règles qui visent un lieu
MAX_DURATION = 3

ALIASES = {"quota": "quota", "reserve": "reserve", "réserve": "reserve", "repos": "repos", "sortie": "sorties",
           "sorties": "sorties", "bateau": "bateau", "bateaux": "bateau", "taille": "bateau"}

# écart de valeur sous lequel deux propositions de même type et de même cible n'en font qu'une (et deux voix se rejoignent) ;
# pour le quota, voir `scenario.proposal_merge_tolerance` et `scenario.vote_tolerance`
VALUE_TOLERANCE = {"reserve": 0.0, "repos": 0.0, "sorties": 1.0, "bateau": 0.0}


def kind_of(raw) -> str | None:
    return ALIASES.get(str(raw).strip().lower()) if raw is not None else None


def plural(n: float, word: str) -> str:
    return f"{n:g} {word}{'s' if n >= 2 else ''}"


def words(kind: str, value: float, place: str | None = None, boat: str | None = None, cap: float | None = None) -> str:
    """Une règle en mots. `place` : l'endroit déjà tourné (« sur la rive de Hennad », « au large », « dans le lac d'Orsane ») ;
    `boat`, `cap` : la plus grande classe de bateau permise et sa cale (t)."""
    if kind == "reserve":
        return f"zone réservée : interdit de pêcher {place or 'dans cette zone'} pendant {plural(value, 'saison')}"
    if kind == "repos":
        return f"repos du lac : interdit de pêcher {place or 'dans ce lac'} pendant {plural(value, 'saison')}"
    if kind == "sorties":
        return f"au plus {plural(value, 'sortie')} en mer par pêcheur et par saison"
    if kind == "bateau":
        return (f"bateaux limités à la taille « {boat} » : les plus gros ne ramènent pas plus de {cap:g} t par saison"
                if boat else "taille de bateau limitée")
    return f"pas plus de {value:g} t par pêcheur et par saison"
