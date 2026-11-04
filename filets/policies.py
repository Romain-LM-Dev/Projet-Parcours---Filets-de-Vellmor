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


def obeys(archetype: str, s: dict) -> bool:
    """Respecte-t-il les règles qui limitent sa pêche (zone réservée, lac au repos, nombre de sorties, taille de bateau) ?
    La famille ancienne et le beau parleur oui ; le nouveau venu tant qu'il peut payer sa saison avec ses économies ; le taiseux
    les contourne, sauf si l'un de ses mensonges vient d'être découvert (comme pour sa déclaration, `declare_rule`)."""
    if archetype == "taiseux":
        return bool(s.get("exposed"))
    if archetype == "nouveau_venu":
        return float(s.get("wealth", 0.0)) >= float(s.get("upkeep", 0.0)) + float(s.get("debt_payment", 0.0))
    return True


def rule_choices(archetype: str, s: dict) -> tuple[dict, str]:
    """Ce qu'un agent à règles répond aux règles de pêche qui le visent : `place` (« large » s'il quitte sa rive réservée, « rive »
    s'il y pêche quand même) et `outings` (le nombre de sorties qu'il fait). Et pourquoi, en mots."""
    out, why = {}, ""
    if s.get("banned"):
        return out, why
    ob = obeys(archetype, s)
    if s.get("shore_closed"):
        out["place"] = "large" if ob else "rive"
        why += " ; sa rive est réservée : " + ("il pêche au large" if ob else "il y pêche quand même")
    if s.get("outings_cap"):
        out["outings"] = int(s["outings_cap"]) if ob else int(s.get("outings_n", s["outings_cap"]))
        why += f" ; la règle limite les sorties à {int(s['outings_cap'])} : " + ("il s'y tient" if ob else "il en fait autant qu'avant")
    return out, why


def catch_rule(archetype: str, s: dict) -> tuple[float, str]:
    v, why = _catch_base(archetype, s)
    if s.get("banned") or not obeys(archetype, s):
        return v, why
    if s.get("lake_closed") or (s.get("shore_closed") and s.get("large_closed")):
        return 0.0, "règle : sa zone de pêche est fermée, il reste à quai"
    limit = s.get("boat_limit")
    if limit is not None and v > limit:
        return round(limit, 1), why + " ; bornée par la taille de bateau permise"
    return v, why


def _catch_base(archetype: str, s: dict) -> tuple[float, str]:
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


# Combien de fois mieux (en tonnes nettes de la route) il faut que ce soit ailleurs pour que ce caractère quitte son lac : la famille
# ancienne est attachée au sien, le nouveau venu, qui a des dettes, va où l'on pêche.
LEAVE = {"ancienne_famille": 1.6, "taiseux": 1.4, "beau_parleur": 1.25, "nouveau_venu": 1.15}


def lake_choice_rule(archetype: str, s: dict) -> tuple[str | None, str]:
    """Le lac d'un agent à règles : le sien, sauf si un autre lui rapporterait nettement plus (ce que le lac lui laisse prendre là-bas,
    réduit par le trajet, moins ce que la route coûte, en tonnes) ; il le quitte aussi s'il est vide et qu'ailleurs on peut encore pêcher.
    Renvoie le nom du lac choisi (None : le sien) et pourquoi."""
    options = s.get("lake_options") or []
    ob = obeys(archetype, s)
    if ob:                                    # il ne va pas où la pêche est interdite (lac au repos, large réservé)
        options = [o for o in options if not o.get("closed")]
    if not options or s.get("banned"):
        return None, ""
    shut = s.get("lake_closed") or (s.get("shore_closed") and s.get("large_closed"))
    price = max(float(s.get("price", 100.0)), 1e-9)

    def allowed(hold: float, quota) -> float:      # qui respecte la règle du lac où il pêche n'y prend pas plus que le quota de ce lac
        return min(hold, float(quota)) if ob and quota is not None else hold

    here = 0.0 if shut and ob else allowed(float(s["boat_capacity"]), s.get("quota"))      # son lac lui est fermé : il n'y gagne rien

    def net(o: dict) -> float:
        return allowed(float(o["hold"]), o.get("quota")) * float(o["factor"]) - float(o["cost"]) / price

    best = max(options, key=lambda o: (net(o), o["name"]))
    if here <= 0.05 and net(best) > 0.05:
        return best["name"], f"son lac est vide, {best['label']} a encore du poisson"
    if net(best) > LEAVE.get(archetype, 1.4) * max(here, 0.05):
        return best["name"], (f"{best['label']} lui rapporterait {net(best):.1f} t, route comprise, contre {here:.1f} t chez lui")
    if archetype == "taiseux" and not ob:
        # il ne se laisse pas lier : il va où la règle est la plus lâche (pas de quota, ou un plus grand), si la route ne lui coûte pas trop
        def looseness(quota, closed=False) -> float:
            return -1.0 if closed else float("inf") if quota is None else float(quota)
        home = looseness(s.get("quota"), s.get("lake_closed"))
        looser = [o for o in options if looseness(o.get("quota"), o.get("closed")) > home + 0.5 and net(o) >= 0.7 * here]
        if looser:
            pick = max(looser, key=lambda o: (looseness(o.get("quota"), o.get("closed")), net(o), o["name"]))
            return pick["name"], f"la règle est plus lâche à {pick['label']}"
    return None, ""


def at_lake(s: dict, option: dict | None) -> dict:
    """L'état tel qu'il se présente à ce pêcheur dans cet autre lac (None : le sien) : ce qu'il en croit, sa capacité, ceux qui y pêchent
    déjà (plus lui), ce que le lac lui laisse viser. Sert à décider combien pêcher là-bas."""
    if option is None:
        return s
    return {**s, "stock_estimate": option["est"], "capacity": option["capacity"], "n_fishers": option["fishers"] + 1,
            "boat_capacity": option["hold"], "lake_closed": False, "shore_closed": False, "large_closed": False,
            # les règles de CE lac (quota, sorties, taille de bateau) : il y obéit à celles-là, pas à celles de son lac
            **{k: option[k] for k in ("quota", "outings_cap", "boat_limit") if k in option}}


def _round_half(x: float) -> float:
    return round(x * 2) / 2


def propose_rule(archetype: str, s: dict, rng=None) -> tuple[str, float, str | None, str] | None:
    """La règle qu'un agent à règles propose, selon sa situation et son caractère : (type, valeur, cible, ce qu'il dit), ou None.
    Un lac bas appelle un repos ; un coin trop pêché, une réserve ; de gros bateaux qui pèsent sur le lac, une taille maximale ;
    des prises qui dépassent la règle d'un lac moyen, moins de sorties ; sinon un quota. La famille ancienne s'inquiète d'un lac
    bas ou d'un coin vidé ; le nouveau venu ne vise que les gros bateaux ; le taiseux ne propose rien. `rng` (le faux LLM des tests) :
    tirage pondéré par la situation parmi tout ce qui est possible, au lieu du premier choix du caractère. `s` : état de la veillée
    (stock déjà projeté à la saison suivante)."""
    if archetype not in ("ancien", "beau_parleur", "ancienne_famille", "nouveau_venu"):
        return None
    ratio = s["stock_estimate"] / max(s["capacity"], 1e-9)
    kinds, hot, big, over = set(s.get("rule_kinds") or ()), s.get("hot_zone"), s.get("big_boats"), s.get("rule_over")
    names, n_out = s.get("boat_names") or [], int(s.get("outings_n", 6))
    zone = hot or s.get("own_zone")
    lo = s.get("min_catch", 0.0)
    q = max(lo, _round_half(sustainable_share(s["stock_estimate"], s["capacity"], s["n_fishers"])))
    cand: dict[str, tuple[float, str | None, str]] = {"quota": (q, None, f"Fixons-nous une règle : {q:g} tonnes chacun.")}
    if "repos" not in kinds and s.get("lake_target"):
        cand["repos"] = (1.0, s["lake_target"], "Le lac est trop bas : laissons-le au repos une saison, sans pêche.")
    if "reserve" not in kinds and zone:
        d = 2.0 if ratio < 0.5 else 1.0
        cand["reserve"] = (d, zone, f"Interdisons la rive de {zone} pendant {d:g} saison{'s' if d > 1 else ''} : on y a trop pêché.")
    if "sorties" not in kinds and n_out >= 2:
        n = float(max(1, n_out // 2))
        cand["sorties"] = (n, None, f"Limitons chacun à {n:g} sorties en mer par saison.")
    if "bateau" not in kinds and len(names) >= 2:
        cand["bateau"] = (float(len(names) - 1), None,
                          f"Les plus gros bateaux prennent trop : limitons la taille à la {names[len(names) - 2]}.")
    wanted = {"ancien": [("repos", ratio < 0.35), ("reserve", bool(hot)), ("sorties", ratio < 0.5 and (over or 0) >= 0.5),
                         ("bateau", bool(big)), ("quota", True)],
              "beau_parleur": [("reserve", bool(hot)), ("bateau", bool(big)), ("sorties", ratio < 0.5), ("quota", True)],
              "ancienne_famille": [("repos", ratio < 0.4), ("reserve", bool(hot))],
              "nouveau_venu": [("bateau", bool(big) and int(s.get("my_boat_rank", 1)) < len(names))]}[archetype]
    if rng is not None and archetype in ("ancien", "beau_parleur"):
        weight = {"repos": 5 if ratio < 0.35 else 2 if ratio < 0.5 else 0, "reserve": 5 if hot else 1,    # (jamais de repos sur un lac plein)
                  "sorties": 3 if ratio < 0.5 or (over or 0) >= 0.4 else 1, "bateau": 5 if big else 1, "quota": 2}
        kinds_ok = sorted(k for k in cand if weight[k] > 0)
        kind = rng.choices(kinds_ok, [weight[k] for k in kinds_ok])[0]
    else:
        kind = next((k for k, ok in wanted if ok and k in cand), None)
    if kind is None:
        return None
    value, target, said = cand[kind]
    if kind in ("quota", "sorties", "bateau"):        # ces règles-là peuvent viser son lac plutôt que tout le monde (cible = le lac)
        lake = rule_lake(s, rng)
        if lake is not None:
            target, said = lake, said.rstrip(".") + f", sur {s.get('lake_label') or 'notre lac'} seulement."
    return kind, value, target, said


def rule_lake(s: dict, rng=None) -> str | None:
    """Le lac que vise la règle d'un agent à règles, ou None (tout le périmètre de la veillée). Il parle pour SON lac, d'après l'état
    de chaque lac tel qu'il le croit : si les lacs sont à peu près aussi pleins, une règle commune fait l'affaire ; si l'un est bas et
    l'autre plein, ils n'appellent pas la même règle, donc il vise le sien. `rng` (le faux LLM des tests) : tirage de la graine."""
    ratios = s.get("lake_ratios") or {}
    if len(ratios) < 2 or not s.get("lake_target"):
        return None
    if rng is not None:
        return s["lake_target"] if rng.random() < 0.7 else None
    return s["lake_target"] if max(ratios.values()) - min(ratios.values()) > 0.2 else None


def likes_rule(archetype: str, s: dict, kind: str, target: str | None, value: float) -> bool:
    """Un agent à règles soutient-il cette proposition d'un autre type que le quota ? La famille ancienne, le beau parleur et le
    taiseux (une règle de plus à contourner) oui ; le nouveau venu, endetté, seulement si elle ne le touche pas ou s'il peut se
    le permettre."""
    if archetype != "nouveau_venu":
        return True
    if kind == "bateau":
        return int(s.get("my_boat_rank", 1)) <= value
    if kind == "reserve":
        return target != s.get("own_zone")
    if kind == "repos":
        return s["stock_estimate"] / max(s["capacity"], 1e-9) < 0.3
    return obeys(archetype, s)


def speak_rule(archetype: str, s: dict, rng=None) -> tuple[dict, str]:
    """`s` : état de la veillée vu par l'agent (stock estimé, propositions, prises visibles, etc.).
    À la veillée, on raisonne sur la saison prochaine, donc sur le stock attendu après repeuplement. `rng` : voir `propose_rule`."""
    s = {**s, "stock_estimate": projected(s["stock_estimate"], s["capacity"], s["growth_rate"])}
    judged = trust_rule(archetype, s.get("facts") or {}, s.get("trust_ctx"))    # ce qu'il pense de ce qu'il vient d'apprendre
    out = {"message": "", "destinataire": "tous", "proposition_type": None, "proposition_valeur": None,
           "proposition_cible": None, "proposition_quota": None, "soutien": None,
           "promesse": None, "accuse": None, "confiance": judged, "exclure": None, "reautoriser": None, "patrouille": None}

    def propose(kind: str, value: float, target: str | None, said: str):
        out.update(proposition_type=kind, proposition_valeur=value, proposition_cible=target, message=said)
        if kind == "quota":
            out["proposition_quota"] = value        # (l'ancien champ, pour qui le lit encore)

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
    # une proposition d'un autre type en tête (réserve, repos, sorties, taille de bateau) : on la soutient si elle convient
    lr = s.get("leading_rule")            # (id, type, cible, valeur) ou None
    if lr and lr[1] != "quota" and s.get("leading_rule_trust", 1.0) >= 0.3 and likes_rule(archetype, s, lr[1], lr[2], lr[3]):
        out["soutien"] = lr[0]
        if archetype == "ancien":
            out["message"] = "Cette règle me paraît juste. Tenez-vous-y."
            return out, "ancien : soutient la règle en tête (type " + lr[1] + ")"
        planned, _ = catch_rule(archetype, {**s, "quota": s.get("quota")})
        out["promesse"] = planned if archetype != "taiseux" else max(lo, round(planned / 1.4, 1))
        out["message"] = f"Je soutiens cette règle et je pêcherai {out['promesse']:g} tonnes."
        return out, f"{archetype} : soutient la règle en tête (type {lr[1]})"
    if archetype == "ancien":
        q = max(lo, _round_half(sustainable_share(s["stock_estimate"], s["capacity"], s["n_fishers"])))
        if leading is None or leading[1] > q + 0.5:   # soutient toute proposition au moins aussi prudente que la sienne
            pr = propose_rule(archetype, s, rng) if not lr else None
            if pr is not None and pr[0] != "quota":
                propose(*pr)
                return out, f"ancien : propose une règle de type {pr[0]} selon le lac et ses rives"
            out["proposition_quota"] = out["proposition_valeur"] = q
            out["proposition_type"] = "quota"
            lake = rule_lake(s, rng)
            out["proposition_cible"] = lake
            out["message"] = (f"Le lac a besoin de temps. Je propose que chacun s'en tienne à {q:g} tonnes la saison prochaine"
                              + (f", sur {s.get('lake_label') or 'notre lac'}." if lake else "."))
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
    pr = None
    # (la famille ancienne et le nouveau venu attendent d'avoir entendu les autres : ils ne proposent qu'au 2e tour, si rien n'est sur la table)
    if not leading and not lr and not (archetype == "ancienne_famille" and accused and s["round"] > 1) and \
            (archetype == "beau_parleur" or s["round"] > 1):
        pr = propose_rule(archetype, s, rng if archetype == "beau_parleur" else None)
    if archetype == "ancienne_famille" and accused and s["round"] > 1:
        out["accuse"] = accused
        out["message"] = f"Certains ont pris bien plus que leur part. Je pêcherai {planned:g} tonnes, pas plus."
    elif pr is not None:
        propose(*pr)
    else:
        out["message"] = f"Je compte pêcher {planned:g} tonnes la saison prochaine."
    if leading and (archetype != "nouveau_venu" or leading[1] >= 0.8 * (needs(s) + 1.0)):
        out["soutien"] = leading[0]
    return out, f"{archetype} : annonce sa prise prévue, soutient si la règle lui convient"
