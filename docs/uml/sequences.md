# Diagrammes de séquence

Un diagramme de séquence se lit de haut en bas : l'ordre des appels descend, chaque colonne est un objet du code. Une flèche pleine `->>` est un appel, une flèche pointillée `-->>` une réponse ou un signal. Les blocs `par` montrent des appels qui se font en même temps, `loop` une répétition, `alt` un choix, `opt` une étape facultative. Les notes `Note` rappellent l'autre temps, le **temps simulé** du monde (la saison dure 30 jours simulés) : réfléchir ne prend pas de temps simulé, agir en prend (`docs/temps.md`).

Huit scénarios, découpés en plusieurs diagrammes quand il y a trop de participants pour un seul : (a) démarrer une partie (a1 à a3), (b) la décision de prise d'un pêcheur (b1 à b3), (c) la veillée (c1, c2), (d) une rumeur injectée par le joueur, (e) le rejeu (e1 bus local, e2 Kafka), (f) la fin de saison, (g) le tirage d'une vallée depuis le menu, (h) l'arrêt d'une partie.

Déploiement représenté : celui de l'architecture complète (`docs/architecture.md`), avec le bus Kafka, le service `bridge` (processus séparé qui porte l'API FastAPI), les services `indicators` et `store`, PostgreSQL + pgvector, le stockage objet S3 (MinIO) et Ollama. Le bus **local** (`LocalBus`, sans Kafka) est la variante des essais rapides : le moteur ouvre lui-même l'API (`filets/cli.py:131-146`), les topics sont des listes d'abonnés en mémoire, et il calcule les indicateurs lui-même (`filets/engine.py:318-322`). Là où la variante change l'ordre des appels, le diagramme le dit.

Vocabulaire des participants : *StartMenu*, *Main* (`main.gd`), *WsClient* : scripts Godot. *ApiServer* : l'API FastAPI (`Hub` + routes, `filets/api.py`), portée par le *Bridge* (`filets/services/bridge.py`) en Kafka. *Kafka* : le courtier, avec cinq topics `filets.events`, `filets.indicators`, `filets.commands`, `filets.status`, `filets.deadletter` (`config/default.yaml:196-204`). *KafkaBus* : l'objet `bus` du moteur. *Engine* : le salon. *World* : la partie. *SeasonScheduler* : l'ordonnanceur d'une saison. *EventFactory* : fabrique et publie les événements ; *Recorder* : écrit `events.jsonl`.

## (a) Démarrer une partie depuis le menu

### a1. Du clic jusqu'à la commande reçue par le moteur

Le joueur règle sa partie dans le menu et clique sur « Démarrer la partie ». Le menu vérifie que chaque pêcheur a un prénom, fabrique le dictionnaire de configuration et le signale à `Main`, qui l'envoie en commande JSON `start_game` par WebSocket. L'API la transmet au pont, qui la dépose dans le topic Kafka `filets.commands`. Côté moteur, un fil du `KafkaBus` lit ce topic et pose la commande dans une file locale ; la boucle du salon (toutes les 0,1 s) la prend.

```mermaid
sequenceDiagram
    autonumber
    actor J as Joueur
    participant SM as StartMenu
    participant M as Main main.gd
    participant WS as WsClient
    participant API as ApiServer Hub
    participant BR as Bridge amain
    participant K as Kafka filets.commands
    participant KB as KafkaBus thread _consume
    participant ENG as Engine serve

    J->>SM: clic sur Démarrer la partie (_on_start)
    alt moteur indisponible ou prénom vide
        SM->>SM: return ou show_error(Chaque pêcheur a besoin d'un prénom)
    else prêt
        SM->>SM: busy = true puis build_config()
        SM-->>M: signal start_requested(cfg)
        M->>WS: send(type start_game, config cfg)
        alt WebSocket non ouvert
            WS-->>M: false
            M->>SM: show_error(Pas de connexion au moteur)
        else ouvert
            WS->>API: send_text(JSON)
            API->>API: socket reçoit puis hub.handle_text(raw)
            API->>API: json.loads puis dispatch(cmd)
            API->>BR: on_command(cmd)
            BR->>K: aio.send(prod, cfg, commands, cmd)
            KB->>K: Consumer.poll
            K-->>KB: message
            KB->>KB: _commands.put(json.loads)
            loop toutes les 0,1 s tant que le salon est ouvert
                ENG->>KB: poll_commands()
            end
            KB-->>ENG: liste de commandes dont start_game
            ENG->>ENG: _play(cmd.config)
            ENG->>KB: poll_commands() pour vider les clics répétés
        end
    end
```

Dans le code :
- Godot : `godot/scripts/start_menu.gd:1402-1413` (`_on_start`), `:1377` (`build_config`), `:14` (signal `start_requested`) ; `godot/scripts/main.gd:552` (connexion), `:598-600` (`_on_menu_start`), `:723-726` (`_send`) ; `godot/scripts/ws_client.gd:58-62` (`send`, refus si non ouvert).
- API : `filets/api.py:321-335` (`socket`), `:293` (`handle_text`), `:282` (`dispatch`, appelle `on_command`).
- Pont : `filets/services/bridge.py:28-30` (`on_command` publie sur `commands`), `filets/aio.py:97` (`send`), `:90` (`producer`).
- Bus du moteur : `filets/bus.py:106` (`KafkaBus`), `:134` (`_consume`, fil), `:158` (`poll_commands`), `:131` (`wait_ready`, partition de commandes reçue avant d'annoncer le salon).
- Moteur : `filets/engine.py:348-374` (`serve`, `poll_commands` `:358`, `start_game` `:360`, vidage de la file après la partie), `:437` (`_play`).
- Variante bus local : `filets/cli.py:140` (`make_api(..., bus.send_command, ...)`), `filets/bus.py:65-74` (`LocalBus.send_command`, `poll_commands`) : le pont et Kafka disparaissent, l'API pose la commande directement dans la file du moteur.

### a2. Le moteur prépare, crée le monde et ouvre la partie

Le moteur annonce `starting`, construit la configuration de la partie (en validant la demande), puis vérifie et charge les modèles, la base et le stockage objet. Pendant ce temps (parfois une minute pour charger un modèle), une tâche republie l'état toutes les 1,5 s pour que Godot ne croie pas le moteur mort. Si tout est prêt, `World` est construit (horloge, contrôle, `EventFactory`, `Recorder`, `LLMRouter`, mémoires, retriever), puis `run()` ouvre le stockage et émet `run_start`.

```mermaid
sequenceDiagram
    autonumber
    participant ENG as Engine
    participant KB as KafkaBus
    participant K as Kafka
    participant OL as Ollama
    participant PG as PostgreSQL pgvector
    participant S3 as Stockage objet S3
    participant W as World
    participant EF as EventFactory
    participant REC as Recorder

    ENG->>KB: publish status = starting
    KB->>K: produce filets.status
    ENG->>ENG: build_game_config(base_cfg, request)
    Note over ENG: validate_request et validate_lakes, GameRequestError si refus
    par préparation _prepare
        ENG->>ENG: tâche beat toutes les 1,5 s publish_status avec detail
        KB->>K: produce filets.status
    and vérifications preflight
        ENG->>ENG: used_models(cfg), clé API présente ?
        ENG->>OL: GET api/tags
        OL-->>ENG: modèles présents
        opt modèle de décision absent
            ENG->>ENG: retire le niveau reflexe, les réflexes passeront par le petit modèle
        end
        ENG->>OL: POST v1/systemone ou api/generate pour charger chaque modèle (keep_alive 30m)
        OL-->>ENG: 200
        ENG->>PG: asyncpg.connect (si pgvector ou historique postgres)
        ENG->>OL: POST api/embed (modèle de plongement)
        ENG->>S3: objects.open puis aclose
    end
    alt refus ou service absent
        ENG->>KB: publish status = idle avec error
    else tout est prêt
        ENG->>ENG: unique_run_id(cfg) et choix de l'option LLM
        ENG->>W: World(cfg, bus, run_id, engine_id, lobby, advised_speed)
        W->>REC: Recorder(run_dir) ouvre events.jsonl
        W->>EF: EventFactory(run_id, clock, bus, recorder)
        ENG->>W: ctl.set_speed ou set_fast
        ENG->>W: run()
        W->>S3: objects.open
        W->>PG: vectors.open puis retriever.open (corpus vectorisé)
        W->>W: start()
        W->>EF: emit(run_start)
        Note over W,EF: temps simulé t = 0, début de la saison 1
        EF->>EF: validate_event puis seq et event_id
        EF->>KB: publish(events, ev)
        KB->>K: produce filets.events
        EF->>REC: write(ev)
        W->>EF: emit(memory_write) pour Une nouvelle année commence
        W->>W: lake_update(init) puis publish_status
        W->>W: tâche _command_pump (0,05 s)
    end
```

Dans le code :
- Moteur : `filets/engine.py:437-479` (`_play`), `:342-346` (`publish_status`), `:152` (`build_game_config`), `:44` (`validate_request`), `:125` (`validate_lakes`), `:416-435` (`_prepare`, tâche `beat` `:424-428`), `:207` (`preflight`, `GET /api/tags` `:229`, chargement `:247-259`), `:263` (`check_storage` : PostgreSQL, plongement, stockage objet), `filets/cli.py:75` (`unique_run_id`).
- Monde : `filets/world.py:213` (`World.__init__`), `:226-227` (`SimClock`, `GameControl`), `:230` (`Recorder`), `:233` (`EventFactory`), `:253-254` (mémoires), `:320-324` (retriever), `:325` (`LLMRouter`), `:2976` (`run`), `:2918` (`open_storage`), `:2873` (`start`), `:1732` (`_command_pump`).
- Événements : `filets/events.py:35` (`EventFactory`), `:71` (`emit`), `:108` (`bus.publish`), `:14-28` (`Recorder`) ; `filets/bus.py:144` (`KafkaBus.publish`).
- Échec : `filets/engine.py:450-461`.

### a3. La diffusion de `run_start` : services, API, Godot

Le même événement est lu par trois consommateurs Kafka indépendants : le service `indicators` (il se place sur le dernier `run_start` et publie les indicateurs dans `filets.indicators`), le service `store` (il écrit dans la base, puis valide sa position) et le pont (qui alimente le tampon de l'API). L'API ne garde que l'historique du run en cours : à `run_start` elle vide son tampon. Godot reçoit chaque message, remet son affichage à zéro à `run_start` et ferme le menu quand l'état passe à `running`.

```mermaid
sequenceDiagram
    autonumber
    participant K as Kafka
    participant IND as Service indicators
    participant IP as IndicatorPublisher
    participant ST as Service store
    participant DB as PostgreSQL ou SQLite
    participant BR as Bridge amain
    participant API as ApiServer Hub
    participant WS as WsClient
    participant M as Main main.gd
    participant SM as StartMenu

    par service indicators
        K-->>IND: events depuis le dernier run_start (aio.messages)
        IND->>IP: on_event(run_start)
        IP->>IP: _open(run_id) ouvre indicators.jsonl
        IP->>K: produce filets.indicators à chaque indicateur
    and service store
        K-->>ST: getmany(2000 messages max)
        ST->>DB: add_event(data) puis add_indicator
        ST->>DB: commit()
        ST->>K: consumer.commit() après la base
    and pont
        K-->>BR: events (depuis run_start), indicators, status (aio.messages)
        BR->>API: push(topic, data)
    end
    API->>API: loop.call_soon_threadsafe(queue.put_nowait)
    API->>API: _pump : sous verrou
    alt topic status avec catalog
        API->>API: relaye catalog à part si changé puis status allégé
    else events run_start
        API->>API: buffer = vide, current_run = run_id
    else indicators
        API->>API: écarte un autre run ou un doublon
    end
    API->>API: buffer.append(msg) puis _broadcast(msg)
    API-->>WS: send_text(topic status)
    WS-->>M: signal message(status)
    M->>M: _on_status : engine = s, world.paused, set_thinking
    M->>SM: set_engine(starting)
    API-->>WS: send_text(topic events, run_start)
    WS-->>M: signal message(events)
    M->>M: _on_event(run_start) puis _reset(ev)
    M->>M: world.reset_world, chart.reset, legend.set_villages
    M->>SM: close() quand l'état est running
```

Dans le code :
- Indicateurs : `filets/services/indicators.py:20-43` (`amain`), `:30-31` (`messages`, `on_event`), `filets/pipeline.py:28` (`on_event`), `:49-56` (`_open`), `filets/aio.py:29` (`last_run_start_offset`), `:64` (`assigned_consumer`), `:81` (`messages`), `:103-135` (`PublisherBus`).
- Historique : `filets/services/store.py:43-77` (`amain`, lecture groupée `:56`, `add_event` `:64`, `commit` `:68`, `consumer.commit` `:69`), `filets/pgstore.py:88` et `filets/store.py:82` (`add_event`), `:102`/`:105` (`add_indicator`).
- Pont et API : `filets/services/bridge.py:36-43` (consommateur et `push`), `filets/api.py:213` (`push`), `:236-266` (`_pump`), `:229` (`_broadcast`).
- Godot : `godot/scripts/ws_client.gd:28-56` (`_process` lit les paquets et émet `message`), `godot/scripts/main.gd:729-755` (`_on_message`), `:608-640` (`_on_status`), `:757-762` (`_on_event`), `:1161` (`_reset`), `:1175-1182` (`reset_world`, `chart.reset`, `legend.set_villages`), `:629-631` (fermeture du menu).
- Variante bus local : `filets/engine.py:318-322` (l'`IndicatorPublisher` est dans le moteur et s'abonne à `events`), `filets/cli.py:141-143` (`bus.subscribe(topic, bridge.push)`) : pas de service `indicators`, `store` ni `bridge`, les événements passent par des appels de fonction.

## (b) La décision de prise d'un pêcheur

C'est la décision centrale du jeu : combien pêcher. L'ordonnanceur inscrit pour chaque pêcheur une `Decision` au jour de départ de ce pêcheur, puis les lance par lots en parallèle. Trois diagrammes : b1 l'observation (ce que l'agent sait), b2 le choix système 1 ou 2 et l'appel du modèle (avec le limiteur et la file de modèles), b3 la sortie et l'application de la prise.

### b1. Ordonnancement et observation : mémoire et RAG

Avant tout appel, `observe` assemble ce que l'agent sait à l'instant `horizon` et rien d'autre. Avec PostgreSQL + pgvector, la mémoire de l'agent et le corpus partagé sont interrogés en même temps ; chaque recherche transforme la requête en vecteur (Ollama, `/api/embed`) puis interroge la base. Si la base ou le modèle de plongement tombe, la recherche passe en BM25 en mémoire (`degraded`). Sans base, la recherche se fait directement en mémoire.

```mermaid
sequenceDiagram
    autonumber
    participant S as SeasonScheduler
    participant A as decide_catch
    participant W as World
    participant MS as VectorMemory
    participant R as VectorRetriever
    participant EM as Embedder
    participant OL as Ollama
    participant PG as PostgreSQL pgvector

    Note over S: jour de départ du pêcheur = horizon h, fixé à open_season
    S->>S: at(h, PECHEURS, id, Decision(decide_catch, depart))
    S->>S: play puis run_batch : assemble le lot
    S->>S: parallel(jobs) puis think(noms, True)
    S->>S: publish_status avec thinking
    S->>A: make() dans SimClock.local(h) et EventFactory.defer(buf)
    A->>W: observe(agent, h, catch)
    W->>W: lake.observe (estimation bruitée du stock)
    W->>W: note_lake, applicable_norm, rule_view, known_catches
    W->>W: carnet, clue_lines, active_rumors(h), pinned
    par mémoire de l'agent
        W->>MS: aretrieve(query, h, top_k, exclude)
        MS->>MS: bank.flush()
        MS->>EM: embed(query)
        EM->>OL: POST api/embed (cache LRU)
        OL-->>EM: vecteur
        MS->>PG: search_memories(run, owner, vecteur, h)
        PG-->>MS: lignes classées
    and corpus et lore
        W->>R: asearch(query, hameau, h, top_k)
        R->>R: _flush_lore()
        R->>EM: embed(query)
        R->>PG: search_chunks puis search_lore
        PG-->>R: passages classés
    end
    alt base ou plongement indisponible
        MS-->>W: retrieve() en BM25 mémoire
        R-->>W: local.search() en BM25 mémoire
    end
    W->>W: retrieved = pinned, mémoire, corpus, rumeurs en tête
    W-->>A: obs, state, retrieved, used
```

Dans le code :
- Ordonnancement : `filets/scheduler.py:147-158` (`open_season`, `Decision(a.id, 1.0, ...)` à `opening + a.offset_days`), `:84-98` (`play`), `:100-115` (`run_batch`), `:117-135` (`parallel`), `:137-145` (`think`), `:38-43` (`Decision`), `:64-67` (`at`).
- Observation : `filets/world.py:1250` (`observe`), `:1262-1263` (`lake.observe`, `note_lake`), `:1279` (`pinned`), `:1314-1321` (mémoire et corpus : `retrieve`/`search`, ou `aretrieve`/`asearch` en `asyncio.gather` avec la base), `:1322-1334` (assemblage de `retrieved`, rumeurs en tête `:1328`), `:684` (`active_rumors`), `:1200` (`carnet`), `:1020` (`clue_lines`).
- Mémoire : `filets/memory.py:60` (`retrieve`), `:119-135` (`VectorMemory.aretrieve`), `:91` (`MemoryBank.flush`).
- RAG : `filets/rag.py:179` (`Retriever.search`), `:257-272` (`VectorRetriever.asearch`), `:231` (`_flush_lore`).
- Plongement : `filets/vectors.py:72-95` (`embed` : cache, lots, `POST /api/embed` `:65`).

### b2. Le choix système 1 ou système 2 et l'appel du modèle

Un agent à règles ne consulte aucun modèle : sa prise vient de `catch_rule`. Un agent à IA passe par le routage : avec le profil de réflexion « adaptatif », une routine (lac sain et stable) va au système 1 (réflexe, rapide), tout le reste au système 2 (réflexion, schéma JSON imposé). Sans profil adaptatif tout est système 2. L'appel passe par `LLMRouter.complete`, qui choisit le client du niveau, puis par la file `ModelGate` (si le fournisseur est local) et le limiteur de débit, avant le POST vers Ollama.

```mermaid
sequenceDiagram
    autonumber
    participant A as decide_catch
    participant RT as LLMRouter
    participant CTL as GameControl
    participant CL as Client Ollama
    participant GATE as ModelGate
    participant RL as RateLimiter
    participant OL as Ollama
    participant EF as EventFactory

    alt agent à règles
        A->>A: lake_choice_rule, catch_rule, declare_rule, rule_choices
        A->>EF: emit(decision) justification Règle appliquée
    else agent à IA
        A->>A: routing.choose_system(obs, catch) si profil adaptatif
        alt système 1 réflexe
            A->>RT: complete(agent, tier reflexe ou petit, hint S1)
        else système 2 réflexion
            A->>RT: complete(agent, tier de l'agent, hint S2 + schéma)
        end
        RT->>CTL: checkpoint (pause, arrêt)
        RT->>RT: call_id, clock.in_flight + 1
        alt client SystemOne tier reflexe
            RT->>CL: SystemOneClient.complete
            CL->>GATE: acquire(model) si max_concurrency
            Note over GATE: regroupe les requêtes par modèle, au plus un échange de modèle par vague
            GATE-->>CL: place obtenue
            CL->>OL: POST v1/systemone
        else client OpenAICompat
            RT->>CL: OpenAICompatClient.complete
            CL->>GATE: acquire(model)
            GATE-->>CL: place obtenue
            CL->>RL: limiter.wait (rpm)
            CL->>OL: POST v1/chat/completions (json_schema, seed)
        end
        OL-->>CL: texte JSON
        CL->>GATE: release()
        CL-->>RT: LLMResult
        RT->>CTL: checkpoint : en pause la réponse attend la reprise
        RT->>RT: usage : calls, tokens, by_tier, by_system
        RT->>EF: emit(llm_call)
        opt système 1 et system_one
            RT->>RT: écrit s1_calls.jsonl pour bench-reflexe
        end
        RT-->>A: LLMResult
        opt système 1 en échec
            A->>RT: complete(tier petit)
            RT->>OL: POST v1/chat/completions
        end
        opt système 2 sans réponse lisible et réflexe disponible
            A->>RT: complete(hint S1)
            RT->>OL: POST v1/systemone
        end
        A->>A: extract_json puis detect_drift
        opt statut non ok ou JSON illisible ou sortie de rôle
            A->>EF: emit(incident) quota, no_response, unparseable, out_of_role
        end
    end
```

Dans le code :
- Agent : `filets/agents.py:144` (`decide_catch`), `:154-167` (règles), `:170` (`routing.choose_system`), `:171-186` (réflexe et reprise), `:79-136` (`_ask_llm`, `world.router.complete` `:108`, reprise `petit` `:119`, incidents `:121-136`), `:139` (`reflex_usable`).
- Routage : `filets/routing.py:24` (`reasons_to_think`), `:53` (`choose_system`) ; `filets/prompts.py:42` (`is_adaptive`).
- Routeur : `filets/llm.py:335-362` (`LLMRouter.__init__`, `describe`), `:365-420` (`complete`), `:406` (événement `llm_call`), `:384` (cas annulé).
- Clients : `filets/llm.py:154-174` (`OpenAICompatClient`, `gate` `:173`, `limiter` `:167`), `:176-188` (`complete` avec `gate.acquire` `:181`), `:190-237` (`_complete`, `limiter.wait` `:207`, POST `:209`), `:250-322` (`SystemOneClient`, `gate` `:266`, `complete` `:269-278`).
- File et limiteur : `filets/llm.py:44-59` (`RateLimiter`), `:61-152` (`ModelGate` : `acquire` `:109`, `release` `:124`, `_dispatch` `:132`, `_start_switch` `:147`).
- Contrôle : `filets/control.py:83` (`checkpoint`).

### b3. La sortie : décision publiée dans l'ordre, puis prise appliquée

Les événements des décisions d'un lot sont mis en attente et ne sont émis qu'à la fin, dans l'ordre de la file (jamais dans l'ordre où les modèles répondent). Pour chaque décision, `then` appelle `depart`, qui prépare la sortie ; les effets sur le lac sont des événements du futur dans la file. Le poisson sort du lac à la fin de chaque sortie (un jour simulé après le départ), et le retour vend, déclare et laisse des indices.

```mermaid
sequenceDiagram
    autonumber
    participant S as SeasonScheduler
    participant A as decide_catch
    participant W as World
    participant EF as EventFactory
    participant REC as Recorder
    participant KB as Bus Kafka
    participant G as Main main.gd

    A->>A: borne la prise [min, cale], déclaration au plus égale à la prise
    opt prise absente ou invalide
        A->>A: catch_rule (repli), fallback = true
    end
    A->>EF: emit(decision)
    Note over EF: dans defer : mis en tampon avec un identifiant provisoire
    A->>W: _note_observation(obs, dec), agent.last_decision = dec
    A-->>S: Outcome(valeur, données, décision)
    S->>S: think(noms, False) puis publish_status
    S->>EF: flush(buf) dans l'ordre de la file
    EF->>EF: seq et event_id définitifs
    EF->>KB: publish(events, decision)
    EF->>REC: write(ev)
    S->>W: heal_event_ids(renamed)
    loop pour chaque décision du lot, dans l'ordre
        S->>S: SimClock.local(h) puis then(res) = depart(agent, outcome, h)
        S->>W: plan_trip(agent, valeur, décision, h, declared, lake_name)
        W-->>S: Trip (sorties, jours, lac, coin)
        S->>S: at(jour + 1, land_outing(trip, k)) pour chaque sortie
        S->>S: at(retour, finish_trip(trip))
    end
    Note over S,W: temps simulé : la décision n'a rien coûté, la sortie dure un jour
    S->>S: show(t) avance l'horloge jusqu'à l'échéance
    S->>W: land_outing(trip, k)
    W->>W: lake.take(part, cellule) puis lake_update(catch)
    W->>EF: emit(lake_update)
    S->>W: finish_trip(trip) au retour
    W->>W: vente, richesse, déclaration à l'ancien, indices, réputation
    W->>EF: emit(catch)
    EF->>KB: publish(events, catch)
    KB-->>G: via bridge et API : topic events
    G->>G: _on_event puis world.on_event
    Note over G: la barque sort, +x t s'affiche, une ligne entre dans le fil
```

Dans le code :
- Décision : `filets/agents.py:187-231` (bornage, repli, déclaration, événement `decision` `:222`), `:65-70` (`_note_observation`), `:58` (`Outcome`).
- Publication ordonnée : `filets/scheduler.py:117-135` (`parallel`, `flush` `:131`), `filets/events.py:50-57` (`defer`), `:59-69` (`flush`, `heal_event_ids` appelé `scheduler.py:133`), `filets/world.py:387` (`heal_event_ids`).
- Effets : `filets/scheduler.py:160-171` (`depart`, `plan_trip` `:163`), `filets/world.py:1506` (`plan_trip`), `:1559-1568` (`land_outing`), `:544-555` (`lake_update`, `lake_update` émis `:550`), `:1570` (`finish_trip`, événement `catch` `:1595`), `filets/lake.py:50` (`take`).
- Affichage : `godot/scripts/main.gd:757` (`_on_event`, `catch` `:776`), `godot/scripts/world_view.gd:1167` (`on_event`, `catch` `:1223`).

## (c) La veillée au fil de l'eau

À J25 18 h simulé, les pêcheurs se retrouvent chez l'ancien. Il n'y a pas de tours synchrones : l'ordonnanceur prépare en parallèle les répliques de tous ceux qui ont quelque chose à dire (première passe), choisit qui parle (d'abord celui à qui l'on vient de s'adresser, sinon l'ordre tiré de la graine), vérifie si la réplique choisie est périmée et, si oui, la prépare de nouveau (seconde passe). Une seule personne parle à la fois ; sa réplique dure `speech_minutes` (20 minutes simulées par défaut) et ses effets s'appliquent à sa fin. Plusieurs villages tiennent leur veillée de front (une instance `Village` chacun) : leurs préparations partent dans le même lot parallèle.

### c1. La boucle de préparation et de parole

```mermaid
sequenceDiagram
    autonumber
    participant S as SeasonScheduler
    participant V1 as Village 1
    participant V2 as Village 2
    participant A as speak
    participant W as World
    participant RT as LLMRouter
    participant OL as Ollama
    participant EF as EventFactory

    Note over S: J25 18:00 temps simulé, evening() est un effet de classe CONSEIL
    S->>W: open_assemblies(season, close_t)
    W->>W: investigate(season) : indices de la saison réunis
    S->>EF: emit(phase assembly open)
    S->>V1: Village(sched, asm1, ta)
    S->>V2: Village(sched, asm2, ta)
    loop tant qu'un village n'est pas terminé
        S->>V1: prep_jobs()
        S->>V2: prep_jobs()
        Note over V1,V2: ceux qui n'ont pas de réplique prête, ont encore droit à la parole et ont de quoi dire
        S->>S: prepare(jobs) première passe
        par réplique de chaque agent, tous villages confondus
            S->>A: speak(w, agent, asm, tour, h)
            A->>W: observe(agent, h, speak, asm, tour)
            A->>RT: complete via _ask_llm (système 2)
            RT->>OL: POST v1/chat/completions
        and
            S->>A: speak(w, autre agent, asm, tour, h)
            A->>RT: complete via _ask_llm (système 2)
            RT->>OL: POST v1/chat/completions
        end
        S->>V1: prepared de chaque agent = (réponse, h, tour, paroles et propositions connues)
        S->>V2: prepared de chaque agent
        S->>V1: pick()
        V1-->>S: l'adressé de la dernière parole, sinon clé de la graine, None si rien de prêt (village terminé)
        S->>V2: pick()
        S->>V1: redo(agent choisi) puis stale()
        S->>V2: redo(agent choisi) puis stale()
        opt réplique périmée : on s'est adressé à lui, nommé, accusé, ou une proposition concurrente est apparue
            S->>S: prepare(redo) seconde passe
            par
                S->>A: speak(w, agent, asm, tour, v.t)
                A->>RT: complete (système 2)
                RT->>OL: POST v1/chat/completions
            end
        end
        S->>V1: speak(agent)
        V1->>W: post_utterance(agent, asm, outcome, tour, h)
        W->>EF: emit(utterance) avec to = destinataire
        S->>V2: speak(agent)
        V2->>W: post_utterance(...)
        Note over V1,V2: V.t avance de speech_minutes : la réplique dure, ses effets s'appliquent à sa fin
        Note over V1: l'adressé sera choisi en premier au prochain passage et sa réplique, périmée, refaite
    end
    Note over S: sortie de boucle : plus personne n'a rien à dire (aucune parole et aucune préparation)
```

Dans le code :
- Boucle : `filets/scheduler.py:173-211` (`evening`) ; boucle `while True` `:187-202` ; première passe `:190`, `pick` `:191`, `redo` `:193-197`, seconde passe `:198`, `speak` `:199-201`, sortie `:202`.
- `prepare` : `filets/scheduler.py:213-220`.
- Village : `filets/scheduler.py:233-241` (`Village`), `:245-256` (`prep_jobs`), `:258-266` (`pick`), `:268-278` (`stale`), `:280-287` (`redo`), `:289-302` (`speak`, `SimClock.local(end)` `:298`).
- Agent et monde : `filets/agents.py:232` (`speak`, système 2 `:250`), `filets/world.py:2039` (`open_assemblies`, `investigate` appelée `:2042`), `:2162` (`has_reason_to_speak`), `:2066` (`post_utterance`, `utterance` `:2073`).

### c2. Les bulletins, les propositions et la clôture

Après la dernière parole, chaque participant à IA rend un bulletin : la proposition de règle qu'il soutient (s'il n'en a soutenu aucune) puis son vote sur chaque sanction proposée. Ces appels partent tous en parallèle. À la clôture (J29), chaque proposition est tranchée, les règles adoptées entrent en vigueur et chacun en garde un souvenir.

```mermaid
sequenceDiagram
    autonumber
    participant S as SeasonScheduler
    participant A as ballot
    participant W as World
    participant RT as LLMRouter
    participant OL as Ollama
    participant EF as EventFactory
    participant MS as MemoryStore

    Note over S: après la dernière parole, avant la clôture de la veillée
    par un bulletin par participant à IA
        S->>A: ballot(w, agent, asm)
        opt aucune proposition soutenue
            A->>RT: complete via _quota_ballot
            RT->>OL: POST v1/chat/completions
            A->>W: _support(agent, asm, proposal, u)
            W->>EF: emit(support)
        end
        opt sanctions en attente
            A->>RT: complete via _sanction_ballot
            RT->>OL: POST v1/chat/completions
            A->>W: vote_sanction(agent, sanction, oui ou non)
        end
    end
    S->>S: at(assembly_close_day, CONSEIL, close)
    Note over S: J29 temps simulé, close() est un effet
    S->>W: close_assembly(asm) pour chaque assemblée
    W->>W: close_sanctions(asm) : les présents qui n'ont pas voté le font selon leur caractère
    W->>W: closing_vote(asm) : soutiens des agents à règles
    W->>EF: emit(norm_adopted) pour la règle retenue
    W->>MS: remember(agent, Règle adoptée chez l'ancien, ...)
    W->>EF: emit(assembly_end)
    S->>EF: emit(phase assembly close)
```

Dans le code :
- Bulletins : `filets/scheduler.py:204-205` (`parallel(ballots)`), `filets/agents.py:289` (`ballot`), `:302` (`_sanction_ballot`), `:404` (`_quota_ballot`), `filets/world.py:2285` (`_support`, événement `support` `:2286`), `:2222` (`vote_sanction`).
- Clôture : `filets/scheduler.py:207-211`, `filets/world.py:2517` (`close_assembly`, `norm_adopted` `:2539`, `remember` `:2551`, `assembly_end` `:2559`), `:2232` (`close_sanctions`), `:2496` (`closing_vote`), `:2492` (`ballots`).

## (d) Une injection du joueur : la rumeur

Le joueur tape une phrase dans le champ « rumeur » de Godot et clique sur « Diffuser » (ou valide avec Entrée). La commande `announcement` suit le même chemin que `start_game` jusqu'au bus, mais c'est maintenant le `World` en cours de partie qui l'écoute (une tâche qui interroge le bus toutes les 0,05 s, même quand le moteur attend un modèle). Le monde enregistre un événement `injection`, garde la rumeur dans sa liste et la glisse dans la mémoire de chaque agent. À la décision suivante, `observe` la remonte en tête des éléments récupérés.

```mermaid
sequenceDiagram
    autonumber
    actor J as Joueur
    participant M as Main main.gd
    participant WS as WsClient
    participant API as ApiServer Hub
    participant BR as Bridge
    participant K as Kafka
    participant KB as KafkaBus
    participant W as World
    participant EF as EventFactory
    participant MS as MemoryStore de chaque agent

    J->>M: saisit la rumeur puis Diffuser ou Entrée (_rumor)
    M->>M: strip_edges, ignore si vide
    M->>WS: _send puis send(announcement, text)
    alt pas de connexion
        WS-->>M: false
        M->>M: _feed Injection impossible : pas de connexion au pont
    else connecté
        WS->>API: texte JSON
        API->>API: handle_text puis dispatch
        API->>BR: on_command(cmd)
        BR->>K: aio.send(commands)
        KB->>K: poll puis _commands.put
    end
    loop toutes les 0,05 s (_command_pump)
        W->>KB: poll_commands()
    end
    KB-->>W: announcement
    W->>W: handle_command(cmd, source ui)
    W->>W: validate_command(cmd)
    alt commande invalide
        W->>KB: publish deadletter
        KB->>K: produce filets.deadletter
    else valide
        W->>EF: emit(injection, announcement, source ui)
        Note over W,EF: temps simulé : horodaté à clock.now(), l'instant du monde
        EF->>KB: publish events
        W->>W: texte tronqué à 300 caractères
        W->>W: rumors.append(texte, saison, t, event_id)
        loop chaque agent
            W->>MS: remember(On raconte dans la vallée, rumeur, importance 0.8)
            MS->>MS: add(t, texte, kind, importance)
            W->>EF: emit(memory_write)
        end
    end
    K-->>BR: events
    BR->>API: push(events)
    API-->>WS: topic events
    WS-->>M: signal message
    M->>M: _on_event, cas injection, ligne dans le fil
    Note over W: décisions suivantes : observe puis active_rumors(h), la rumeur est en tête des éléments récupérés
```

Dans le code :
- Godot : `godot/scripts/main.gd:537-545` (champ, bouton « Diffuser »), `:702-705` (`_rumor`), `:723-726` (`_send`), `:1052` (cas `injection` de `_on_event`).
- Transport : `filets/api.py:293`, `:282` ; `filets/services/bridge.py:28` ; `filets/bus.py:134`, `:158`.
- Monde : `filets/world.py:1732-1747` (`_command_pump`), `:1728` (`poll_commands`), `:1663` (`handle_command`), `:1664-1667` (`validate_command` puis `deadletter`), `filets/schemas.py:246` (`validate_command`), `filets/world.py:1675` (`injection`), `:1688-1696` (branche `announcement`), `:399-407` (`remember`, événement `memory_write`), `filets/memory.py:49` (`add`).
- Récupération : `filets/world.py:684` (`active_rumors`), `:1328-1330` (rumeurs en tête de `retrieved`).
- La sécheresse (`drought`) suit le même chemin : `filets/world.py:1676-1683` (`lake.shock` sur chaque lac, souvenir « Sécheresse »).

## (e) Le rejeu d'une partie

Rejouer ne relance aucun modèle : `python -m filets replay RUN_ID` relit le journal `events.jsonl` enregistré par le `Recorder` et le republie sur le bus, événement après événement, à la cadence d'origine (`processed_at`) divisée par la vitesse, en ajoutant `replay: true` et `replayed_at`. Godot s'y connecte comme à une partie en direct, avec la même interface. Les injections faites pendant un rejeu sont ignorées.

### e1. Rejeu avec le bus local

Le rejeu ouvre lui-même l'API et calcule les indicateurs (`IndicatorPublisher` abonné au bus local), puis compare leur journal à celui de la partie d'origine.

```mermaid
sequenceDiagram
    autonumber
    actor J as Enseignant
    participant CLI as cli.py replay
    participant D as runs events.jsonl
    participant BUS as LocalBus
    participant IP as IndicatorPublisher
    participant API as ApiServer Hub
    participant WS as WsClient
    participant M as Main main.gd

    J->>CLI: python -m filets replay RUN_ID --speed 4 --ws
    CLI->>D: load_events(run_id)
    D-->>CLI: liste des événements
    CLI->>BUS: make_bus (sans consommateur de commandes)
    CLI->>API: make_api(...) puis start()
    Note over API: commande reçue : (rejeu : injection ignorée)
    CLI->>BUS: subscribe events vers API.push et indicators vers API.push
    CLI->>IP: IndicatorPublisher puis subscribe events
    J->>M: lance Godot
    M->>WS: connexion au WebSocket
    WS->>API: connexion
    API-->>WS: hello avec buffered puis le tampon éventuel
    loop pour chaque événement du journal
        Note over CLI: attend processed_at / vitesse (temps réel), au plus 2 s d'un coup
        CLI->>BUS: publish(events, ev avec replay et replayed_at)
        BUS-->>API: push(events)
        API-->>WS: topic events
        WS-->>M: signal message
        M->>M: _on_event puis world.on_event
        BUS-->>IP: on_event(ev)
        IP->>IP: run_start ouvre indicators_replay.jsonl
        IP->>BUS: publish(indicators)
        BUS-->>API: push(indicators)
        API-->>WS: topic indicators
        WS-->>M: signal message
        M->>M: _on_indicator
    end
    opt le joueur injecte pendant le rejeu
        M->>WS: send(commande)
        WS->>API: texte JSON
        API->>CLI: on_command : (rejeu : injection ignorée)
    end
    CLI->>BUS: flush
    CLI->>IP: close()
    CLI->>CLI: compare_indicators(run_id)
    Note over CLI: IDENTIQUES ou DIFFÉRENTS à indicators.jsonl de la partie d'origine
    opt option linger
        CLI->>CLI: attend Ctrl+C, API maintenue ouverte
    end
```

Dans le code :
- Commande : `filets/cli.py:5` (usage), `:402-403` (sous-commande), `:468-471` (appel).
- Rejeu : `filets/cli.py:156-159` (`load_events`), `:162` (`replay`), `:165` (`make_bus(..., consume_commands=False)`), `:168-173` (API, injection ignorée `:169`), `:176-178` (`IndicatorPublisher`), `:179-187` (boucle, attente `processed_at / speed` `:181`, `publish` avec `replay` et `replayed_at` `:186`), `:188` (`flush`), `:189-191` (`close`, `compare_indicators`), `:205` (comparaison).
- Indicateurs : `filets/pipeline.py:28-47` (`on_event`, journal `indicators_replay.jsonl` `:30`), `:35` (`replayed_at`).
- Godot : `filets/api.py:268-277` (`attach`, message `hello`), `godot/scripts/main.gd:729-755`, `:757`, `:1122`.

### e2. Rejeu avec Kafka

Le rejeu produit dans le topic `filets.events` ; les services habituels font le reste : `indicators` recalcule (dans `indicators_replay.jsonl` grâce à l'indicateur `replay`), `store` archive (colonne `replay` à 1 ; les indicateurs d'origine sont gardés à part, `replay = 0`), le pont relaie à Godot. Le rejeu ne calcule pas lui-même les indicateurs (c'est le service) et ne peut donc pas les comparer à ceux de l'original.

```mermaid
sequenceDiagram
    autonumber
    actor J as Enseignant
    participant CLI as cli.py replay
    participant D as runs events.jsonl
    participant KB as KafkaBus producteur
    participant K as Kafka
    participant IND as Service indicators
    participant ST as Service store
    participant DB as PostgreSQL ou SQLite
    participant BR as Bridge
    participant API as ApiServer Hub
    participant M as Godot Main

    J->>CLI: python -m filets replay RUN_ID --bus kafka
    CLI->>D: load_events(run_id)
    CLI->>KB: make_bus(group filets-replay, sans commandes)
    loop pour chaque événement du journal
        Note over CLI: attend processed_at / vitesse
        CLI->>KB: publish(events, ev avec replay et replayed_at)
        KB->>K: produce filets.events (clé = acteur)
        K-->>IND: events
        IND->>IND: on_event : run_start ouvre indicators_replay.jsonl
        IND->>K: produce filets.indicators (replay = true)
        K-->>ST: events et indicators
        ST->>DB: add_event puis add_indicator (replay = 1)
        ST->>DB: commit puis consumer.commit
        K-->>BR: events et indicators
        BR->>API: push(topic, data)
        API->>API: run_start vide le tampon puis broadcast
        API-->>M: topic events puis indicators
        M->>M: _on_event puis _on_indicator
    end
    CLI->>KB: flush()
    CLI->>KB: close()
```

Dans le code :
- Producteur : `filets/cli.py:165` (`make_bus` renvoie un `KafkaBus` si `bus.kind` vaut `kafka`), `filets/bus.py:177` (`make_bus`), `:144` (`KafkaBus.publish`), `:166` (`flush`), `:169` (`close`).
- Services : `filets/services/indicators.py:20-43`, `filets/services/store.py:43-77`, `filets/pipeline.py:30` (journal du rejeu), `filets/pgstore.py:29`, `:89`, `:108` et `filets/store.py:28`, `:83`, `:106` (colonne `replay` des indicateurs).
- Pont : `filets/services/bridge.py:36-43`, `filets/api.py:236-266` (`_pump`).

## (f) La fin de saison

À J29,9 simulé (jour du repeuplement) l'ordonnanceur appelle `regrowth`. Le monde clôt la saison : l'ancien pèse les indices, chaque lac se repeuple, les promesses sont jugées, la richesse est ajustée, les souvenirs et le « lore » (ce que la vallée sait) sont écrits, et l'événement `season_end` est publié. Le récit du narrateur est lancé en tâche de fond et se rédige pendant la préparation de la saison suivante. Le service d'indicateurs transforme `season_end` en indicateurs de fin de saison, que Godot dessine dans la courbe.

```mermaid
sequenceDiagram
    autonumber
    participant S as SeasonScheduler
    participant W as World
    participant L as Lake
    participant MS as MemoryStore
    participant R as Retriever
    participant EF as EventFactory
    participant K as Bus Kafka
    participant IND as Service indicators
    participant API as Bridge et API
    participant M as Main main.gd

    Note over S: J29,9 temps simulé, regrowth est un effet de classe MONDE
    S->>EF: emit(phase regrowth open)
    S->>W: end_season(season)
    W->>W: investigate(season) puis weigh_evidence(season)
    loop chaque lac
        W->>L: regrow(growth du climat)
        L-->>W: delta
        W->>EF: emit(lake_update, cause regrowth)
    end
    W->>W: lake_cells()
    loop chaque pêcheur
        opt une promesse existe
            W->>EF: emit(promise_outcome)
            opt trahison connue de la vallée
                W->>R: add_lore(agent, texte, event_id, all, 0.9)
                R->>R: add_lore(passage, cap)
                W->>EF: emit(lore_added)
            end
            opt promesse non tenue
                W->>MS: remember(J'avais promis ..., promesse, 0.9)
                W->>EF: emit(memory_write)
            end
        end
        W->>W: wealth moins entretien et remboursement
        W->>MS: remember(Bilan de la saison ..., bilan, 0.5)
        W->>EF: emit(memory_write)
    end
    W->>EF: emit(season_end)
    EF->>K: publish(events, season_end)
    S->>S: recit = ensure_future(narrate) dans SimClock.local(t)
    S-->>S: la boucle de la saison se termine, play() rend la tâche du récit
    K-->>IND: season_end
    IND->>K: produce filets.indicators (trigger season_end)
    K-->>API: events et indicators
    API-->>M: topic events (season_end) puis topic indicators
    M->>M: _on_indicator puis chart.set_season(saison, valeurs)
    Note over S,W: la saison suivante : prepare_season(season + 1) pendant que le récit s'écrit
    S->>W: prepare_season : debrief(season) puis elect(season + 1) et plan_patrol(season + 1) en parallèle
```

Le récit du narrateur, ensuite :

```mermaid
sequenceDiagram
    autonumber
    participant S as SeasonScheduler
    participant W as World
    participant RT as LLMRouter
    participant GATE as ModelGate
    participant OL as Ollama
    participant EF as EventFactory
    participant K as Bus Kafka
    participant M as Main main.gd

    S->>W: narrate(season) dans une tâche, SimClock.local(fin de saison)
    W->>W: narrator_facts(season, limite 14)
    alt grand modèle disponible et fournisseur non scripté
        W->>RT: complete(narrateur, grand, narration, messages, hint S2, schéma, seed)
        RT->>GATE: acquire(model)
        RT->>OL: POST v1/chat/completions
        OL-->>RT: texte JSON (recit)
        RT->>GATE: release
        RT->>EF: emit(llm_call)
        RT-->>W: LLMResult
        opt réponse manquante ou illisible
            W->>EF: emit(incident, no_response ou unparseable)
        end
    end
    opt pas de texte
        W->>W: le récit reprend les faits
    end
    W->>EF: emit(narration, source narrateur ou faits)
    EF->>K: publish(events, narration)
    K-->>M: via bridge et API
    M->>M: _on_event, cas narration, onglet Récit du narrateur
```

Dans le code :
- Ordonnancement : `filets/scheduler.py:222-231` (`regrowth`, tâche `narrate` `:227-230`), `filets/world.py:2968-2974` (`prepare_season`), `:1809` (`debrief`), `:1771` (`elect`), `:1819` (`plan_patrol`).
- Fin de saison : `filets/world.py:2563` (`end_season`), `:772` (`investigate`), `:836` (`weigh_evidence`), `filets/lake.py:87` (`regrow`), `filets/world.py:544` (`lake_update`), `:2573` (`promise_outcome`), `:2577-2580` (`add_lore`), `:409-418` (`add_lore`, événement `lore_added`), `:2582-2585` (`remember`), `:2587` (bilan), `:2591` (`season_end`).
- RAG : `filets/rag.py:167` (`Retriever.add_lore`), `:225` (`VectorRetriever.add_lore`, écrit en base par `_flush_lore` `:231`).
- Narrateur : `filets/world.py:2747` (`narrator_facts`), `:2847-2872` (`narrate`, appel `:2859`, repli sur les faits `:2865`, événement `narration` `:2870`).
- Indicateurs : `filets/services/indicators.py:30-38`, `filets/pipeline.py:28`.
- Godot : `godot/scripts/main.gd:1122` (`_on_indicator`), `:1158` (`chart.set_season`), `:757` (`_on_event`).
- Partie suivante si l'ancien rapporte et élit : `filets/world.py:2968-2974`.

## (g) Le tirage d'une vallée depuis le menu

Dans le menu, le joueur règle le nombre de villages, de pêcheurs, de lacs, la flotte et la graine (ou choisit « Aléatoire »), ou clique sur « Générer la vallée » / « Autre vallée ». Un délai court (`_gen_timer`) regroupe les réglages rapides. Le menu envoie `generate_world` avec un identifiant ; le moteur, en salon (`idle` ou `ended`), génère la vallée (la même pour la même graine), remplace sa composition de base dans le catalogue et publie son état avec le catalogue. Le pont relaie le catalogue à part ; Godot le reçoit et le menu remplace sa liste de pêcheurs et ses lacs, sans toucher aux autres réglages.

```mermaid
sequenceDiagram
    autonumber
    actor J as Joueur
    participant SM as StartMenu
    participant M as Main main.gd
    participant WS as WsClient
    participant API as ApiServer Hub
    participant BR as Bridge
    participant K as Kafka
    participant ENG as Engine
    participant CAT as catalog.generate_world

    J->>SM: change un nombre ou clique Générer la vallée
    SM->>SM: _on_gen_spin puis _gen_timer.start
    SM->>SM: _on_generate : params villages, fishers, seed, fleet, lakes, patrols, mode
    alt une demande est déjà en route depuis moins de 5 s
        SM->>SM: _regenerate si les nombres ont changé
    else
        SM->>SM: _pending_generation = id, btn_generate.disabled
        SM-->>M: signal generate_requested(params + id)
        M->>WS: send(generate_world, config)
        WS->>API: texte JSON
        API->>BR: on_command(cmd)
        BR->>K: produce filets.commands
        K-->>ENG: via KafkaBus puis poll_commands
        alt état idle ou ended
            ENG->>ENG: generate(req) : valide flotte, mode, bornes de LIMITS, villages au plus pêcheurs, lacs au plus villages
            alt paramètres refusés
                ENG->>K: publish status avec error (puis error remis à None)
                K-->>M: status avec error
                M->>SM: show_error(texte)
            else
                ENG->>CAT: generate_world(base_cfg, villages, fishers, seed, fleet, lakes, patrols, mode)
                alt mode random
                    CAT->>CAT: lakes.random_valley(seed)
                end
                CAT->>CAT: base_population, villages_of_specs, resolve_lakes
                CAT-->>ENG: hamlets, base_population, lakes, patrols
                ENG->>ENG: catalog = hamlets, base_population, lakes, generation(id)
                ENG->>K: publish status avec catalog
                K-->>BR: status
                BR->>API: push(status)
                API->>API: sépare le catalogue : topic catalog puis status allégé
                API-->>WS: topic catalog
                WS-->>M: signal message(catalog)
                M->>SM: set_catalog(cat)
                SM->>SM: seule la vallée a changé : réinitialise pêcheurs et lacs, _pending_generation = vide
            end
        end
    end
```

Dans le code :
- Menu : `godot/scripts/start_menu.gd:1313-1323` (`_on_gen_spin`), `:1336-1354` (`_on_generate`, `_pending_generation`, `generate_requested.emit`), `:569` (`_gen_timer`), `:650` (`set_catalog`), `:641` (`_same_but_valley`), `:1171` (`_load_lakes`).
- Godot : `godot/scripts/main.gd:603-605` (`_on_menu_generate`), `:729-737` (`catalog` dans `_on_message`).
- Moteur : `filets/engine.py:360-374` (dispatch de `generate_world` `:370`), `:376-414` (`generate`), `filets/catalog.py:119-142` (`generate_world`), `filets/lakes.py:254` (`random_valley`), `filets/catalog.py:145` (`build_catalog`).
- API : `filets/api.py:213-224` (`push` sépare `catalog`), `:236-247` (`_pump`, `catalog` relayé si changé).

## (h) L'arrêt d'une partie

« Arrêter la partie » est irréversible : une boîte de confirmation « Oui, arrêter / Non » s'ouvre. Si le joueur confirme, la commande `stop` arrive au monde, qui lève un drapeau d'arrêt dans le contrôle de partie. Tout point de passage (`checkpoint`) lève alors `StopRun`, et `guard` annule le travail en cours, y compris les appels de modèle déjà partis (qui laissent une trace `llm_call` de statut « cancelled »). La partie se termine proprement : `run_end`, archivage, état `ended`.

```mermaid
sequenceDiagram
    autonumber
    actor J as Joueur
    participant M as Main main.gd
    participant WS as WsClient
    participant API as ApiServer Hub
    participant K as Kafka
    participant W as World run et _command_pump
    participant CTL as GameControl
    participant S as SeasonScheduler
    participant RT as LLMRouter
    participant OL as Ollama
    participant EF as EventFactory
    participant S3 as Stockage objet S3
    participant ENG as Engine

    J->>M: clique Arrêter la partie (btn_stop ou btn_stop_top)
    M->>M: _on_stop_pressed : stop_dlg.popup_centered()
    alt le joueur répond Non
        M->>M: la boîte se ferme, rien n'est envoyé
    else Oui, arrêter
        M->>WS: _send(stop) puis send
        WS->>API: texte JSON
        API->>K: via Bridge : produce filets.commands
        loop toutes les 0,05 s
            W->>K: poll_commands() via KafkaBus
        end
        K-->>W: stop
        W->>W: handle_command(stop) puis _control_command
        W->>W: stop_requested = true, stopped_reason = stop
        W->>EF: emit(injection, stop)
        W->>CTL: request_stop()
        CTL->>CTL: _stop.set puis clock.resume et _run.set
        W->>W: publish_status()
        S->>CTL: checkpoint() ou guard(...)
        CTL-->>S: StopRun
        CTL->>RT: guard annule la tâche en cours
        RT->>OL: requête abandonnée
        RT->>EF: emit(llm_call, status cancelled) si la requête était partie
        W->>W: run : except StopRun, stop_requested
        W->>W: finally : annule les récits et le _command_pump
        W->>W: finish()
        W->>EF: emit(run_end, reason stop)
        W->>RT: aclose()
        W->>K: bus.flush puis publish_status(ended)
        W->>W: écrit summary.json, recorder.close
        W->>S3: archive_run (events.jsonl, indicators, config, summary)
        W->>W: memory_bank.flush, fermeture du stockage
        W-->>ENG: run() rend la main
        ENG->>ENG: end_reason = stop, final_status
        ENG->>K: publish_status(ended)
        K-->>M: via bridge : status ended
        M->>M: _on_status puis _show_end : Partie arrêtée
    end
```

Dans le code :
- Godot : `godot/scripts/main.gd:358` (`btn_stop`), `:560` (`btn_stop_top`), `:594-596` (`_on_stop_pressed`), `:562-568` (`stop_dlg` : titre, texte, « Oui, arrêter », « Non », `confirmed` envoie `stop`), `:645-662` (`_show_end`, `_refresh_end_text`, « Partie arrêtée »).
- Monde : `filets/world.py:1663` (`handle_command`), `:1698-1704` (`stop`), `filets/control.py:24` (`StopRun`), `:75` (`request_stop`), `:83` (`checkpoint`), `:107` (`guard`).
- Fin de partie : `filets/world.py:2976-3010` (`run`, `StopRun` `:2997`, `finally` `:3002-3010`), `:2900` (`finish`, `run_end` `:2901`, `summary.json`), `:2926` (`close_storage`, archivage `:2931`), `filets/llm.py:384-396` (appel annulé, trace `cancelled`).
- Moteur : `filets/engine.py:458-479` (`end_reason`, `final_status`, `publish_status("ended")`).
