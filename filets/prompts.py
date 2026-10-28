"""Prompts des agents LLM (en français, rôle incarné, sortie JSON stricte).

Deux profils de réflexion (`llm.reflection`) :

* `complete` : réponses libres (1 à 3 phrases), contexte complet. C'est le profil de référence des expériences.
* `rapide`   : une phrase courte par champ de texte, contexte allégé, longueur de réponse bornée. Sur un modèle local,
  c'est la génération (≈ 17 tokens/s pour un 7B sur une carte de 6 Go) qui coûte le plus : des réponses trois fois plus
  courtes rendent chaque appel environ deux fois plus rapide.
"""
from __future__ import annotations

import math

from .lake import EXTINCT_BELOW

WORLD = (
    "La vallée de Vellmor est fermée. Son lac est la seule réserve de poisson. {villages} se le partagent. "
    "Personne ne possède le lac et aucune loi n'encadre la pêche ; "
    "seuls comptent les accords que les villages passent entre eux, le soir, chez l'ancien. "
    "Le poisson se vend au marché de chaque village. Le lac se repeuple seul entre deux saisons, "
    "à condition qu'on lui en laisse le temps : les anciens disent qu'il se refait le mieux quand on le laisse autour de "
    "la moitié de sa capacité (environ {half:.0f} tonnes), qu'un lac très bas ne se refait presque plus, et qu'un lac "
    "vide ne se refait jamais. Quand il est plein, il contient environ {capacity:.0f} tonnes."
)

STYLE = (
    "Tu n'es pas un assistant : tu es ce personnage, avec ses intérêts, ses peurs et sa mauvaise foi éventuelle. "
    "Tu parles comme un habitant de la vallée, jamais comme un conseiller. Tu ne connais que ce qui est écrit "
    "ci-dessous. Réponds uniquement par un objet JSON valide, sans texte autour."
)
BRIEF_STYLE = " Sois très bref : une seule phrase courte (20 mots au plus) pour chaque champ de texte."

# longueur de réponse permise (tokens) : assez pour un JSON complet, pas pour un discours
BRIEF_MAX_TOKENS = {"catch": 125, "speak": 200}


def is_brief(cfg_llm: dict) -> bool:
    """Réponses courtes et contexte allégé : profils `rapide` et `adaptive` (dont le système 2 est « rapide »)."""
    return str(cfg_llm.get("reflection", "complete")) in ("rapide", "adaptive")


def is_adaptive(cfg_llm: dict) -> bool:
    """Profil `adaptive` : système 1 (réflexe) pour les décisions de routine, système 2 (réflexion) sinon. Voir `routing.py`."""
    return str(cfg_llm.get("reflection", "complete")) == "adaptive"


# Système 1 : un nombre, rien d'autre. Le contexte tient en une dizaine de lignes (environ 150 tokens, contre 1 500 à 2 000
# pour le système 2) et la réponse en une quinzaine de tokens.
REFLEX_MAX_TOKENS = 16
REFLEX_SCHEMA = {"type": "object", "properties": {"prise": {"type": "number"}}, "required": ["prise"],
                 "additionalProperties": False}


def cap_text(x: float, digits: int = 2) -> str:
    """Une limite en tonnes, arrondie VERS LE BAS : 3,636 t s'affiche 3,63, jamais 3,64 (un pêcheur qui répond le maximum affiché ne
    doit pas dépasser la limite)."""
    return f"{math.floor(x * 10 ** digits + 1e-9) / 10 ** digits:g}"


def villages_text(villages) -> str:
    """« Quatre villages (Ostrel, Bramois, Tilque et Hennad) » : les villages de la vallée, pour le décor des prompts."""
    names = list(villages or ())
    if not names:
        return "Plusieurs villages"
    count = ["Zéro", "Un", "Deux", "Trois", "Quatre", "Cinq", "Six", "Sept", "Huit", "Neuf", "Dix", "Onze", "Douze"]
    head = f"{count[len(names)] if len(names) < len(count) else len(names)} village{'s' if len(names) > 1 else ''}"
    return head + (f" ({', '.join(names[:-1])} et {names[-1]})" if len(names) > 1 else f" ({names[0]})")


def day_line(obs: dict) -> str:
    """La saison de l'année et les événements en cours (vide : aucun climat dans cette partie)."""
    return obs.get("conditions") or ""


def boat_line(obs: dict) -> str:
    lo, hi = obs.get("min_catch", 0.0), float(cap_text(obs["boat_capacity"]))
    if obs.get("boat"):
        # la prise visée n'est pas la prise réelle : le temps de chaque sortie, la chance, la saison de l'année et les événements la font varier
        aim = f"de {lo:g} à {hi:g} t" if lo else f"jusqu'à {hi:g} t"
        return (f"Ton bateau est une {obs['boat']} : tu peux viser {aim} par saison, en plusieurs sorties ; ce que tu prends vraiment "
                "dépend du temps de chaque jour (les petits bateaux souffrent le plus par gros temps), de ta chance du moment, "
                "de la saison de l'année et des événements.")
    if lo:
        return f"Une sortie rapporte au moins {lo:g} t (on ne revient jamais bredouille) et au plus {hi:g} t par saison."
    return f"Une sortie rapporte au plus {hi:g} t par saison."


def catch_range(obs: dict) -> str:
    lo = obs.get("min_catch", 0.0)
    return f"entre {lo:g} et {cap_text(obs['boat_capacity'])}" + ("" if lo else " ; 0 si tu restes à quai")


def reflex_messages(p, obs: dict) -> list[dict]:
    """La question du système 1 : la prise d'un pêcheur dont la situation est de routine (lac sain et stable, un engagement ou
    une règle à suivre, pas de rumeur, finances correctes). Seul ce qui sert à ce réflexe y figure."""
    cap, est = obs["capacity"], obs["stock_estimate"]
    lines = [f"Saison {obs['season']}. Le lac est à {100 * est / cap:.0f} % ({lake_level(est, cap, obs.get('collapse_ratio', 0.05))})"
             f", il n'a pas baissé. {boat_line(obs)}"]
    if day_line(obs):
        lines.append(day_line(obs))
    if obs.get("pinned"):
        lines.append("Tes engagements : " + " ".join(obs["pinned"]))
    if obs.get("norms"):
        lines.append("Règles en vigueur : " + " ".join(obs["norms"]))
    lines.append(f"Tes finances : {obs['wealth']:.0f} écus ; dépenses de la saison : {obs['upkeep'] + obs['debt_payment']:.0f} écus.")
    lines.append(f"Combien de tonnes pêches-tu ? Réponds en JSON : {{\"prise\": <tonnes, {catch_range(obs)}>}}")
    who = f"Tu es {p.name}, {p.archetype_label}, du village de {p.hamlet}. {p.traits} Réponds uniquement par un objet JSON."
    return [{"role": "system", "content": who}, {"role": "user", "content": "\n".join(lines)}]


PATROL_WHO = ("Tu es le capitaine de la patrouille du lac de Vellmor : une barque de surveillance, payée par la vallée (chaque "
              "pêcheur y contribue). Tu ne pêches pas et tu n'as aucun pouvoir de punir : tu mesures la charge des barques que tu "
              "croises, et ce que tu mesures, l'ancien le dit à toute la vallée. Tu choisis toi-même où aller, d'après les soupçons "
              "et les indices que les villageois et les pêcheurs ont partagés ; personne ne sait où tu passeras. Tu es juste : tu ne "
              "soupçonnes que sur des indices, et tu laisses tranquilles ceux que tu as trouvés honnêtes.")


WORLD_LAKES = (
    "La vallée de Vellmor est fermée. Ses lacs sont ses seules réserves de poisson : {lakes}. Personne ne possède les lacs et "
    "aucune loi n'encadre la pêche ; seuls comptent les accords que les villages passent entre eux, le soir, chez l'ancien. "
    "Le poisson se vend au marché de chaque village. Chaque lac se repeuple seul entre deux saisons, à condition qu'on lui en "
    "laisse le temps : les anciens disent qu'il se refait le mieux quand on le laisse autour de la moitié de sa capacité, qu'un "
    "lac très bas ne se refait presque plus, et qu'un lac vide ne se refait jamais."
)


def lake_ref(label: str) -> str:
    """« le lac d'Orsane » (le nom propre garde sa majuscule)."""
    return "le " + label[0].lower() + label[1:]


def lakes_text(lakes: list[tuple[str, list[str]]]) -> str:
    """« le lac de Vellmor (Ostrel et Bramois), le lac d'Orsane (Tilque) » : les lacs de la vallée et leurs villages."""
    return ", ".join(f"{lake_ref(label)} ({' et '.join(v)})" for label, v in lakes)


def persona(p, capacity: float, brief: bool = False, villages=(), world: str | None = None) -> str:
    who = PATROL_WHO if getattr(p, "role", "") == "patrouille" else (
        f"Tu es {p.name}, {p.archetype_label}, du village de {p.hamlet}. "
        f"{p.experience} an{'s' if p.experience > 1 else ''} de pêche sur le lac. {p.traits} Ta façon de parler : {p.voice}.")
    world = world or WORLD.format(capacity=capacity, half=capacity / 2, villages=villages_text(villages))
    return f"{world}\n\n{who}\n\n{STYLE}{BRIEF_STYLE if brief else ''}"


def _bullets(items: list[str], empty: str = "rien") -> str:
    return "\n".join(f"- {x}" for x in items) if items else f"- {empty}"


def _cut(items: list[str], n: int, width: int) -> list[str]:
    """Garde les `n` dernières entrées, chacune tronquée à `width` caractères."""
    return [x if len(x) <= width else x[:width - 1] + "…" for x in items[-n:]]


def lake_level(est: float, capacity: float, collapse_ratio: float = 0.05) -> str:
    """Le niveau du lac en mots, comme un pêcheur le dirait en regardant l'eau. Les seuils tournent autour de la moitié de la
    capacité, là où le lac se repeuple le plus vite (les anciens le savent), et du seuil d'effondrement."""
    ratio = est / capacity if capacity > 0 else 0.0
    if est < EXTINCT_BELOW:
        return "vide : il n'y a plus de poisson"
    if ratio < collapse_ratio:
        return "presque vide : il ne se refera presque plus"
    if ratio < 0.25:
        return "très bas : il se refera lentement"
    if ratio < 0.45:
        return "bas, bien en dessous de la moitié"
    if ratio < 0.55:
        return "à peu près à moitié plein"
    if ratio < 0.75:
        return "entamé, mais encore au-dessus de la moitié"
    if ratio < 0.95:
        return "bien rempli"
    return "plein"


def lake_trend(est: float, capacity: float, history: list[dict]) -> str:
    """Ce que le pêcheur voit changer : le niveau actuel comparé à la dernière ouverture de la pêche qu'il a vue (à l'ouverture
    d'une saison, celle de la saison passée ; à la veillée, celle de la saison en cours : c'est ce que la pêche vient de faire
    au lac) ; à défaut, à son dernier constat."""
    if not history:
        return ""
    openings = [h for h in history if h["phase"] == "pêche"]
    ref = (openings or history)[-1]["est"]
    if est < EXTINCT_BELOW:
        return "il vient de se vider" if ref >= EXTINCT_BELOW else "il reste vide"
    delta = est - ref
    if delta <= -0.15 * capacity:
        return "il a beaucoup baissé"
    if delta <= -0.04 * capacity:
        return "il a baissé"
    if delta >= 0.04 * capacity:
        return "il remonte"
    return "il est stable"


def lake_block(obs: dict) -> str:
    """L'état du lac, en tête du contexte : niveau en pourcentage de la capacité, en mots, et ce qu'on en a vu jusqu'ici."""
    est = obs["stock_estimate"]
    cap = obs.get("capacity")
    if not cap:
        return f"Ton estimation du stock du lac : environ {est:.0f} tonnes."
    where = f" ({obs['lake_name']}, celui de ton village)" if obs.get("lake_name") else ""
    head = (f"État du lac{where} en ce moment, tel que tu le constates toi-même : environ {est:.0f} tonnes sur {cap:.0f} à pleine "
            f"capacité, soit {100 * est / cap:.0f} % ({lake_level(est, cap, obs.get('collapse_ratio', 0.05))}).")
    hist = obs.get("stock_history") or []
    if not hist:
        return head
    when = {"pêche": "ouverture de la pêche", "veillée": "veillée, la pêche faite"}
    seen = "; ".join(f"{h.get('when') or h['label'].rsplit(' ', 1)[0]} ({when.get(h['phase'], h['phase'])}) ≈ {h['est']:.0f} t"
                     for h in hist)
    return f"{head}\nCe que tu as constaté du lac jusqu'ici : {seen}; maintenant ≈ {est:.0f} t ({lake_trend(est, cap, hist)})."


def social_line(obs: dict) -> str:
    """Ce que les autres ont pris la saison dernière, en une phrase. Un pêcheur sait à peu près ce que font ses voisins : un
    repère commun resserre les comportements (avant, l'un pêchait 0 t et l'autre 10 t sur le même lac, au même moment, parce que
    chaque modèle partait de son propre sentiment du « raisonnable »). Muet quand on connaît trop peu de prises."""
    vals = obs.get("last_season_catches") or []
    if len(vals) < 3:
        return ""
    mid = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2
    return (f"\nEn résumé, la saison dernière, les {len(vals)} pêcheurs dont tu connais la prise ont pris entre {vals[0]:g} et "
            f"{vals[-1]:g} t, {mid:.1f} t pour le pêcheur du milieu.")


def surplus_line(obs: dict) -> str:
    """Le repère des anciens (« laisse le lac à moitié ») traduit en tonnes : ce qui dépasse la moitié du lac, et ce que cela
    fait par pêcheur. Ce sont des faits sur le lac, pas un ordre. Sans cette ligne, les petits modèles lisent « la moitié,
    environ 50 tonnes » comme un quota de prise, et ne divisent pas par le nombre de barques : à 51 % ils écrivaient « il faut des
    prises modestes » puis demandaient 6 t chacun, soit tout le lac à huit. (Une phrase « si chacun prenait la part égale de ce
    qui reste » faisait pire : ils s'alignaient sur ce chiffre.)"""
    cap = obs.get("capacity")
    if not cap:
        return ""
    half, n = cap / 2, obs.get("n_fishers")
    surplus = max(0.0, obs["stock_estimate"] - half)
    each = f", soit {surplus / n:.1f} t par pêcheur (vous êtes {n})" if n else ""
    # sans cette phrase, sur un lac plein, la vallée votait 2 t chacun pour 6 t de surplus par pêcheur : du poisson perdu
    full = (" Bien rempli, le lac ne se repeuple presque plus : ce surplus, on peut le pêcher sans l'abîmer."
            if obs["stock_estimate"] >= 0.75 * cap else "")
    # ce que le lac rend, d'une saison à l'autre : sans ce chiffre, « laisse le lac à moitié » ne laissait à pêcher que le surplus
    # (1 t chacun à 60 %) et les règles votées étaient plus dures que ce que le lac supporte
    r = obs.get("growth")
    best = f" À la moitié, il se repeuple le plus vite : environ {r * cap / 4:.0f} t par saison" + \
        (f", soit {r * cap / 4 / n:.1f} t par pêcheur" if n else "") + "." if r else ""
    return (f"Repère des anciens : il y a {surplus:.0f} tonnes au-dessus de la moitié du lac ({half:.0f} t){each}.{full}{best} "
            "Ce qu'on prend sous la moitié, le lac ne le rend pas vite.\n")


def lake_reminder(obs: dict) -> str:
    """Quelques lignes, juste avant la question : ce que le pêcheur vient de lire en tête du contexte ne doit pas se perdre en
    route (les petits modèles lisent surtout la fin)."""
    cap = obs.get("capacity")
    if not cap:
        return ""
    est = obs["stock_estimate"]
    return (f"Rappel : le lac est à {100 * est / cap:.0f} % ({lake_level(est, cap, obs.get('collapse_ratio', 0.05))}) ; "
            "pour l'état du lac, ce que tu constates toi-même compte plus que ce qu'on a pu en dire aux veillées passées.\n"
            + surplus_line(obs))


def rule_reminder(obs: dict) -> str:
    """La règle votée qui s'applique à ce pêcheur, rappelée juste avant la question (les petits modèles lisent surtout la fin).
    Sans ce rappel, ils raisonnaient sur le lac seul et dépassaient le quota qu'ils venaient de voter : 0 pêcheur sur 8 le
    respectait. Le pêcheur reste libre de tricher ; il sait seulement ce que cela veut dire."""
    rule = obs.get("rule")
    if not rule:
        return ""
    who = "tu l'as soutenue" if rule["supported"] else "tu ne l'as pas soutenue, mais la vallée l'a adoptée"
    return (f"Règle votée à la veillée : pas plus de {rule['quota']:g} t par pêcheur cette saison ({who}). "
            "La dépasser, c'est trahir la parole de la vallée : chacun en jugera selon sa morale, et ceux qui ne te font plus "
            "confiance peuvent proposer de t'interdire de pêche.\n")


def rule_review(obs: dict) -> str:
    """Ce que la règle en vigueur a donné, en faits : combien de pêcheurs l'ont dépassée, d'après leurs déclarations. Avant de
    reproposer la même règle ou une autre, on sait si elle tient ; sans cela, un petit modèle recopiait son chiffre d'une veillée à
    l'autre (sept réponses sur douze à l'identique)."""
    rule, vals = obs.get("rule"), obs.get("last_season_catches") or []
    if not rule or not vals:
        return ""
    over = sum(v > rule["quota"] + 0.05 for v in vals)
    return (f"Bilan de la règle de {rule['quota']:g} t : parmi les {len(vals)} pêcheurs dont tu connais la prise, {over} l'ont "
            f"dépassée et {len(vals) - over} l'ont respectée.\n")


def trust_word(v: float) -> str:
    return ("très faible" if v < 0.25 else "faible" if v < 0.4 else "moyenne" if v < 0.6 else "bonne" if v < 0.8
            else "forte")


def trust_line(obs: dict) -> str:
    """La confiance de l'agent envers les autres, en mots ; seuls ceux qui s'écartent de la moyenne sont nommés (peu de tokens)."""
    trust = obs.get("trust") or []
    if not trust:
        return ""
    marked = [f"{name} {trust_word(v)}" for name, v in trust if not 0.4 <= v < 0.6]
    out = ("Ta confiance envers les autres : moyenne pour tous, personne ne t'a encore déçu ni convaincu." if not marked else
           "Ta confiance envers les autres : " + ", ".join(marked) + ("; les autres, moyenne." if len(marked) < len(trust) else "."))
    if obs.get("neighbors"):          # ce qui pèse aussi sur ce qu'on pense d'un pêcheur : qu'il soit un voisin, ce qu'on en dit
        out += " Tes voisins (ton village) : " + ", ".join(obs["neighbors"]) + "."
    if obs.get("valley"):
        out += (" Ce que la vallée pense d'eux (la confiance moyenne des autres) : "
                + ", ".join(f"{name} {trust_word(v)}" for name, v in obs["valley"]) + ".")
    return out


def carnet_block(obs: dict) -> str:
    """Le carnet : ce que l'agent est seul à savoir (ses vraies prises et ce qu'il en a déclaré), ses engagements, sa confiance
    envers les autres. Court et toujours présent : c'est ce qui garde un personnage cohérent d'une décision à l'autre (il sait
    s'il a menti, à qui il a promis, de qui il se méfie), là où des souvenirs retrouvés au hasard ne le garantissent pas."""
    lines = list(obs.get("carnet") or []) + list(obs.get("pinned") or [])
    tl = trust_line(obs)
    if tl:
        lines.append(tl)
    return "Ton carnet (ce que toi seul sais) :\n" + _bullets(lines, "rien à noter")


def clues_block(obs: dict) -> str:
    """Les indices que l'agent connaît (patrouille, barques vues rentrer ou partir, train de vie, comptes du lac) et les interdits
    de pêche : de quoi soupçonner quelqu'un, ou s'inquiéter pour soi. Vide (aucun token) s'il n'y en a pas."""
    lines = list(obs.get("clues") or [])
    if obs.get("banned_others"):
        lines.append("interdits de pêche par la vallée : " + ", ".join(obs["banned_others"]) + ".")
    return ("\n\nIndices et soupçons dans la vallée :\n" + _bullets(lines)) if lines else ""


def trust_schema(ids: list[str] | None) -> dict:
    """Le jugement de confiance : un entier de −3 à +3 par pêcheur, chacun une fois au plus. Avec les prénoms connus (ceux que
    l'invite montre : le moteur lit aussi un identifiant), le schéma interdit à une IA de répéter les mêmes clés jusqu'à épuiser sa
    réponse (réponses illisibles constatées avec un petit modèle, qui écrivait aussi des noms au lieu des identifiants)."""
    step = {"type": "integer", "minimum": -3, "maximum": 3}
    if ids:
        return {"type": "object", "properties": {i: step for i in ids}, "additionalProperties": False}
    return {"type": "object", "additionalProperties": step}


def answer_schema(purpose: str, brief: bool = False, fisher: bool = True, ids: list[str] | None = None) -> dict:
    """Forme exacte de la réponse, pour les fournisseurs qui savent la faire respecter (Ollama : voir `llm.OpenAICompatClient`).
    Tous les champs sont présents, dans cet ordre : pour une prise, la justification (ce que l'agent constate du lac) vient AVANT
    le nombre, qui s'écrit donc à la suite de ce raisonnement et non avant lui. Les textes sont bornés."""
    text = {"type": "string", "maxLength": 160 if brief else 400}
    ident = {"type": "string", "maxLength": 8}
    if purpose == "catch":
        props = {"justification": text, "prise": {"type": "number"}, "declaration": {"type": "number"}}
    else:
        props = {"message": text, "destinataire": ident, "proposition_quota": {"type": ["number", "null"]},
                 "soutien": {"type": ["string", "null"], "maxLength": 8}}
        if fisher:
            props["promesse"] = {"type": ["number", "null"]}
        props["accuse"] = {"type": ["string", "null"], "maxLength": 8}
        props["confiance"] = trust_schema(ids)
        if fisher:
            props["exclure"] = {"type": ["string", "null"], "maxLength": 8}
            props["reautoriser"] = {"type": ["string", "null"], "maxLength": 8}
            props["patrouille"] = {"type": ["string", "null"], "maxLength": 10}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def time_lines(obs: dict) -> list[str]:
    """Où l'on en est, en toutes lettres : le moment, ce que fait la saison à cet instant, et son calendrier (quand la pêche
    ferme, quand a lieu la veillée) : chaque action a ainsi sa place dans le temps."""
    phase = f" : {obs['phase']}" if obs.get("phase") else ""
    return [f"Nous sommes en {obs['label']}{phase}.", *([obs["calendar"]] if obs.get("calendar") else [])]


def context_block(obs: dict, brief: bool = False) -> str:
    parts = time_lines(obs)
    parts.append(lake_block(obs))
    if day_line(obs):
        parts.append(day_line(obs))
    if obs.get("rumors"):
        # Les rumeurs sont dites à tout le monde : elles figurent dans chaque décision, sans dépendre de ce que la
        # mémoire retrouve (une rumeur perdue parmi des dizaines de souvenirs n'aurait aucun effet).
        parts.append("Rumeurs qui courent dans la vallée en ce moment (tu ne sais pas si elles sont vraies, mais "
                     "tout le monde les a entendues) :\n" + _bullets([f"« {r} »" for r in obs["rumors"]]))
    if obs.get("role") != "ancien":
        parts.append(
            f"Tes finances : {obs['wealth']:.0f} écus. Chaque saison te coûte {obs['upkeep']:.0f} écus pour vivre"
            + (f", plus {obs['debt_payment']:.0f} écus de remboursement de dette" if obs["debt_payment"] else "")
            + f". Le poisson se vend {obs['price']:.0f} écus la tonne. {boat_line(obs)}")
    known = _cut(obs["known_catches"], 3, 260) if brief else obs["known_catches"]
    memories = _cut(obs["memories"][:4], 4, 170) if brief else obs["memories"]
    documents = _cut(obs["documents"][:2], 2, 230) if brief else obs["documents"]
    parts.append("Règles en vigueur entre pêcheurs :\n" + _bullets(obs["norms"], "aucune règle n'a été adoptée"))
    parts.append("Prises que les autres ont déclarées à l'ancien (tu ne connais que ces chiffres) :\n"
                 + _bullets(known, "aucune déclaration connue") + social_line(obs))
    if obs.get("promises"):
        parts.append("Promesses de la dernière veillée, et ce qu'on en sait :\n" + _bullets(obs["promises"]))
    parts.append(carnet_block(obs) + clues_block(obs))
    parts.append("Tes souvenirs qui reviennent :\n" + _bullets(memories, "aucun souvenir précis"))
    parts.append("Ce qu'on raconte dans la vallée (archives, comptes, récits) :\n" + _bullets(documents, "rien de particulier"))
    return "\n\n".join(parts)


def catch_messages(p, obs: dict, capacity: float, brief: bool = False) -> list[dict]:
    if obs.get("banned"):
        seen = "ce que tu constates du lac, ce que tu fais de ton interdiction"
    else:
        seen = "ce que tu constates du lac, ce que tu fais de la règle votée" if obs.get("rule") else "ce que tu constates du lac"
    just = f"<1 phrase courte : {seen}, et ce que tu en conclus>" if brief else \
        f"<1 à 3 phrases, à la première personne : {seen}, et ce que tu en conclus>"
    rumor = ("Une rumeur qui te concerne, ou qui parle du lac, peut peser sur ta décision : tiens-en compte comme le "
             "ferait ton personnage.\n" if obs.get("rumors") else "")
    if obs.get("banned"):
        ask = (
            "C'est le moment de décider. La vallée a voté ton exclusion : tant qu'elle ne vote pas de te laisser pêcher à "
            "nouveau, tu n'as pas le droit de sortir. Tu peux rester à quai (0 t), ou pêcher en cachette, loin de ta rive ; mais "
            "un voisin peut voir ta barque partir" + (", et la patrouille du lac peut te croiser (on ne sait pas où elle passera)"
                                                      if obs.get("patrol") else "") + ". "
            "Pris, tu perdrais encore la confiance des autres ; à quai, tu peux espérer la regagner.\n"
            + lake_reminder(obs) + rumor
            + f"Réponds en JSON, dans cet ordre : {{\"justification\": \"{just}\", "
              f"\"prise\": <0 si tu restes à quai, sinon les tonnes pêchées en cachette, jusqu'à {cap_text(obs['boat_capacity'])}>, "
              "\"declaration\": 0}"
        )
    else:
        ask = (
            "C'est le moment de décider combien tu vas pêcher cette saison.\n"
            + lake_reminder(obs)
            + rule_reminder(obs)
            + rumor
            + "En rentrant, tu déclareras ta prise à l'ancien : les autres ne connaîtront que ce chiffre. Tu la déclares telle "
              "quelle, sauf si tu choisis de cacher une part (par intérêt ou par peur) : tu peux mentir, mais "
              "les voisins qui pêchent du même côté voient les barques rentrer"
            + (" et la patrouille du lac mesure celles qu'elle croise (on ne sait pas où elle passera)" if obs.get("patrol") else "")
            + " : un dépassement avoué se pardonne plus facilement qu'un mensonge découvert.\n"
            + f"Réponds en JSON, dans cet ordre : {{\"justification\": \"{just}\", "
              f"\"prise\": <tonnes, {catch_range(obs)}>, "
              "\"declaration\": <tonnes que tu déclares à l'ancien : exactement ta prise, ou moins seulement si tu choisis de la cacher>}"
        )
    return [{"role": "system", "content": persona(p, capacity, brief, obs.get("villages", ()), obs.get("world"))},
            {"role": "user", "content": context_block(obs, brief) + "\n\n" + ask}]


def veillee_block(obs: dict) -> str:
    """Le contexte d'une réplique : ce qui sert à parler ce soir (le lac en une ligne, les règles, les déclarations, le carnet),
    sans les archives, ni le détail du lac saison par saison, ni celui des finances. Environ moitié moins de tokens que le
    contexte d'une prise : la parole coûtait 80 % des tokens d'une partie."""
    est, cap = obs["stock_estimate"], obs.get("capacity")
    parts = time_lines(obs)
    if cap:
        trend = lake_trend(est, cap, obs.get("stock_history") or [])
        parts.append(f"Le lac, tel que tu le vois : environ {est:.0f} t sur {cap:.0f} ({100 * est / cap:.0f} %, "
                     f"{lake_level(est, cap, obs.get('collapse_ratio', 0.05))})" + (f" ; {trend}." if trend else "."))
    else:
        parts.append(f"Le lac, tel que tu le vois : environ {est:.0f} t.")
    if day_line(obs):
        parts.append(day_line(obs))
    if obs.get("rumors"):
        parts.append("Rumeurs qui courent (vraies ou non, tout le monde les a entendues) : "
                     + " ; ".join(f"« {r} »" for r in obs["rumors"]))
    if obs.get("role") != "ancien":
        need = obs["upkeep"] + obs["debt_payment"]
        parts.append(f"Tes finances : {obs['wealth']:.0f} écus ; il t'en faut {need:.0f} par saison"
                     + (f", soit environ {need / obs['price']:.1f} t de poisson." if obs.get("price") else "."))
    parts.append("Règles en vigueur : " + ("; ".join(obs["norms"]) + "." if obs["norms"] else "aucune règle adoptée."))
    parts.append("Prises déclarées à l'ancien :\n" + _bullets(obs["known_catches"][-3:], "aucune déclaration connue"))
    if obs.get("promises"):
        parts.append("Promesses de la dernière veillée, et ce qu'on en sait :\n" + _bullets(obs["promises"]))
    parts.append(carnet_block(obs) + clues_block(obs))
    if obs.get("memories"):
        parts.append("Souvenirs :\n" + _bullets(_cut(obs["memories"][:2], 2, 140)))
    return "\n\n".join(parts)


def speak_messages(p, obs: dict, capacity: float, brief: bool = False) -> list[dict]:
    people = ", ".join(f"{x['id']} = {x['name']} ({x['label']})" for x in obs["participants"])
    transcript_lines = _cut(obs["transcript"], 8, 170) if brief else obs["transcript"]
    transcript = _bullets(transcript_lines, "personne n'a encore parlé")
    proposals = _bullets(obs["proposals"], "aucune proposition de règle pour l'instant")
    fisher = obs.get("role") != "ancien"
    msg = "<ce que tu dis à voix haute, 1 phrase courte>" if brief else "<ce que tu dis à voix haute, 1 à 3 phrases>"
    fields = [
        f"\"message\": \"{msg}\"",
        "\"destinataire\": \"tous\" ou l'identifiant d'une personne présente",
        "\"proposition_quota\": <tonnes par pêcheur et par saison d'une règle nouvelle que tu proposes, selon le lac et ce qu'il "
        "te faut pour vivre, ou null " + ("pour garder la règle en vigueur" if obs.get("rule") else "si tu n'en proposes pas") + ">",
        "\"soutien\": \"<identifiant d'une proposition que tu soutiens, ex. P2>\" ou null",
    ]
    if fisher:
        fields.append("\"promesse\": <tonnes que tu annonces pêcher la saison prochaine, ou null>")
    fields.append("\"accuse\": \"<identifiant d'un pêcheur que tu accuses d'avoir trop pêché>\" ou null")
    # la confiance : c'est l'agent qui dit ce que chaque acte, chaque parole change pour lui (le moteur n'y ajoute rien)
    # « ce soir » : sans cela, un petit modèle sanctionnait encore à chaque veillée un dépassement vieux de deux saisons
    fields.append("\"confiance\": {\"<prénom>\": <de -3 à +3>} pour ceux envers qui ce que tu apprends ce soir (saison "
                  f"{obs['season']} : prises, indices, paroles) change ta confiance, selon ta morale et tes intérêts (-3 : tu "
                  "ne le crois plus du tout, +3 : il a gagné ta confiance) ; les saisons d'avant comptent déjà dans ta "
                  "confiance ; {} si rien ne change")
    # ce qu'on peut proposer dépend de ce qui existe : on ne réautorise que s'il y a des interdits, on ne retire qu'une patrouille
    # qui sort (un petit modèle parlait de « réautoriser » quand personne n'était interdit)
    banned = bool(obs.get("banned_others") or obs.get("banned"))
    patrol = bool(obs.get("patrol"))
    if fisher:
        fields.append("\"exclure\": \"<identifiant d'un pêcheur que tu proposes d'interdire de pêche>\" ou null")
        fields.append("\"reautoriser\": \"<identifiant d'un pêcheur interdit que tu proposes de laisser pêcher à nouveau>\" ou null"
                      if banned else "\"reautoriser\": null (personne n'est interdit de pêche)")
        if obs.get("patrol_enabled", True):
            fields.append("\"patrouille\": \"retirer\" (tu proposes au conseil de supprimer la patrouille du lac) ou null" if patrol
                          else "\"patrouille\": \"installer\" (tu proposes au conseil de voter une patrouille du lac) ou null")
    rumor_hint = ("Une rumeur court : tu peux la relayer, la démentir, t'en défendre si elle te vise, ou accuser quelqu'un. "
                  if obs.get("rumors") else "")
    if obs.get("clues"):
        rumor_hint += "Les indices peuvent te faire soupçonner quelqu'un (ou te viser) : à toi de juger qui croire. "
    sanction_acts = ""
    if fisher:
        sanction_acts = ", proposer d'interdire un pêcheur de pêche" + (" (ou d'en réautoriser un)" if banned else "")
        if obs.get("patrol_enabled", True):
            sanction_acts += ", " + ("de retirer la patrouille du lac" if patrol else "d'installer une patrouille du lac")
    sanctions = ("Propositions d'exclure, de réautoriser ou de patrouille sur la table :\n" + _bullets(obs["sanctions"]) + "\n\n"
                 if obs.get("sanctions") else "")
    who_line = "".join(f"{x}\n" for x in (obs.get("delegate"), obs.get("patrol_line")) if x)
    if obs.get("independent"):
        # asynchrone : chacun s'exprime de son côté ; il n'entend rien, ne voit rien de ce que les autres déposent avant le vote
        room = ("Chacun s'exprime ce soir de son côté, sans entendre les autres : tu ne sais pas ce qu'ils diront. Tous voteront "
                "ensuite sur tout ce qui aura été proposé.\n\n")
        acts = ("À toi de parler. Tu peux proposer une règle, promettre, accuser"
                + sanction_acts)
    else:
        direct = (f"On s'est adressé à toi :\n{_bullets(obs['addressed'])}\n\n" if obs.get("addressed") else "")
        room = (f"Ce qui a déjà été dit ce soir :\n{transcript}\n\n{direct}Propositions de règle sur la table :\n{proposals}\n\n"
                f"{sanctions}")
        acts = ("À toi de parler. Tu peux proposer une règle, soutenir une proposition, promettre, accuser"
                + sanction_acts)
    turn = "" if obs.get("independent") else f", tour de parole {obs['round']}"
    ask = (
        f"Veillée chez l'ancien ({obs['scope_label']}){turn}. Présents : {people}.\n\n"
        f"{room}{who_line}{acts}"
        + f", ou simplement donner ton avis. {rumor_hint}Rien ne t'oblige à tenir parole.\n"
        + lake_reminder(obs) + rule_review(obs)
        + "Réponds en JSON : {" + ", ".join(fields) + "}"
    )
    # la veillée a son propre contexte, plus court ; en réflexion complète (profil de référence), le contexte reste entier
    ctx = veillee_block(obs) if brief else context_block(obs, brief)
    return [{"role": "system", "content": persona(p, capacity, brief, obs.get("villages", ()), obs.get("world"))},
            {"role": "user", "content": ctx + "\n\n" + ask}]


# Le bulletin de vote : un identifiant de proposition (ou « aucune »), rien d'autre.
BALLOT_MAX_TOKENS = 10


def ballot_schema(ids: list[str]) -> dict:
    return {"type": "object", "properties": {"vote": {"enum": [*ids, "aucune"]}}, "required": ["vote"], "additionalProperties": False}


def ballot_messages(p, table: list[str], est: float, capacity: float, collapse_ratio: float = 0.05) -> list[dict]:
    who = f"Tu es {p.name}, {p.archetype_label}, du village de {p.hamlet}. {p.traits} Réponds uniquement par un objet JSON."
    body = (f"La veillée touche à sa fin. Le lac est à {100 * est / capacity:.0f} % ({lake_level(est, capacity, collapse_ratio)}).\n"
            "Propositions de règle sur la table :\n" + "\n".join(table) +
            "\nPour laquelle votes-tu ? Réponds en JSON : {\"vote\": \"<identifiant d'une proposition, ou aucune>\"}")
    return [{"role": "system", "content": who}, {"role": "user", "content": body}]


# ---------------------------------------------------------------- questions typées pour un modèle de décision (système 1)
# Un modèle comme `tev1` ne génère pas de texte : il choisit une option, ou un niveau dans une échelle, et donne les probabilités.
# Ces fonctions décrivent la même décision que `reflex_messages` / `ballot_messages`, sous cette forme.

NARRATION_SCHEMA = {"type": "object", "properties": {"recit": {"type": "string", "maxLength": 600}},
                    "required": ["recit"], "additionalProperties": False}
NARRATION_MAX_TOKENS = 260
NARRATION_TEMPERATURE = 0.3      # un récit fidèle plutôt qu'inventif : à 0,7, un petit modèle enjolive (« le lac à son apogée »)


def narration_messages(p, facts: list[str], capacity: float, villages=(), world: str | None = None) -> list[dict]:
    """Le récit de la saison par l'ancien, pour le joueur : quelques phrases avec sa voix, à partir des seuls faits relevés
    dans le journal de la partie (il n'invente rien, il raconte)."""
    ask = ("La saison vient de finir. Voici ce qui s'est passé, tel qu'on l'a vu au marché et à la veillée :\n"
           + "\n".join(f"- {f}" for f in facts)
           + "\n\nRaconte cette saison en 2 à 4 phrases, avec ta voix d'ancien, comme au coin du feu, et ce que tu en penses. "
             "N'invente rien : ne parle que de ce qui est dans cette liste. S'il n'y est question ni de promesses, ni de "
             "règle, ni d'accusation, n'en parle pas. Pour le lac, reprends le mot de la liste, sans l'exagérer ; pour une "
             "règle, dis si c'est la première, une règle reconduite, plus stricte ou assouplie, comme la liste le dit. "
             "Le temps de la pêche peut expliquer de maigres prises : tu peux le dire. Quand tu cites quelqu'un, reprends son nom et ce que la liste dit de lui, sans le confondre avec un autre. Des phrases simples et complètes, en bon français. "
             "Réponds en JSON : {\"recit\": \"<ton récit>\"}")
    return [{"role": "system", "content": persona(p, capacity, True, villages, world)}, {"role": "user", "content": ask}]


def catch_levels(boat_capacity: float, n: int = 10, lo: float = 0.0) -> list[float]:
    """Les niveaux de prise proposés au modèle de décision : de la prise minimale à la capacité de la barque, en `n` paliers."""
    top = float(cap_text(boat_capacity, 1))           # jamais au-dessus de la limite (3,636 t : 3,6 t, pas 3,7)
    return [min(round(lo + i * (boat_capacity - lo) / (n - 1), 1), top) for i in range(n)]


def reflex_system_one(p, obs: dict) -> dict:
    """La prise de routine en question typée : l'état (les mêmes lignes que `reflex_messages`), une échelle de prises."""
    msgs = reflex_messages(p, obs)
    state = msgs[0]["content"].replace(" Réponds uniquement par un objet JSON.", "") + "\n" + \
        msgs[1]["content"].rsplit("\n", 1)[0]
    levels = catch_levels(obs["boat_capacity"], lo=obs.get("min_catch", 0.0))
    criteria = [f"{t:g} t" + (" : il reste à quai" if t == 0 else "") for t in levels]
    return {"state": state, "values": {"prise": levels},
            "questions": {"prise": {"type": "score", "criteria": criteria,
                                    "instructions": "Combien de tonnes ce pêcheur pêche-t-il cette saison, vu l'état du lac, "
                                                    "ses engagements et les règles ?"}}}


# Le vote sur une exclusion (ou une réautorisation) : « oui » ou « non » par proposition, selon sa confiance envers le pêcheur
# visé, sa morale (le caractère) et ses intérêts (sa situation).
SANCTION_MAX_TOKENS = 40


def sanction_schema(ids: list[str]) -> dict:
    return {"type": "object", "properties": {i: {"enum": ["oui", "non"]} for i in ids}, "required": list(ids),
            "additionalProperties": False}


def sanction_messages(p, items: dict[str, str], situation: str) -> list[dict]:
    who = f"Tu es {p.name}, {p.archetype_label}, du village de {p.hamlet}. {p.traits} Réponds uniquement par un objet JSON."
    body = ("La veillée touche à sa fin. La vallée vote sur ces propositions ; tu votes selon ta confiance, ta morale et tes "
            f"intérêts. {situation}\n" + "\n".join(f"- {i} : {t}" for i, t in items.items())
            + "\nRéponds en JSON : {" + ", ".join(f"\"{i}\": \"oui\" ou \"non\"" for i in items) + "}")
    return [{"role": "system", "content": who}, {"role": "user", "content": body}]


def sanction_system_one(p, items: dict[str, str], situation: str) -> dict:
    """Le même vote en questions typées : une question oui/non par proposition (la probabilité du oui)."""
    state = f"{p.name}, {p.archetype_label}, du village de {p.hamlet}. {p.traits}\n{situation}"
    return {"state": state, "questions": {i: {"type": "noul", "instructions": f"Ce pêcheur vote-t-il pour : {t}"}
                                          for i, t in list(items.items())[:25]}}


def ballot_system_one(p, proposals: dict[str, str], est: float, capacity: float, collapse_ratio: float = 0.05) -> dict:
    """Le bulletin de vote en question typée : `proposals` = identifiant → description (« 1.5 t par pêcheur, proposée par… »)."""
    state = (f"{p.name}, {p.archetype_label}, du village de {p.hamlet}. {p.traits}\n"
             f"La veillée touche à sa fin. Le lac est à {100 * est / capacity:.0f} % ({lake_level(est, capacity, collapse_ratio)}).")
    criteria = {**dict(list(proposals.items())[:25]), "aucune": "aucune de ces propositions"}   # 26 options au plus
    return {"state": state,
            "questions": {"vote": {"type": "choice", "criteria": criteria,
                                   "instructions": "Pour quelle proposition de règle ce pêcheur vote-t-il ?"}}}


# L'élection de l'élu d'un village : chaque pêcheur vote pour celui qui, selon lui, parlera le mieux au conseil pour le village.
ELECTION_MAX_TOKENS = 10


def election_schema(ids: list[str]) -> dict:
    return {"type": "object", "properties": {"vote": {"enum": list(ids)}}, "required": ["vote"], "additionalProperties": False}


def election_messages(p, items: dict[str, str], situation: str) -> list[dict]:
    who = f"Tu es {p.name}, {p.archetype_label}, du village de {p.hamlet}. {p.traits} Réponds uniquement par un objet JSON."
    body = ("Ton village choisit celui qui siégera pour lui au conseil de la vallée, chez l'ancien : il y parlera et y votera au "
            "nom de tous les pêcheurs du village, toi compris, et ceux-ci subiront ses décisions. Tu votes pour celui que tu "
            f"juges le plus apte à défendre tes intérêts et ceux du village, selon ta confiance et ta morale. {situation}\n"
            + "\n".join(f"- {i} : {t}" for i, t in items.items())
            + "\nPour qui votes-tu ? Réponds en JSON : {\"vote\": \"<identifiant>\"}")
    return [{"role": "system", "content": who}, {"role": "user", "content": body}]


def election_system_one(p, items: dict[str, str], situation: str) -> dict:
    """La même élection en question typée : un choix parmi les pêcheurs du village."""
    state = f"{p.name}, {p.archetype_label}, du village de {p.hamlet}. {p.traits}\n{situation}"
    return {"state": state, "questions": {"vote": {"type": "choice", "criteria": dict(list(items.items())[:26]),
                                                   "instructions": "Qui ce pêcheur choisit-il pour siéger au conseil de la "
                                                                   "vallée au nom de son village ?"}}}


# Le bilan d'un villageois qui n'était pas au conseil : ce que l'ancien lui en rapporte, et ce qu'il en pense de chacun.
DEBRIEF_MAX_TOKENS = 70
def debrief_schema(ids: list[str] | None = None) -> dict:
    return {"type": "object", "properties": {"confiance": trust_schema(ids)}, "required": ["confiance"],
            "additionalProperties": False}


DEBRIEF_SCHEMA = debrief_schema()


def debrief_messages(p, lines: list[str], trust: str, situation: str) -> list[dict]:
    who = (f"Tu es {p.name}, {p.archetype_label}, du village de {p.hamlet}. {p.experience} ans de pêche sur le lac. {p.traits} "
           "Réponds uniquement par un objet JSON.")
    body = ("Tu n'étais pas au conseil de la vallée, chez l'ancien : ton élu y parlait pour ton village. Voici ce que l'ancien "
            f"t'en rapporte, et ce que tu sais des autres pêcheurs :\n{_bullets(lines, 'rien de particulier')}\n{trust}\n"
            f"{situation}\nCe que tu apprends change-t-il ta confiance envers l'un d'eux, selon ta morale et tes intérêts ? "
            "Réponds en JSON : {\"confiance\": {\"<prénom>\": <de -3 à +3>}} (-3 : tu ne le crois plus du tout, +3 : il a "
            "gagné ta confiance ; {} si rien ne change).")
    return [{"role": "system", "content": who}, {"role": "user", "content": body}]


# La route de la patrouille du lac, décidée par son capitaine au début de la saison.
PATROL_MAX_TOKENS = 170


def patrol_schema(targets: list[str], legs: int, days: int) -> dict:
    step = {"type": "object", "properties": {"cible": {"enum": list(targets)}, "jours": {"type": "integer", "minimum": 1,
                                                                                        "maximum": days}},
            "required": ["cible", "jours"], "additionalProperties": False}
    return {"type": "object", "properties": {"raison": {"type": "string", "maxLength": 160},
                                             "etapes": {"type": "array", "items": step, "minItems": 1, "maxItems": legs}},
            "required": ["raison", "etapes"], "additionalProperties": False}


def patrol_messages(p, capacity: float, villages, lines: list[str], legs: int, days: int, world: str | None = None) -> list[dict]:
    body = (f"Une saison de pêche va s'ouvrir. Tu as {days} jours de mer à répartir sur {legs} étape{'s' if legs > 1 else ''} au plus. "
            f"Voici ce que tu sais, zone par zone :\n{_bullets(lines)}\n\n"
            "Une étape est une zone du lac (un village, ou « large ») où tu passes les jours que tu y mets, en mesurant les barques de "
            "ceux qui y pêchent ; ou un pêcheur que tu suis de près (son identifiant), que tu mesures où qu'il aille. Où vas-tu, "
            "combien de jours à chaque étape, et pourquoi ? Réponds en JSON : {\"raison\": \"<une phrase>\", \"etapes\": "
            "[{\"cible\": \"<zone ou identifiant>\", \"jours\": <nombre>}]}")
    return [{"role": "system", "content": persona(p, capacity, True, villages, world)}, {"role": "user", "content": body}]
