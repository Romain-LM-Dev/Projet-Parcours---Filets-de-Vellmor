# FILETS — architecture, temps, communication, stockage

Ce document explique comment les morceaux du jeu se parlent et où vont les données. Le détail des réglages est dans le
[README](../README.md).

## 1. Architecture

```
 Godot (menu, scène, pilotage)        navigateur, script, tableau de bord
        │  ▲                                   │ REST JSON (/api/…, doc sur /docs)
        │  │ WebSocket JSON (/ws)              │
        ▼  │                                   ▼
   service « bridge » : API FastAPI (REST + WebSocket) ◄──┐
        ▲                                                   │
        │ Kafka (topics : events, indicators, commands, status, deadletter)
        │                                                   │
        ├──────────► MOTEUR PYTHON (asyncio) ───────────────┤───► Ollama : /v1/chat/completions (Qwen, réflexion)
        │            monde, agents, horloge                 │            /v1/systemone (tev1, décisions simples)
        │                 │        │                        │            /api/embed (plongements du RAG)
        │                 │        └── RAG ───► PostgreSQL + pgvector (corpus et souvenirs, avec leur vecteur)
        │                 └── archive ───────► stockage objet S3 (documents du corpus, fichiers des parties)
   service « indicators »             service « store »
   (calcule en flux)                  (historique : PostgreSQL, ou SQLite)
```

| Processus | Rôle |
|---|---|
| **Moteur** (`python -m filets serve`) | Le « salon » : attend `start_game`, joue la partie (lac, pêcheurs, veillées, normes), appelle les IA, publie tout ce qui arrive. Un seul processus asyncio. |
| **indicators** | Lit `filets.events`, recalcule les indicateurs (stock en % de la capacité, norme, promesses, tokens par système…) et les publie. Il se place seul sur le dernier `run_start` : démarré avant, pendant ou après la partie, il aboutit aux mêmes chiffres. |
| **store** | Range événements et indicateurs dans **PostgreSQL** (`storage.history: postgres`) ou SQLite (`data/history.db`), pour les requêtes d'analyse. Il ne valide sa position dans Kafka qu'après l'écriture en base. |
| **bridge** | L'**API FastAPI** sur `:8765` : WebSocket pour Godot (`/` et `/ws`, protocole inchangé) et REST pour tout le reste (`/api/status`, `/api/catalog`, `POST /api/commands`, `/api/runs`, `/api/runs/{id}/events`, `/api/runs/{id}/memories`). Documentation essayable sur `/docs`. Elle n'écoute que sur 127.0.0.1 (aucune authentification). |
| **PostgreSQL + pgvector** | Avec `config/data.yaml` : le RAG (passages du corpus et souvenirs des agents, avec leur vecteur) et l'historique des parties. |
| **Stockage objet S3** | Avec `config/data.yaml` : les fichiers bruts, à savoir les documents du corpus et l'archive de chaque partie (`events.jsonl`, `indicators.jsonl`, `config.json`, `summary.json`). SeaweedFS dans `docker-compose.yml`, ou tout service S3 (MinIO, AWS…). |
| **Godot** | Affiche, ne décide rien : menu, carte de la vallée, fil des interactions, inspecteur d'agent, barre de pilotage. |
| **Ollama** | Serveur de modèles locaux. Seul le moteur lui parle. |

Sans Kafka (`serve` seul, ou les tests), un bus en mémoire (`LocalBus`) a la même interface et le moteur ouvre lui-même l'API : c'est le mode des essais rapides. Sans `config/data.yaml`, le RAG reste en mémoire (BM25) et l'historique dans SQLite : aucun service à lancer.

### Godot et Ollama : il n'y a pas de lien direct

Godot n'appelle jamais un modèle. Le chemin d'une décision de pêcheur :

1. le moteur construit le contexte de l'agent (son état du lac, sa mémoire, ce qu'il sait des autres…) ;
2. il envoie à Ollama soit une requête `POST /v1/chat/completions` (Qwen) avec un schéma JSON qui impose la forme de la réponse, soit, pour une décision simple, une **question typée** `POST /v1/systemone` au modèle de décision (§ 4) ;
3. la réponse (un JSON) est validée, devient un événement `decision`, puis `catch` ;
4. ces événements partent sur Kafka, l'API les relaie à Godot, qui les dessine (une barque sort, « +3,2 t », une ligne dans le fil).

Dans l'autre sens, ce que fait le joueur dans Godot (démarrer, pause, vitesse, rumeur, sécheresse…) est une **commande** JSON : Godot → API (WebSocket) → `filets.commands` → moteur, qui la lit toutes les 50 ms, la valide et la tient pour un événement `injection`. Un script peut envoyer la même commande en REST (`POST /api/commands`) : elle est validée avant de partir (422 si elle ne l'est pas).

## 2. Temporalité et horloge

Le monde a son propre temps, **simulé**, en jours : une saison dure 30 jours. Chaque événement porte deux temps :

* `sim_time` : quand il se passe dans le monde ;
* `processed_at` : quand le système l'a traité (temps réel, pauses déduites).

Le calendrier d'une saison : J0 06:00 ouverture de la pêche ; J20 fermeture ; J25 18:00 veillée ; J29 fin de veillée et vote ; J29,9 repeuplement et bilan.

Deux manières de le faire avancer, au choix à chaque saison :

* **Synchrone** : tous les pêcheurs décident sur le même instantané du monde, puis agissent ensemble. La lenteur d'une IA ne change rien au temps du monde. Les attentes ne servent qu'à l'affichage (au plus 4 s par étape, divisées par la vitesse).
* **Asynchrone** : chacun va à son rythme (décalage de 0 à 4 jours) et le temps du monde suit le temps réel, à `sim_hours_per_second × vitesse` (3 heures simulées par seconde à × 1) **tant qu'une IA réfléchit**. Une IA qui met 30 s agit 90 heures plus tard dans le monde, sur un lac qui a changé, et peut rater sa fenêtre : c'est l'effet étudié.

Ce qui réduit l'attente sans fausser le monde :

* quand **personne ne réfléchit**, l'horloge accélère (`idle_speedup`, × 40) : on ne regarde pas un monde vide ;
* la **vitesse** (× 1/16 à × 16, ou « max ») se change à tout moment ; **la pause** fige tout, y compris les appels aux IA ;
* à la **fermeture d'une fenêtre** (pêche, veillée), les appels des IA qui réfléchissent encore sont abandonnés : leur réponse ne servirait plus ;
* le **système 1** (§ 4) réduit le temps de réflexion lui-même, et le modèle de décision open plus encore.

## 3. Communication et mémoire

### Ce qui circule : des événements JSON

Tout fait du monde est un événement avec la même enveloppe (`event_id`, `run_id`, `seq`, `sim_time`, `processed_at`, `actor`, `payload`) et un `payload` décrit par un schéma JSON (`schemas/*.json`, exportés par `python -m filets schemas`). Les natures : `decision`, `utterance`, `proposal`, `support`, `promise`, `accusation`, `norm_adopted`, `catch`, `sale`, `lake_update`, `llm_call`, `incident`, `injection`, `memory_write`…

### La veillée

Chaque tour de parole est un événement `utterance` (qui parle, à qui, ce qu'il a entendu avant). Ses effets sont des événements séparés :

* une **proposition** de quota ; deux quotas à moins de 0,75 t l'un de l'autre sont la même proposition (celui qui propose la deuxième la soutient) ;
* un **soutien**, une **promesse**, une **accusation** ;
* le **vote de clôture** : chaque pêcheur à IA qui n'a soutenu aucune proposition remplit un **bulletin** (une question à choix au modèle de décision, ou à défaut au petit modèle ; réponse : l'identifiant d'une proposition ou « aucune ») ; à défaut de réponse, il vote pour la proposition la plus proche de ce qu'il a dit vouloir (à 1,5 t près), ou s'abstient s'il n'a rien dit de chiffré ;
* une proposition soutenue par **plus de la moitié des pêcheurs présents** devient une **règle** (`norm_adopted`) pour la saison suivante.

### Mémoire personnelle et collective

* **Personnelle** : chaque agent a son flux de souvenirs datés. À chaque décision, il retrouve les plus utiles par **récence, importance et pertinence**. La pertinence est mesurée par BM25 sur les mots (par défaut), ou par la **similarité de sens** des vecteurs dans pgvector (`rag.backend: pgvector`, § 6). Ses **engagements** (une promesse faite, une accusation reçue) sont épinglés : ils reviennent à chaque décision tant qu'ils sont d'actualité, même s'il compte les trahir. Il garde aussi la suite de ses propres constats du lac (`stock_seen`) pour en voir la tendance.
* **Collective** : ce que tout le monde peut savoir. Les règles adoptées, les prises que le marché rend visibles, ce qui s'est dit à la veillée, les rumeurs du joueur (présentes dans chaque décision, deux saisons), et un **corpus** de récits et de comptes (`corpus/`, retrouvé par pertinence). Avec pgvector, les souvenirs de tous les agents d'une partie forment une mémoire collective interrogeable par le sens : `GET /api/runs/{id}/memories?q=…&agent=F01&until=12.5`.
* Rien n'est retrouvé avant son instant : un agent n'agit jamais sur une information qu'il n'avait pas encore (C6, vérifié). Avec pgvector, ce filtre (et celui du hameau pour le corpus) est dans la requête SQL elle-même.

### Pas de perte d'information

* **Journal d'abord.** Chaque événement est écrit dans `runs/<id>/events.jsonl` par le moteur lui-même, avant et indépendamment de Kafka : même si un service tombe, la partie est complète et rejouable (`python -m filets replay <id>`, sans aucun appel d'IA). Avec un stockage objet, ces fichiers sont archivés à la fin de la partie.
* **Kafka comme intergiciel.** Producteur `acks=all` et idempotent, une seule partition pour `filets.events` (ordre total garanti), conservation 7 jours (une heure pour l'état du moteur). Les services lisent à leur rythme et reprennent au dernier `run_start`.
* **Historique sans perte ni doublon.** Le service `store` écrit dans la base, valide la transaction, et seulement ensuite valide sa position dans Kafka. Une panne entre les deux fait relire quelques messages, que l'écriture idempotente (`ON CONFLICT DO NOTHING`) ignore.
* **Souvenirs écrits avant d'être cherchés.** Avec pgvector, un souvenir attend dans une file et toute recherche commence par écrire la file (un seul lot de vecteurs, une seule requête). Si la base tombe en cours de partie, la recherche se rabat sur BM25 en mémoire : aucune décision n'est privée de contexte.
* **Validation partout.** Un événement non conforme à son schéma n'est jamais perdu en silence : il va dans `filets.deadletter` et un `incident` le dit. Il en est de même d'une commande invalide.
* **Vérification.** `python -m filets verify <id>` contrôle les schémas, l'ordre, la monotonie du temps simulé et l'absence d'information venue du futur.
* **Communication avec les IA : JSON.** Requêtes et réponses sont du JSON (API compatible OpenAI, et `/v1/systemone` d'Ollama), avec une limite de débit, des reprises et le décompte des tokens de chaque appel (`llm_call`).

## 4. Économie de tokens : système 1 et système 2

Chaque appel à un modèle coûte du temps, de l'énergie, et des tokens facturés sur une API. Le profil `llm.reflection: adaptive` répartit l'effort, comme Kahneman oppose le réflexe et la réflexion :

| | Système 1 — réflexe | Système 2 — réflexion |
|---|---|---|
| Quand | prise de **routine** : lac à plus de 70 % et qui ne baisse pas, un engagement ou une règle à suivre, aucune rumeur, finances correctes ; **bulletins de vote** | tout le reste : première saison, lac qui baisse ou sous 70 %, rumeur, finances tendues, rien pour guider ; **toutes les paroles de la veillée** |
| Contexte | une dizaine de lignes (≈ 150 tokens) | contexte complet allégé (≈ 1 500 à 2 000 tokens) |
| Réponse | un niveau ou une option : `{"prise": 3.3}`, `{"vote": "P1"}` | la justification (ce que l'agent constate du lac), puis le nombre |
| Modèle | le **modèle de décision open** (tev1 0,8B) s'il y en a un, sinon le petit modèle de langage | celui de l'agent (Qwen 3B ou 1,5B) |

**Le modèle de décision open (`config/ollama_open.yaml`, menu « Ollama · rapide + réflexes open »).** Un modèle de langage génère du texte, token après token, même pour répondre « 3 ». Un modèle de décision « système 1 » (`tev1` de Together AI, affiné à partir de Qwen 3.5, 0,8 Md de paramètres, environ 0,8 Go) répond à une **question typée** sur un état donné, via `POST /v1/systemone` d'Ollama, qui suit l'API « Jev » de TypeSafe. Le modèle demande Ollama 0.40.4 ou plus :

* `score` : une échelle ordonnée (2 à 26 niveaux). La prise de routine est une échelle de 10 niveaux, de 0 t (« il reste à quai ») à la capacité de la barque. La réponse est le niveau moyen pondéré par les probabilités (3,5 tombe entre le niveau 3 et le niveau 4), et le moteur le convertit en tonnes ;
* `choice` : une option parmi 2 à 26. Le bulletin de vote propose les propositions de la veillée, plus « aucune » ;
* `noul` : la probabilité que ce soit vrai.

La réponse tient en un ou deux tokens, avec les probabilités de chaque option et une **confiance**, c'est-à-dire la concentration de ces probabilités (pas la chance d'avoir raison). La confiance est notée dans la justification (« Réflexe (système 1, tev1:0.8b) : lac sain et stable. Confiance 0.82. »). Si le modèle manque (Ollama trop ancien, modèle non téléchargé), la partie se lance quand même et ces décisions passent par le petit modèle de langage : une économie en moins, aucune décision perdue. Ollama le présente comme expérimental, à ne pas utiliser pour des décisions à fort enjeu sans relecture : ici, il ne décide que de prises de routine et de bulletins, et chaque réponse est tracée.

Chaque `llm_call` et chaque `decision` porte son système (`S1` / `S2`) et son niveau (`reflexe`, `petit`, `grand`), et les indicateurs comptent appels et tokens par système (`llm_calls_s1`, `llm_tokens_s2`…). On peut donc dire ce que la réflexion a coûté et ce que le réflexe a épargné. Les profils `rapide` et `complete` passent tout en système 2 (`complete` reste le profil de référence des expériences).

**Fiabilité des données.** La forme de la réponse est imposée au fournisseur par un schéma JSON (Ollama : décodage contraint, aucun champ oublié, textes bornés), ou par le type de la question pour le modèle de décision. Une graine stable par partie, agent, saison, nature et tour est envoyée (même configuration, mêmes réponses). Toute décision qui retombe sur la règle de repli est marquée `fallback` et signalée par un incident, donc comptée.

## 5. Bibliothèques asynchrones

Tout ce qui attend (un modèle, Kafka, la base, le stockage objet) est attendu sans bloquer, dans une seule boucle asyncio par processus :

| Pour | Bibliothèque | Où |
|---|---|---|
| les modèles (Ollama, Groq…) et les plongements | **httpx** (`AsyncClient`) | moteur (`llm.py`, `vectors.py`) |
| l'API REST + WebSocket | **FastAPI** sur **uvicorn**, dans la boucle du moteur ou du service | `api.py` |
| Kafka côté services | **aiokafka** (consommateurs `async for`, producteur idempotent) | `aio.py`, `services/` |
| PostgreSQL + pgvector | **asyncpg** (pool de connexions, type `vector` déclaré par `pgvector.asyncpg`) | `vectors.py`, `pgstore.py` |
| le stockage objet S3 | **miniopy-async** | `objects.py` |

Le moteur garde `confluent-kafka` pour publier : publier y est déjà un simple dépôt dans la file de librdkafka, sans attente.

## 6. Stockage : PostgreSQL + pgvector et stockage objet

```
docker compose --profile data up -d     # PostgreSQL 17 + pgvector (127.0.0.1:5433), SeaweedFS S3 (127.0.0.1:8333)
ollama pull embeddinggemma              # plongements multilingues, 768 dimensions
python -m filets serve --config config/data.yaml --llm ollama_open     # ou : .\start.ps1 -Kafka -Ollama -OllamaProfile open -Data
```

| Donnée | Où | Pourquoi |
|---|---|---|
| passages du corpus et leur vecteur | PostgreSQL, table `rag_chunks_768` | recherche par le sens, droits (hameau, instant simulé) appliqués dans la requête ; vectorisés une fois (l'empreinte du corpus rendu sert de clé) |
| souvenirs des agents et leur vecteur | PostgreSQL, table `rag_memories_768` | mémoire personnelle (score récence + importance + pertinence calculé par la base) et mémoire collective interrogeable |
| événements, indicateurs, runs | PostgreSQL, tables `events` (JSONB, index GIN), `indicators`, `runs`, et les vues `v_catches`, `v_season_indicators`… | analyse en SQL (`python -m filets query analysis/queries_pg.sql --pg`), écrit par le service `store` ou `python -m filets ingest --pg` |
| documents sources du corpus | stockage objet, `corpus/<empreinte>/*.md` | le texte brut à côté de ses morceaux vectorisés (chaque passage garde la clé de son document) |
| archive de chaque partie | stockage objet, `runs/<run_id>/…` | conservation hors de la machine de jeu |

**Plongements.** `embeddinggemma` (300 M paramètres, multilingue) tourne sur le **processeur** (`cpu: true`) pour laisser la carte graphique de 6 Go aux modèles de langage. Un cache par texte évite de recalculer la même phrase entendue par huit pêcheurs. Mesure sur cette machine : une partie de 3 saisons à 8 pêcheurs a écrit 624 souvenirs et 29 passages avec leur vecteur. Les tests utilisent un plongement haché sans modèle (`kind: hash`), déterministe.

**Une table par dimension** (`rag_chunks_768`, `rag_chunks_384`…), et chaque ligne porte le nom du modèle qui l'a calculée : deux modèles ne mélangent jamais leurs vecteurs.

**Pourquoi SQLite reste le défaut.** Pour jouer ou tester, aucun service n'est nécessaire. PostgreSQL apporte l'écriture concurrente (moteur et services), le JSONB indexé, la recherche vectorielle dans la base et le partage entre machines. Les vues portent les mêmes noms dans les deux bases.
