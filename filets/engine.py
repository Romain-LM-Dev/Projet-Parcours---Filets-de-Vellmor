"""Le moteur de jeu en « salon » : il attend qu'on lance une partie depuis l'interface, la joue, puis revient au salon.

    python -m filets serve [--bus local|kafka] [--ws]

États publiés sur le topic `status` (voir `schemas.STATUS`) :

    idle      le salon attend `start_game` (menu de démarrage dans Godot)
    starting  la demande est validée, la partie se prépare (vérification du fournisseur d'IA…)
    running   la partie tourne                       paused   elle est en pause
    ended     la partie est finie ou arrêtée ; `start_game` en lance une autre, `new_game` revient au salon

La demande `start_game` porte la configuration choisie dans le menu (voir `validate_request`). Elle est
validée ici, jamais dans l'interface : une demande invalide laisse le salon ouvert avec un message d'erreur.
"""
from __future__ import annotations

import asyncio
import collections
import copy
import datetime as dt
import logging
import traceback
import uuid
from typing import Callable

import httpx

from .bus import LocalBus
from .catalog import (COMMUNICATIONS, COUNCILS, FLEETS, LIMITS, LLM_OPTIONS, MODES, REFLECTIONS, SPEEDS, build_catalog,
                      generate_world)
from .config import deep_merge, load_config, normalize
from .console import console_printer, print_summary
from .lakes import resolve_lakes
from .pipeline import IndicatorPublisher
from .profiles import VILLAGE_NAMES, validate_custom

log = logging.getLogger("filets.engine")


class GameRequestError(ValueError):
    """La demande de partie est invalide ; le message est destiné au joueur."""


def validate_request(req: dict) -> list[str]:
    """Erreurs (en français) d'une demande `start_game` ; liste vide si elle est valide."""
    if not isinstance(req, dict):
        return ["demande de partie invalide"]
    errs = []
    if req.get("mode") not in [m["id"] for m in MODES]:
        errs.append("mode inconnu (synchrone ou asynchrone)")
    lo, hi = LIMITS["seasons"]
    if not isinstance(req.get("seasons"), int) or isinstance(req.get("seasons"), bool) or not lo <= req["seasons"] <= hi:
        errs.append(f"le nombre de saisons doit être un entier entre {lo} et {hi}")
    lo, hi = LIMITS["seed"]
    if not isinstance(req.get("seed"), int) or isinstance(req.get("seed"), bool) or not lo <= req["seed"] <= hi:
        errs.append(f"la graine doit être un entier entre {lo} et {hi}")
    if req.get("communication") not in [c["id"] for c in COMMUNICATIONS]:
        errs.append("mode de communication inconnu")
    if not isinstance(req.get("catches_visible"), bool):
        errs.append("« prises visibles » doit être vrai ou faux")
    if req.get("council", "delegates") not in [c["id"] for c in COUNCILS]:
        errs.append("composition du conseil inconnue (un élu par village, ou tous les pêcheurs)")
    for key, label in (("climate", "le climat"), ("patrol", "la patrouille")):
        if not isinstance(req.get(key, True), bool):
            errs.append(f"{label} doit être vrai ou faux")
    patrols = req.get("patrols", 1)
    lo, hi = LIMITS["patrols"]
    if not isinstance(patrols, int) or isinstance(patrols, bool) or not lo <= patrols <= hi:
        errs.append(f"le nombre de patrouilles doit être un entier entre {lo} et {hi}")
    for key, hi, label in (("travel_days", 10, "la route entre les lacs (en jours)"),
                           ("travel_cost", 1000, "le coût de la route (en écus par jour de mer)")):
        v = req.get(key, 0)
        if not (isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= hi):
            errs.append(f"{label} doit être un nombre entre 0 et {hi}")
    hold = req.get("hold_fraction", 0.5)
    if not (isinstance(hold, (int, float)) and not isinstance(hold, bool) and 0.05 <= hold <= 1.0):
        errs.append("la part du poisson qu'un bateau peut prendre doit être un nombre entre 0,05 et 1")
    rate = req.get("event_rate", 0.3)
    if not (isinstance(rate, (int, float)) and not isinstance(rate, bool) and 0 <= rate <= 1):
        errs.append("la fréquence des événements doit être un nombre entre 0 et 1")
    luck = req.get("luck", 0.4)
    if not (isinstance(luck, (int, float)) and not isinstance(luck, bool) and 0 <= luck <= 0.6):
        errs.append("l'aléa de la pêche doit être un nombre entre 0 et 0,6")
    if req.get("llm", "scripted") not in [o["id"] for o in LLM_OPTIONS]:
        errs.append("moteur d'IA inconnu")
    speed = req.get("speed", 1.0)
    if speed != "max" and not (isinstance(speed, (int, float)) and not isinstance(speed, bool) and speed > 0):
        errs.append("vitesse invalide")
    if req.get("reflection", "rapide") not in [r["id"] for r in REFLECTIONS]:
        errs.append("réflexion des IA inconnue (rapide ou complète)")
    lo, hi = LIMITS["assembly_rounds"]
    rounds = req.get("assembly_rounds", 2)
    if not isinstance(rounds, int) or isinstance(rounds, bool) or not lo <= rounds <= hi:
        errs.append(f"le nombre de tours de parole doit être un entier entre {lo} et {hi}")
    lake = req.get("lake", {})
    cap = lake.get("capacity") if isinstance(lake, dict) else "x"
    lo, hi = LIMITS["capacity"]
    if cap is not None and not (isinstance(cap, (int, float)) and not isinstance(cap, bool) and lo <= cap <= hi):
        errs.append(f"la capacité du lac doit être un nombre de tonnes entre {lo} et {hi}")
    rate = lake.get("growth_rate") if isinstance(lake, dict) else None
    lo, hi = LIMITS["growth_rate"]
    if rate is not None and not (isinstance(rate, (int, float)) and not isinstance(rate, bool) and lo <= rate <= hi):
        errs.append(f"le taux de repeuplement du lac doit être un nombre entre {lo:g} et {hi:g}")
    errs += validate_lakes(lake.get("lakes") if isinstance(lake, dict) else None, req.get("population"))
    if not isinstance(req.get("stop_on_extinction", True), bool):
        errs.append("« arrêter si le lac est vide » doit être vrai ou faux")
    pop = req.get("population")
    if not isinstance(pop, dict):
        errs.append("population absente")
    else:
        fishers = pop.get("fishers")
        errs += validate_custom(fishers)
        lo, hi = LIMITS["fishers"]
        if isinstance(fishers, list) and fishers and not lo <= len(fishers) <= hi:
            errs.append(f"le nombre de pêcheurs doit être compris entre {lo} et {hi}")
        vlo, vhi = LIMITS["villages"]
        if isinstance(fishers, list) and fishers and all(isinstance(f, dict) for f in fishers) and \
                len({f.get("hamlet") for f in fishers}) > vhi:
            errs.append(f"la vallée compte au plus {vhi} villages")
        if pop.get("elder_kind", "llm") not in ("llm", "rule"):
            errs.append("type d'ancien inconnu")
    return errs


def validate_lakes(lakes, pop) -> list[str]:
    """Erreurs (en français) de la description des lacs d'une demande : chaque lac (nom, capacité en tonnes, part pleine au départ,
    repeuplement, villages) et leur cohérence avec les villages de la vallée. Vide si elle est valide ou absente."""
    if lakes is None:
        return []
    if not isinstance(lakes, list) or not lakes or not all(isinstance(k, dict) for k in lakes):
        return ["les lacs doivent être une liste d'au moins un lac"]
    errs = []
    for key, label in (("capacity", "la capacité"), ("stock_ratio", "la part pleine au départ"), ("growth_rate", "le repeuplement")):
        lo, hi = LIMITS["capacity"] if key == "capacity" else LIMITS["stock_ratio"] if key == "stock_ratio" else LIMITS["growth_rate"]
        for k in lakes:
            v = k.get(key)
            if v is not None and not (isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi):
                errs.append(f"{label} d'un lac doit être un nombre entre {lo:g} et {hi:g}")
                break
    fishers = pop.get("fishers") if isinstance(pop, dict) else None
    if errs or not (isinstance(fishers, list) and fishers and all(isinstance(f, dict) for f in fishers)):
        return errs
    hamlets = sorted({f.get("hamlet") for f in fishers}, key=lambda h: VILLAGE_NAMES.index(h) if h in VILLAGE_NAMES else 99)
    try:
        resolve_lakes({"lakes": lakes, "capacity_per_fisher": 12.5, "initial_ratio": 1.0, "growth_rate": 1.0}, hamlets,
                      collections.Counter(f.get("hamlet") for f in fishers))
    except ValueError as exc:
        errs.append(str(exc))
    return errs


def build_game_config(base_cfg: dict, req: dict) -> dict:
    """Configuration complète d'une partie : la base du moteur, surchargée par ce qu'a choisi le joueur."""
    errs = validate_request(req)
    if errs:
        raise GameRequestError(" · ".join(errs[:4]))
    pop = req["population"]
    patrols = req["patrols"] if "patrols" in req else (1 if req.get("patrol", True) else 0)
    llm = next(o for o in LLM_OPTIONS if o["id"] == req.get("llm", "scripted"))
    over: dict = {
        "run": {"seasons": req["seasons"], "seed": req["seed"], "label": f"menu-{llm['id']}"},
        "time": {"mode": req["mode"]},
        "scenario": {"communication": req["communication"], "catches_visible": req["catches_visible"],
                     "council": req.get("council", base_cfg["scenario"].get("council", "delegates")),
                     "patrol": {"enabled": patrols > 0, "count": patrols},
                     "assembly_rounds": req.get("assembly_rounds", base_cfg["scenario"]["assembly_rounds"])},
        "population": {"custom": copy.deepcopy(pop["fishers"]), "elder": bool(pop.get("elder", True)),
                       "elder_kind": pop.get("elder_kind", "llm")},
        "climate": {"enabled": req.get("climate", True), "event_rate": float(req.get("event_rate", 0.3))},
        "economy": {"luck": float(req.get("luck", base_cfg["economy"].get("luck", 0.0))),
                    "hold_fraction": float(req.get("hold_fraction", base_cfg["economy"].get("hold_fraction", 0.5))),
                    "travel_days": float(req.get("travel_days", base_cfg["economy"].get("travel_days", 1.5))),
                    "travel_cost": float(req.get("travel_cost", base_cfg["economy"].get("travel_cost", 10.0)))},
    }
    if llm["config"]:
        preset = load_config(llm["config"])["llm"]
        over["llm"] = {"tiers": preset["tiers"], "reflection": preset.get("reflection", "complete")}
    if "reflection" in req:                       # le choix du menu l'emporte sur celui du moteur d'IA
        over.setdefault("llm", {})["reflection"] = req["reflection"]
    lake = req.get("lake") or {}
    if lake.get("capacity") is not None:          # limite du stock du lac choisie ; sinon 12,5 t par pêcheur
        over.setdefault("lake", {})["capacity"] = float(lake["capacity"])
    if lake.get("growth_rate") is not None:       # taux de repeuplement choisi ; sinon celui de la configuration (1,0)
        over.setdefault("lake", {})["growth_rate"] = float(lake["growth_rate"])
    if lake.get("lakes"):                         # les lacs, un à un : nom, poisson, repeuplement, villages
        over.setdefault("lake", {})["lakes"] = copy.deepcopy(lake["lakes"])
    if "stop_on_extinction" in req:
        over["run"]["stop_on_extinction"] = req["stop_on_extinction"]
    return normalize(deep_merge(base_cfg, over))


def used_models(cfg: dict) -> dict[str, set[str]]:
    """Fournisseur → modèles dont CETTE partie a réellement besoin : seuls les niveaux portés par un pêcheur (ou l'ancien)
    à IA comptent. Une partie où tous les pêcheurs ont le petit modèle n'exige pas le grand."""
    from .profiles import build_population

    tiers = {p.tier for p in build_population(cfg) if p.kind == "llm" and p.tier}
    if tiers and "reflexe" in cfg["llm"]["tiers"]:
        tiers.add("reflexe")                      # le modèle de décision des réflexes (système 1) et des bulletins de vote
    wanted: dict[str, set[str]] = {}
    for tier in tiers:
        spec = cfg["llm"]["tiers"][tier]
        wanted.setdefault(spec["provider"], set()).add(spec["model"])
    return wanted


async def preflight(cfg: dict, progress: Callable[[str], None] | None = None) -> None:
    """Vérifie, avant de lancer, que les fournisseurs d'IA choisis répondent (message clair plutôt qu'une partie
    de pêcheurs qui se rabattent tous sur leurs règles de repli), et charge les modèles locaux en mémoire : sans cela,
    la première saison commencerait par des appels qui attendent le chargement du modèle et dépassent leur délai.
    `progress(texte)` est appelé à chaque étape, pour que l'interface puisse dire ce qui se passe."""
    llm = cfg["llm"]
    say = progress or (lambda _text: None)
    for prov, models in used_models(cfg).items():
        if prov == "scripted":
            continue
        say(f"Vérification de {prov}…")
        pcfg = llm["providers"].get(prov, {})
        if pcfg.get("api_key_env"):
            import os
            if not os.environ.get(pcfg["api_key_env"]):
                raise GameRequestError(f"la variable d'environnement {pcfg['api_key_env']} est absente "
                                       f"(nécessaire pour {prov})")
        if pcfg.get("local") == "colibri":
            # Colibri charge son modèle au démarrage du serveur : il suffit qu'il réponde et serve le bon modèle
            base = pcfg["base_url"].rstrip("/")
            try:
                async with httpx.AsyncClient(timeout=5.0) as http:
                    served = {m.get("id") for m in (await http.get(f"{base}/models")).json().get("data", [])}
            except (httpx.HTTPError, ValueError, AttributeError):
                raise GameRequestError(f"Colibri ne répond pas sur {base} : lancez .\\start.ps1 -Colibri") from None
            if not models <= served:
                raise GameRequestError(f"Colibri sert {', '.join(sorted(served)) or 'aucun modèle'}, "
                                       f"pas {', '.join(sorted(models - served))}")
            continue
        if prov == "ollama" or pcfg.get("local"):
            base = pcfg["base_url"].rstrip("/")
            root = base[:-3] if base.endswith("/v1") else base
            try:
                async with httpx.AsyncClient(timeout=3.0) as http:
                    r = await http.get(f"{root}/api/tags")
                    present = {m.get("name") for m in r.json().get("models", [])}
            except (httpx.HTTPError, ValueError):
                raise GameRequestError(f"Ollama ne répond pas sur {root} : lancez l'application Ollama") from None
            missing = sorted(m for m in models if m not in present and f"{m}:latest" not in present)
            reflex = llm["tiers"].get("reflexe", {})
            if reflex.get("provider") == prov and reflex.get("model") in missing:
                # le modèle de décision est une économie, pas une nécessité : sans lui, la partie se joue, et les réflexes
                # passent par le petit modèle de langage
                llm["tiers"].pop("reflexe")
                missing.remove(reflex["model"])
                models = models - {reflex["model"]}
                say(f"Modèle de décision {reflex['model']} absent (ollama pull {reflex['model']}, Ollama 0.40.4 ou plus) : "
                    "les réflexes passeront par le petit modèle.")
                log.warning("modèle de décision %s absent : niveau « reflexe » retiré de la partie", reflex["model"])
            if missing:
                raise GameRequestError("modèle Ollama absent : " + ", ".join(f"ollama pull {m}" for m in missing))
            for k, model in enumerate(sorted(models), 1):
                say(f"Chargement du modèle {model} ({k}/{len(models)}) : la première fois, cela peut prendre une minute…")
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=3.0)) as http:
                        if pcfg.get("kind") == "systemone":      # un modèle de décision se charge par une question
                            r = await http.post(f"{root}/v1/systemone", json={
                                "model": model, "state": "Le lac est plein.", "keep_alive": "30m",
                                "questions": {"plein": {"type": "noul", "instructions": "Le lac est-il plein ?"}}})
                        else:
                            r = await http.post(f"{root}/api/generate", json={"model": model, "prompt": "", "keep_alive": "30m"})
                except httpx.HTTPError as exc:
                    raise GameRequestError(f"Ollama n'a pas pu charger {model} : {exc or type(exc).__name__}") from None
                if r.status_code != 200:
                    raise GameRequestError(f"Ollama n'a pas pu charger {model} : {r.text[:160]}")
    await check_storage(cfg, say)


async def check_storage(cfg: dict, say: Callable[[str], None]) -> None:
    """La base (PostgreSQL + pgvector), le modèle de plongement et le stockage objet, s'ils sont demandés : un message
    clair avant la partie plutôt qu'une erreur au premier souvenir."""
    from .objects import make_objects
    from .vectors import EmbeddingError, make_embedder, postgres_dsn

    rag, storage = cfg["rag"], cfg.get("storage", {})
    if rag.get("backend", "bm25") == "pgvector" or storage.get("history") == "postgres":
        import asyncpg

        dsn = postgres_dsn(cfg)
        say("Vérification de PostgreSQL…")
        try:
            conn = await asyncpg.connect(dsn, timeout=3.0)
            await conn.close()
        except (OSError, asyncio.TimeoutError, asyncpg.PostgresError) as exc:
            where = dsn.rsplit("@", 1)[-1]
            raise GameRequestError(f"PostgreSQL ne répond pas sur {where} ({type(exc).__name__}) : "
                                   "lancez « docker compose --profile data up -d »") from None
    if rag.get("backend", "bm25") == "pgvector":
        emb = make_embedder(rag)
        say(f"Chargement du modèle de plongement {emb.name}…")
        try:
            await emb.embed(["Le lac de Vellmor."])
        except EmbeddingError as exc:
            model = rag.get("embeddings", {}).get("model", "")
            hint = f" (ollama pull {model})" if "not found" in str(exc) or "404" in str(exc) else ""
            raise GameRequestError(f"modèle de plongement indisponible{hint} : {exc}") from None
        finally:
            await emb.aclose()
    objects = make_objects(cfg)
    if objects is not None:
        say("Vérification du stockage objet…")
        try:
            await objects.open()
        except Exception as exc:
            raise GameRequestError(f"stockage objet injoignable ({objects.where}) : {str(exc)[:120]}") from None
        finally:
            await objects.aclose()


class Engine:
    """Boucle du salon. Le bus et le pont WebSocket (en local) appartiennent à l'appelant."""

    def __init__(self, base_cfg: dict, bus, quiet: bool = False, engine_id: str | None = None,
                 default_llm: str = "scripted"):
        self.base_cfg = base_cfg
        self.bus = bus
        self.quiet = quiet
        self.engine_id = engine_id or uuid.uuid4().hex[:8]
        self.catalog = build_catalog(base_cfg, default_llm)
        self.state = "idle"
        self.error: str | None = None
        self.end_reason: str | None = None
        self.last_run_id: str | None = None
        self.final_status: dict = {}     # dernier état de la partie terminée, republié tant qu'on est en « ended »
        self.detail: str | None = None   # ce que fait le moteur pendant la préparation (chargement d'un modèle…)
        self.world = None
        self.pub: IndicatorPublisher | None = None
        if isinstance(bus, LocalBus):
            # en bus local, les indicateurs sont calculés ici ; avec Kafka, c'est le service dédié
            self.pub = IndicatorPublisher(bus, base_cfg["output"]["runs_dir"], base_cfg["scenario"]["quota_tolerance"])
            bus.subscribe("events", self.pub.on_event)
        if not quiet:
            bus.subscribe("events", console_printer())

    # ------------------------------------------------------------------ état
    def status(self) -> dict:
        base = self.final_status if self.state == "ended" else {}
        out = {**base, "state": self.state, "engine_id": self.engine_id,
               "wall_clock": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
               "run_id": self.last_run_id, "end_reason": self.end_reason, "error": self.error, "controls": True,
               "lobby": True, "detail": self.detail}
        if self.state in ("idle", "ended"):
            # Le menu reflète les options de CE moteur (mode, saisons, pêcheurs, IA présélectionnés au lancement) :
            # avec Kafka, le pont est un autre processus qui l'ignore, donc le moteur l'envoie avec son état.
            out["catalog"] = self.catalog
        return out

    def publish_status(self, state: str | None = None, **changes):
        if state:
            self.state = state
        self.bus.publish("status", {**self.status(), **changes}, key="engine")

    # ------------------------------------------------------------------ boucle
    async def serve(self) -> None:
        # Kafka : le consommateur de commandes doit avoir sa partition avant que le salon s'annonce,
        # sinon un « Démarrer » envoyé trop tôt serait perdu.
        if not await asyncio.to_thread(self.bus.wait_ready, 30.0):
            log.warning("le consommateur de commandes n'a pas reçu sa partition en 30 s")
        self.publish_status("idle")
        if not self.quiet:
            print("Salon ouvert : lancez une partie depuis le menu de Godot (Ctrl+C pour quitter).")
        n = 0
        while True:
            for cmd in self.bus.poll_commands():
                ctype = cmd.get("type")
                if ctype == "start_game":
                    await self._play(cmd.get("config") or {})
                    # tout ce qui attendait dans la file date d'avant cette partie (clics répétés sur « Démarrer »…) :
                    # on l'écarte plutôt que d'enchaîner des parties que personne n'a demandées
                    self.bus.poll_commands()
                    break
                if ctype == "new_game" and self.state != "idle":
                    self.error = self.end_reason = None
                    self.publish_status("idle")
                if ctype == "generate_world" and self.state in ("idle", "ended"):
                    self.generate(cmd.get("config") or {})
            n += 1
            if n % 20 == 0:
                self.publish_status()
            await asyncio.sleep(0.1)

    def generate(self, req: dict) -> None:
        """Le menu demande une vallée : ses villages et ses pêcheurs, générés d'après ces paramètres et la graine (la même
        vallée pour les mêmes paramètres). Le moteur remplace la composition de base du catalogue, que le menu affiche."""
        errs = []
        got = {}
        fleet = req.get("fleet", "mixte")
        if fleet not in [f["id"] for f in FLEETS]:
            errs.append("la flotte doit être l'une de : " + ", ".join(f["id"] for f in FLEETS))
        mode = req.get("mode", "params")
        if mode not in ("params", "random"):
            errs.append("la génération doit être paramétrée ou aléatoire")
        # (aléatoire : la graine seule décide, le reste est tiré d'elle)
        keys = (("seed", "graine"),) if mode == "random" else (("villages", "villages"), ("fishers", "pêcheurs"), ("seed", "graine"),
                                                              ("lakes", "lacs"), ("patrols", "patrouilles"))
        for key, label in keys:
            lo, hi = LIMITS[key]
            v = req.get(key, 1 if key in ("lakes", "patrols") else None)
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                errs.append(f"le nombre de {label} doit être un entier entre {lo} et {hi}" if key != "seed"
                            else f"la graine doit être un entier entre {lo} et {hi}")
            got[key] = v
        if not errs and mode == "params" and got["villages"] > got["fishers"]:
            errs.append("il faut au moins un pêcheur par village")
        if not errs and mode == "params" and got["lakes"] > got["villages"]:
            errs.append("il faut au moins un village par lac")
        if errs:
            self.error = " · ".join(errs)
            self.publish_status()
            self.error = None            # un refus se dit une fois : redemandé, le même refus doit se lire de nouveau
            return
        self.error = None
        world = generate_world(self.base_cfg, got.get("villages", 4), got.get("fishers", 8), got["seed"], fleet,
                               got.get("lakes", 1), got.get("patrols", 1), mode)
        self.catalog = {**self.catalog, "hamlets": world["hamlets"], "base_population": world["base_population"],
                        "lakes": world["lakes"],
                        "generation": {"id": req.get("id"), "villages": world["villages"], "fishers": world["fishers"],
                                       "seed": got["seed"], "fleet": world["fleet"], "lakes": len(world["lakes"]),
                                       "patrols": world["patrols"], "mode": mode}}
        self.publish_status()

    async def _prepare(self, cfg: dict) -> None:
        """Vérifie et charge les IA demandées. Charger un modèle local peut prendre une minute : pendant ce temps le moteur
        continue d'annoncer son état. Sans cela, l'interface, qui le croit mort après quelques secondes de silence, afficherait
        « moteur injoignable » alors qu'il travaille."""
        def progress(text: str) -> None:
            self.detail = text
            self.publish_status()

        async def beat() -> None:
            while True:
                await asyncio.sleep(1.5)
                self.publish_status()

        beater = asyncio.create_task(beat())
        try:
            await preflight(cfg, progress)
        finally:
            beater.cancel()
            await asyncio.gather(beater, return_exceptions=True)
            self.detail = None

    async def _play(self, request: dict) -> None:
        from .cli import unique_run_id      # import tardif : cli dépend de ce module
        from .world import World

        self.error = self.end_reason = None
        self.publish_status("starting")
        try:
            cfg = build_game_config(self.base_cfg, request)
            await self._prepare(cfg)
            run_id = unique_run_id(cfg)
            llm = next(o for o in LLM_OPTIONS if o["id"] == request.get("llm", "scripted"))
            world = World(cfg, self.bus, run_id, engine_id=self.engine_id, lobby=True,
                          advised_speed=None if llm["id"] == "scripted" else llm["async_speed"])
        except GameRequestError as exc:
            self.error = str(exc)
            self.publish_status("idle")
            if not self.quiet:
                print("Demande refusée :", exc)
            return
        except Exception as exc:     # configuration ou fournisseur inutilisable : le salon reste ouvert
            log.exception("préparation de la partie impossible")
            self.error = f"préparation impossible : {exc}"
            self.publish_status("idle")
            return
        self.world, self.last_run_id = world, run_id
        speed = request.get("speed", 1.0)
        if speed == "max":
            world.ctl.set_fast(True)
        else:
            world.ctl.set_speed(float(speed))
        try:
            await world.run()
            self.end_reason = world.stopped_reason
        except Exception as exc:
            log.error("la partie s'est arrêtée sur une erreur :\n%s", traceback.format_exc())
            self.end_reason = f"erreur : {exc}"
        finally:
            self.world = None
        if not self.quiet:
            print_summary(world, self.pub)
        self.final_status = world.status_payload("ended", end_reason=self.end_reason, paused=False)
        self.publish_status("ended")

    def close(self) -> None:
        if self.pub:
            self.pub.close()
