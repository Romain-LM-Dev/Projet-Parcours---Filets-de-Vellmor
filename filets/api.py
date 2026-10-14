"""L'API de FILETS : FastAPI, en REST et en WebSocket.

Godot 4 parle WebSocket nativement (`WebSocketPeer`) mais pas le protocole Kafka. Cette API est son unique porte d'entrée :

* **WebSocket** (`/` et `/ws`, même protocole qu'avant : Godot n'a rien à changer) : relaie les topics `events`, `indicators` et
  `status`, et renvoie dans `commands` les ordres décidés depuis l'interface (injections, pause, vitesse, lancement d'une partie…).
* **REST** (`/api/...`, documentée et essayable sur `/docs`) : état, catalogue du menu, envoi d'une commande validée, liste des
  runs et de leurs événements. N'importe quel outil (navigateur, script, tableau de bord) peut piloter ou lire une partie sans
  parler WebSocket.

La mémoire de la partie en cours est conservée : une scène Godot ouverte en retard reconstitue tout l'état (mémoires comprises).
Seuls les messages du run en cours sont rejoués : les indicateurs d'un autre run, ou déjà reçus, sont écartés.

Messages vers Godot : {"topic": "catalog"|"status"|"hello"|"events"|"indicators", "data": {...}}
  - `catalog` : ce dont le menu de démarrage a besoin (à la connexion, puis à chaque changement) ;
  - `status`  : état du moteur ; seul le dernier est conservé et rejoué à la connexion ;
  - `hello`   : nombre de messages d'historique qui suivent.
Messages depuis Godot : {"type": "drought"} | {"type": "pause"} | {"type": "start_game", "config": {...}} | ...

L'API écoute sur 127.0.0.1 par défaut : elle n'a aucune authentification et peut lancer ou arrêter une partie.
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable, Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict

from .schemas import COMMAND_TYPES, validate_command

log = logging.getLogger("filets.api")

RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


# ---------------------------------------------------------------- modèles de l'API
class Command(BaseModel):
    """Une commande pour le moteur. Les champs en plus de `type` dépendent de la commande (`value`, `text`, `factor`, `config`)."""

    model_config = ConfigDict(extra="allow", json_schema_extra={"examples": [
        {"type": "pause"}, {"type": "set_speed", "value": 0.25}, {"type": "announcement", "text": "Le lac baisse."},
        {"type": "drought", "factor": 0.5}]})
    type: Literal[tuple(COMMAND_TYPES)]            # type: ignore[valid-type]


class Accepted(BaseModel):
    accepted: bool
    type: str


class Health(BaseModel):
    status: str
    clients: int
    run_id: str | None
    engine_state: str | None


class RunSummary(BaseModel):
    run_id: str
    finished: bool
    reason: str | None = None
    seasons_completed: int | None = None
    final_stock: float | None = None
    capacity: float | None = None
    llm_calls: int | None = None
    wall_s: float | None = None
    by_system: dict[str, Any] | None = None


# ---------------------------------------------------------------- les runs enregistrés
class LocalRuns:
    """Les runs du dossier `runs/` : un dossier par run (`events.jsonl`, `config.json`, `summary.json`)."""

    def __init__(self, runs_dir: Path | str):
        self.dir = Path(runs_dir)

    def _summary(self, run_id: str) -> dict | None:
        d = self.dir / run_id
        if not (d / "events.jsonl").exists():
            return None
        out: dict[str, Any] = {"run_id": run_id, "finished": False}
        s = d / "summary.json"
        if s.exists():
            data = json.loads(s.read_text(encoding="utf-8"))
            out.update({"finished": True, "reason": data.get("reason"), "seasons_completed": data.get("seasons_completed"),
                        "final_stock": data.get("final_stock"), "capacity": data.get("capacity"),
                        "llm_calls": data.get("llm_calls"), "wall_s": data.get("wall_s"), "by_system": data.get("by_system")})
        return out

    async def list_runs(self, limit: int = 50) -> list[dict]:
        def work():
            dirs = [p for p in self.dir.iterdir() if p.is_dir()] if self.dir.exists() else []
            dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return [r for r in (self._summary(p.name) for p in dirs[:limit]) if r]
        return await asyncio.to_thread(work)

    async def get_run(self, run_id: str) -> dict | None:
        def work():
            out = self._summary(run_id)
            if out is not None and (self.dir / run_id / "config.json").exists():
                out["config"] = json.loads((self.dir / run_id / "config.json").read_text(encoding="utf-8"))
            return out
        return await asyncio.to_thread(work)

    async def events(self, run_id: str, etype: str | None, limit: int, offset: int) -> list[dict] | None:
        def work():
            path = self.dir / run_id / "events.jsonl"
            if not path.exists():
                return None
            out, seen = [], 0
            with open(path, encoding="utf-8") as f:
                for line in f:
                    ev = json.loads(line)
                    if etype and ev["type"] != etype:
                        continue
                    if seen >= offset:
                        out.append(ev)
                        if len(out) >= limit:
                            break
                    seen += 1
            return out
        return await asyncio.to_thread(work)


class PgMemories:
    """La mémoire collective des runs dans PostgreSQL + pgvector (avec `rag.backend: pgvector`) : les souvenirs de tous les
    agents, cherchés par le sens. La connexion s'ouvre à la première question."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.store = None
        self.lock = asyncio.Lock()

    async def _open(self):
        async with self.lock:
            if self.store is None:
                from .vectors import PgVectorStore, make_embedder, postgres_dsn

                store = PgVectorStore(postgres_dsn(self.cfg), make_embedder(self.cfg["rag"]))
                await store.open()
                self.store = store
        return self.store

    async def search(self, run_id: str, q: str, k: int, agent: str | None = None, until: float | None = None) -> dict:
        store = await self._open()
        [vec] = await store.embedder.embed([q])
        rows = await store.run_memories(run_id, vec, k, agent, until)
        return {"run_id": run_id, "query": q, "embedder": store.model, "results": [
            {"agent": r["owner"], "t": r["t"], "text": r["body"], "kind": r["kind"], "importance": r["importance"],
             "event_id": r["event_id"], "score": round(float(r["score"]), 4)} for r in rows]}

    async def aclose(self) -> None:
        if self.store is not None:
            await self.store.aclose()
            await self.store.embedder.aclose()
            self.store = None


def memories_for(cfg: dict) -> PgMemories | None:
    return PgMemories(cfg) if cfg.get("rag", {}).get("backend", "bm25") == "pgvector" else None


# ---------------------------------------------------------------- le concentrateur (état partagé par tous les clients)
class Hub:
    """Ce que tous les clients partagent : catalogue, dernier état, historique du run en cours, abonnés en direct.

    `push` est appelable depuis n'importe quel fil (consommateur Kafka compris). L'ordre est garanti : un client reçoit
    l'historique, puis le direct, jamais l'inverse.
    """

    def __init__(self, on_command: Callable[[dict], Any], buffer_max: int = 60000, catalog: dict | None = None):
        self.on_command = on_command
        self.clients: set[WebSocket] = set()
        self.buffer: list[str] = []
        self.buffer_max = buffer_max
        self.loop: asyncio.AbstractEventLoop | None = None
        self.queue: asyncio.Queue | None = None
        self._pump_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._catalog_msg = json.dumps({"topic": "catalog", "data": catalog}, ensure_ascii=False) if catalog else None
        self.last_status: str | None = None
        self.current_run: str | None = None
        self._seen_indicators: set[str] = set()

    # --- cycle de vie
    async def start_hub(self):
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue()
        self._pump_task = asyncio.create_task(self._pump())

    async def stop_hub(self):
        if self._pump_task:
            await self.drain()
            self._pump_task.cancel()
            await asyncio.gather(self._pump_task, return_exceptions=True)

    async def drain(self, timeout: float = 2.0):
        try:
            await asyncio.wait_for(self.queue.join(), timeout)
        except asyncio.TimeoutError:
            pass

    # --- entrée des messages
    def push(self, topic: str, data: dict):
        """Appelable depuis n'importe quel fil."""
        if self.loop is None:
            return
        if topic == "status" and "catalog" in data:
            # le moteur joint son catalogue à son état : on le relaie à part, l'état reste léger
            cat = json.dumps({"topic": "catalog", "data": data["catalog"]}, ensure_ascii=False)
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("catalog", None, None, None, cat))
            data = {k: v for k, v in data.items() if k != "catalog"}
        msg = json.dumps({"topic": topic, "data": data}, ensure_ascii=False)
        ident = None
        if topic == "indicators":
            p = data.get("payload", {})
            ident = f"{data.get('run_id')}|{p.get('trigger')}|{p.get('source_event_id')}"
        self.loop.call_soon_threadsafe(self.queue.put_nowait, (topic, data.get("type"), data.get("run_id"), ident, msg))

    async def _broadcast(self, msg: str):
        for ws in list(self.clients):
            try:
                await ws.send_text(msg)
            except Exception:
                self.clients.discard(ws)

    async def _pump(self):
        while True:
            topic, etype, run_id, ident, msg = await self.queue.get()
            try:
                async with self._lock:
                    if topic == "catalog":
                        if msg != self._catalog_msg:          # changé (autre moteur, autres options) : on le renvoie
                            self._catalog_msg = msg
                            await self._broadcast(msg)
                        continue
                    if topic == "status":
                        self.last_status = msg
                        await self._broadcast(msg)
                        continue
                    if topic == "events" and etype == "run_start":
                        self.buffer = []
                        self.current_run = run_id
                        self._seen_indicators.clear()
                    elif topic == "indicators":
                        if self.current_run is not None and run_id != self.current_run:
                            continue                        # indicateur d'un autre run
                        if ident in self._seen_indicators:
                            continue                        # déjà reçu (service redémarré, relecture…)
                        self._seen_indicators.add(ident)
                    self.buffer.append(msg)
                    if len(self.buffer) > self.buffer_max:
                        self.buffer = self.buffer[-self.buffer_max:]
                    await self._broadcast(msg)
            finally:
                self.queue.task_done()

    # --- clients WebSocket
    async def attach(self, ws: WebSocket):
        async with self._lock:
            if self._catalog_msg:
                await ws.send_text(self._catalog_msg)
            if self.last_status:
                await ws.send_text(self.last_status)
            await ws.send_text(json.dumps({"topic": "hello", "data": {"buffered": len(self.buffer)}}))
            for msg in list(self.buffer):
                await ws.send_text(msg)
            self.clients.add(ws)

    def detach(self, ws: WebSocket):
        self.clients.discard(ws)

    async def dispatch(self, cmd: dict) -> bool:
        """Transmet une commande au moteur. Une commande qui échoue est journalisée : elle ne coupe jamais la connexion."""
        try:
            result = self.on_command(cmd)
            if inspect.isawaitable(result):
                await result
            return True
        except Exception:
            log.exception("commande %r non transmise", cmd.get("type"))
            return False

    async def handle_text(self, raw: str):
        try:
            cmd = json.loads(raw)
        except json.JSONDecodeError:
            return
        if isinstance(cmd, dict) and cmd.get("type"):
            await self.dispatch(cmd)

    # --- ce que l'API REST lit
    @property
    def catalog(self) -> dict | None:
        return json.loads(self._catalog_msg)["data"] if self._catalog_msg else None

    @property
    def status(self) -> dict | None:
        return json.loads(self.last_status)["data"] if self.last_status else None


# ---------------------------------------------------------------- l'application
def create_app(hub: Hub, runs: Any = None, memories: Any = None) -> FastAPI:
    app = FastAPI(title="FILETS", version="1",
                  description="Pilotage et lecture d'une partie de FILETS (la tragédie des communs au lac de Vellmor). "
                              "Le flux en direct passe par le WebSocket `/ws` (le même que celui de Godot).")
    app.add_middleware(CORSMiddleware, allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
                       allow_methods=["GET", "POST"], allow_headers=["*"])
    app.state.hub = hub
    app.state.runs = runs

    async def socket(ws: WebSocket):
        await ws.accept()
        try:
            await hub.attach(ws)
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("text") is not None:
                    await hub.handle_text(message["text"])
        except Exception:                     # client parti en cours d'envoi : rien à signaler
            pass
        finally:
            hub.detach(ws)

    app.add_api_websocket_route("/", socket)          # l'adresse que Godot utilise depuis toujours
    app.add_api_websocket_route("/ws", socket)

    @app.get("/api/health", response_model=Health, tags=["état"])
    async def health():
        st = hub.status or {}
        return Health(status="ok", clients=len(hub.clients), run_id=hub.current_run, engine_state=st.get("state"))

    @app.get("/api/status", tags=["état"], summary="Le dernier état publié par le moteur")
    async def status():
        if hub.status is None:
            raise HTTPException(404, "le moteur ne s'est pas encore annoncé")
        return hub.status

    @app.get("/api/catalog", tags=["état"], summary="Ce dont le menu de démarrage a besoin")
    async def catalog():
        if hub.catalog is None:
            raise HTTPException(404, "pas encore de catalogue")
        return hub.catalog

    @app.post("/api/commands", response_model=Accepted, status_code=202, tags=["pilotage"],
              summary="Envoyer une commande au moteur (pause, vitesse, rumeur, démarrer une partie…)")
    async def command(cmd: Command):
        body = cmd.model_dump()
        errors = validate_command(body)
        if errors:
            raise HTTPException(422, errors)
        if not await hub.dispatch(body):
            raise HTTPException(503, "le moteur n'a pas pu recevoir la commande")
        return Accepted(accepted=True, type=cmd.type)

    def need_runs():
        if runs is None:
            raise HTTPException(501, "aucun stockage de runs configuré")
        return runs

    def check_id(run_id: str):
        if not RUN_ID.match(run_id):
            raise HTTPException(422, "identifiant de run invalide")

    @app.get("/api/runs", response_model=list[RunSummary], tags=["runs"], summary="Les runs enregistrés, les plus récents d'abord")
    async def list_runs(limit: int = Query(50, ge=1, le=500)):
        return await need_runs().list_runs(limit)

    @app.get("/api/runs/{run_id}", tags=["runs"], summary="Un run : résumé et configuration")
    async def get_run(run_id: str):
        check_id(run_id)
        out = await need_runs().get_run(run_id)
        if out is None:
            raise HTTPException(404, "run inconnu")
        return out

    @app.get("/api/runs/{run_id}/events", tags=["runs"], summary="Les événements d'un run, filtrables par nature")
    async def run_events(run_id: str, type: str | None = None, limit: int = Query(200, ge=1, le=5000),
                         offset: int = Query(0, ge=0)):
        check_id(run_id)
        out = await need_runs().events(run_id, type, limit, offset)
        if out is None:
            raise HTTPException(404, "run inconnu")
        return out

    @app.get("/api/runs/{run_id}/memories", tags=["runs"],
             summary="Chercher par le sens dans la mémoire collective d'un run (PostgreSQL + pgvector)")
    async def run_memories(run_id: str, q: str = Query(..., min_length=2, max_length=500),
                           agent: str | None = Query(None, pattern=r"^[A-Za-z0-9_-]{1,40}$"),
                           k: int = Query(10, ge=1, le=100), until: float | None = Query(None, ge=0)):
        """`q` : la question ; `agent` : un seul agent (F01…) ; `until` : seulement ce qui était su à cet instant simulé."""
        check_id(run_id)
        if memories is None:
            raise HTTPException(501, "mémoire vectorielle non configurée (rag.backend: pgvector, voir config/data.yaml)")
        try:
            return await memories.search(run_id, q, k, agent, until)
        except Exception as exc:
            log.warning("recherche dans la mémoire collective impossible : %s", exc)
            raise HTTPException(503, f"base de la mémoire indisponible : {type(exc).__name__}") from None

    return app


# ---------------------------------------------------------------- le serveur
class _Server(uvicorn.Server):
    @contextlib.contextmanager
    def capture_signals(self):
        yield            # Ctrl+C reste à celui qui a lancé le moteur : uvicorn ne détourne pas les signaux


class ApiServer(Hub):
    """Le concentrateur et son serveur HTTP/WebSocket, dans la boucle asyncio de l'appelant (moteur ou service)."""

    def __init__(self, host: str, port: int, on_command: Callable[[dict], Any], buffer_max: int = 60000,
                 catalog: dict | None = None, runs: Any = None, memories: Any = None):
        super().__init__(on_command, buffer_max, catalog)
        self.host, self._port, self.runs, self.memories = host, port, runs, memories
        self.app: FastAPI | None = None
        self._server: _Server | None = None
        self._serve_task: asyncio.Task | None = None

    @property
    def port(self) -> int:
        """Le port réellement ouvert (utile quand on a demandé le port 0)."""
        return self._server.servers[0].sockets[0].getsockname()[1]

    async def start(self):
        await self.start_hub()
        self.app = create_app(self, self.runs, self.memories)
        config = uvicorn.Config(self.app, host=self.host, port=self._port, log_level="warning", log_config=None,
                                access_log=False, lifespan="off", ws_max_size=2 ** 20, timeout_graceful_shutdown=1)
        self._server = _Server(config)
        self._serve_task = asyncio.create_task(self._server.serve())
        while not self._server.started:
            if self._serve_task.done():
                self._serve_task.result()
                raise RuntimeError("le serveur de l'API s'est arrêté au démarrage")
            await asyncio.sleep(0.02)
        log.info("API FILETS sur http://%s:%d (WebSocket sur /ws, documentation sur /docs)", self.host, self.port)

    async def stop(self):
        await self.stop_hub()
        if self.memories is not None:
            await self.memories.aclose()
        if self._server:
            self._server.should_exit = True
            if self._serve_task:
                await asyncio.gather(self._serve_task, return_exceptions=True)
