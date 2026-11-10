# Décisions, IA et mémoire

Cette partie répond à la question « **comment un pêcheur décide-t-il ?** ». Une décision vient soit d'un modèle de langage
(chemin LLM : `agents.py` construit l'invite, `llm.py` l'envoie), soit d'une règle de son archétype (`policies.py`, agents « à
règles »). Le moteur ne décide jamais à leur place. Autour de la décision : la mémoire de l'agent, la recherche de contexte
(RAG) et les vecteurs. Les fichiers qui ne contiennent que des fonctions sont montrés comme `<<module>>`.

## 1. Les décisions : agents, règles et routage

`agents.py` offre les fonctions de décision (`decide_catch`, `speak`, `ballot`…). Chacune choisit son chemin : réflexe
(`routing.py` dit s'il faut réfléchir ou non), règle d'archétype (`policies.py`), ou appel au modèle via le routeur du monde.

```mermaid
classDiagram
    class agents {
        <<module>>
        +reflex_usable(world) bool
        +decide_catch(world, agent, horizon, rescue) Outcome
        +speak(world, agent, assembly, rnd, horizon) Outcome
        +ballot(world, agent, asm)
        +ballot_election(world, voter, candidates, season) str
        +debrief_villager(world, agent, asm)
        +patrol_decision(world, season, legs, days, lines)
    }
    class Outcome {
        +float value
        +dict data
    }
    class Agent {
        +Profile profile
        +MemoryStore memory
        +Random rng
        +float wealth
        +dict last_decision
        +list stock_seen
    }
    class policies {
        <<module>>
        +catch_rule(archetype, s) tuple
        +speak_rule(archetype, s, rng) tuple
        +propose_rule(archetype, s, rng) tuple
        +trust_rule(archetype, facts, ctx) dict
        +sanction_vote(archetype, trust, action) bool
        +declare_rule(archetype, s, v) tuple
        +lake_choice_rule(archetype, s) tuple
        +elect_rule(others, experience, me) str
    }
    class routing {
        <<module>>
        +reasons_to_think(obs) list
        +choose_system(obs, purpose) tuple
    }
    class prompts {
        <<module>>
        +narration_messages(facts)
        +reflex_system_one(...)
    }
    class World {
        +LLMRouter router
        +Retriever retriever
    }
    class LLMRouter

    agents ..> Agent : decide pour
    agents ..> Outcome : retourne
    agents ..> policies : agent a regles
    agents ..> routing : reflexe ou reflexion
    agents ..> prompts : construit les invites
    agents ..> World : lit l etat, appelle router
    World ..> LLMRouter : world.router
    Agent ..> Outcome
```

`Outcome` (valeur + données de la décision) est le résultat commun des fonctions de décision. Les fonctions de `policies.py`
sont pures : même état, même réponse.

**Pour aller plus loin**
- `filets/agents.py:25` (`Agent`), `:58` (`Outcome`), `:144` (`decide_catch`), `:232` (`speak`), `:289` (`ballot`)
- `filets/policies.py:55` (`catch_rule`), `:384` (`speak_rule`), `:308` (`propose_rule`)
- `filets/routing.py:24` (`reasons_to_think`), `:53` (`choose_system`) ; `filets/prompts.py` (toutes les invites)

## 2. Les modèles : routeur, clients, limiteurs

`LLMRouter` reçoit chaque demande d'un agent et la confie au client du fournisseur associé à son niveau (`tier` : grand ou
petit). Les clients parlent à Ollama ou à une API compatible OpenAI ; `ScriptedClient` est le faux modèle des tests (réponses
fabriquées, latences simulées). `RateLimiter` borne le débit et `ModelGate` regroupe les requêtes locales par modèle pour éviter
les échanges de modèle en mémoire graphique. Aucun lien d'héritage : les clients partagent seulement la méthode `complete`.

```mermaid
classDiagram
    class LLMRouter {
        +dict cfg
        +dict clients
        +dict tiers
        +Usage usage
        +complete(agent, tier, purpose, messages, hint) LLMResult
        +describe() dict
        +aclose()
    }
    class LLMResult {
        +str text
        +str status
        +int prompt_tokens
        +int completion_tokens
        +float latency_s
        +str model
        +str tier
    }
    class Usage {
        +int calls
        +int prompt_tokens
        +int completion_tokens
        +float latency_s
        +int cancelled
        +dict by_tier
    }
    class OpenAICompatClient {
        +str name
        +str base_url
        +bool json_schema
        +RateLimiter limiter
        +ModelGate gate
        +complete(model, messages, hint, tier) LLMResult
    }
    class SystemOneClient {
        +str name
        +ModelGate gate
        +complete(model, messages, hint, tier) LLMResult
    }
    class ScriptedClient {
        +dict cfg
        +Random rng
        +float scale
        +complete(model, messages, hint, tier) LLMResult
    }
    class RateLimiter {
        +float interval
        +wait()
    }
    class ModelGate {
        +int slots
        +int max_streak
        +int running
        +str active
        +acquire(model)
        +release()
    }
    class llm {
        <<module>>
        +extract_json(text) dict
        +detect_drift(texts) tuple
        +to_number(v) float
        +level_value(score, scale) float
    }

    LLMRouter "1" *-- "1..*" OpenAICompatClient : clients
    LLMRouter "1" *-- "0..*" SystemOneClient : clients
    LLMRouter "1" *-- "0..1" ScriptedClient : clients
    LLMRouter "1" *-- "1" Usage
    LLMRouter ..> LLMResult : rend
    OpenAICompatClient "1" *-- "1" RateLimiter
    OpenAICompatClient "1" *-- "0..1" ModelGate
    SystemOneClient "1" *-- "0..1" ModelGate
    OpenAICompatClient ..> LLMResult
    SystemOneClient ..> LLMResult
    ScriptedClient ..> LLMResult
    LLMRouter ..> llm : lit les reponses
```

Ce que renvoie un client est un `LLMResult` ; c'est le routeur qui tient les comptes (`Usage`), publie les événements d'appel et
gère erreurs, pauses et annulations. Le fournisseur « scripted » est choisi dans la configuration (`llm.tiers`).

**Pour aller plus loin**
- `filets/llm.py:335` (`LLMRouter`), `:30` (`LLMResult`), `:154` (`OpenAICompatClient`), `:250` (`SystemOneClient`)
- `filets/llm.py:44` (`RateLimiter`), `:61` (`ModelGate`), `:325` (`Usage`)
- `filets/scripted.py:33` (`ScriptedClient`)

## 3. Mémoire, recherche de contexte (RAG) et vecteurs

Chaque `Agent` a un `MemoryStore` (liste de `Memory` classés par récence, importance et pertinence). Avec PostgreSQL + pgvector,
c'est un `VectorMemory`, qui garde aussi la liste locale et se replie sur BM25 si la base tombe. Le `Retriever` cherche dans le
corpus de documents (`Passage`) par BM25 ; `VectorRetriever` fait la même chose avec les vecteurs, en s'appuyant sur un
`Retriever` local comme filet de sécurité. `PgVectorStore` range passages, lore et souvenirs ; les embedders calculent les vecteurs.

```mermaid
classDiagram
    class Memory {
        +str id
        +float t
        +str text
        +str kind
        +float importance
        +bool pinned
        +int expires_season
    }
    class MemoryStore {
        +str owner
        +list items
        +float decay
        +dict w
        +add(t, text, kind, importance) Memory
        +pinned(horizon, season) list
        +retrieve(query, horizon, k) list
        +aretrieve(query, horizon, k) list
    }
    class VectorMemory {
        +MemoryBank bank
        +add(t, text, kind, importance) Memory
        +aretrieve(query, horizon, k) list
    }
    class MemoryBank {
        +PgVectorStore store
        +str run_id
        +list pending
        +bool degraded
        +flush()
    }
    class Passage {
        +str id
        +str title
        +str text
        +list visible_to
        +float sim_time
        +str source
    }
    class BM25 {
        +scores(query) list
    }
    class Retriever {
        +list passages
        +dict files
        +add_lore(passage, cap) list
        +search(query, hamlet, horizon, k) list
        +asearch(query, hamlet, horizon, k) list
    }
    class VectorRetriever {
        +Retriever local
        +str corpus
        +bool degraded
        +add_lore(passage, cap) list
        +asearch(query, hamlet, horizon, k) list
        +open()
    }
    class PgVectorStore {
        +str dsn
        +int dim
        +put_chunks(corpus, rows)
        +search_chunks(corpus, qvec, hamlet, horizon, k)
        +put_memories(run_id, rows)
        +search_memories(run_id, owner, qvec, horizon, exclude, weights)
        +put_lore(run_id, rows)
    }
    class HashEmbedder {
        +int dim
        +vector(text) list
        +embed(texts) list
    }
    class OllamaEmbedder {
        +str model
        +int dim
        +embed(texts) list
    }
    class Agent {
        +MemoryStore memory
    }

    MemoryStore <|-- VectorMemory
    MemoryStore "1" *-- "0..*" Memory : items
    VectorMemory o-- MemoryBank : bank
    MemoryBank o-- PgVectorStore : store
    Agent "1" *-- "1" MemoryStore : memory
    Retriever "1" *-- "0..*" Passage : passages
    Retriever ..> BM25 : classe les passages
    VectorRetriever "1" *-- "1" Retriever : local
    VectorRetriever o-- PgVectorStore : store
    PgVectorStore o-- HashEmbedder : embedder
    PgVectorStore o-- OllamaEmbedder : embedder
    MemoryStore ..> BM25 : pertinence
```

`HashEmbedder` (sac de mots haché, sans réseau) et `OllamaEmbedder` (modèle d'Ollama) jouent le même rôle ; `make_embedder`
(dans `vectors.py`) choisit l'un ou l'autre selon la configuration. `rag.py` contient aussi des fonctions utilitaires
(`normalize`, `tokenize`, `lore_passage`, `render`).

**Pour aller plus loin**
- `filets/memory.py:29` (`Memory`), `:41` (`MemoryStore`), `:80` (`MemoryBank`), `:104` (`VectorMemory`)
- `filets/rag.py:81` (`Passage`), `:54` (`BM25`), `:136` (`Retriever`), `:204` (`VectorRetriever`)
- `filets/vectors.py:34` (`HashEmbedder`), `:57` (`OllamaEmbedder`), `:134` (`PgVectorStore`), `:101` (`make_embedder`)
- `filets/world.py:249` (création de `MemoryBank` / `VectorMemory`), `:320` (création du retriever)
