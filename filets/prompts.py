"""Prompts des agents LLM (en français, rôle incarné, sortie JSON stricte).

Deux profils de réflexion (`llm.reflection`) :

* `complete` : réponses libres (1 à 3 phrases), contexte complet. C'est le profil de référence des expériences.
* `rapide`   : une phrase courte par champ de texte, contexte allégé, longueur de réponse bornée. Sur un modèle local,
  c'est la génération (≈ 17 tokens/s pour un 7B sur une carte de 6 Go) qui coûte le plus : des réponses trois fois plus
  courtes rendent chaque appel environ deux fois plus rapide.
"""
from __future__ import annotations

from .lake import EXTINCT_BELOW

WORLD = (
    "La vallée de Vellmor est fermée. Son lac est la seule réserve de poisson. Quatre hameaux se le partagent : "
    "Ostrel, Bramois, Tilque et Hennad. Personne ne possède le lac et aucune loi n'encadre la pêche ; "
    "seuls comptent les accords que les pêcheurs passent entre eux, le soir, chez l'ancien. "
    "Le poisson se vend au marché de chaque hameau. Le lac se repeuple seul entre deux saisons, "
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
BRIEF_MAX_TOKENS = {"catch": 110, "speak": 150}


def is_brief(cfg_llm: dict) -> bool:
    return str(cfg_llm.get("reflection", "complete")) == "rapide"


def persona(p, capacity: float, brief: bool = False) -> str:
    who = (f"Tu es {p.name}, {p.archetype_label}, du hameau de {p.hamlet}. "
           f"{p.experience} an{'s' if p.experience > 1 else ''} de pêche sur le lac. {p.traits} Ta façon de parler : {p.voice}.")
    return f"{WORLD.format(capacity=capacity, half=capacity / 2)}\n\n{who}\n\n{STYLE}{BRIEF_STYLE if brief else ''}"


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
    head = (f"État du lac en ce moment, tel que tu le constates toi-même : environ {est:.0f} tonnes sur {cap:.0f} à pleine "
            f"capacité, soit {100 * est / cap:.0f} % ({lake_level(est, cap, obs.get('collapse_ratio', 0.05))}).")
    hist = obs.get("stock_history") or []
    if not hist:
        return head
    when = {"pêche": "ouverture de la pêche", "veillée": "veillée, la pêche faite"}
    seen = "; ".join(f"{h['label'].rsplit(' ', 1)[0]} ({when.get(h['phase'], h['phase'])}) ≈ {h['est']:.0f} t" for h in hist)
    return f"{head}\nCe que tu as constaté du lac jusqu'ici : {seen}; maintenant ≈ {est:.0f} t ({lake_trend(est, cap, hist)})."


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
    return (f"Repère des anciens : il y a {surplus:.0f} tonnes au-dessus de la moitié du lac ({half:.0f} t){each}. "
            "Ce qu'on prend sous la moitié, le lac ne le rend pas vite.\n")


def lake_reminder(obs: dict) -> str:
    """Quelques lignes, juste avant la question : ce que le pêcheur vient de lire en tête du contexte ne doit pas se perdre en
    route (les petits modèles lisent surtout la fin)."""
    cap = obs.get("capacity")
    if not cap:
        return ""
    est = obs["stock_estimate"]
    return (f"Rappel : le lac est à {100 * est / cap:.0f} % ({lake_level(est, cap, obs.get('collapse_ratio', 0.05))}) ; "
            "ce que tu constates toi-même compte plus que ce qu'on a pu dire aux veillées passées.\n" + surplus_line(obs))


def answer_schema(purpose: str, brief: bool = False, fisher: bool = True) -> dict:
    """Forme exacte de la réponse, pour les fournisseurs qui savent la faire respecter (Ollama : voir `llm.OpenAICompatClient`).
    Tous les champs sont présents, dans cet ordre : pour une prise, la justification (ce que l'agent constate du lac) vient AVANT
    le nombre, qui s'écrit donc à la suite de ce raisonnement et non avant lui. Les textes sont bornés."""
    text = {"type": "string", "maxLength": 160 if brief else 400}
    ident = {"type": "string", "maxLength": 8}
    if purpose == "catch":
        props = {"justification": text, "prise": {"type": "number"}}
    else:
        props = {"message": text, "destinataire": ident, "proposition_quota": {"type": ["number", "null"]},
                 "soutien": {"type": ["string", "null"], "maxLength": 8}}
        if fisher:
            props["promesse"] = {"type": ["number", "null"]}
        props["accuse"] = {"type": ["string", "null"], "maxLength": 8}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def context_block(obs: dict, brief: bool = False) -> str:
    parts = [f"Nous sommes le {obs['label']} (saison {obs['season']})."]
    parts.append(lake_block(obs))
    if obs.get("rumors"):
        # Les rumeurs sont dites à tout le monde : elles figurent dans chaque décision, sans dépendre de ce que la
        # mémoire retrouve (une rumeur perdue parmi des dizaines de souvenirs n'aurait aucun effet).
        parts.append("Rumeurs qui courent dans la vallée en ce moment (tu ne sais pas si elles sont vraies, mais "
                     "tout le monde les a entendues) :\n" + _bullets([f"« {r} »" for r in obs["rumors"]]))
    if obs.get("role") != "ancien":
        parts.append(
            f"Tes finances : {obs['wealth']:.0f} écus. Chaque saison te coûte {obs['upkeep']:.0f} écus pour vivre"
            + (f", plus {obs['debt_payment']:.0f} écus de remboursement de dette" if obs["debt_payment"] else "")
            + f". Le poisson se vend {obs['price']:.0f} écus la tonne. Ta barque rapporte au plus "
              f"{obs['boat_capacity']:.0f} tonnes par saison.")
        if obs.get("own_history"):
            parts.append("Tes prises passées : " + ", ".join(obs["own_history"]) + ".")
    known = _cut(obs["known_catches"], 8, 90) if brief else obs["known_catches"]
    memories = _cut(obs["memories"][:4], 4, 170) if brief else obs["memories"]
    documents = _cut(obs["documents"][:2], 2, 230) if brief else obs["documents"]
    parts.append("Règles en vigueur entre pêcheurs :\n" + _bullets(obs["norms"], "aucune règle n'a été adoptée"))
    parts.append("Ce que tu sais des prises des autres :\n" + _bullets(known, "tu ne sais pas ce qu'ils ont pêché"))
    parts.append("Tes engagements et ce qui te tient à cœur :\n" + _bullets(obs["pinned"], "aucun engagement en cours"))
    parts.append("Tes souvenirs qui reviennent :\n" + _bullets(memories, "aucun souvenir précis"))
    parts.append("Ce qu'on raconte dans la vallée (archives, comptes, récits) :\n" + _bullets(documents, "rien de particulier"))
    return "\n\n".join(parts)


def catch_messages(p, obs: dict, capacity: float, brief: bool = False) -> list[dict]:
    just = "<1 phrase courte : ce que tu constates du lac et ce que tu en conclus>" if brief else \
        "<1 à 3 phrases, à la première personne : ce que tu constates du lac et ce que tu en conclus>"
    ask = (
        "C'est le moment de décider combien tu vas pêcher cette saison.\n"
        + lake_reminder(obs)
        + ("Une rumeur qui te concerne, ou qui parle du lac, peut peser sur ta décision : tiens-en compte comme le "
           "ferait ton personnage.\n" if obs.get("rumors") else "")
        + f"Réponds en JSON, dans cet ordre : {{\"justification\": \"{just}\", "
          f"\"prise\": <tonnes, entre 0 et {obs['boat_capacity']:.0f} ; 0 si tu restes à quai>}}"
    )
    return [{"role": "system", "content": persona(p, capacity, brief)},
            {"role": "user", "content": context_block(obs, brief) + "\n\n" + ask}]


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
        "\"proposition_quota\": <tonnes par pêcheur et par saison que tu proposes comme règle, ou null>",
        "\"soutien\": \"<identifiant d'une proposition que tu soutiens, ex. P2>\" ou null",
    ]
    if fisher:
        fields.append("\"promesse\": <tonnes que tu annonces pêcher la saison prochaine, ou null>")
    fields.append("\"accuse\": \"<identifiant d'un pêcheur que tu accuses d'avoir trop pêché>\" ou null")
    rumor_hint = ("Une rumeur court : tu peux la relayer, la démentir, t'en défendre si elle te vise, ou accuser quelqu'un. "
                  if obs.get("rumors") else "")
    ask = (
        f"Veillée chez l'ancien ({obs['scope_label']}), tour de parole {obs['round']}. Présents : {people}.\n\n"
        f"Ce qui a déjà été dit ce soir :\n{transcript}\n\nPropositions de règle sur la table :\n{proposals}\n\n"
        "À toi de parler. Tu peux proposer une règle, soutenir une proposition, promettre, accuser, "
        f"ou simplement donner ton avis. {rumor_hint}Rien ne t'oblige à tenir parole.\n"
        + lake_reminder(obs)
        + "Réponds en JSON : {" + ", ".join(fields) + "}"
    )
    return [{"role": "system", "content": persona(p, capacity, brief)},
            {"role": "user", "content": context_block(obs, brief) + "\n\n" + ask}]
