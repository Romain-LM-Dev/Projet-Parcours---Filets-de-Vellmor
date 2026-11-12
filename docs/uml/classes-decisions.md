# Décisions, IA et mémoire

Cette partie répond à « **comment un pêcheur décide-t-il ?** ». Une décision vient soit d'un modèle de langage (`agents.py` construit
l'invite avec `prompts.py`, `llm.py` l'envoie), soit d'une règle de son archétype (`policies.py`). Le moteur ne décide jamais à leur
place. Autour : la mémoire de l'agent, la recherche de contexte (RAG) et les vecteurs. Les fichiers qui ne contiennent que des
fonctions sont montrés comme `<<module>>` (fonctions et constantes publiques). Même légende que `classes-monde.md`.

## 1. Fonctions de décision, règles d'archétype et routage

`agents.py` offre les fonctions de décision (`decide_plan` : le plan de la saison ; `decide_catch` : chaque sortie, avec ce qu'il déclare à son retour ; `speak`, `ballot`…). Chacune choisit son chemin : réflexe ou réflexion (`routing.py`), règle d'archétype (`policies.py`) ou appel au modèle via `world.router`. `Outcome` est le résultat commun.

```mermaid
classDiagram
    class agents {
        <<module>>
        +dict PLACES
        +reflex_usable(world) bool
        +decide_plan(world, agent, horizon) Outcome
        +decide_catch(world, agent, horizon, rescue) Outcome
        +speak(world, agent, assembly, rnd, horizon) Outcome
        +ballot(world, agent, asm) None?
        +ballot_election(world, voter, candidates, season) str?
        +debrief_villager(world, agent, asm) None?
        +patrol_decision(world, season, legs, days, lines, agent) tuplelisttuplestr?
    }
    class Agent {
        +Profile profile
        +MemoryStore memory
        +random.Random rng
        +float wealth
        +float offset_days
        +dict catches
        +dict? last_decision
        +list stock_seen
        +dict declared
        +dict outings
        +float form
        +int form_season
        +dict plans
        +dict? prev
        +float temper
        +dict lake_choice
        +int? spot
        +dict spots
        +str id
        +bool is_fisher
        +str archetype
    }
    class Outcome {
        +float? value
        +dict data
        +dict decision
        +bool ok
    }
    class policies {
        <<module>>
        +dict JUDGE
        +dict EXCLUDE_BELOW
        +dict VOTE_EXCLUDE_BELOW
        +dict REAUTHORIZE_FROM
        +dict PATROL_WANTS
        +dict KIN_SOFT
        +dict GOSSIP
        +dict LEAVE
        +sustainable_share(stock_est, capacity, n_fishers) float
        +needs(s) float
        +clamp(x, hi, lo) float
        +obeys(archetype, s) bool
        +rule_choices(archetype, s) tuple
        +catch_rule(archetype, s) tuple
        +outing_rule(archetype, s, first) tuple
        +patrol_vote(archetype, lies, action) bool
        +elect_rule(others, experience, me) str
        +trust_rule(archetype, facts, ctx) dict
        +sanction_vote(archetype, trust, action) bool
        +sanction_rule(archetype, s, judged) dict
        +declare_rule(archetype, s, v) tuple
        +declare_outing(archetype, s, landed) tuple
        +projected(stock, capacity, r) float
        +lake_choice_rule(archetype, s) tuple
        +at_lake(s, option) dict
        +propose_rule(archetype, s, rng) tuple?
        +rule_lake(s, rng) str?
        +likes_rule(archetype, s, kind, target, value) bool
        +speak_rule(archetype, s, rng) tuple
    }
    class routing {
        <<module>>
        +float HEALTHY_RATIO
        +float FALLING_RATIO
        +reasons_to_think(obs) list
        +choose_system(obs, purpose) tuple
        +snapshot(obs) dict
        +season_reasons(obs) list
        +outing_reasons(obs, prev) list
        +choose_outing_system(obs, prev) tuple
    }
    class World
    class Profile
    class MemoryStore
    class prompts
    class LLMRouter
    agents ..> Agent : decide pour
    agents ..> Outcome : retourne
    agents ..> policies : agent a regles
    agents ..> routing : S1 ou S2
    agents ..> prompts : invites
    agents ..> World : lit l etat
    agents ..> LLMRouter : via world.router
    Agent "1" *-- "1" Profile : profile
    Agent o-- MemoryStore : memory
```

**Pour aller plus loin**
- `filets/agents.py:26` (`Agent`)
- `filets/agents.py:62` (`Outcome`)
- `filets/agents.py:171` (`decide_plan`)
- `filets/agents.py:265` (`decide_catch`)
- `filets/agents.py:363` (`speak`)
- `filets/agents.py:420` (`ballot`)
- `filets/policies.py:55` (`catch_rule`)
- `filets/policies.py:95` (`outing_rule`)
- `filets/policies.py:264` (`declare_outing`)
- `filets/policies.py:420` (`speak_rule`)
- `filets/policies.py:344` (`propose_rule`)
- `filets/routing.py:24` (`reasons_to_think`)
- `filets/routing.py:89` (`outing_reasons`)
- `filets/routing.py:53` (`choose_system`)

## 2. Les invites (`prompts.py`)

Toutes les invites vues par les agents (en français simple) et les schémas de réponse attendus. Module de fonctions pures : même état, même texte.

```mermaid
classDiagram
    class prompts {
        <<module>>
        +str WORLD
        +str STYLE
        +str BRIEF_STYLE
        +dict BRIEF_MAX_TOKENS
        +int REFLEX_MAX_TOKENS
        +dict REFLEX_SCHEMA
        +dict REFLEX_OUTING_SCHEMA
        +list LIEUX
        +str PATROL_WHO
        +str WORLD_LAKES
        +list RULE_KINDS
        +any WHEN_HELP
        +int BALLOT_MAX_TOKENS
        +dict NARRATION_SCHEMA
        +int NARRATION_MAX_TOKENS
        +float NARRATION_TEMPERATURE
        +int NARRATION_WIDTH
        +int SANCTION_MAX_TOKENS
        +int ELECTION_MAX_TOKENS
        +int DEBRIEF_MAX_TOKENS
        +any DEBRIEF_SCHEMA
        +int PATROL_MAX_TOKENS
        +is_brief(cfg_llm) bool
        +is_adaptive(cfg_llm) bool
        +cap_text(x, digits) str
        +villages_text(villages) str
        +day_line(obs) str
        +boat_line(obs) str
        +catch_range(obs) str
        +reflex_messages(p, obs) list
        +lake_ref(label) str
        +lakes_text(lakes) str
        +persona(p, capacity, brief, villages, world) str
        +lake_level(est, capacity, collapse_ratio) str
        +lake_trend(est, capacity, history) str
        +lake_block(obs) str
        +social_line(obs) str
        +surplus_line(obs) str
        +lake_reminder(obs) str
        +rule_reminder(obs) str
        +fishing_rules_reminder(obs) str
        +rule_review(obs) str
        +rule_types_help(obs, brief) str
        +trust_word(v) str
        +trust_line(obs) str
        +carnet_block(obs) str
        +clues_block(obs) str
        +trust_schema(ids) dict
        +answer_schema(purpose, brief, fisher, ids, lakes, extras) dict
        +time_lines(obs) list
        +context_block(obs, brief) str
        +lake_options_block(obs) str
        +hide_stakes(obs) str
        +season_block(obs) str
        +catch_messages(p, obs, capacity, brief, plan) list
        +veillee_block(obs) str
        +speak_messages(p, obs, capacity, brief) list
        +ballot_schema(ids) dict
        +ballot_messages(p, table, est, capacity, collapse_ratio) list
        +narration_messages(facts) list
        +narration_numbers_message(extra) str
        +repeated_line_message(text, who, season) str
        +catch_levels(boat_capacity, n, lo) list
        +reflex_system_one(p, obs) dict
        +sanction_schema(ids) dict
        +sanction_messages(p, items, situation) list
        +sanction_system_one(p, items, situation) dict
        +ballot_system_one(p, proposals, est, capacity, collapse_ratio) dict
        +election_schema(ids) dict
        +election_messages(p, items, situation) list
        +election_system_one(p, items, situation) dict
        +debrief_schema(ids) dict
        +debrief_messages(p, lines, trust, situation) list
        +debrief_system_one(p, lines, trust, situation, ids) dict
        +patrol_schema(targets, legs, days) dict
        +patrol_messages(p, capacity, villages, lines, legs, days, world) list
    }
    class agents
    class LLMRouter
    class World
    agents ..> prompts
    World ..> prompts : narration
    prompts ..> LLMRouter : fournit les messages
```

**Pour aller plus loin**
- `filets/prompts.py:748` (`narration_messages`), `:765` (`narration_numbers_message`), `:714` (`repeated_line_message`)
- `filets/prompts.py:755` (`reflex_system_one`)

## 3. Modèles : routeur, clients, limiteurs

`LLMRouter` reçoit chaque demande d'un agent et la confie au client du fournisseur associé à son niveau (`tier`). Les clients parlent à Ollama ou à une API compatible OpenAI ; `ScriptedClient` est le faux modèle des tests. `RateLimiter` borne le débit, `ModelGate` regroupe les requêtes locales par modèle. Les clients ne partagent aucune classe de base : seulement la méthode `complete`.

```mermaid
classDiagram
    class LLMRouter {
        +any cfg
        +any clock
        +any events
        +any ctl
        +dict clients
        +any tiers
        -int _n
        +Usage usage
        +__init__(cfg, clock, events, rng_seed, ctl)
        +describe() dict
        +complete(agent, tier, purpose, messages, hint) LLMResult
        +aclose()
    }
    class LLMResult {
        +str? text
        +str status
        +int prompt_tokens
        +int completion_tokens
        +float latency_s
        +int retries
        +str call_id
        +str model
        +str provider
        +str tier
        +str detail
    }
    class Usage {
        +int calls
        +int prompt_tokens
        +int completion_tokens
        +float latency_s
        +int cancelled
        +dict by_tier
        +dict by_system
    }
    class OpenAICompatClient {
        +str name
        +bool json_schema
        +bool seed
        +any base_url
        +any api_key
        +RateLimiter limiter
        +dict cfg
        +ModelGate gate
        +AsyncClient http
        +__init__(name, base_url, api_key_env, rpm, cfg, timeout_s, max_concurrency, json_schema, seed)
        +complete(model, messages, hint, tier) LLMResult
        -_complete(model, messages, hint) LLMResult
    }
    class SystemOneClient {
        +str name
        +any url
        +dict cfg
        +ModelGate gate
        +AsyncClient http
        +__init__(name, base_url, cfg, timeout_s, max_concurrency)
        +complete(model, messages, hint, tier) LLMResult
        -_ask(model, hint, t0) LLMResult
    }
    class ScriptedClient {
        +dict cfg
        +Random rng
        +float scale
        +__init__(pcfg, seed)
        +complete(model, messages, hint, tier) LLMResult
        +fisher_answer(hint, arch, s, noise, out_of_role) dict
    }
    class RateLimiter {
        +any interval
        -float _next
        -Lock _lock
        +__init__(rpm)
        +wait()
    }
    class ModelGate {
        +int slots
        +int max_streak
        +int running
        +str? active
        +int streak
        -int _seq
        +dict waiting
        +int swaps
        +__init__(slots, max_streak)
        -_clean(model) deque
        -_others_waiting() bool
        -_can_start(model) bool
        -_start(model) None?
        +acquire(model) None?
        +release() None?
        -_next_model() str?
        -_dispatch() None?
        -_start_switch(model) None?
    }
    class llm {
        <<module>>
        +any OUT_OF_ROLE
        +any ASSISTANT_POSTURE
        +level_value(score, scale) float
        +extract_json(text) dict?
        +detect_drift(args) tuple
        +to_number(v) float?
    }
    class scripted {
        <<module>>
        +dict JUSTIF
        +list WORDS
        +any SCARCITY
        +any ACCUSATORY
        +dict ECHO
        +word_for(hours, rng) str
        +react_to_rumor(purpose, arch, s, data) None?
    }
    class World
    class GameControl
    class EventFactory
    World "1" *-- "1" LLMRouter : router
    LLMRouter "1" *-- "1..*" OpenAICompatClient : clients
    LLMRouter "1" *-- "0..*" SystemOneClient : clients
    LLMRouter "1" *-- "0..1" ScriptedClient : clients
    LLMRouter "1" *-- "1" Usage : usage
    LLMRouter o-- GameControl : ctl
    LLMRouter o-- EventFactory : events
    LLMRouter ..> LLMResult : rend
    OpenAICompatClient "1" *-- "1" RateLimiter : limiter
    OpenAICompatClient "1" *-- "0..1" ModelGate : gate
    SystemOneClient "1" *-- "0..1" ModelGate : gate
    OpenAICompatClient ..> LLMResult
    SystemOneClient ..> LLMResult
    ScriptedClient ..> LLMResult
    LLMRouter ..> llm : extract_json, to_number
    ScriptedClient ..> scripted : react_to_rumor
```

**Pour aller plus loin**
- `filets/llm.py:335` (`LLMRouter`)
- `filets/llm.py:30` (`LLMResult`)
- `filets/llm.py:325` (`Usage`)
- `filets/llm.py:154` (`OpenAICompatClient`)
- `filets/llm.py:250` (`SystemOneClient`)
- `filets/llm.py:44` (`RateLimiter`)
- `filets/llm.py:61` (`ModelGate`)
`filets/scripted.py:48` (`ScriptedClient`)

## 4. Mémoire et recherche de contexte (RAG)

Chaque `Agent` a un `MemoryStore` (liste de `Memory`, classés par récence, importance et pertinence BM25). Avec PostgreSQL + pgvector c'est un `VectorMemory`, adossé à une `MemoryBank`. Le `Retriever` cherche dans le corpus (`Passage`) par BM25 ; `VectorRetriever` fait de même avec les vecteurs, avec un `Retriever` local en secours.

```mermaid
classDiagram
    class Memory {
        +str id
        +float t
        +str text
        +str kind
        +float importance
        +bool pinned
        +int? expires_season
        +str? source_event_id
        +str? event_id
    }
    class MemoryStore {
        +str owner
        +list items
        +float decay
        +dict w
        -int _n
        +__init__(owner, decay, weights)
        +add(t, text, kind, importance, pinned, expires_season, source_event_id) Memory
        +pinned(horizon, season) list
        +retrieve(query, horizon, k, exclude) list
        +aretrieve(query, horizon, k, exclude) list
    }
    class VectorMemory {
        +MemoryBank bank
        +__init__(owner, decay, weights, bank)
        +add(t, text, kind, importance, pinned, expires_season, source_event_id) Memory
        +aretrieve(query, horizon, k, exclude) list
    }
    class MemoryBank {
        +any store
        +any embedder
        +any run_id
        +list pending
        +Lock lock
        +bool degraded
        +__init__(store, embedder, run_id)
        +flush() None?
    }
    class Passage {
        +str id
        +str title
        +str text
        +list visible_to
        +float sim_time
        +list tokens
        +str agent
        +float importance
        +str source
    }
    class BM25 {
        +list docs
        +any k1
        +any b
        +int N
        +any avgdl
        +dict idf
        +list tfs
        +__init__(docs, k1, b)
        +scores(query) list
    }
    class Retriever {
        +list passages
        +dict files
        +list lore
        -any _all
        +BM25 bm25
        +__init__(corpus_dir, values, villages, market)
        -_index() None?
        +add_lore(p, cap) list
        +search(query, hamlet, horizon, k) list
        +open() None?
        +asearch(query, hamlet, horizon, k) list
        +aclose() None?
    }
    class VectorRetriever {
        +Retriever local
        +any passages
        +dict by_id
        +any store
        +any embedder
        +any objects
        +any min_score
        +any corpus
        +bool degraded
        +str run_id
        -list _new
        -set _gone
        +__init__(corpus_dir, values, store, embedder, objects, min_score, villages, market)
        +add_lore(p, cap) list
        -_flush_lore() None?
        +open() None?
        +asearch(query, hamlet, horizon, k) list
        +search(query, hamlet, horizon, k) list
        +aclose() None?
    }
    class rag {
        <<module>>
        +set STOP
        +list REGISTER_VARIANTS
        +normalize(text) str
        +tokenize(text) list
        +lore_passage(event_id, agent, text, visible_to, t, importance) Passage
        +render(text, values) str
        +register_body(village, market) str
    }
    class Agent
    class PgVectorStore
    class World
    MemoryStore <|-- VectorMemory
    MemoryStore "1" *-- "0..*" Memory : items
    VectorMemory o-- MemoryBank : bank
    MemoryBank o-- PgVectorStore : store
    Agent "1" *-- "1" MemoryStore : memory
    Retriever "1" *-- "0..*" Passage : passages
    Retriever ..> BM25 : classe
    MemoryStore ..> BM25 : pertinence
    VectorRetriever "1" *-- "1" Retriever : local
    VectorRetriever o-- PgVectorStore : store
    Retriever ..> rag : normalize, tokenize
    World "1" *-- "1" Retriever : retriever
    World "1" o-- "0..1" MemoryBank : memory_bank
```

**Pour aller plus loin**
- `filets/memory.py:29` (`Memory`)
- `filets/memory.py:41` (`MemoryStore`)
- `filets/memory.py:80` (`MemoryBank`)
- `filets/memory.py:104` (`VectorMemory`)
- `filets/rag.py:81` (`Passage`)
- `filets/rag.py:54` (`BM25`)
- `filets/rag.py:136` (`Retriever`)
- `filets/rag.py:204` (`VectorRetriever`)

## 5. Vecteurs et base pgvector (`vectors.py`)

Les deux calculateurs de vecteurs (`HashEmbedder` sans réseau, `OllamaEmbedder` via Ollama) et `PgVectorStore`, qui range passages, lore et souvenirs dans PostgreSQL. `make_embedder` choisit l'un ou l'autre selon la configuration.

```mermaid
classDiagram
    class HashEmbedder {
        +int dim
        +str name
        +__init__(dim)
        +vector(text) list
        +embed(texts) list
        +aclose() None?
    }
    class OllamaEmbedder {
        +str url
        +any model
        +any dim
        +any name
        +dict options
        +any batch
        +any cache_max
        +OrderedDict cache
        +AsyncClient http
        +__init__(base_url, model, dim, cpu, timeout_s, batch, cache_max)
        +embed(texts) list
        +aclose() None?
    }
    class PgVectorStore {
        +any dsn
        +any embedder
        +any dim
        +any model
        +any chunks
        +any memories
        +str lore
        +None pool
        +__init__(dsn, embedder)
        +open() None?
        +aclose() None?
        +count_chunks(corpus) int
        +put_chunks(corpus, rows) None?
        +search_chunks(corpus, qvec, hamlet, horizon, k, min_score)
        +put_lore(run_id, rows) None?
        +delete_lore(run_id, ids) None?
        +drop_lore(run_id) None?
        +search_lore(run_id, qvec, hamlet, horizon, k, min_score)
        +put_memories(run_id, rows) None?
        +search_memories(run_id, owner, qvec, horizon, exclude, weights, decay, k)
        +run_memories(run_id, query_vec, k, owner, horizon)
    }
    class EmbeddingError {
    }
    class vectors {
        <<module>>
        +make_embedder(rag_cfg)
        +postgres_dsn(cfg) str
        +connect_pool(dsn, vector, timeout)
        +wait_for_postgres(dsn, timeout_s) None?
    }
    class MemoryBank
    class VectorRetriever
    EmbeddingError --|> RuntimeError
    PgVectorStore o-- HashEmbedder : embedder
    PgVectorStore o-- OllamaEmbedder : embedder
    OllamaEmbedder ..> EmbeddingError : leve
    MemoryBank o-- PgVectorStore
    VectorRetriever o-- PgVectorStore
    vectors ..> HashEmbedder : make_embedder
    vectors ..> OllamaEmbedder : make_embedder
```

**Pour aller plus loin**
- `filets/vectors.py:34` (`HashEmbedder`)
- `filets/vectors.py:57` (`OllamaEmbedder`)
- `filets/vectors.py:134` (`PgVectorStore`)
- `filets/vectors.py:101` (`make_embedder`)
