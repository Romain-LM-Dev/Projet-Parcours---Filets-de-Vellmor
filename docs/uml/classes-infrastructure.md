# Infrastructure : salon, API, bus, événements, indicateurs, stockage

Cette partie est tout ce qui **entoure la simulation** : le salon qui lance les parties (`Engine`), l'API HTTP/WebSocket
qui parle à l'interface Godot, le bus par lequel passent les événements, l'enregistrement de ces événements, le calcul des
indicateurs (KPI) et le stockage de l'historique. Les fichiers de fonctions (`api.py` pour ses routes, `cli.py`, `config.py`,
`catalog.py`, `bench.py`, `services/`) sont montrés comme `<<module>>`.

## 1. Le salon, l'API et le bus

`Engine` est la boucle du salon : il attend une demande de partie, construit la configuration, crée un `World` et publie son
état. L'`ApiServer` (un `Hub` + FastAPI) relaie les messages vers les clients WebSocket et reçoit les commandes. Le bus
(`LocalBus` en local, `KafkaBus` en mode distribué) transporte événements et commandes ; `Bus` est le contrat commun.

```mermaid
classDiagram
    class Engine {
        +dict base_cfg
        +Bus bus
        +str engine_id
        +dict catalog
        +str state
        +World world
        +IndicatorPublisher pub
        +serve()
        +generate(req)
        +status() dict
        +publish_status(state)
        +close()
    }
    class World
    class Bus {
        <<classe de base>>
        +publish(topic, event, key)
        +subscribe(topic, callback)
        +send_command(cmd)
        +poll_commands() list
        +wait_ready(timeout) bool
        +flush()
        +close()
    }
    class LocalBus {
        +dict _subs
        +Queue _commands
        +dict counts
    }
    class KafkaBus {
        +str bootstrap
        +dict topics
        +str group
    }
    class Hub {
        +set clients
        +list buffer
        +str last_status
        +str current_run
        +push(topic, data)
        +attach(ws)
        +detach(ws)
        +dispatch(cmd) bool
    }
    class ApiServer {
        +str host
        +FastAPI app
        +LocalRuns runs
        +PgMemories memories
        +start()
        +stop()
    }
    class LocalRuns {
        +list_runs(limit) list
        +get_run(run_id) dict
        +events(run_id, etype, limit, offset) list
    }
    class PgMemories {
        +search(run_id, q, k, agent, until) dict
    }
    class api {
        <<module>>
        +create_app(hub, runs, memories) FastAPI
        +GET api_health
        +GET api_status
        +GET api_catalog
        +POST api_commands
        +GET api_runs
        +GET runs_id
        +GET runs_id_events
        +GET runs_id_memories
    }
    class engine {
        <<module>>
        +validate_request(req) list
        +build_game_config(base_cfg, req) dict
        +preflight(cfg, progress)
        +check_storage(cfg, say)
    }

    Bus <|.. LocalBus
    Bus <|.. KafkaBus
    Hub <|-- ApiServer
    Engine o-- Bus : bus
    Engine ..> World : cree une partie
    World o-- Bus : bus
    ApiServer o-- LocalRuns : runs
    ApiServer o-- PgMemories : memories
    ApiServer ..> api : create_app
    api ..> Hub : routes
```

Dans `cli.py`, `serve` crée le bus et l'`ApiServer` puis donne la commande reçue à l'`Engine`. En mode Kafka, l'API et le
pont (`services/bridge.py`) tournent dans un autre processus que le moteur.

**Pour aller plus loin**
- `filets/engine.py:304` (`Engine`), `:44` (`validate_request`), `:152` (`build_game_config`)
- `filets/api.py:173` (`Hub`), `:422` (`ApiServer`), `:312` (`create_app` et routes), `:80` (`LocalRuns`), `:134` (`PgMemories`)
- `filets/bus.py:40` (`Bus`), `:50` (`LocalBus`), `:106` (`KafkaBus`), `:177` (`make_bus`)

## 2. Événements, indicateurs et stockage

Tout ce qui se passe est un **événement** : `EventFactory` les fabrique (numérotés, horodatés), les envoie sur le bus et les
écrit via le `Recorder` dans `runs/<run>/events.jsonl`. `IndicatorPublisher` écoute le bus, nourrit un `IndicatorEngine` qui
calcule les KPI (Gini, stock, quotas…) et les republie. L'historique de plusieurs parties va dans une base (`HistoryStore`
SQLite ou `PgHistoryStore` PostgreSQL) ; les fichiers volumineux vont au stockage objet (`LocalObjects` ou `S3Objects`).

```mermaid
classDiagram
    class World {
        +EventFactory events
        +Recorder recorder
        +object objects
    }
    class EventFactory {
        +str run_id
        +SimClock clock
        +int seq
        +dict index
        +int deadletters
        +emit(etype, payload, actor, sim_time) dict
        +defer(buf)
        +flush(buf)
    }
    class Recorder {
        +Path run_dir
        +write(event)
        +flush()
        +close()
    }
    class Bus {
        <<classe de base>>
    }
    class IndicatorPublisher {
        +IndicatorEngine engine
        +Bus bus
        +bool journal
        +list lags
        +on_event(ev) dict
        +close()
    }
    class IndicatorEngine {
        +float tol
        +reset()
        +ingest(ev) dict
        +season_values(season) tuple
        +lakes_detail(season) dict
        +snapshot(ev, trigger, sources) dict
        +season_snapshot(ev) dict
    }
    class HistoryStore {
        +Connection db
        +add_event(ev)
        +add_indicator(msg)
        +ingest_run_dir(run_dir) int
        +commit()
        +close()
    }
    class PgHistoryStore {
        +str dsn
        +list _events
        +list _indicators
        +open()
        +add_event(ev)
        +add_indicator(msg)
        +commit()
        +fetch(sql, args)
    }
    class LocalObjects {
        +Path root
        +put_bytes(key, data, ctype) str
        +get_bytes(key) bytes
        +exists(key) bool
        +list(prefix) list
    }
    class S3Objects {
        +str bucket
        +put_bytes(key, data, ctype) str
        +get_bytes(key) bytes
        +exists(key) bool
        +list(prefix) list
    }
    class objects {
        <<module>>
        +make_objects(cfg)
        +archive_run(objects, run_dir, run_id) list
    }

    World "1" *-- "1" EventFactory : events
    World "1" *-- "0..1" Recorder : recorder
    EventFactory o-- Recorder
    EventFactory o-- Bus
    IndicatorPublisher "1" *-- "1" IndicatorEngine : engine
    IndicatorPublisher o-- Bus
    objects ..> LocalObjects : make_objects
    objects ..> S3Objects : make_objects
    World ..> objects : archive en fin de partie
```

`IndicatorPublisher` vit dans `pipeline.py` (et non dans `indicators.py`, qui ne contient que `IndicatorEngine`). Le schéma
de chaque événement est dans `schemas.py`. `LocalObjects` et `S3Objects` ont les mêmes méthodes sans classe commune.

**Pour aller plus loin**
- `filets/events.py:35` (`EventFactory`), `:14` (`Recorder`) ; `filets/schemas.py` (un schéma par événement)
- `filets/pipeline.py:16` (`IndicatorPublisher`) ; `filets/indicators.py:36` (`IndicatorEngine`)
- `filets/store.py:76` (`HistoryStore`) ; `filets/pgstore.py:71` (`PgHistoryStore`)
- `filets/objects.py:36` (`LocalObjects`), `:76` (`S3Objects`), `:119` (`make_objects`), `:135` (`archive_run`)

## 3. Services, configuration, catalogue, ligne de commande

Les modules de service (`services/`) sont des processus séparés du mode Kafka : l'un calcule les indicateurs, l'autre range
l'historique, le dernier relie le bus à l'interface. Chacun a une fonction `main` et une boucle `amain`. `config.py` charge
et normalise la configuration YAML ; `catalog.py` fabrique le menu de démarrage ; `cli.py` expose les commandes
(`run`, `serve`, `replay`, `verify`, `batch`, `schemas`…) ; `bench.py` rejoue des appels enregistrés pour comparer des modèles.

```mermaid
classDiagram
    class cli {
        <<module>>
        +build_cfg(args) dict
        +run_once(cfg, ws, ws_port)
        +serve(cfg, ws, ws_port)
        +replay(run_id, cfg, speed, ws, ws_port, linger) bool
        +verify(run_id, cfg) bool
        +batch(configs, runs, base_args, db_path)
        +export_schemas()
        +main(argv)
    }
    class config {
        <<module>>
        +load_config(path, overrides) dict
        +deep_merge(base, over) dict
        +normalize(cfg) dict
        +apply_random_valley(cfg)
        +sustainable_yield(cfg) float
    }
    class catalog {
        <<module>>
        +build_catalog(cfg, llm) dict
        +generate_world(cfg, villages, fishers, seed) dict
        +base_population(cfg) list
        +boats_catalog(cfg) list
    }
    class bench {
        <<module>>
        +load_calls(path, limit) list
        +bench(cfg, rows) dict
        +run(run_id, cfg, runs_dir, limit, port) int
    }
    class services_indicators {
        <<module>>
        +amain(cfg)
        +main()
    }
    class services_store {
        <<module>>
        +amain(cfg, sqlite_path, dsn, stop)
        +main()
    }
    class services_bridge {
        <<module>>
        +amain(cfg, host, port)
        +main()
    }
    class services_common {
        <<module>>
        +base_args(desc)
        +kafka_cfg(args) dict
        +consume_forever(consumer, handle, stop, on_idle)
    }
    class Engine
    class World
    class ApiServer
    class IndicatorPublisher
    class HistoryStore
    class PgHistoryStore

    cli ..> config : load_config
    cli ..> Engine : serve
    cli ..> World : run_once
    cli ..> ApiServer : make_api
    cli ..> HistoryStore : batch, ingest
    Engine ..> catalog : build_catalog
    services_indicators ..> IndicatorPublisher
    services_indicators ..> services_common
    services_store ..> HistoryStore : sqlite
    services_store ..> PgHistoryStore : postgres
    services_store ..> services_common
    services_bridge ..> ApiServer
    services_bridge ..> services_common
```

**Pour aller plus loin**
- `filets/cli.py:359` (`main`), `:86` (`run_once`), `:131` (`serve`), `:162` (`replay`), `:219` (`verify`)
- `filets/config.py:26` (`load_config`), `:64` (`normalize`) ; `filets/catalog.py:145` (`build_catalog`)
- `filets/bench.py:48` (`bench`), `:77` (`run`)
- `filets/services/indicators.py:20`, `store.py:43`, `bridge.py:23` (les trois `amain`) ; `services/_common.py:26`
