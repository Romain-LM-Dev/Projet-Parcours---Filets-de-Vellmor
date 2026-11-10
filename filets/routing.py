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
    if obs.get("banned"):
        why.append("interdit de pêche")             # rester à quai ou pêcher en cachette : ce n'est jamais de la routine
    hist = obs.get("stock_history") or []
    if not hist:
        why.append("première observation du lac")
    if est / cap < HEALTHY_RATIO:
        why.append("lac sous 70 %")
    openings = [h for h in hist if h["phase"] == "pêche"]
    if openings and est < openings[-1]["est"] - FALLING_RATIO * cap:
        why.append("le lac baisse")
    if any(o["ratio"] > est / cap for o in obs.get("lake_options") or []):
        why.append("un autre lac paraît mieux fourni")      # aller pêcher ailleurs se pèse
    if obs.get("rumors"):
        why.append("rumeur")
    if obs.get("events"):
        why.append("événement sur le lac")          # tempête, sécheresse… : ce n'est pas une saison comme les autres
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


# ------------------------------------------------------------------ les sorties (docs/peche.md)
def _sky(obs: dict) -> str:
    w = obs.get("today")
    return w if w in ("tempête", "calme") else "ordinaire"


def snapshot(obs: dict) -> dict:
    """Ce que le pêcheur avait sous les yeux à une décision : la prochaine sortie ne se compare qu'à cela."""
    return {"reasons": set(season_reasons(obs)), "est": obs["stock_estimate"], "sky": _sky(obs), "rumors": len(obs.get("rumors") or []),
            "events": len(obs.get("events") or []), "norms": len(obs.get("norms") or []), "clues": len(obs.get("clues") or [])}


def season_reasons(obs: dict) -> list[str]:
    """Les raisons de la saison : celles d'une décision de prise, plus l'état de son quota et de son plan."""
    why = reasons_to_think(obs)
    quota, taken = (obs.get("rule") or {}).get("quota"), obs.get("taken") or 0.0
    if quota is not None and taken >= 0.8 * quota:
        why.append("quota de saison presque atteint ou dépassé")
    plan = obs.get("plan")
    if plan and obs.get("outing"):
        left = plan["total"] - taken
        if left <= 0.05:
            why.append("plan rempli")
        elif left > obs["cale"] * max(0, int(obs.get("days_left", 0) / 0.4)):
            why.append("plan impossible à tenir avant la fermeture")
    return why


def outing_reasons(obs: dict, prev: dict | None) -> list[str]:
    """Pourquoi la prochaine sortie mérite le système 2 : ce qui a changé depuis sa décision précédente `prev` (un `snapshot`). Sans
    décision précédente, toutes les raisons de la saison. Liste vide : de la routine, le réflexe suffit."""
    now = season_reasons(obs)
    if prev is None:
        return now
    why = [r for r in now if r not in prev["reasons"]]
    cap = obs.get("capacity")
    if _sky(obs) != prev["sky"]:
        why.append(f"le temps change ({_sky(obs)})")
    if len(obs.get("rumors") or []) > prev["rumors"] or len(obs.get("events") or []) > prev["events"]:
        why.append("rumeur ou événement nouveau")
    if len(obs.get("norms") or []) > prev["norms"]:
        why.append("règle nouvelle")
    if len(obs.get("clues") or []) > prev["clues"]:
        why.append("indice ou accusation contre lui")
    if cap and obs["stock_estimate"] < prev["est"] - FALLING_RATIO * cap:
        why.append("le lac a nettement baissé")
    return why


def choose_outing_system(obs: dict, prev: dict | None) -> tuple[str, str]:
    """(système, raison) d'une décision de sortie : le réflexe si rien n'a changé depuis la précédente, le grand modèle sinon."""
    why = outing_reasons(obs, prev)
    return (S2, "; ".join(why)) if why else (S1, "routine : rien n'a changé depuis ma décision précédente")
