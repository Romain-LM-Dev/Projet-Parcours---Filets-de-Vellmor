"""Politiques à règles fixes.

Elles servent à trois choses :
1. les pêcheurs à règles de la population hybride (A6) ;
2. la baseline sans LLM (E1, `rule_fraction: 1.0`) ;
3. la solution de repli quand un agent LLM ne répond pas ou répond de façon inexploitable (A4).

Chaque décision renvoie le nom de la règle appliquée, consultable dans l'inspecteur (D2).
"""
from __future__ import annotations

import math


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
    if s.get("banned"):
        # interdit de pêche : le taiseux sort quand même, en cachette, avec une petite prise ; les autres restent à quai
        if archetype == "taiseux":
            return clamp(max(1.0, 0.6 * share), cap), "interdit de pêche : sort en cachette, une petite prise"
        return 0.0, "interdit de pêche : reste à quai"
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


# Ce que chaque caractère retient de ce qu'il apprend d'un pêcheur, en dixièmes de confiance (de −3 à +3, comme une IA) : sa
# morale et ses intérêts. La famille ancienne tient à la règle ; le nouveau venu, endetté, pardonne à qui pêche pour vivre mais
# pas à qui l'accuse ; le taiseux ne juge guère les autres, mais en veut à qui dénonce ; le beau parleur tient à la parole donnée.
JUDGE = {   # dépasse un peu / beaucoup, tient la règle, mensonge établi, pris en cachette, promesse trahie / tenue,
    #         m'accuse, a témoigné, interdit resté à l'écart
    "ancienne_famille": {"over_slight": -1, "over_big": -2, "within": 1, "lie": -3, "secret": -3, "broken": -2, "kept": 1,
                         "accused_me": -1, "testified": 1, "stayed_away": 1},
    "nouveau_venu": {"over_slight": 0, "over_big": -1, "within": 0, "lie": -2, "secret": -1, "broken": -1, "kept": 1,
                     "accused_me": -3, "testified": 0, "stayed_away": 2},
    "taiseux": {"over_slight": 0, "over_big": 0, "within": 0, "lie": -1, "secret": 0, "broken": 0, "kept": 0,
                "accused_me": -3, "testified": -1, "stayed_away": 1},
    "beau_parleur": {"over_slight": -1, "over_big": -1, "within": 1, "lie": -3, "secret": -2, "broken": -3, "kept": 2,
                     "accused_me": -2, "testified": 1, "stayed_away": 1},
    "ancien": {"over_slight": -1, "over_big": -2, "within": 1, "lie": -3, "secret": -3, "broken": -2, "kept": 1,
               "accused_me": 0, "testified": 1, "stayed_away": 1},
}
# Sous ce niveau de confiance, il propose d'interdire un pêcheur de pêche (None : jamais, le taiseux ne veut pas se faire
# remarquer et l'ancien relate, il ne sanctionne pas) ; sous celui-ci, il vote l'exclusion ; à partir du dernier, il propose
# et vote de réautoriser un exclu (le nouveau venu, qui sait ce qu'est le besoin, pardonne le plus vite).
EXCLUDE_BELOW = {"ancienne_famille": 0.25, "beau_parleur": 0.2, "nouveau_venu": 0.1}
VOTE_EXCLUDE_BELOW = {"ancienne_famille": 0.35, "beau_parleur": 0.3, "nouveau_venu": 0.15, "taiseux": 0.1}
REAUTHORIZE_FROM = {"ancienne_famille": 0.5, "beau_parleur": 0.45, "nouveau_venu": 0.35, "taiseux": 0.3}


# La patrouille du lac : combien de mensonges ou de sorties en cachette établis ces deux dernières saisons il faut à chaque caractère
# (à règles) pour la vouloir. La famille ancienne et le beau parleur tiennent à la parole donnée ; le nouveau venu, endetté,
# rechigne à payer ; le taiseux n'en veut jamais (il n'aime pas qu'on regarde dans sa barque).
PATROL_WANTS = {"ancienne_famille": 1, "beau_parleur": 1, "nouveau_venu": 3}


def patrol_vote(archetype: str, lies: int, action: str) -> bool:
    """Le vote d'un agent à règles sur l'installation (`patrouille`) ou le retrait (`fin_patrouille`) de la patrouille du lac."""
    wants = PATROL_WANTS.get(archetype)
    if action == "patrouille":
        return wants is not None and lies >= wants
    return wants is None or lies < wants


def elect_rule(others: dict[str, float], experience: dict[str, int], me: str) -> str:
    """Le vote d'un agent à règles pour l'élu de son village : celui des autres en qui il a le plus confiance (à égalité, le plus
    d'expérience) ; seul dans son village, lui-même."""
    if not others:
        return me
    return max(others, key=lambda c: (others[c], experience.get(c, 0), c))


# Ce que chaque caractère laisse peser en plus de la table : l'indulgence envers un voisin (qu'on a vu au travail, qu'on retrouve au
# marché) et le poids de ce qu'on dit du pêcheur dans la vallée.
KIN_SOFT = {"ancienne_famille": 0.25, "nouveau_venu": 0.25, "taiseux": 0.0, "beau_parleur": 0.1, "ancien": 0.0}
GOSSIP = {"ancienne_famille": 0.6, "nouveau_venu": 0.4, "taiseux": 0.1, "beau_parleur": 0.8, "ancien": 0.3}


def trust_rule(archetype: str, facts: dict, ctx: dict | None = None) -> dict[str, int]:
    """Le jugement d'un agent à règles sur ce qu'il vient d'apprendre de chacun (`facts` : identifiant -> faits), en dixièmes de
    confiance, de −3 à +3. Un dépassement avoué coûte toujours moins qu'un mensonge établi.

    Sans `ctx`, la table de son caractère (`JUDGE`) décide seule. Avec lui, elle n'est que le point de départ, et le jugement pèse
    tout ce qui peut compter pour cet agent : la gravité d'un mensonge (l'écart avec la déclaration), l'indulgence envers un voisin,
    la chance (une prise qui dépasse la règle de ce que la chance explique, `luck`, ou un jour de banc de poissons, n'est pas un
    défi à la règle), ses propres dettes (il comprend qui pêche pour vivre) et sa propre triche (qui a triché pardonne), ce qu'il
    pensait déjà du pêcheur (on perd d'autant plus qu'on en avait ; on gagne de moins en moins, jamais au-delà de 90 % par la seule obéissance, et
    lentement quand on a été déçu : sans cela, la confiance de chacun monterait à 100 % à force d'obéir), ce qu'on en dit dans la vallée, et son tempérament (`harsh`).
    Le résultat est un nombre réel, arrondi au hasard de l'agent (`rng`) : la même nouvelle ne change pas toujours la confiance du
    même nombre de dixièmes."""
    j = JUDGE.get(archetype, JUDGE["ancienne_famille"])
    out = {}
    for sid, f in facts.items():
        terms: list[tuple[float, str]] = []
        over = f.get("over")
        if over is not None:
            if over <= 0:
                terms.append((j["within"], "ok"))
            elif ctx:     # de plus en plus grave, sans palier, et seulement au-delà de ce que la chance explique
                eff = max(0.0, over - 0.75 * float(ctx.get("luck", 0.0)))
                if eff > 0:
                    terms.append((j["over_slight"] + (j["over_big"] - j["over_slight"]) * min(eff / 0.5, 1.0), "over"))
            else:
                terms.append((j["over_slight"] if over < 0.5 else j["over_big"], "over"))
        if f.get("lie"):
            terms.append((j["lie"] * (0.6 + 0.4 * min(f.get("gap", 1.0), 2.0) if ctx else 1.0), "lie"))
        for key in ("secret", "accused_me", "testified", "stayed_away"):
            if f.get(key):
                terms.append((j[key], "secret" if key == "secret" else "other"))
        if f.get("promise") is not None:
            terms.append((j["kept"], "ok") if f["promise"] else (j["broken"], "over"))
        steps = float(sum(v for v, _ in terms))
        if ctx:
            luck = float(ctx.get("yield", 1.0))
            excuse = 0.25 if luck > 1.3 else 0.5 if luck > 1.1 else 1.0
            kin = KIN_SOFT.get(archetype, 0.0) if f.get("kin") else 0.0
            steps = 0.0
            for v, kind in terms:
                if v < 0:
                    w = (1.0 - kin) * float(ctx.get("harsh", 1.0))
                    if kind == "over":
                        w *= excuse * (0.5 if ctx.get("debt", 0) > 0 else 1.0)
                    if kind in ("over", "lie", "secret") and ctx.get("cheated"):
                        w *= 0.6
                    v *= w
                steps += v
            if f.get("rep") is not None:
                steps += GOSSIP.get(archetype, 0.3) * (f["rep"] - 0.5) * 2
            old = f.get("old")
            if old is not None and steps:
                if steps < 0:
                    steps *= 0.6 + 0.8 * old
                else:
                    steps *= max(0.0, min(1.0, (0.9 - old) * 2.5)) * (0.7 if old < 0.3 else 1.0)
        steps = max(-3.0, min(3.0, steps))
        rng = (ctx or {}).get("rng")
        n = (math.floor(steps) + (rng.random() < steps - math.floor(steps))) if rng is not None else int(round(steps))
        if n:
            out[sid] = int(n)
    return out


def sanction_vote(archetype: str, trust: float, action: str) -> bool:
    """Le vote d'un agent à règles sur l'exclusion (ou la réautorisation) d'un pêcheur, selon sa confiance envers lui."""
    if action == "exclure":
        below = VOTE_EXCLUDE_BELOW.get(archetype)
        return below is not None and trust < below
    return trust >= REAUTHORIZE_FROM.get(archetype, 0.5)


def sanction_rule(archetype: str, s: dict, judged: dict[str, int]) -> dict:
    """Ce qu'un agent à règles propose à la veillée : interdire de pêche celui en qui il n'a presque plus confiance, ou rendre
    le droit de pêcher à un exclu qui l'a regagnée (sa confiance après le jugement de ce soir)."""
    trust = {k: v + 0.1 * judged.get(k, 0) for k, v in (s.get("trust") or {}).items()}
    present, banned, out = set(s.get("present") or ()), set(s.get("banned_ids") or ()), {}
    below = EXCLUDE_BELOW.get(archetype)
    if below is not None:
        low = [(v, k) for k, v in trust.items() if k in present and k not in banned and v < below]
        if low:
            out["exclure"] = min(low)[1]
    regained = [(v, k) for k, v in trust.items() if k in banned and v >= REAUTHORIZE_FROM.get(archetype, 1.1)]
    if regained:
        out["reautoriser"] = max(regained)[1]
    return out


def declare_rule(archetype: str, s: dict, v: float) -> tuple[float, str]:
    """Ce que le pêcheur dit à l'ancien avoir pêché. Le taiseux, qui pêche au-delà de la règle, déclare la règle, sauf si l'un de
    ses mensonges vient d'être découvert ; les autres disent vrai."""
    quota = s.get("quota")
    if archetype == "taiseux" and quota is not None and v > quota and not s.get("exposed"):
        return round(max(s.get("min_catch", 0.0), min(v, quota)), 1), "taiseux : déclare la règle, pas sa prise"
    return v, "déclare sa vraie prise"


def projected(stock: float, capacity: float, r: float) -> float:
    """Stock attendu à l'ouverture de la saison suivante, après repeuplement."""
    return stock + r * stock * (1 - stock / capacity)


def speak_rule(archetype: str, s: dict) -> tuple[dict, str]:
    """`s` : état de la veillée vu par l'agent (stock estimé, propositions, prises visibles, etc.).
    À la veillée, on raisonne sur la saison prochaine, donc sur le stock attendu après repeuplement."""
    s = {**s, "stock_estimate": projected(s["stock_estimate"], s["capacity"], s["growth_rate"])}
    judged = trust_rule(archetype, s.get("facts") or {}, s.get("trust_ctx"))    # ce qu'il pense de ce qu'il vient d'apprendre
    out = {"message": "", "destinataire": "tous", "proposition_quota": None, "soutien": None,
           "promesse": None, "accuse": None, "confiance": judged, "exclure": None, "reautoriser": None, "patrouille": None}
    lies, wants = s.get("lies_recent", 0), PATROL_WANTS.get(archetype)
    if not s.get("patrol_enabled", True):
        pass
    elif archetype in ("ancienne_famille", "beau_parleur") and not s.get("has_patrol") and wants is not None and lies >= wants:
        out["patrouille"] = "installer"
    elif archetype in ("taiseux", "nouveau_venu") and s.get("has_patrol") and (wants is None or lies < wants):
        out["patrouille"] = "retirer"
    leading = s.get("leading_proposal")  # (id, quota) ou None
    if leading and s.get("leading_trust", 1.0) < 0.3:
        leading = None                    # on ne soutient pas la proposition de quelqu'un qu'on ne croit plus
    lo = s.get("min_catch", 0.0)          # un quota sous la prise minimale d'une sortie n'aurait pas de sens
    if archetype != "ancien":             # l'ancien relate les faits, il ne propose pas de sanction
        out.update(sanction_rule(archetype, s, judged))
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
