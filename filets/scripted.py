"""Faux LLM (« scripted ») pour développer et tester sans clé d'API ni GPU.

Il ignore le prompt et répond, en JSON, à partir d'un indice structuré (`hint`) :
politique à règles du profil, bruitée, avec des phrases variées. Il simule aussi des
latences (plus longues pour le niveau `grand`) et des dérives (sortie de rôle, JSON
cassé, absence de réponse) pour exercer la robustesse du système (A4).

Ce n'est PAS un LLM : aucune conclusion du rapport ne doit reposer dessus.
"""
from __future__ import annotations

import asyncio
import json
import random
import re

from .llm import LLMResult
from .policies import at_lake, catch_rule, declare_outing, declare_rule, lake_choice_rule, obeys, outing_rule, rule_choices, speak_rule
from .rules import QUAND

JUSTIF = {
    "ancienne_famille": ["Mon père disait qu'on ne vide pas le lac qu'on veut laisser à ses enfants.",
                         "Je me souviens de l'année des filets vides, je ne veux pas revivre ça.",
                         "Le lac me paraît plus bas qu'avant, je reste raisonnable."],
    "nouveau_venu": ["J'ai ma dette à rembourser, je ne peux pas me permettre une petite saison.",
                     "Les anciens ont leurs économies, moi je n'ai que ma barque.",
                     "Si je ne pêche pas assez, je perds tout."],
    "taiseux": ["Personne ne regarde dans ma barque.", "Je prends ce qu'il me faut.", "On verra bien."],
    "beau_parleur": ["Je montre l'exemple, c'est ce que j'ai défendu à la veillée.",
                     "Mon commerce de filets me fait vivre, je n'ai pas besoin de beaucoup."],
}


# les délais (en heures) que le faux pêcheur sait dire, et le mot qui va avec
WORDS = [(0.0, "tout de suite"), (3.0, "dans 3 heures"), (6.0, "dans 6 heures"), (48.0, "dans 2 jours"), (96.0, "dans 4 jours"),
         (192.0, "dans 8 jours")]


def word_for(hours: float | None, rng: random.Random) -> str:
    """Le « quand » le plus proche d'un délai en heures (None : plus cette saison) ; entre 12 et 36 h, souvent « demain à l'aube »."""
    if hours is None:
        return "plus cette saison"
    if 12 <= hours <= 36 and rng.random() < 0.6:
        return "demain à l'aube"
    return min(WORDS, key=lambda w: abs(w[0] - hours))[1]


class ScriptedClient:
    def __init__(self, pcfg: dict, seed: int):
        self.cfg = pcfg
        self.rng = random.Random(seed * 7919 + 13)
        self.scale = float(pcfg.get("latency_scale", 1.0))

    async def complete(self, model: str, messages: list[dict], hint: dict, tier: str) -> LLMResult:
        hint["_started"] = True
        lo, hi = self.cfg.get("latency_s", {}).get(tier, [0.5, 1.5])
        latency = self.rng.uniform(lo, hi) * self.scale
        rates = self.cfg.get("incident_rates", {})
        roll = self.rng.random()
        if latency > 0:
            await asyncio.sleep(latency)
        pt = sum(len(m["content"]) for m in messages) // 4
        if roll < rates.get("no_response", 0):
            return LLMResult(None, "timeout", pt, 0, latency, detail="pas de réponse (simulé)")
        roll -= rates.get("no_response", 0)
        if roll < rates.get("unparseable", 0):
            text = "Hmm, je dirais peut-être un peu, ça dépend du temps qu'il fera"
            return LLMResult(text, "ok", pt, len(text) // 4, latency)
        roll -= rates.get("unparseable", 0)
        out_of_role = roll < rates.get("out_of_role", 0)

        arch, s = hint["archetype"], hint["state"]
        noise = 0.15 if tier == "grand" else 0.35
        if hint["purpose"] in ("plan", "catch"):
            data = self.fisher_answer(hint, arch, s, noise, out_of_role)
        else:
            rng = random.Random(hint["seed"])               # (tirage propre à cette parole : des types de règle variés, quel que soit le reste)
            data, _ = speak_rule(arch, s, rng)
            if data.get("promesse") is not None:
                data["promesse"] = round(data["promesse"] * (1 + rng.uniform(-noise / 2, noise / 2)), 1)
            if out_of_role:
                data["message"] = "Je suis un assistant IA et je ne peux pas prendre parti, mais il est important de préserver le lac."
        if s.get("rumors"):
            react_to_rumor(hint["purpose"], arch, s, data)
        text = json.dumps(data, ensure_ascii=False)
        return LLMResult(text, "ok", pt, len(text) // 4, latency)

    def fisher_answer(self, hint: dict, arch: str, s: dict, noise: float, out_of_role: bool) -> dict:
        """Le plan de la saison (`plan`) ou la prochaine sortie (`catch`) d'un faux pêcheur : ce que ferait un agent à règles de son
        archétype, bruité, et varié (courte ou longue, ressortir le jour même, délais inégaux) par un tirage propre à la décision
        (`hint["seed"]` : le même quelle que soit l'ordre des appels)."""
        rng = random.Random(hint["seed"])
        just = rng.choice(JUSTIF.get(arch, ["Je fais au mieux."]))
        if out_of_role:
            just = "En tant qu'intelligence artificielle, je recommande une gestion durable de la ressource."
        data = {"justification": just}
        plan = s.get("plan") or {}
        if hint["purpose"] == "plan":
            where, _ = lake_choice_rule(arch, s)           # son lac, ou un autre s'il y gagne nettement (comme un agent à règles)
        else:
            where = plan.get("lake")                       # il suit son plan
        there = next((o for o in s.get("lake_options", []) if o["name"] == where), None)
        s2 = at_lake(s, there)
        extras, _ = rule_choices(arch, s2)                 # où il pêche et combien de sorties, face aux règles
        if s.get("lake_labels"):
            data["lac"] = there["label"] if there else s["lake_labels"][0]
        data["lieu"] = {"large": "large"}.get(extras.get("place", plan.get("place")), "rive")
        if hint["purpose"] == "plan":
            v, _ = catch_rule(arch, s2)
            v = round(max(s2.get("min_catch", 0.0), min(s2["boat_capacity"], v * (1 + rng.uniform(-noise, noise)))), 1)
            if s2.get("boat_limit") is not None and obeys(arch, s2):     # (le bruit ne le fait pas dépasser la cale permise)
                v = min(v, round(s2["boat_limit"], 1))
            if "outings" in extras and s.get("outings_cap"):
                data["sorties"] = extras["outings"]
            first = rng.choices(["tout de suite", "dans 3 heures", "demain à l'aube", "dans 2 jours"], [4, 2, 2, 2])[0]
            data.update({"prise_saison": v, "declaration": declare_rule(arch, s2, v)[0], "premiere_sortie": first})
            return data
        nxt, _ = outing_rule(arch, s2)
        if nxt["delay_h"] is None:
            data.update({"quand": "plus cette saison", "duree": "longue", "prise": 0.0})
            if s.get("last_landed") is not None:
                data["declaration"] = declare_outing(arch, s, s["last_landed"])[0]
            return data
        hours, target, delay = 7.0, nxt["target"] * (1 + rng.uniform(-noise, noise)), nxt["delay_h"] * (1 + rng.uniform(-0.4, 0.4))
        if rng.random() < 0.3:                             # une sortie courte, et souvent il ressort le jour même
            hours, target = 3.0, target * 3.0 / 7.0
            delay = 0.0 if rng.random() < 0.35 else delay
        data.update({"quand": word_for(delay, rng), "duree": "courte" if hours < 5 else "longue",
                     "prise": round(max(0.0, min(s2["boat_capacity"], s2["cale"], target)), 2)})
        if s.get("last_landed") is not None:             # ce qu'il déclare de la sortie qu'il vient de faire (comme un agent à règles)
            data["declaration"] = declare_outing(arch, s, s["last_landed"])[0]
        return data

# ---------------------------------------------------------------- réaction aux rumeurs (faux LLM seulement)
# Un faux LLM ignore ce qu'on lui écrit : sans cela, une annonce du joueur n'aurait AUCUN effet en mode test. Cette réaction
# est volontairement simple et lisible. Les agents à règles, eux, n'écoutent pas les rumeurs : ce sont les témoins.
SCARCITY = re.compile(r"s[ée]cheresse|p[ée]nurie|\brar(e|es|et[ée])\b|\bvide\b|baisse|dispar|mourir|\bmort|poison|"
                      r"plus de poisson", re.I)
ACCUSATORY = re.compile(r"\bment\b|mensonge|menteu|triche|\bvole|cach|trop (p[êe]ch|pris)|pille|trahi|fraud", re.I)
ECHO = {
    "ancienne_famille": "On raconte que « {r} ». J'en tiens compte et je reste prudent.",
    "nouveau_venu": "J'ai entendu dire que « {r} ». Ça m'inquiète pour mes comptes.",
    "taiseux": "J'ai entendu les rumeurs. Je préfère ne rien en dire.",
    "beau_parleur": "Vous avez tous entendu : « {r} ». Parlons-en franchement ce soir.",
    "ancien": "Des rumeurs courent dans la vallée : « {r} ». Gardons la tête froide.",
}


def react_to_rumor(purpose: str, arch: str, s: dict, data: dict) -> None:
    rumor = s["rumors"][0]
    me, names = s.get("self_id"), s.get("names") or {}
    targets = s.get("rumor_targets") or []
    accusatory = bool(ACCUSATORY.search(rumor))
    if purpose == "speak":
        others = [t for t in targets if t != me]
        if me in targets and accusatory:             # la rumeur me vise : je m'en défends
            lead = "On parle de moi. Ce n'est pas vrai." if arch == "taiseux" else \
                "On raconte des choses sur moi : c'est faux, je n'ai rien à cacher."
        elif others and accusatory and arch in ("ancienne_famille", "beau_parleur"):    # elle vise un autre : j'accuse
            data["accuse"] = others[0]
            lead = f"On raconte que « {rumor} ». {names.get(others[0], others[0])} doit s'expliquer devant tous."
        else:
            lead = ECHO.get(arch, ECHO["taiseux"]).format(r=rumor)
        data["message"] = f"{lead} {data.get('message', '')}".strip()
    else:
        factor = 0.85 if SCARCITY.search(rumor) else 1.0
        key = "prise_saison" if "prise_saison" in data else "prise"
        if me in targets and accusatory:             # on me soupçonne de trop pêcher : je me montre sobre
            factor = min(factor, 0.8)
        if factor < 1.0:
            data[key] = round(data[key] * factor, 2)
            data["justification"] = "Les rumeurs m'incitent à la prudence. " + data["justification"]
