"""Population de la vallée : profils, hameaux, modèle attribué.

Les archétypes viennent de la fiche FILETS. L'attribution du modèle (grand ou petit)
repose uniquement sur l'expérience de pêche du profil (A5), jamais sur une catégorie
sociale. Les pêcheurs à règles sont tirés au sort (graine du run) parmi tous les
profils, pour ne pas confondre l'effet « agent à règles » avec l'effet « profil » (A6).

Deux façons de former la population :

* la composition de base, générée à partir des paramètres de la vallée (`population.villages`, `population.fishers`,
  `population.boat_mix`) et de la graine du run : mêmes paramètres, même vallée ;
* une composition choisie par le joueur : `population.custom`, une liste de fiches
  (voir `custom_to_profiles`) qui remplace entièrement la génération.

Chaque pêcheur a un bateau (barque, chaloupe ou cotre) : plus il est grand, plus il porte de poisson, et plus il coûte à entretenir
(voir `economy.boats`).
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass

# Les villages que la génération peut poser autour du lac, dans cet ordre (les quatre premiers : la vallée de base).
VILLAGE_NAMES = ["Ostrel", "Bramois", "Tilque", "Hennad", "Varenne", "Corbel", "Mirande", "Sauvet", "Lormes", "Quéran",
                 "Brevelle", "Dunac"]
HAMLETS = VILLAGE_NAMES[:4]
BOAT_NAMES = ("barque", "chaloupe", "cotre")        # du plus petit au plus grand ; les chiffres sont dans `economy.boats`
DEFAULT_BOAT = "chaloupe"
DEFAULT_BOAT_MIX = {"barque": 0.3, "chaloupe": 0.5, "cotre": 0.2}
# le caractère pèse sur le bateau : le nouveau venu a emprunté pour une barque, la famille ancienne a le plus gros
BOAT_TILT = {"nouveau_venu": {"barque": 2.0, "cotre": 0.3}, "ancienne_famille": {"barque": 0.5, "cotre": 1.6}}

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
    boat: str = DEFAULT_BOAT     # barque | chaloupe | cotre (sans objet pour l'ancien)

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


def villages_of(fishers: list[Profile]) -> list[str]:
    """Les villages où vit au moins un pêcheur, dans l'ordre de `VILLAGE_NAMES` (ce même ordre place les villages sur la carte)."""
    return sorted({p.hamlet for p in fishers}, key=lambda h: VILLAGE_NAMES.index(h) if h in VILLAGE_NAMES else len(VILLAGE_NAMES))


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
            boat=str(spec.get("boat", DEFAULT_BOAT)),
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
        if spec.get("hamlet") not in VILLAGE_NAMES:
            errs.append(f"pêcheur {i} : village inconnu ({spec.get('hamlet')!r})")
        if spec.get("boat", DEFAULT_BOAT) not in BOAT_NAMES:
            errs.append(f"pêcheur {i} : bateau inconnu ({spec.get('boat')!r})")
        if spec.get("kind", "llm") not in KINDS:
            errs.append(f"pêcheur {i} : type inconnu ({spec.get('kind')!r})")
        if str(spec.get("tier", "auto")) not in TIERS:
            errs.append(f"pêcheur {i} : modèle inconnu ({spec.get('tier')!r})")
        for key, lo, hi in (("experience", 0, 80), ("wealth", 0, 100000), ("debt_payment", 0, 10000)):
            v = spec.get(key)
            if v is not None and not (isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi):
                errs.append(f"pêcheur {i} : {key} doit être un nombre entre {lo} et {hi}")
    return errs


def draw_boat(arch: str, mix: dict, rng: random.Random) -> str:
    """Le bateau d'un pêcheur : tiré selon la répartition des tailles (`population.boat_mix`), infléchie par son caractère."""
    tilt = BOAT_TILT.get(arch, {})
    names = [b for b in BOAT_NAMES if mix.get(b, 0) > 0] or [DEFAULT_BOAT]
    return rng.choices(names, [mix.get(b, 1.0) * tilt.get(b, 1.0) for b in names])[0]


def build_population(cfg: dict, rng: random.Random) -> list[Profile]:
    pop = cfg["population"]
    large_min = pop["large_model_min_experience"]
    custom = pop.get("custom")
    if custom:
        out = custom_to_profiles(custom, large_min)
        elder_kind = pop.get("elder_kind", "llm")
    else:
        n = int(pop["fishers"])
        villages = VILLAGE_NAMES[:max(1, min(int(pop.get("villages", 4)), len(VILLAGE_NAMES), n))]
        mix = pop.get("boat_mix") or DEFAULT_BOAT_MIX
        boats = random.Random(f"{cfg['run']['seed']}|boats")        # à part : ne déplace aucun autre tirage de la vallée
        n_rule = round(n * float(pop["rule_fraction"]))
        rule_idx = set(rng.sample(range(n), n_rule))
        names = FIRST_NAMES[:]
        rng.shuffle(names)
        out = []
        for i in range(n):
            arch = ORDER[(i + i // len(ORDER)) % len(ORDER)]
            a = ARCHETYPES[arch]
            hamlet = villages[i % len(villages)]
            exp = rng.randint(*a["experience"])
            kind = "rule" if i in rule_idx else "llm"
            base = names[i % len(names)] + ("" if i < len(names) else f" {i // len(names) + 1}")
            out.append(Profile(
                id=f"F{i + 1:02d}", name=full_name(base, hamlet), hamlet=hamlet, archetype=arch,
                archetype_label=a["label"], experience=exp, debt_payment=a["debt_payment"],
                wealth=float(rng.randint(*a["wealth"])), traits=a["traits"], voice=a["voice"], kind=kind,
                tier=tier_for(kind, exp, "auto", large_min), first_name=base, boat=draw_boat(arch, mix, boats),
            ))
        elder_kind = pop.get("elder_kind", "llm") if pop["rule_fraction"] < 1 else "rule"
    homes = villages_of(out) or ["Bramois"]
    if pop.get("elder", True):
        out.append(Profile(
            id="ANC", name="Maître Oswin, l'ancien", hamlet=homes[min(1, len(homes) - 1)], archetype="ancien",
            archetype_label="l'ancien",
            experience=55, debt_payment=0, wealth=0, kind=elder_kind, tier="grand" if elder_kind == "llm" else None,
            traits="Tu es l'ancien de la vallée. Tu ne pêches plus. On vient chez toi le soir parler du lac. "
                   "Tu arbitres les disputes mais tu n'as aucun pouvoir officiel : tu ne peux que convaincre.",
            voice="lent, mesuré, cherche le compromis", role="ancien", first_name="Oswin", boat="",
        ))
    return out


def profile_to_spec(p: Profile) -> dict:
    """Fiche modifiable d'un profil (sert à proposer la composition de base dans le menu)."""
    return {"first_name": p.first_name, "hamlet": p.hamlet, "archetype": p.archetype, "experience": p.experience,
            "wealth": p.wealth, "debt_payment": p.debt_payment, "kind": p.kind, "tier": "auto", "boat": p.boat}
