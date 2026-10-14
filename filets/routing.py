"""Système 1 ou système 2 ? Un routage pour dépenser les tokens là où la réflexion change quelque chose.

Deux manières de décider, d'après la distinction de Kahneman :

* **Système 1, le réflexe.** Une situation de routine ne demande pas un long raisonnement : le lac est sain et stable, le
  pêcheur a un engagement ou une règle à suivre, aucune rumeur, des finances correctes. Il reçoit un contexte de quelques lignes
  (environ 150 tokens), répond par un nombre seul (une quinzaine de tokens) et c'est le petit modèle qui le produit.
* **Système 2, la réflexion.** Dès que quelque chose sort de l'ordinaire (première saison, lac sous 70 % ou qui baisse, rumeur,
  finances tendues, rien pour guider), le pêcheur reçoit le contexte complet allégé du profil « rapide » et son propre modèle
  raisonne : la justification s'écrit avant le nombre.

Les paroles de la veillée restent toujours du système 2 : c'est là que la réflexion sert. Le routage ne s'applique qu'avec le
profil `llm.reflection: adaptive` ; chaque appel porte son système (`llm_call.system`, `decision.system`) et les tokens se
comptent par système, ce qui permet de dire ce que la réflexion a coûté et ce que le réflexe a épargné.
"""
from __future__ import annotations

S1, S2 = "S1", "S2"

HEALTHY_RATIO = 0.7        # sous 70 % de la capacité, le lac mérite qu'on y réfléchisse
FALLING_RATIO = 0.04       # une baisse de plus de 4 % de la capacité depuis la dernière ouverture est un signal


def reasons_to_think(obs: dict) -> list[str]:
    """Pourquoi cette décision mérite le système 2 (liste vide : c'est de la routine)."""
    why = []
    cap, est = obs.get("capacity"), obs["stock_estimate"]
    if not cap:
        return ["lac inconnu"]
    hist = obs.get("stock_history") or []
    if not hist:
        why.append("première observation du lac")
    if est / cap < HEALTHY_RATIO:
        why.append("lac sous 70 %")
    openings = [h for h in hist if h["phase"] == "pêche"]
    if openings and est < openings[-1]["est"] - FALLING_RATIO * cap:
        why.append("le lac baisse")
    if obs.get("rumors"):
        why.append("rumeur")
    if obs["wealth"] < obs["upkeep"] + obs["debt_payment"]:
        why.append("finances tendues")
    if not obs.get("pinned") and not obs.get("norms"):
        why.append("aucun engagement ni règle pour guider")
    return why


def choose_system(obs: dict, purpose: str) -> tuple[str, str]:
    """(système, raison). Seules les prises peuvent relever du système 1."""
    if purpose != "catch":
        return S2, "parole de la veillée"
    why = reasons_to_think(obs)
    return (S2, "; ".join(why)) if why else (S1, "routine : lac sain et stable, engagement ou règle à suivre")
