"""Politiques à règles fixes.

Elles servent à trois choses :
1. les pêcheurs à règles de la population hybride (A6) ;
2. la baseline sans LLM (E1, `rule_fraction: 1.0`) ;
3. la solution de repli quand un agent LLM ne répond pas ou répond de façon inexploitable (A4).

Chaque décision renvoie le nom de la règle appliquée, consultable dans l'inspecteur (D2).
"""
from __future__ import annotations


def sustainable_share(stock_est: float, capacity: float, n_fishers: int) -> float:
    """Part par pêcheur qui ramène le lac à la moitié de sa capacité, là où il se repeuple le plus vite."""
    return max(0.0, stock_est - capacity / 2) / max(1, n_fishers)


def needs(s: dict) -> float:
    return (s["upkeep"] + s["debt_payment"]) / s["price"]


def clamp(x: float, hi: float, lo: float = 0.0) -> float:
    return round(max(lo, min(hi, x)), 1)


def catch_rule(archetype: str, s: dict) -> tuple[float, str]:
    share = sustainable_share(s["stock_estimate"], s["capacity"], s["n_fishers"])
    quota = s.get("quota")
    # personne ne demande plus que ce qu'il voit dans le lac, mais une sortie rapporte toujours la prise minimale
    lo = s.get("min_catch", 0.0)
    cap = max(lo, min(s["boat_capacity"], max(0.0, s["stock_estimate"])))
    if archetype == "ancienne_famille":
        v = min(share, quota) if quota is not None else share
        return clamp(v, cap, lo), "prudence : part durable" + (" bornée par le quota adopté" if quota is not None else "")
    if archetype == "nouveau_venu":
        need = needs(s) + 1.0
        if quota is not None and quota >= 0.8 * need:
            return clamp(quota, cap, lo), "besoin couvert par le quota : respecte le quota"
        return clamp(max(need, share), cap, lo), "besoin : couvrir dépenses et dette (+1 t de marge)"
    if archetype == "taiseux":
        ref = quota if quota is not None else share
        return clamp(1.4 * ref + 0.5, cap, lo), "opportunisme discret : 140 % de la référence"
    if archetype == "beau_parleur":
        ref = min(share, quota) if quota is not None else share
        return clamp(0.8 * ref, cap, lo), "petite pêche : 80 % de la référence"
    return clamp(share, cap, lo), "part durable"


def projected(stock: float, capacity: float, r: float) -> float:
    """Stock attendu à l'ouverture de la saison suivante, après repeuplement."""
    return stock + r * stock * (1 - stock / capacity)


def speak_rule(archetype: str, s: dict) -> tuple[dict, str]:
    """`s` : état de la veillée vu par l'agent (stock estimé, propositions, prises visibles, etc.).
    À la veillée, on raisonne sur la saison prochaine, donc sur le stock attendu après repeuplement."""
    s = {**s, "stock_estimate": projected(s["stock_estimate"], s["capacity"], s["growth_rate"])}
    out = {"message": "", "destinataire": "tous", "proposition_quota": None, "soutien": None,
           "promesse": None, "accuse": None}
    leading = s.get("leading_proposal")  # (id, quota) ou None
    lo = s.get("min_catch", 0.0)          # un quota sous la prise minimale d'une sortie n'aurait pas de sens
    if archetype == "ancien":
        q = max(lo, round(sustainable_share(s["stock_estimate"], s["capacity"], s["n_fishers"]) * 2) / 2)
        if leading is None or leading[1] > q + 0.5:   # soutient toute proposition au moins aussi prudente que la sienne
            out["proposition_quota"] = q
            out["message"] = f"Le lac a besoin de temps. Je propose que chacun s'en tienne à {q:g} tonnes la saison prochaine."
        else:
            out["soutien"] = leading[0]
            out["message"] = "Cette proposition me paraît juste. Tenez-vous-y."
        return out, "ancien : quota = ce qui dépasse la moitié du lac après repeuplement, partagé entre pêcheurs"
    planned, _ = catch_rule(archetype, {**s, "quota": leading[1] if leading else s.get("quota")})
    if archetype == "taiseux":
        planned_said = max(lo, round(planned / 1.4, 1))  # annonce ce qu'on attend de lui
        out["promesse"] = planned_said
        out["message"] = f"Je prendrai {planned_said:g} tonnes."
        if leading:
            out["soutien"] = leading[0]
        return out, "taiseux : promet la référence, soutient la proposition en tête"
    out["promesse"] = planned
    accused = s.get("overfisher")
    if archetype == "ancienne_famille" and accused and s["round"] > 1:
        out["accuse"] = accused
        out["message"] = f"Certains ont pris bien plus que leur part. Je pêcherai {planned:g} tonnes, pas plus."
    elif archetype == "beau_parleur" and leading is None:
        q = max(lo, round(sustainable_share(s["stock_estimate"], s["capacity"], s["n_fishers"]) * 2) / 2)
        out["proposition_quota"] = q
        out["message"] = f"Fixons-nous une règle : {q:g} tonnes chacun, et tout le monde y gagnera."
    else:
        out["message"] = f"Je compte pêcher {planned:g} tonnes la saison prochaine."
    if leading and (archetype != "nouveau_venu" or leading[1] >= 0.8 * (needs(s) + 1.0)):
        out["soutien"] = leading[0]
    return out, f"{archetype} : annonce sa prise prévue, soutient si la règle lui convient"
