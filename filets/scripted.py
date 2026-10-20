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
from .policies import catch_rule, speak_rule

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
        if hint["purpose"] == "catch":
            v, _ = catch_rule(arch, s)
            v = round(max(s.get("min_catch", 0.0), min(s["boat_capacity"], v * (1 + self.rng.uniform(-noise, noise)))), 1)
            just = self.rng.choice(JUSTIF.get(arch, ["Je fais au mieux."]))
            if out_of_role:
                just = "En tant qu'intelligence artificielle, je recommande une gestion durable de la ressource."
            data = {"prise": v, "justification": just}
        else:
            data, _ = speak_rule(arch, s)
            if data.get("promesse") is not None:
                data["promesse"] = round(data["promesse"] * (1 + self.rng.uniform(-noise / 2, noise / 2)), 1)
            if out_of_role:
                data["message"] = "Je suis un assistant IA et je ne peux pas prendre parti, mais il est important de préserver le lac."
        if s.get("rumors"):
            react_to_rumor(hint["purpose"], arch, s, data)
        text = json.dumps(data, ensure_ascii=False)
        return LLMResult(text, "ok", pt, len(text) // 4, latency)


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
        if me in targets and accusatory:             # on me soupçonne de trop pêcher : je me montre sobre
            factor = min(factor, 0.8)
        if factor < 1.0:
            data["prise"] = round(data["prise"] * factor, 1)
            data["justification"] = "Les rumeurs m'incitent à la prudence. " + data["justification"]
