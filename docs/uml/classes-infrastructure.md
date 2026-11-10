# Infrastructure : salon, API, bus, événements, indicateurs, stockage

Cette partie est tout ce qui **entoure la simulation** : le salon qui lance les parties (`Engine`), l'API HTTP/WebSocket qui parle à
l'interface Godot, le bus qui transporte les événements, leur enregistrement, le calcul des indicateurs (KPI) et le stockage.
Les fichiers de fonctions (`api.py` pour ses routes, `cli.py`, `config.py`, `catalog.py`, `bench.py`, `services/`) sont montrés
comme `<<module>>`. Même légende que `classes-monde.md`.

Fichiers Python couverts ailleurs : `world.py`, `lake.py`, `lakes.py`, `rules.py`, `climate.py`, `clock.py`, `control.py`, `scheduler.py`,
`profiles.py`, `agents.py` (voir `classes-monde.md`) ; `policies.py`, `routing.py`, `prompts.py`, `llm.py`, `scripted.py`, `memory.py`, `rag.py`,
`vectors.py` (voir `classes-decisions.md`). Les paquets `__init__.py` ne contiennent que la version (`__version__`) ou une docstring.

## 1. Le salon et le bus

`Engine` est la boucle du salon : il attend une demande de partie, construit la configuration, crée un `World` et publie son état. Le bus (`LocalBus` en local, `KafkaBus` distribué) transporte événements et commandes ; `Bus` est le contrat commun. `PublisherBus` (`aio.py`) est le même contrat pour les services asynchrones, sans hériter de `Bus`.

```mermaid
classDiagram
    class Engine {
        +dict base_cfg
        +any bus
        +bool quiet
        +str? engine_id
        +any catalog
        +str state
        +str? error
        +str? end_reason
        +str? last_run_id
        +dict final_status
        +str? detail
        +None world
        +IndicatorPublisher? pub
        +__init__(base_cfg, bus, quiet, engine_id, default_llm)
        +status() dict
        +publish_status(state, kwargs)
        +serve() None?
        +generate(req) None?
        -_prepare(cfg) None?
        -_play(request) None?
        +close() None?
    }
    class GameRequestError {
    }
    class engine {
        <<module>>
        +validate_request(req) list
        +validate_lakes(lakes, pop) list
        +build_game_config(base_cfg, req) dict
        +used_models(cfg) dict
        +preflight(cfg, progress) None?
        +check_storage(cfg, say) None?
    }
    class Bus {
        <<classe de base>>
        +publish(topic, event, key) None?
        +subscribe(topic, callback) None?
        +send_command(cmd) None?
        +poll_commands() list
        +wait_ready(timeout) bool
        +flush() None?
        +close() None?
    }
    class LocalBus {
        -dict _subs
        -queue.Queue _commands
        +dict counts
        +__init__()
        +publish(topic, event, key)
        +subscribe(topic, callback)
        +send_command(cmd)
        +poll_commands()
        +wait_ready(timeout)
        +flush()
        +close()
    }
    class KafkaBus {
        +dict topics
        +Producer producer
        -dict _subs
        -queue.Queue _commands
        -Event _stop
        -None _thread
        +Event commands_ready
        +Consumer consumer
        +__init__(bootstrap, topics, group, consume_commands)
        +wait_ready(timeout) bool
        -_consume()
        +publish(topic, event, key)
        +subscribe(topic, callback)
        +send_command(cmd)
        +poll_commands()
        +flush()
        +close()
    }
    class bus {
        <<module>>
        +tuple TOPIC_KEYS
        +dict RETENTION_MS
        +any DEFAULT_RETENTION_MS
        +int _SCAN_CHUNK
        +any OFFSET_BEGINNING
        +ensure_topics(bootstrap, topics) None?
        +make_bus(cfg, group, consume_commands) Bus
        +kafka_consumer(cfg, group, topics, from_beginning)
        +last_run_start_offset(cfg, timeout) int
        +kafka_assigned_consumer(cfg, group, positions)
    }
    class PublisherBus {
        +any producer
        +any topics
        +asyncio.Queue queue
        -any _worker
        +__init__(p, topics)
        +publish(topic, event, key) None?
        +subscribe(topic, callback) None?
        -_run() None?
        +aflush() None?
        +aclose() None?
    }
    class aio {
        <<module>>
        +int _SCAN_CHUNK
        +last_run_start_offset(cfg, timeout_ms) int
        +assigned_consumer(cfg, positions) AIOKafkaConsumer
        +messages(consumer) AsyncIterator
        +producer(cfg) AIOKafkaProducer
        +send(p, cfg, topic_key, event, key) None?
    }
    class World
    class IndicatorPublisher
    Bus <|-- LocalBus
    Bus <|-- KafkaBus
    GameRequestError --|> ValueError
    Engine o-- Bus : bus
    Engine ..> World : cree une partie
    Engine "1" *-- "0..1" IndicatorPublisher : pub
    Engine ..> engine : validate_request, build_game_config
    Engine ..> GameRequestError : leve
    World o-- Bus : bus
    bus ..> KafkaBus : make_bus
    bus ..> LocalBus : make_bus
    aio ..> bus : OFFSET_BEGINNING
```

**Pour aller plus loin**
- `filets/engine.py:304` (`Engine`)
- `filets/engine.py:44` (`validate_request`)
- `filets/engine.py:152` (`build_game_config`)
- `filets/bus.py:40` (`Bus`)
- `filets/bus.py:50` (`LocalBus`)
- `filets/bus.py:106` (`KafkaBus`)
- `filets/bus.py:177` (`make_bus`)
`filets/aio.py:103` (`PublisherBus`)

## 2. L'API HTTP / WebSocket (`api.py`)

`Hub` partage entre tous les clients le catalogue, le dernier état, l'historique du run et les abonnés en direct ; `ApiServer` y ajoute le serveur FastAPI. Les routes (`/api/health`, `/api/status`, `/api/catalog`, `/api/commands`, `/api/runs`, `/api/runs/{id}`, `/api/runs/{id}/events`, `/api/runs/{id}/memories`, et le WebSocket) sont définies dans `create_app`. `Command`, `Accepted`, `Health`, `RunSummary` sont les modèles Pydantic des échanges.

```mermaid
classDiagram
    class Hub {
        +dict? catalog
        +dict? status
        +Callable on_command
        +set clients
        +list buffer
        +int buffer_max
        +asyncio.AbstractEventLoop? loop
        +asyncio.Queue? queue
        -asyncio.Task? _pump_task
        -Lock _lock
        -any _catalog_msg
        +str? last_status
        +str? current_run
        -set _seen_indicators
        +__init__(on_command, buffer_max, catalog)
        +start_hub()
        +stop_hub()
        +drain(timeout)
        +push(topic, data)
        -_broadcast(msg)
        -_pump()
        +attach(ws)
        +detach(ws)
        +dispatch(cmd) bool
        +handle_text(raw)
    }
    class ApiServer {
        +int port
        +any host
        -any _port
        +any runs
        +any memories
        +FastAPI? app
        -_Server? _server
        -asyncio.Task? _serve_task
        +__init__(host, port, on_command, buffer_max, catalog, runs, memories)
        +start()
        +stop()
    }
    class _Server {
        +capture_signals()
    }
    class LocalRuns {
        +Path dir
        +__init__(runs_dir)
        -_summary(run_id) dict?
        +list_runs(limit) list
        +get_run(run_id) dict?
        +events(run_id, etype, limit, offset) list?
    }
    class PgMemories {
        +dict cfg
        +None store
        +Lock lock
        +__init__(cfg)
        -_open()
        +search(run_id, q, k, agent, until) dict
        +aclose() None?
    }
    class Command {
        +ConfigDict model_config
        +Literal type
    }
    class Accepted {
        +bool accepted
        +str type
    }
    class Health {
        +str status
        +int clients
        +str? run_id
        +str? engine_state
    }
    class RunSummary {
        +str run_id
        +bool finished
        +str? reason
        +int? seasons_completed
        +float? final_stock
        +float? capacity
        +int? llm_calls
        +float? wall_s
        +dict? by_system
    }
    class api {
        <<module>>
        +any RUN_ID
        +memories_for(cfg) PgMemories?
        +create_app(hub, runs, memories) FastAPI
    }
    class BaseModel
    class uvicorn_Server
    Hub <|-- ApiServer
    ApiServer "1" *-- "1" _Server : _server
    _Server --|> uvicorn_Server
    ApiServer o-- LocalRuns : runs
    ApiServer o-- PgMemories : memories
    BaseModel <|-- Command
    BaseModel <|-- Accepted
    BaseModel <|-- Health
    BaseModel <|-- RunSummary
    api ..> Hub : create_app
    api ..> Command : POST commands
    api ..> Accepted
    api ..> Health
    api ..> RunSummary
    api ..> LocalRuns : GET runs
    api ..> PgMemories : GET memories
```

**Pour aller plus loin**
- `filets/api.py:173` (`Hub`)
- `filets/api.py:422` (`ApiServer`)
- `filets/api.py:312` (`create_app`)
- `filets/api.py:80` (`LocalRuns`)
- `filets/api.py:134` (`PgMemories`)
- `filets/api.py:46` (`Command`)

## 3. Événements et indicateurs

Tout ce qui se passe est un **événement** : `EventFactory` les fabrique (numérotés, horodatés, validés par `schemas.py`), les envoie sur le bus et les écrit via `Recorder` dans `runs/<run>/events.jsonl`. `IndicatorPublisher` (dans `pipeline.py`) écoute le bus et nourrit un `IndicatorEngine` qui calcule les KPI, puis les republie. `console.py` affiche les événements et le bilan en texte.

```mermaid
classDiagram
    class EventFactory {
        +str run_id
        +SimClock clock
        +any bus
        +Recorder? recorder
        +int seq
        +dict index
        +None when
        +int deadletters
        +dict renamed
        -int _tmp
        +__init__(run_id, clock, bus, recorder)
        +defer(buf)
        +flush(buf) None?
        +emit(etype, payload, actor, sim_time) dict
    }
    class Recorder {
        +Path run_dir
        -any _f
        +__init__(run_dir)
        +write(event) None?
        +flush()
        +close()
    }
    class IndicatorPublisher {
        +IndicatorEngine engine
        +any bus
        +any runs_dir
        +bool journal
        +str journal_name
        -None _f
        -None _run
        +list lags
        +__init__(bus, runs_dir, quota_tolerance, journal, journal_name)
        +on_event(ev) dict?
        -_open(run_id, name)
        +close()
    }
    class IndicatorEngine {
        +float tol
        +None run_id
        +int skipped
        +float capacity
        +float msy
        +dict fishers
        +float stock
        +int season
        +dict catches
        +dict catch_ids
        +dict fished
        +list norms
        +dict breaches
        +list promise_outcomes
        +dict incidents
        +dict llm
        +dict by_system
        +dict events_by_id
        +int temporal_violations
        +list staleness
        +int utterances
        +int accusations
        +list history
        +dict last_values
        +bool collapsed
        +dict lakes
        +dict lake_catch
        +__init__(quota_tolerance)
        +reset()
        +ingest(ev) dict?
        -_set_lake_stocks(stocks)
        +lakes_detail(season) dict
        -_rules_for(fisher, season) list
        -_kept(n, fisher, season, catch) bool
        +season_values(season) tuple
        +snapshot(ev, trigger, sources, extra) dict
        +season_snapshot(ev) dict
    }
    class indicators {
        <<module>>
        +gini(values) float
    }
    class schemas {
        <<module>>
        +int SCHEMA_VERSION
        +dict NUM
        +dict NUM_OR_NULL
        +dict STR
        +dict STR_OR_NULL
        +dict INT
        +dict BOOL
        +dict IDS
        +dict RETRIEVED
        +any ENVELOPE
        +dict PAYLOADS
        +list COMMAND_TYPES
        +any COMMAND
        +any STATUS
        +obj(required, optional, extra) dict
        +validate_event(event) list
        +validate_command(cmd) list
        +validate_status(status) list
    }
    class console {
        <<module>>
        +console_printer()
        +print_summary(world, pub) None?
    }
    class pipeline {
        <<module>>
    }
    class World
    class SimClock
    class Bus
    World "1" *-- "1" EventFactory : events
    World "1" *-- "0..1" Recorder : recorder
    EventFactory o-- Recorder : recorder
    EventFactory o-- SimClock : clock
    EventFactory o-- Bus : bus
    EventFactory ..> schemas : validate_event
    IndicatorPublisher "1" *-- "1" IndicatorEngine : engine
    IndicatorPublisher o-- Bus : bus
    IndicatorEngine ..> indicators : gini
    console ..> IndicatorPublisher : print_summary
    pipeline ..> IndicatorPublisher
```

**Pour aller plus loin**
- `filets/events.py:35` (`EventFactory`)
- `filets/events.py:14` (`Recorder`)
`filets/pipeline.py:16` (`IndicatorPublisher`)
`filets/indicators.py:36` (`IndicatorEngine`)
- `filets/schemas.py:234` (`validate_event`)
`filets/console.py:5` (`console_printer`)

## 4. Stockage : historique et objets

L'historique de plusieurs parties va dans une base : `HistoryStore` (SQLite) ou `PgHistoryStore` (PostgreSQL). `_SqliteAsync` (dans `services/store.py`) donne à SQLite la même interface asynchrone que `PgHistoryStore`. Les fichiers volumineux vont au stockage objet : `LocalObjects` (disque) ou `S3Objects` (MinIO/S3), qui ont les mêmes méthodes sans classe commune.

```mermaid
classDiagram
    class HistoryStore {
        +any db
        +__init__(path)
        +add_event(ev)
        +add_indicator(msg)
        +ingest_run_dir(run_dir) int
        +commit()
        +close()
    }
    class PgHistoryStore {
        +int pending
        +str dsn
        +None pool
        -list _events
        -list _runs
        -list _indicators
        +__init__(dsn)
        +open() None?
        +add_event(ev) None?
        +add_indicator(msg) None?
        +commit() None?
        -_write(events, runs, indicators) None?
        +ingest_run_dir(run_dir) int
        +fetch(sql, args)
        +close() None?
    }
    class _SqliteAsync {
        +HistoryStore db
        +any add_event
        +any add_indicator
        +__init__(path)
        +open() None?
        +commit() None?
        +close() None?
    }
    class LocalObjects {
        +Path root
        +str where
        +__init__(root)
        -_path(key) Path
        +open() None?
        +put_bytes(key, data, ctype) str
        +get_bytes(key) bytes
        +exists(key) bool
        +list(prefix) list
        +aclose() None?
    }
    class S3Objects {
        +str bucket
        +str where
        +Minio client
        +__init__(endpoint, bucket, access_key, secret_key, secure, region)
        +open() None?
        +put_bytes(key, data, ctype) str
        +get_bytes(key) bytes
        +exists(key) bool
        +list(prefix) list
        +aclose() None?
    }
    class objects {
        <<module>>
        +tuple RUN_FILES
        +content_type(name) str
        +make_objects(cfg)
        +archive_run(objects, run_dir, run_id) list
    }
    class services_store {
        <<module>>
        +amain(cfg, sqlite_path, dsn, stop, group) None?
        +main()
    }
    class World
    _SqliteAsync "1" *-- "1" HistoryStore : db
    services_store ..> PgHistoryStore : si dsn
    services_store ..> _SqliteAsync : sinon
    objects ..> LocalObjects : make_objects
    objects ..> S3Objects : make_objects
    World ..> objects : make_objects, archive_run
```

**Pour aller plus loin**
`filets/store.py:76` (`HistoryStore`)
`filets/pgstore.py:71` (`PgHistoryStore`)
- `filets/objects.py:36` (`LocalObjects`)
- `filets/objects.py:76` (`S3Objects`)
- `filets/objects.py:119` (`make_objects`)
- `filets/objects.py:135` (`archive_run`)
`filets/services/store.py:26` (`_SqliteAsync`)

## 5. Services du mode distribué (`services/`)

En mode Kafka, trois processus séparés du moteur : `indicators` (calcule les KPI), `store` (range l'historique), `bridge` (relie le bus à l'interface Godot par l'API). `_common` leur fournit les arguments de ligne de commande et la boucle de consommation.

```mermaid
classDiagram
    class services__common {
        <<module>>
        +base_args(desc) argparse.ArgumentParser
        +kafka_cfg(args) dict
        +consume_forever(consumer, handle, stop, on_idle)
    }
    class services_indicators {
        <<module>>
        +amain(cfg)
        +main()
    }
    class services_store {
        <<module>>
        +amain(cfg, sqlite_path, dsn, stop, group) None?
        +main()
    }
    class services_bridge {
        <<module>>
        +amain(cfg, host, port)
        +main()
    }
    class IndicatorPublisher
    class PublisherBus
    class ApiServer
    class LocalRuns
    class HistoryStore
    class PgHistoryStore
    class config
    class vectors
    class aio
    services_indicators ..> IndicatorPublisher
    services_indicators ..> PublisherBus
    services_indicators ..> services_common
    services_store ..> HistoryStore
    services_store ..> PgHistoryStore
    services_store ..> services_common
    services_bridge ..> ApiServer
    services_bridge ..> LocalRuns
    services_bridge ..> services_common
    services_common ..> config : load_config
    services_store ..> vectors : postgres_dsn
    services_bridge ..> aio
```

**Pour aller plus loin**
- `filets/services/indicators.py:20` (`amain`)
- `filets/services/store.py:43` (`amain`)
- `filets/services/bridge.py:23` (`amain`)
- `filets/services/_common.py:26` (`consume_forever`)

## 6. Configuration, catalogue, ligne de commande et banc d'essai

`config.py` charge et normalise la configuration YAML ; `catalog.py` fabrique le menu de démarrage ; `cli.py` expose les commandes (`run`, `serve`, `replay`, `verify`, `batch`, `schemas`…) ; `bench.py` rejoue des appels enregistrés pour comparer des modèles. `__main__.py` ne fait qu'appeler `cli.main()`.

```mermaid
classDiagram
    class config {
        <<module>>
        +any ROOT
        +deep_merge(base, over) dict
        +load_config(path, overrides) dict
        +set_dotted(d, dotted, value) None?
        +apply_random_valley(cfg) None?
        +normalize(cfg) dict
        +sustainable_yield(cfg) float
    }
    class catalog {
        <<module>>
        +dict LIMITS
        +list SPEEDS
        +list LLM_OPTIONS
        +list REFLECTIONS
        +list MODES
        +list COMMUNICATIONS
        +list COUNCILS
        +list FLEETS
        +fleet_mix(cfg, fleet) dict
        +boats_catalog(cfg) list
        +base_population(cfg) list
        +generate_world(cfg, villages, fishers, seed, fleet, lakes, patrols, mode) dict
        +villages_of_specs(specs) list
        +build_catalog(cfg, llm) dict
    }
    class cli {
        <<module>>
        +build_cfg(args) dict
        +new_run_id(cfg) str
        +make_api(cfg, port, on_command, catalog)
        +unique_run_id(cfg) str
        +run_once(cfg, ws, ws_port, linger, run_id, quiet) str
        +serve(cfg, ws, ws_port, quiet, llm) None?
        +load_events(run_id, runs_dir) list
        +replay(run_id, cfg, speed, ws, ws_port, linger) bool
        +compare_indicators(run_id, runs_dir) bool
        +verify(run_id, cfg) bool
        +batch(configs, runs, base_args, db_path) None?
        +sql_blocks(text) list
        +print_table(title, columns, rows) None?
        +ingest_pg(dsn, runs_dir, ids) None?
        +query_pg(dsn, blocks) None?
        +retrieval_sample(run_id, cfg, n, seed) Path
        +export_schemas()
        +main(argv)
    }
    class bench {
        <<module>>
        +server_running(port, host) bool
        +norm(purpose, key, v)
        +same(purpose, a, b) bool
        +load_calls(path, limit) list
        +bench(cfg, rows) dict
        +run(run_id, cfg, runs_dir, limit, port) int
    }
    class Engine
    class World
    class ApiServer
    class HistoryStore
    class IndicatorEngine
    class LocalBus
    class llm
    cli ..> config : load_config
    cli ..> Engine : serve
    cli ..> World : run_once
    cli ..> ApiServer : make_api
    cli ..> HistoryStore : batch
    cli ..> IndicatorEngine : verify
    cli ..> LocalBus : make_bus
    Engine ..> catalog : build_catalog
    Engine ..> config : deep_merge, load_config
    bench ..> llm : OpenAICompatClient, extract_json
```

**Pour aller plus loin**
- `filets/cli.py:359` (`main`)
- `filets/cli.py:86` (`run_once`)
- `filets/cli.py:131` (`serve`)
- `filets/cli.py:162` (`replay`)
- `filets/cli.py:219` (`verify`)
- `filets/config.py:26` (`load_config`)
- `filets/config.py:64` (`normalize`)
- `filets/catalog.py:145` (`build_catalog`)
- `filets/bench.py:48` (`bench`)
- `filets/bench.py:77` (`run`)
