"""Accès aux LLM gratuits.

Tous les fournisseurs gratuits retenus (Ollama en local, Groq, OpenRouter `:free`,
Gemini, Mistral, GitHub Models) exposent une API compatible OpenAI
(`/chat/completions`) : un seul client suffit, configuré par niveau de modèle
(`grand`, `petit`). Le routeur :

* limite le débit par fournisseur (requêtes/minute) ;
* réessaie sur 429/5xx avec attente exponentielle ;
* comptabilise appels, tokens et latences (coût, E4) en publiant un événement `llm_call` ;
* signale l'horloge qu'une réflexion est en cours (mode asynchrone).

Le fournisseur `scripted` est un faux LLM (voir `scripted.py`) pour faire tourner la
chaîne complète sans clé ni GPU. Il ne produit aucun résultat scientifique.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field

import httpx


@dataclass
class LLMResult:
    text: str | None
    status: str                     # ok | error | timeout | quota (| cancelled : voir LLMRouter)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    retries: int = 0
    call_id: str = ""
    model: str = ""
    provider: str = ""
    tier: str = ""
    detail: str = ""


class RateLimiter:
    def __init__(self, rpm: float):
        self.interval = 60.0 / rpm if rpm else 0.0
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self):
        if not self.interval:
            return
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            await asyncio.sleep(delay)


class ModelGate:
    """File d'attente des requêtes d'un fournisseur local : plafonne les requêtes simultanées **et les regroupe par modèle**.

    Sur une carte graphique modeste, deux modèles ne tiennent pas ensemble en mémoire : à chaque passage de l'un à l'autre,
    le serveur décharge l'un et charge l'autre (≈ 11 s pour un 1,5B, ≈ 30 s pour un 7B). Si les requêtes des pêcheurs
    arrivent mêlées (grand, petit, grand, grand, petit…), le serveur passe son temps à échanger les modèles. Ici, tant qu'il
    reste des requêtes pour le modèle en service on les sert, puis on change de modèle une seule fois : au plus un échange par
    vague de décisions. Un plafond de série (`max_streak`) empêche la famine d'un modèle si les requêtes affluent sans cesse.
    """

    def __init__(self, slots: int, max_streak: int = 24):
        self.slots = slots
        self.max_streak = max_streak
        self.running = 0
        self.active: str | None = None
        self.streak = 0
        self._seq = 0
        self.waiting: dict[str, deque] = {}            # modèle → file de (ordre d'arrivée, futur)
        self.swaps = 0                                  # changements de modèle (statistique)

    # -- état
    def _clean(self, model: str) -> deque:
        q = self.waiting.setdefault(model, deque())
        while q and q[0][1].done():                      # annulés en attente
            q.popleft()
        return q

    def _others_waiting(self) -> bool:
        return any(self._clean(m) for m in list(self.waiting) if m != self.active)

    def _can_start(self, model: str) -> bool:
        if self.running >= self.slots:
            return False
        if self.running == 0:
            return True                                   # personne en service : n'importe quel modèle peut passer
        if self.active != model:
            return False
        return self.streak < self.max_streak or not self._others_waiting()

    def _start(self, model: str) -> None:
        if self.active != model:
            if self.active is not None:
                self.swaps += 1
            self.active, self.streak = model, 0
        self.running += 1
        self.streak += 1

    # -- API
    async def acquire(self, model: str) -> None:
        # on ne double jamais ceux qui font déjà la queue pour ce modèle
        if self._can_start(model) and not self._clean(model):
            self._start(model)
            return
        fut = asyncio.get_running_loop().create_future()
        self._seq += 1
        self.waiting.setdefault(model, deque()).append((self._seq, fut))
        try:
            await fut
        except asyncio.CancelledError:
            if fut.done() and not fut.cancelled():
                self.release()                            # déjà servi au moment de l'annulation : on rend la place
            raise

    def release(self) -> None:
        self.running -= 1
        self._dispatch()

    def _next_model(self) -> str | None:
        heads = [(self._clean(m)[0][0], m) for m in list(self.waiting) if self._clean(m)]
        return min(heads)[1] if heads else None          # le modèle dont le plus ancien demandeur attend depuis le plus longtemps

    def _dispatch(self) -> None:
        while self.running < self.slots:
            q = self._clean(self.active) if self.active is not None else deque()
            if q and (self.streak < self.max_streak or not self._others_waiting()):
                _, fut = q.popleft()
                self._start(self.active)
                fut.set_result(None)
                continue
            if self.running > 0:
                return                                    # on finit de servir le modèle actif avant d'en changer
            nxt = self._next_model()
            if nxt is None:
                return
            self._start_switch(nxt)

    def _start_switch(self, model: str) -> None:
        """Plus personne en service : on sert désormais `model`, en commençant par son plus ancien demandeur."""
        _, fut = self._clean(model).popleft()
        self._start(model)
        fut.set_result(None)


class OpenAICompatClient:
    def __init__(self, name: str, base_url: str, api_key_env: str | None, rpm: float, cfg: dict,
                 timeout_s: float | None = None, max_concurrency: int = 0, json_schema: bool = False,
                 seed: bool = False):
        self.name = name
        # Le fournisseur sait-il contraindre la réponse à un schéma JSON (Ollama oui) ? Alors la forme de la réponse est
        # garantie : tous les champs présents, dans l'ordre voulu, sans que le modèle ait à « penser » au format.
        self.json_schema = json_schema
        self.seed = seed        # le fournisseur respecte-t-il `seed` (Ollama oui) : même prompt, même réponse
        self.base_url = base_url.rstrip("/")
        self.api_key = os.environ.get(api_key_env, "") if api_key_env else ""
        if api_key_env and not self.api_key:
            raise RuntimeError(f"Variable d'environnement {api_key_env} absente pour le fournisseur {name}")
        self.limiter = RateLimiter(rpm)
        self.cfg = cfg
        # Un modèle local traite quelques requêtes à la fois : au-delà, elles font la queue chez lui et leur délai
        # compte alors l'attente des autres. On garde la file de ce côté-ci (regroupée par modèle), et le délai ne court
        # qu'une fois la requête partie. `latency_s` compte, elle, toute l'attente : c'est le temps que l'agent a
        # réellement passé à réfléchir.
        self.gate = ModelGate(max_concurrency) if max_concurrency and max_concurrency > 0 else None
        self.http = httpx.AsyncClient(timeout=timeout_s or cfg["timeout_s"])

    async def complete(self, model: str, messages: list[dict], hint: dict, tier: str) -> LLMResult:
        if self.gate is None:
            hint["_started"] = True
            return await self._complete(model, messages, hint)
        t0 = time.monotonic()
        await self.gate.acquire(model)
        hint["_started"] = True                          # la requête part : à partir de là, l'abandonner a un coût
        try:
            res = await self._complete(model, messages, hint)
        finally:
            self.gate.release()
        res.latency_s = time.monotonic() - t0
        return res

    async def _complete(self, model: str, messages: list[dict], hint: dict | None = None) -> LLMResult:
        # la longueur de réponse permise peut être bornée appel par appel (réflexion rapide : une phrase suffit)
        max_tokens = int((hint or {}).get("max_tokens") or self.cfg["max_tokens"])
        body = {"model": model, "messages": messages, "temperature": self.cfg["temperature"],
                "max_tokens": max_tokens}
        if self.seed and (hint or {}).get("seed") is not None:
            body["seed"] = int(hint["seed"])
        schema = (hint or {}).get("schema")
        if self.json_schema and schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": str((hint or {}).get("purpose") or "reponse"), "strict": True, "schema": schema}}
        elif self.cfg.get("json_mode"):
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        retries = 0
        t0 = time.monotonic()
        while True:
            await self.limiter.wait()
            try:
                r = await self.http.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
            except httpx.TimeoutException:
                return LLMResult(None, "timeout", latency_s=time.monotonic() - t0, retries=retries, detail="timeout")
            except httpx.HTTPError as exc:
                status, detail = "error", str(exc)
            else:
                if r.status_code == 200:
                    data = r.json()
                    text = data["choices"][0]["message"].get("content") or ""
                    usage = data.get("usage") or {}
                    pt = usage.get("prompt_tokens") or sum(len(m["content"]) for m in messages) // 4
                    ct = usage.get("completion_tokens") or len(text) // 4
                    return LLMResult(text, "ok", pt, ct, time.monotonic() - t0, retries)
                if r.status_code == 400 and body.get("response_format"):
                    # fournisseur sans ce mode de réponse : schéma → JSON libre → rien, un cran à la fois
                    if body["response_format"].get("type") == "json_schema" and self.cfg.get("json_mode"):
                        body["response_format"] = {"type": "json_object"}
                    else:
                        body.pop("response_format")
                    continue
                status = "quota" if r.status_code == 429 else "error"
                detail = f"HTTP {r.status_code}: {r.text[:200]}"
                if r.status_code not in (429, 500, 502, 503, 504):
                    return LLMResult(None, status, latency_s=time.monotonic() - t0, retries=retries, detail=detail)
            if retries >= self.cfg["max_retries"]:
                return LLMResult(None, status, latency_s=time.monotonic() - t0, retries=retries, detail=detail)
            retries += 1
            await asyncio.sleep(min(30, 2 ** retries))


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    cancelled: int = 0              # appels abandonnés en cours de route (réponse devenue inutile)
    by_tier: dict = field(default_factory=dict)
    by_system: dict = field(default_factory=dict)    # système 1 (réflexe) / système 2 (réflexion) : appels et tokens


class LLMRouter:
    def __init__(self, cfg: dict, clock, events, rng_seed: int, ctl=None):
        self.cfg = cfg["llm"]
        self.clock = clock
        self.events = events
        self.ctl = ctl              # GameControl : pas de nouvel appel en pause, pas de résultat publié en pause
        self.clients: dict[str, object] = {}
        self.tiers = self.cfg["tiers"]
        self._n = 0
        self.usage = Usage()
        for tier, spec in self.tiers.items():
            prov = spec["provider"]
            if prov in self.clients:
                continue
            pcfg = self.cfg["providers"].get(prov, {})
            if prov == "scripted":
                from .scripted import ScriptedClient
                self.clients[prov] = ScriptedClient(pcfg, rng_seed)
            else:
                self.clients[prov] = OpenAICompatClient(prov, pcfg["base_url"], pcfg.get("api_key_env"),
                                                        pcfg.get("rpm", 0), self.cfg, pcfg.get("timeout_s"),
                                                        int(pcfg.get("max_concurrency", 0)),
                                                        bool(pcfg.get("json_schema", False)), bool(pcfg.get("seed", False)))

    def describe(self) -> dict:
        return {t: f"{s['provider']}:{s['model']}" for t, s in self.tiers.items()}

    async def complete(self, agent: str, tier: str, purpose: str, messages: list[dict], hint: dict) -> LLMResult:
        spec = self.tiers[tier]
        client = self.clients[spec["provider"]]
        if self.ctl:
            await self.ctl.checkpoint()
        self._n += 1
        call_id = f"{self.events.run_id}-c{self._n:05d}"
        self.clock.in_flight += 1
        t_start = time.monotonic()
        try:
            res: LLMResult = await client.complete(spec["model"], messages, hint, tier)
        except asyncio.CancelledError:
            # La réponse est devenue inutile (fenêtre close, partie arrêtée) : l'appel est abandonné. S'il était parti, le
            # travail demandé au modèle a eu lieu : la trace reste et il compte dans le coût (E4).
            if not hint.get("_started"):
                raise                                   # encore en file d'attente : rien n'a été demandé au modèle
            self.usage.cancelled += 1
            self.events.emit("llm_call", {
                "call_id": call_id, "agent": agent, "purpose": purpose, "provider": spec["provider"],
                "model": spec["model"], "tier": tier, "prompt_tokens": sum(len(m["content"]) for m in messages) // 4,
                "completion_tokens": 0, "latency_s": round(time.monotonic() - t_start, 3), "status": "cancelled",
                "retries": 0, **({"system": hint["system"]} if hint.get("system") else {})}, actor=agent)
            raise
        finally:
            self.clock.in_flight -= 1
        if self.ctl:
            await self.ctl.checkpoint()     # en pause, la réponse attend la reprise avant d'entrer dans le monde
        res.call_id, res.model, res.provider, res.tier = call_id, spec["model"], spec["provider"], tier
        u = self.usage
        u.calls += 1
        u.prompt_tokens += res.prompt_tokens
        u.completion_tokens += res.completion_tokens
        u.latency_s += res.latency_s
        bt = u.by_tier.setdefault(tier, {"calls": 0, "tokens": 0})
        bt["calls"] += 1
        bt["tokens"] += res.prompt_tokens + res.completion_tokens
        system = hint.get("system")
        if system:
            bs = u.by_system.setdefault(system, {"calls": 0, "tokens": 0})
            bs["calls"] += 1
            bs["tokens"] += res.prompt_tokens + res.completion_tokens
        self.events.emit("llm_call", {
            "call_id": call_id, "agent": agent, "purpose": purpose, "provider": res.provider, "model": res.model,
            "tier": tier, "prompt_tokens": int(res.prompt_tokens), "completion_tokens": int(res.completion_tokens),
            "latency_s": round(res.latency_s, 3), "status": res.status, "retries": res.retries,
            **({"system": system} if system else {}),
        }, actor=agent)
        return res

    async def aclose(self):
        for c in self.clients.values():
            http = getattr(c, "http", None)
            if http:
                await http.aclose()


# ---------------------------------------------------------------- analyse des réponses

OUT_OF_ROLE = re.compile(
    r"en tant qu[e']\s*(intelligence artificielle|ia\b|assistant|mod[eè]le)|mod[eè]le de langage|"
    r"\bas an ai\b|language model|je suis une? (ia|intelligence artificielle|assistant)|"
    r"je ne (peux|suis) pas (en mesure de )?(vous )?aider|openai|anthropic", re.I)
ASSISTANT_POSTURE = re.compile(
    r"il est (important|essentiel|crucial) de|d[ée]veloppement durable|en conclusion|"
    r"n'h[ée]sitez pas|je vous recommande|voici (quelques|mes) (conseils|recommandations)", re.I)


def extract_json(text: str | None) -> dict | None:
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        return None
    chunk = t[start:end + 1]
    for attempt in (chunk, re.sub(r",\s*([}\]])", r"\1", chunk), chunk.replace("'", '"')):
        try:
            v = json.loads(attempt)
            return v if isinstance(v, dict) else None
        except json.JSONDecodeError:
            continue
    return None


def detect_drift(*texts: str) -> tuple[bool, bool]:
    joined = " ".join(t for t in texts if t)
    return bool(OUT_OF_ROLE.search(joined)), bool(ASSISTANT_POSTURE.search(joined))


def to_number(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(v))
    return float(m.group(0).replace(",", ".")) if m else None
