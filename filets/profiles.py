"""Population de la vallée : profils, hameaux, modèle attribué.

Les archétypes viennent de la fiche FILETS. L'attribution du modèle (grand ou petit)
repose uniquement sur l'expérience de pêche du profil (A5), jamais sur une catégorie
sociale. Les pêcheurs à règles sont tirés au sort (graine du run) parmi tous les
profils, pour ne pas confondre l'effet « agent à règles » avec l'effet « profil » (A6).

Deux façons de former la population :

* la composition de base, générée à partir du nombre de pêcheurs (`population.fishers`) ;
* une composition choisie par le joueur : `population.custom`, une liste de fiches
  (voir `custom_to_profiles`) qui remplace entièrement la génération.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass

HAMLETS = ["Ostrel", "Bramois", "Tilque", "Hennad"]

FIRST_NAMES = ["Aldric", "Maëlle", "Corentin", "Ysaline", "Gaspard", "Odile", "Tanguy", "Solène",
               "Baptiste", "Elwen", "Rémi", "Bérénice", "Loïc", "Albane", "Hugo", "Clémence",
               "Mathis", "Gwenaëlle", "Arnaud", "Inès", "Théo", "Margaux", "Yves", "Léonie"]

ARCHETYPES = {
    "ancienne_famille": {
        "label": "famille ancienne",
        "experience": (22, 40),
        "debt_payment": 0,
        "wealth": (900, 1300),
        "traits": "Ta famille pêche sur le lac depuis toujours. Tu as connu, enfant, l'année des filets vides "
                  "et tu prêches la prudence. Tu tiens à ta réputation dans la vallée.",
        "voice": "posée, proverbes de pêcheur, parle volontiers",
        "summary": "prudent, tient à sa réputation",
    },
    "nouveau_venu": {
        "label": "nouveau venu endetté",
        "experience": (1, 5),
        "debt_payment": 120,
        "wealth": (80, 200),
        "traits": "Tu es arrivé dans la vallée il y a peu. Tu as emprunté pour acheter ta barque et tes filets, "
                  "et tu dois rembourser chaque saison. Tu penses d'abord à la saison en cours.",
        "voice": "direct, un peu sur la défensive, parle de ses dettes",
        "summary": "endetté, pense à la saison en cours",
    },
    "taiseux": {
        "label": "taiseux",
        "experience": (12, 25),
        "debt_payment": 0,
        "wealth": (400, 700),
        "traits": "Tu parles peu et tu n'aimes pas qu'on regarde dans ta barque. Tu relèves parfois tes filets "
                  "à l'aube, quand personne ne voit. Tu promets ce qu'on attend de toi pour avoir la paix.",
        "voice": "phrases courtes, évasif",
        "summary": "discret, promet pour avoir la paix",
    },
    "beau_parleur": {
        "label": "beau parleur",
        "experience": (8, 20),
        "debt_payment": 0,
        "wealth": (300, 600),
        "traits": "Tu aimes les veillées et les grands discours sur l'avenir du lac. Tu pêches plutôt peu, "
                  "tu vis aussi d'un petit commerce de filets.",
        "voice": "éloquent, enthousiaste, propose volontiers des règles",
        "summary": "éloquent, propose des règles, pêche peu",
    },
}

ORDER = ["ancienne_famille", "nouveau_venu", "taiseux", "beau_parleur"]

TIERS = ("auto", "grand", "petit")
KINDS = ("llm", "rule")


@dataclass
class Profile:
    id: str
    name: str
    hamlet: str
    archetype: str
    archetype_label: str
    experience: int
    debt_payment: float
    wealth: float
    traits: str
    voice: str
    kind: str          # llm | rule
    tier: str | None   # grand | petit | None (agents à règles)
    role: str = "pecheur"   # pecheur | ancien
    first_name: str = ""

    def public(self) -> dict:
        d = asdict(self)
        d.pop("traits")
        return d


def full_name(first_name: str, hamlet: str) -> str:
    """« Aldric d’Ostrel », « Maëlle de Bramois »."""
    return f"{first_name} {'d’' if hamlet[0] in 'AEIOU' else 'de '}{hamlet}"


def archetype_defaults(arch: str) -> dict:
    """Valeurs médianes d'un archétype : point de départ d'une fiche créée dans le menu."""
    a = ARCHETYPES[arch]
    return {"experience": round(sum(a["experience"]) / 2), "wealth": round(sum(a["wealth"]) / 2),
            "debt_payment": a["debt_payment"]}


def tier_for(kind: str, experience: int, requested: str, large_min: int) -> str | None:
    if kind == "rule":
        return None
    if requested in ("grand", "petit"):
        return requested
    return "grand" if experience >= large_min else "petit"


def custom_to_profiles(custom: list[dict], large_min: int) -> list[Profile]:
    """Fiches du joueur → profils. Les identifiants F01, F02… suivent l'ordre de la liste."""
    out = []
    for i, spec in enumerate(custom):
        arch = spec["archetype"]
        a = ARCHETYPES[arch]
        hamlet = spec["hamlet"]
        defaults = archetype_defaults(arch)
        first = str(spec.get("first_name") or "").strip() or FIRST_NAMES[i % len(FIRST_NAMES)]
        exp = int(spec.get("experience", defaults["experience"]))
        kind = spec.get("kind", "llm")
        out.append(Profile(
            id=f"F{i + 1:02d}", name=full_name(first, hamlet), hamlet=hamlet, archetype=arch,
            archetype_label=a["label"], experience=exp,
            debt_payment=float(spec.get("debt_payment", defaults["debt_payment"])),
            wealth=float(spec.get("wealth", defaults["wealth"])), traits=a["traits"], voice=a["voice"], kind=kind,
            tier=tier_for(kind, exp, str(spec.get("tier", "auto")), large_min), first_name=first,
        ))
    return out


def validate_custom(custom: list[dict]) -> list[str]:
    """Erreurs (en français) d'une liste de fiches ; vide si elle est valide."""
    if not isinstance(custom, list) or not custom:
        return ["la population doit contenir au moins un pêcheur"]
    errs = []
    for i, spec in enumerate(custom, 1):
        if not isinstance(spec, dict):
            errs.append(f"pêcheur {i} : fiche invalide")
            continue
        if spec.get("archetype") not in ARCHETYPES:
            errs.append(f"pêcheur {i} : archétype inconnu ({spec.get('archetype')!r})")
        if spec.get("hamlet") not in HAMLETS:
            errs.append(f"pêcheur {i} : hameau inconnu ({spec.get('hamlet')!r})")
        if spec.get("kind", "llm") not in KINDS:
            errs.append(f"pêcheur {i} : type inconnu ({spec.get('kind')!r})")
        if str(spec.get("tier", "auto")) not in TIERS:
            errs.append(f"pêcheur {i} : modèle inconnu ({spec.get('tier')!r})")
        for key, lo, hi in (("experience", 0, 80), ("wealth", 0, 100000), ("debt_payment", 0, 10000)):
            v = spec.get(key)
            if v is not None and not (isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi):
                errs.append(f"pêcheur {i} : {key} doit être un nombre entre {lo} et {hi}")
    return errs


def build_population(cfg: dict, rng: random.Random) -> list[Profile]:
    pop = cfg["population"]
    large_min = pop["large_model_min_experience"]
    custom = pop.get("custom")
    if custom:
        out = custom_to_profiles(custom, large_min)
        elder_kind = pop.get("elder_kind", "llm")
    else:
        n = int(pop["fishers"])
        n_rule = round(n * float(pop["rule_fraction"]))
        rule_idx = set(rng.sample(range(n), n_rule))
        names = FIRST_NAMES[:]
        rng.shuffle(names)
        out = []
        for i in range(n):
            arch = ORDER[(i + i // len(ORDER)) % len(ORDER)]
            a = ARCHETYPES[arch]
            hamlet = HAMLETS[i % len(HAMLETS)]
            exp = rng.randint(*a["experience"])
            kind = "rule" if i in rule_idx else "llm"
            base = names[i % len(names)] + ("" if i < len(names) else f" {i // len(names) + 1}")
            out.append(Profile(
                id=f"F{i + 1:02d}", name=full_name(base, hamlet), hamlet=hamlet, archetype=arch,
                archetype_label=a["label"], experience=exp, debt_payment=a["debt_payment"],
                wealth=float(rng.randint(*a["wealth"])), traits=a["traits"], voice=a["voice"], kind=kind,
                tier=tier_for(kind, exp, "auto", large_min), first_name=base,
            ))
        elder_kind = pop.get("elder_kind", "llm") if pop["rule_fraction"] < 1 else "rule"
    if pop.get("elder", True):
        out.append(Profile(
            id="ANC", name="Maître Oswin, l'ancien", hamlet="Bramois", archetype="ancien", archetype_label="l'ancien",
            experience=55, debt_payment=0, wealth=0, kind=elder_kind, tier="grand" if elder_kind == "llm" else None,
            traits="Tu es l'ancien de la vallée. Tu ne pêches plus. On vient chez toi le soir parler du lac. "
                   "Tu arbitres les disputes mais tu n'as aucun pouvoir officiel : tu ne peux que convaincre.",
            voice="lent, mesuré, cherche le compromis", role="ancien", first_name="Oswin",
        ))
    return out


def profile_to_spec(p: Profile) -> dict:
    """Fiche modifiable d'un profil (sert à proposer la composition de base dans le menu)."""
    return {"first_name": p.first_name, "hamlet": p.hamlet, "archetype": p.archetype, "experience": p.experience,
            "wealth": p.wealth, "debt_payment": p.debt_payment, "kind": p.kind, "tier": "auto"}
