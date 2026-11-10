# Diagrammes de communication

Un diagramme de communication (ou de collaboration) montre les mêmes échanges qu'un diagramme de séquence, mais en mettant en avant la structure : les objets sont placés dans le plan, chaque lien entre deux objets est une arête, et l'ordre des messages n'est porté que par leur numéro. Un numéro décimal (« 3.1 ») veut dire « émis pendant le traitement du message 3 » ; une lettre (« 5a », « 5b ») marque des messages envoyés en même temps ; entre crochets, la condition d'un message. La séquence montre mieux l'ordre et les blocs (`par`, `loop`, `alt`), la communication montre mieux qui parle à qui. Mermaid n'a pas ce type de diagramme : on le dessine avec un `flowchart` dont les nœuds sont les objets (« nom : Classe ») et dont les étiquettes d'arêtes sont les messages numérotés. Un nœud qui s'écrit à lui-même a une boucle sur lui-même.

Cette page reprend **tous** les scénarios de `sequences.md`, avec les mêmes objets, les mêmes messages et les mêmes découpages : (a1 à a3) démarrer une partie, (b1 à b3) la décision de prise, (c1, c2) la veillée, (d) la rumeur, (e1, e2) le rejeu avec le bus local puis avec Kafka, (f1, f2) la fin de saison et le récit, (g) le tirage d'une vallée, (h) l'arrêt. Les listes « Dans le code » de `sequences.md` donnent les `fichier:ligne` de chaque message ; chaque section ci-dessous rappelle les lignes de ses messages.

## (a1) Du clic jusqu'à la commande reçue par le moteur

```mermaid
flowchart LR
    J(["joueur"])
    SM["menu : StartMenu"]
    M["main : Main"]
    WS["ws : WsClient"]
    API["api : ApiServer Hub"]
    BR["bridge : amain"]
    K["Kafka : filets.commands"]
    KB["bus : KafkaBus _consume"]
    ENG["engine : Engine"]

    J -->|"1: clic Démarrer la partie (_on_start)"| SM
    SM -->|"1.1: build_config(), busy = true"| SM
    SM -->|"2: signal start_requested(cfg)"| M
    M -->|"3: send(start_game, config)"| WS
    WS -->|"4: send_text(JSON) [WebSocket ouvert]"| API
    WS -->|"3.1: false [fermé] puis show_error"| M
    API -->|"5: handle_text puis dispatch(cmd)"| API
    API -->|"6: on_command(cmd)"| BR
    BR -->|"7: aio.send(commands, cmd)"| K
    KB -->|"8: Consumer.poll"| K
    KB -->|"8.1: _commands.put(json.loads)"| KB
    ENG -->|"9: poll_commands() toutes les 0,1 s"| KB
    ENG -->|"9.1: _play(config)"| ENG
    ENG -->|"9.2: poll_commands() vide la file"| KB
```

Dans le code : `godot/scripts/start_menu.gd:1402-1413`, `:1377` ; `godot/scripts/main.gd:552`, `:598-600`, `:723-726` ; `godot/scripts/ws_client.gd:58-62` ; `filets/api.py:321-335`, `:293`, `:282` ; `filets/services/bridge.py:28-30` ; `filets/aio.py:97` ; `filets/bus.py:134`, `:158` ; `filets/engine.py:348-374`, `:437`. Variante bus local : l'API reçoit `bus.send_command` (`filets/cli.py:140`), pas de pont ni de Kafka.

## (a2) Le moteur prépare, crée le monde et ouvre la partie

```mermaid
flowchart LR
    ENG["engine : Engine"]
    KB["bus : KafkaBus"]
    K["Kafka"]
    OL["ollama : Ollama"]
    PG["pg : PostgreSQL pgvector"]
    S3["objets : S3"]
    W["world : World"]
    EF["events : EventFactory"]
    REC["rec : Recorder"]

    ENG -->|"1: publish(status, starting)"| KB
    KB -->|"1.1: produce filets.status"| K
    ENG -->|"2: build_game_config(base_cfg, request)"| ENG
    ENG -->|"3a: beat toutes les 1,5 s : publish_status"| KB
    ENG -->|"3b.1: GET api/tags"| OL
    ENG -->|"3b.2: POST v1/systemone ou api/generate (chargement)"| OL
    ENG -->|"3b.3: asyncpg.connect"| PG
    ENG -->|"3b.4: POST api/embed (plongement)"| OL
    ENG -->|"3b.5: objects.open puis aclose"| S3
    ENG -->|"4: publish(status, idle) avec error [refus ou service absent]"| KB
    ENG -->|"5: unique_run_id(cfg)"| ENG
    ENG -->|"6: World(cfg, bus, run_id, ...)"| W
    W -->|"6.1: Recorder(run_dir)"| REC
    W -->|"6.2: EventFactory(run_id, clock, bus, recorder)"| EF
    ENG -->|"7: ctl.set_speed ou set_fast"| W
    ENG -->|"8: run()"| W
    W -->|"8.1: objects.open"| S3
    W -->|"8.2: vectors.open, retriever.open"| PG
    W -->|"8.3: start()"| W
    W -->|"9: emit(run_start)"| EF
    EF -->|"9.1: publish(events, ev)"| KB
    KB -->|"9.1.1: produce filets.events"| K
    EF -->|"9.2: write(ev)"| REC
    W -->|"10: emit(memory_write) Une nouvelle année"| EF
    W -->|"11: lake_update(init), publish_status, tâche _command_pump"| W
```

Dans le code : `filets/engine.py:437-479`, `:342`, `:152`, `:416-435`, `:207`, `:229`, `:247-259`, `:263`, `:450-461` ; `filets/cli.py:75` ; `filets/world.py:213`, `:226-233`, `:2976`, `:2918`, `:2873`, `:1732` ; `filets/events.py:71`, `:108`, `:14-28` ; `filets/bus.py:144`.

## (a3) La diffusion de `run_start`

```mermaid
flowchart LR
    K["Kafka"]
    IND["indicators : service"]
    IP["pub : IndicatorPublisher"]
    ST["store : service"]
    DB["db : PostgreSQL ou SQLite"]
    BR["bridge : amain"]
    API["api : ApiServer Hub"]
    WS["ws : WsClient"]
    M["main : Main"]
    SM["menu : StartMenu"]

    K -->|"1a: events depuis run_start (messages)"| IND
    IND -->|"1a.1: on_event(run_start)"| IP
    IP -->|"1a.2: _open : indicators.jsonl, produce filets.indicators"| K
    K -->|"1b: getmany(2000) events et indicators"| ST
    ST -->|"1b.1: add_event, add_indicator"| DB
    ST -->|"1b.2: commit puis consumer.commit"| DB
    K -->|"1c: events, indicators, status"| BR
    BR -->|"1c.1: push(topic, data)"| API
    API -->|"2: call_soon_threadsafe(queue.put_nowait)"| API
    API -->|"3: _pump : catalog à part, run_start vide le tampon, doublons écartés"| API
    API -->|"4: buffer.append puis _broadcast"| API
    API -->|"5: send_text(status)"| WS
    WS -->|"6: signal message(status)"| M
    M -->|"6.1: _on_status"| M
    M -->|"6.2: set_engine(starting)"| SM
    API -->|"7: send_text(events, run_start)"| WS
    WS -->|"8: signal message(events)"| M
    M -->|"8.1: _on_event puis _reset : reset_world, chart.reset, legend.set_villages"| M
    M -->|"9: close() [état running]"| SM
```

Dans le code : `filets/services/indicators.py:20-43` ; `filets/pipeline.py:28`, `:49-56` ; `filets/services/store.py:43-77` ; `filets/services/bridge.py:36-43` ; `filets/api.py:213`, `:236-266`, `:229` ; `godot/scripts/ws_client.gd:28-56` ; `godot/scripts/main.gd:729-755`, `:608-640`, `:757-762`, `:1161`, `:1175-1182`, `:629-631`.

## (b1) Ordonnancement et observation

```mermaid
flowchart LR
    S["sched : SeasonScheduler"]
    A["agent : decide_catch"]
    W["world : World"]
    MS["memory : VectorMemory"]
    R["retriever : VectorRetriever"]
    EM["embedder : Embedder"]
    OL["ollama : Ollama"]
    PG["pg : PostgreSQL pgvector"]

    S -->|"1: at(h, PECHEURS, id, Decision)"| S
    S -->|"2: play, run_batch, parallel(jobs)"| S
    S -->|"2.1: think(noms, True), publish_status"| S
    S -->|"3: make() = decide_catch(w, agent, h)"| A
    A -->|"4: observe(agent, h, catch)"| W
    W -->|"4.1: lake.observe, note_lake, applicable_norm, rule_view, known_catches, carnet, clue_lines, active_rumors, pinned"| W
    W -->|"4.2a: aretrieve(query, h, k, exclude)"| MS
    MS -->|"4.2a.1: bank.flush, embed(query)"| EM
    EM -->|"4.2a.2: POST api/embed (cache LRU)"| OL
    MS -->|"4.2a.3: search_memories"| PG
    W -->|"4.2b: asearch(query, hameau, h, k)"| R
    R -->|"4.2b.1: _flush_lore, embed(query)"| EM
    R -->|"4.2b.2: search_chunks, search_lore"| PG
    MS -->|"4.3: retrieve() BM25 [base ou plongement indisponible]"| MS
    R -->|"4.3: local.search() BM25 [idem]"| R
    W -->|"4.4: retrieved = pinned, mémoire, corpus, rumeurs en tête"| W
    W -->|"5: obs, state, retrieved, used"| A
```

Dans le code : `filets/scheduler.py:147-158`, `:84-115`, `:117-145`, `:38-43`, `:64-67` ; `filets/world.py:1250`, `:1262-1263`, `:1279`, `:1314-1334`, `:684`, `:1200`, `:1020` ; `filets/memory.py:60`, `:119-135`, `:91` ; `filets/rag.py:179`, `:231`, `:257-272` ; `filets/vectors.py:72-95`.

## (b2) Choix système 1 ou 2 et appel du modèle

```mermaid
flowchart LR
    A["agent : decide_catch"]
    RT["router : LLMRouter"]
    CTL["ctl : GameControl"]
    CL["client : OpenAICompat ou SystemOne"]
    GATE["gate : ModelGate"]
    RL["limiter : RateLimiter"]
    OL["ollama : Ollama"]
    EF["events : EventFactory"]

    A -->|"1: lake_choice_rule, catch_rule, declare_rule, rule_choices [agent à règles]"| A
    A -->|"1.1: emit(decision) Règle appliquée"| EF
    A -->|"2: choose_system(obs, catch) [agent à IA, profil adaptatif]"| A
    A -->|"3: complete(agent, tier, hint S1 ou S2 + schéma)"| RT
    RT -->|"3.1: checkpoint (pause, arrêt)"| CTL
    RT -->|"3.2: choisit le client du tier"| CL
    CL -->|"3.3: acquire(model) [max_concurrency]"| GATE
    GATE -->|"3.3.1: place obtenue, un seul échange de modèle par vague"| CL
    CL -->|"3.4: wait() [OpenAICompat, rpm]"| RL
    CL -->|"3.5: POST v1/systemone [SystemOne] ou v1/chat/completions"| OL
    OL -->|"3.6: texte JSON"| CL
    CL -->|"3.7: release()"| GATE
    CL -->|"3.8: LLMResult"| RT
    RT -->|"3.9: checkpoint : la réponse attend la reprise en pause"| CTL
    RT -->|"3.10: usage : calls, tokens, by_tier, by_system"| RT
    RT -->|"3.11: emit(llm_call)"| EF
    RT -->|"3.12: écrit s1_calls.jsonl [système 1]"| RT
    RT -->|"4: LLMResult"| A
    A -->|"5: complete(tier petit) [réflexe en échec]"| RT
    A -->|"6: complete(hint S1) [système 2 illisible, réflexe disponible]"| RT
    A -->|"7: extract_json, detect_drift"| A
    A -->|"8: emit(incident) [statut non ok, illisible, sortie de rôle]"| EF
```

Dans le code : `filets/agents.py:144`, `:154-167`, `:170-186`, `:79-136`, `:108`, `:119`, `:139` ; `filets/routing.py:24`, `:53` ; `filets/llm.py:335-420`, `:154-237`, `:250-322`, `:44-152`, `:406` ; `filets/control.py:83`.

## (b3) Sortie : décision publiée dans l'ordre, puis prise appliquée

```mermaid
flowchart LR
    S["sched : SeasonScheduler"]
    A["agent : decide_catch"]
    W["world : World"]
    EF["events : EventFactory"]
    REC["rec : Recorder"]
    KB["bus : Kafka"]
    G["main : Main Godot"]

    A -->|"1: borne la prise, déclaration au plus égale"| A
    A -->|"1.1: catch_rule [prise invalide, fallback]"| A
    A -->|"2: emit(decision) en tampon (defer)"| EF
    A -->|"3: _note_observation, last_decision"| W
    A -->|"4: Outcome"| S
    S -->|"5: think(noms, False), publish_status"| S
    S -->|"6: flush(buf) dans l'ordre de la file"| EF
    EF -->|"6.1: seq et event_id définitifs, publish(events)"| KB
    EF -->|"6.2: write(ev)"| REC
    S -->|"7: heal_event_ids(renamed)"| W
    S -->|"8: then(res) = depart(agent, outcome, h)"| S
    S -->|"8.1: plan_trip(...)"| W
    W -->|"8.2: Trip"| S
    S -->|"8.3: at(jour + 1, land_outing), at(retour, finish_trip)"| S
    S -->|"9: land_outing(trip, k) [un jour plus tard]"| W
    W -->|"9.1: lake.take puis lake_update(catch)"| W
    W -->|"9.2: emit(lake_update)"| EF
    S -->|"10: finish_trip(trip) [retour]"| W
    W -->|"10.1: vente, richesse, déclaration, indices"| W
    W -->|"10.2: emit(catch)"| EF
    KB -->|"11: events (catch) via bridge et API"| G
    G -->|"11.1: _on_event puis world.on_event"| G
```

Dans le code : `filets/agents.py:187-231`, `:65-70`, `:58` ; `filets/scheduler.py:117-135`, `:160-171` ; `filets/events.py:50-69` ; `filets/world.py:387`, `:1506`, `:1559-1568`, `:544-555`, `:1570`, `:1595` ; `filets/lake.py:50` ; `godot/scripts/main.gd:757`, `:776` ; `godot/scripts/world_view.gd:1167`, `:1223`.

## (c1) La boucle de préparation et de parole

```mermaid
flowchart LR
    S["sched : SeasonScheduler"]
    V1["v1 : Village"]
    V2["v2 : Village"]
    A["agent : speak"]
    W["world : World"]
    RT["router : LLMRouter"]
    OL["ollama : Ollama"]
    EF["events : EventFactory"]

    S -->|"1: open_assemblies(season, close_t)"| W
    W -->|"1.1: investigate(season)"| W
    S -->|"2: emit(phase assembly open)"| EF
    S -->|"3a: Village(sched, asm1, ta)"| V1
    S -->|"3b: Village(sched, asm2, ta)"| V2
    S -->|"4a: prep_jobs() [chaque tour de boucle]"| V1
    S -->|"4b: prep_jobs()"| V2
    S -->|"5: prepare(jobs) première passe"| S
    S -->|"5.1a: speak(w, agent, asm, tour, h)"| A
    A -->|"5.1a.1: observe(agent, h, speak, asm, tour)"| W
    A -->|"5.1a.2: complete via _ask_llm (système 2)"| RT
    RT -->|"5.1a.3: POST v1/chat/completions"| OL
    S -->|"5.1b: speak(w, autre agent, ...) en même temps"| A
    S -->|"5.2: prepared de chaque agent = réponse, h, tour, connus"| V1
    S -->|"5.3: prepared de chaque agent"| V2
    S -->|"6a: pick() : adressé, sinon clé de la graine"| V1
    S -->|"6b: pick()"| V2
    S -->|"7a: redo(agent) puis stale()"| V1
    S -->|"7b: redo(agent) puis stale()"| V2
    S -->|"8: prepare(redo) seconde passe [réplique périmée]"| S
    S -->|"8.1: speak(w, agent, asm, tour, v.t) puis complete puis POST"| A
    S -->|"9a: speak(agent)"| V1
    V1 -->|"9a.1: post_utterance(agent, asm, outcome, tour, h)"| W
    W -->|"9a.2: emit(utterance) to = destinataire"| EF
    S -->|"9b: speak(agent)"| V2
    V2 -->|"9b.1: post_utterance(...)"| W
```

Dans le code : `filets/scheduler.py:173-211` (boucle `:187-202`), `:213-220`, `:233-302` (Village : `prep_jobs` `:245`, `pick` `:258`, `stale` `:268`, `redo` `:280`, `speak` `:289`) ; `filets/agents.py:232`, `:250` ; `filets/world.py:2039`, `:2042`, `:2162`, `:2066`, `:2073`. La boucle recommence (messages 4 à 9) jusqu'à ce qu'aucun village n'ait plus de réplique à dire.

## (c2) Les bulletins, les propositions et la clôture

```mermaid
flowchart LR
    S["sched : SeasonScheduler"]
    A["agent : ballot"]
    W["world : World"]
    RT["router : LLMRouter"]
    OL["ollama : Ollama"]
    EF["events : EventFactory"]
    MS["memory : MemoryStore"]

    S -->|"1: parallel(bulletins) : un ballot par participant à IA"| A
    A -->|"1.1: complete via _quota_ballot [aucune proposition soutenue]"| RT
    RT -->|"1.1.1: POST v1/chat/completions"| OL
    A -->|"1.2: _support(agent, asm, proposition, u)"| W
    W -->|"1.2.1: emit(support)"| EF
    A -->|"1.3: complete via _sanction_ballot [sanctions en attente]"| RT
    A -->|"1.4: vote_sanction(agent, sanction, oui ou non)"| W
    S -->|"2: at(assembly_close_day, close)"| S
    S -->|"3: close_assembly(asm) à J29"| W
    W -->|"3.1: close_sanctions(asm)"| W
    W -->|"3.2: closing_vote(asm)"| W
    W -->|"3.3: emit(norm_adopted)"| EF
    W -->|"3.4: remember(Règle adoptée chez l'ancien)"| MS
    W -->|"3.5: emit(assembly_end)"| EF
    S -->|"4: emit(phase assembly close)"| EF
```

Dans le code : `filets/scheduler.py:204-211` ; `filets/agents.py:289`, `:302`, `:404` ; `filets/world.py:2285-2286`, `:2222`, `:2517`, `:2232`, `:2496`, `:2539`, `:2551`, `:2559`.

## (d) Une injection du joueur : la rumeur

```mermaid
flowchart LR
    J(["joueur"])
    M["main : Main"]
    WS["ws : WsClient"]
    API["api : ApiServer Hub"]
    BR["bridge : amain"]
    K["Kafka"]
    KB["bus : KafkaBus"]
    W["world : World"]
    EF["events : EventFactory"]
    MS["memory : MemoryStore de chaque agent"]

    J -->|"1: Diffuser ou Entrée (_rumor)"| M
    M -->|"1.1: strip_edges, ignore si vide"| M
    M -->|"2: send(announcement, text)"| WS
    WS -->|"2.1: false [pas de connexion] puis _feed Injection impossible"| M
    WS -->|"3: send_text(JSON)"| API
    API -->|"3.1: handle_text, dispatch"| API
    API -->|"4: on_command(cmd)"| BR
    BR -->|"5: aio.send(commands)"| K
    KB -->|"6: poll puis _commands.put"| K
    W -->|"7: poll_commands() toutes les 0,05 s"| KB
    W -->|"7.1: handle_command(cmd, ui), validate_command"| W
    W -->|"7.2: publish(deadletter) [invalide]"| KB
    W -->|"7.3: emit(injection, announcement)"| EF
    EF -->|"7.3.1: publish(events)"| KB
    W -->|"7.4: texte tronqué à 300, rumors.append"| W
    W -->|"7.5: remember(On raconte dans la vallée, rumeur, 0.8) pour chaque agent"| MS
    W -->|"7.5.1: emit(memory_write)"| EF
    K -->|"8: events"| BR
    BR -->|"8.1: push(events)"| API
    API -->|"9: send_text(events)"| WS
    WS -->|"10: signal message"| M
    M -->|"10.1: _on_event, cas injection"| M
```

Dans le code : `godot/scripts/main.gd:537-545`, `:702-705`, `:723-726`, `:1052` ; `filets/api.py:293`, `:282` ; `filets/services/bridge.py:28` ; `filets/world.py:1732-1747`, `:1663-1667`, `:1675`, `:1688-1696`, `:399-407` ; `filets/schemas.py:246` ; `filets/memory.py:49`. Plus tard : `filets/world.py:684`, `:1328-1330` (la rumeur en tête de `retrieved`).

## (e1) Rejeu avec le bus local

```mermaid
flowchart LR
    J(["enseignant"])
    CLI["cli : replay"]
    D["journal : runs events.jsonl"]
    BUS["bus : LocalBus"]
    IP["pub : IndicatorPublisher"]
    API["api : ApiServer Hub"]
    WS["ws : WsClient"]
    M["main : Main"]

    J -->|"1: python -m filets replay RUN_ID --speed 4 --ws"| CLI
    CLI -->|"2: load_events(run_id)"| D
    CLI -->|"3: make_bus sans commandes"| BUS
    CLI -->|"4: make_api puis start()"| API
    CLI -->|"5: subscribe events et indicators vers API.push"| BUS
    CLI -->|"6: IndicatorPublisher, subscribe events"| IP
    J -->|"7: lance Godot"| M
    M -->|"7.1: connexion"| WS
    WS -->|"7.2: connexion WebSocket"| API
    API -->|"7.3: hello avec buffered, puis tampon"| WS
    CLI -->|"8: attend processed_at / vitesse, publish(events, replay=true) [pour chaque événement]"| BUS
    BUS -->|"8.1a: push(events)"| API
    API -->|"8.2a: send_text(events)"| WS
    WS -->|"8.3a: signal message"| M
    M -->|"8.4a: _on_event puis world.on_event"| M
    BUS -->|"8.1b: on_event(ev)"| IP
    IP -->|"8.2b: run_start ouvre indicators_replay.jsonl, publish(indicators)"| BUS
    BUS -->|"8.3b: push(indicators) puis Godot : _on_indicator"| API
    M -->|"9: send(commande) [injection]"| WS
    API -->|"9.1: (rejeu : injection ignorée)"| CLI
    CLI -->|"10: flush, pub.close()"| BUS
    CLI -->|"11: compare_indicators(run_id)"| CLI
```

Dans le code : `filets/cli.py:5`, `:156-205`, `:402-403`, `:468-471` ; `filets/pipeline.py:28-56` ; `filets/api.py:268-277` ; `godot/scripts/main.gd:729-755`, `:757`, `:1122`.

## (e2) Rejeu avec Kafka

```mermaid
flowchart LR
    J(["enseignant"])
    CLI["cli : replay"]
    D["journal : events.jsonl"]
    KB["bus : KafkaBus producteur"]
    K["Kafka"]
    IND["indicators : service"]
    ST["store : service"]
    DB["db : PostgreSQL ou SQLite"]
    BR["bridge : service"]
    API["api : ApiServer Hub"]
    M["main : Godot"]

    J -->|"1: python -m filets replay RUN_ID --bus kafka"| CLI
    CLI -->|"2: load_events(run_id)"| D
    CLI -->|"3: make_bus(group filets-replay)"| KB
    CLI -->|"4: publish(events, replay=true) [pour chaque événement, à la cadence]"| KB
    KB -->|"4.1: produce filets.events"| K
    K -->|"5a: events"| IND
    IND -->|"5a.1: on_event, indicators_replay.jsonl, produce filets.indicators"| K
    K -->|"5b: events et indicators"| ST
    ST -->|"5b.1: add_event, add_indicator (replay=1), commit, consumer.commit"| DB
    K -->|"5c: events et indicators"| BR
    BR -->|"5c.1: push(topic, data)"| API
    API -->|"5c.2: run_start vide le tampon, broadcast"| M
    M -->|"5c.3: _on_event puis _on_indicator"| M
    CLI -->|"6: flush(), close()"| KB
```

Dans le code : `filets/cli.py:165`, `:162-204` ; `filets/bus.py:177`, `:144`, `:166`, `:169` ; `filets/services/indicators.py:20-43` ; `filets/services/store.py:43-77` ; `filets/services/bridge.py:36-43` ; `filets/api.py:236-266` ; `filets/pipeline.py:30`.

## (f1) La fin de saison

```mermaid
flowchart LR
    S["sched : SeasonScheduler"]
    W["world : World"]
    L["lac : Lake"]
    MS["memory : MemoryStore"]
    R["retriever : Retriever"]
    EF["events : EventFactory"]
    K["bus : Kafka"]
    IND["indicators : service"]
    API["bridge et api"]
    M["main : Main"]

    S -->|"1: emit(phase regrowth open)"| EF
    S -->|"2: end_season(season)"| W
    W -->|"2.1: investigate(season), weigh_evidence(season)"| W
    W -->|"2.2: regrow(growth du climat) [chaque lac]"| L
    W -->|"2.3: emit(lake_update, cause regrowth)"| EF
    W -->|"2.4: lake_cells()"| W
    W -->|"2.5: emit(promise_outcome) [une promesse existe]"| EF
    W -->|"2.6: add_lore(agent, texte, event_id, all, 0.9) [trahison connue]"| R
    W -->|"2.6.1: emit(lore_added)"| EF
    W -->|"2.7: remember(J'avais promis ...) [promesse non tenue]"| MS
    W -->|"2.8: wealth moins entretien et remboursement"| W
    W -->|"2.9: remember(Bilan de la saison ...)"| MS
    W -->|"2.9.1: emit(memory_write)"| EF
    W -->|"2.10: emit(season_end)"| EF
    EF -->|"2.10.1: publish(events, season_end)"| K
    S -->|"3: recit = ensure_future(narrate)"| S
    K -->|"4: season_end"| IND
    IND -->|"4.1: produce filets.indicators (season_end)"| K
    K -->|"5: events et indicators"| API
    API -->|"6: topic events puis topic indicators"| M
    M -->|"6.1: _on_indicator puis chart.set_season"| M
    S -->|"7: prepare_season : debrief(season), puis elect et plan_patrol en parallèle"| W
```

Dans le code : `filets/scheduler.py:222-231` ; `filets/world.py:2563`, `:772`, `:836`, `:544`, `:2573`, `:2577-2580`, `:409-418`, `:2582-2591`, `:2968-2974`, `:1809`, `:1771`, `:1819` ; `filets/lake.py:87` ; `filets/rag.py:167`, `:225` ; `filets/services/indicators.py:30-38` ; `godot/scripts/main.gd:1122`, `:1158`.

## (f2) Le récit du narrateur

```mermaid
flowchart LR
    S["sched : SeasonScheduler"]
    W["world : World"]
    RT["router : LLMRouter"]
    GATE["gate : ModelGate"]
    OL["ollama : Ollama"]
    EF["events : EventFactory"]
    K["bus : Kafka"]
    M["main : Main"]

    S -->|"1: narrate(season) dans une tâche"| W
    W -->|"2: narrator_facts(season, 14)"| W
    W -->|"3: complete(narrateur, grand, narration, messages, S2) [grand modèle, non scripté]"| RT
    RT -->|"3.1: acquire(model)"| GATE
    RT -->|"3.2: POST v1/chat/completions"| OL
    OL -->|"3.3: texte JSON recit"| RT
    RT -->|"3.4: release"| GATE
    RT -->|"3.5: emit(llm_call)"| EF
    RT -->|"4: LLMResult"| W
    W -->|"5: emit(incident) [réponse manquante ou illisible]"| EF
    W -->|"6: le récit reprend les faits [pas de texte]"| W
    W -->|"7: emit(narration, source)"| EF
    EF -->|"7.1: publish(events)"| K
    K -->|"8: via bridge et API"| M
    M -->|"8.1: _on_event, cas narration, onglet Récit du narrateur"| M
```

Dans le code : `filets/world.py:2747`, `:2847-2872` ; `filets/llm.py:365-420`, `:109` ; `filets/scheduler.py:227-230`.

## (g) Le tirage d'une vallée depuis le menu

```mermaid
flowchart LR
    J(["joueur"])
    SM["menu : StartMenu"]
    M["main : Main"]
    WS["ws : WsClient"]
    API["api : ApiServer Hub"]
    BR["bridge : amain"]
    K["Kafka"]
    ENG["engine : Engine"]
    CAT["catalog : generate_world"]

    J -->|"1: change un nombre ou clique Générer la vallée"| SM
    SM -->|"1.1: _on_gen_spin, _gen_timer.start"| SM
    SM -->|"1.2: _on_generate : params, id, _pending_generation"| SM
    SM -->|"2: signal generate_requested(params + id) [pas de demande en route depuis moins de 5 s]"| M
    M -->|"3: send(generate_world, config)"| WS
    WS -->|"4: send_text(JSON)"| API
    API -->|"5: on_command(cmd)"| BR
    BR -->|"6: produce filets.commands"| K
    K -->|"7: KafkaBus puis poll_commands [état idle ou ended]"| ENG
    ENG -->|"7.1: generate(req) : valide flotte, mode, bornes, villages au plus pêcheurs, lacs au plus villages"| ENG
    ENG -->|"7.2: publish status avec error [refus]"| K
    ENG -->|"7.3: generate_world(base_cfg, villages, fishers, seed, fleet, lakes, patrols, mode)"| CAT
    CAT -->|"7.3.1: random_valley(seed) [mode random], base_population, resolve_lakes"| CAT
    CAT -->|"7.4: hamlets, base_population, lakes, patrols"| ENG
    ENG -->|"7.5: catalog = ..., generation(id), publish status avec catalog"| K
    K -->|"8: status"| BR
    BR -->|"8.1: push(status)"| API
    API -->|"9: sépare le catalogue : topic catalog"| WS
    WS -->|"10: signal message(catalog)"| M
    M -->|"10.1: set_catalog(cat)"| SM
    SM -->|"10.2: remplace pêcheurs et lacs, _pending_generation vide"| SM
    API -->|"9.1: status avec error"| M
    M -->|"9.2: show_error(texte)"| SM
```

Dans le code : `godot/scripts/start_menu.gd:1313-1323`, `:1336-1354`, `:569`, `:650`, `:641`, `:1171` ; `godot/scripts/main.gd:603-605`, `:729-737` ; `filets/engine.py:360-374`, `:376-414` ; `filets/catalog.py:119-142`, `:145` ; `filets/lakes.py:254` ; `filets/api.py:213-224`, `:236-247`.

## (h) L'arrêt d'une partie

```mermaid
flowchart LR
    J(["joueur"])
    M["main : Main"]
    WS["ws : WsClient"]
    API["api : ApiServer Hub"]
    K["Kafka"]
    W["world : World run et _command_pump"]
    CTL["ctl : GameControl"]
    S["sched : SeasonScheduler"]
    RT["router : LLMRouter"]
    EF["events : EventFactory"]
    S3["objets : S3"]
    ENG["engine : Engine"]

    J -->|"1: clique Arrêter la partie"| M
    M -->|"1.1: _on_stop_pressed : stop_dlg.popup_centered()"| M
    M -->|"2: _send(stop) [Oui, arrêter ; Non : rien]"| WS
    WS -->|"3: send_text(JSON)"| API
    API -->|"4: via Bridge : produce filets.commands"| K
    W -->|"5: poll_commands() toutes les 0,05 s"| K
    W -->|"5.1: handle_command puis _control_command(stop)"| W
    W -->|"5.2: stop_requested = true, stopped_reason = stop"| W
    W -->|"5.3: emit(injection, stop)"| EF
    W -->|"5.4: request_stop()"| CTL
    CTL -->|"5.4.1: _stop.set, clock.resume, _run.set"| CTL
    W -->|"5.5: publish_status()"| W
    S -->|"6: checkpoint() ou guard()"| CTL
    CTL -->|"6.1: StopRun"| S
    CTL -->|"6.2: guard annule la tâche en cours"| RT
    RT -->|"6.3: emit(llm_call, cancelled) [requête partie]"| EF
    W -->|"7: except StopRun, annule récits et _command_pump"| W
    W -->|"8: finish() : emit(run_end, stop)"| EF
    W -->|"8.1: router.aclose(), bus.flush(), publish_status(ended)"| RT
    W -->|"8.2: summary.json, recorder.close(), archive_run"| S3
    W -->|"8.3: memory_bank.flush, fermeture du stockage"| W
    W -->|"9: run() rend la main"| ENG
    ENG -->|"9.1: end_reason = stop, final_status, publish_status(ended)"| K
    K -->|"10: status ended via bridge"| M
    M -->|"10.1: _on_status puis _show_end : Partie arrêtée"| M
```

Dans le code : `godot/scripts/main.gd:358`, `:560`, `:594-596`, `:562-568`, `:645-662` ; `filets/world.py:1663`, `:1698-1704`, `:2976-3010`, `:2900`, `:2926`, `:2931` ; `filets/control.py:24`, `:75`, `:83`, `:107` ; `filets/llm.py:384-396` ; `filets/engine.py:458-479`.
