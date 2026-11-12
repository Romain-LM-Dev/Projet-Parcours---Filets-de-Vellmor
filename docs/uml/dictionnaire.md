# Dictionnaire des variables et des paramètres

Ce dictionnaire donne le sens de chaque réglage et de chaque variable du projet. La première partie couvre ce que l'on
règle sans toucher au code : les clés de la configuration (`config/*.yaml`), les variables d'environnement et les options
de la ligne de commande. La seconde partie couvre les variables du programme : les attributs de chaque classe du moteur
Python et de chaque script Godot, dans le même ordre que les diagrammes de classes, avec leur type, leur unité et leur
rôle.

Unités employées : **t** (tonnes de poisson), **écus** (la monnaie du jeu), **jour simulé** (une saison dure 30 jours
simulés ; `J25 18:00` = 25,75), **s réelle** (seconde d'horloge murale), **part** (nombre de 0 à 1).

## 1. Paramètres de configuration

Une partie est réglée par un fichier YAML. `config/default.yaml` donne toutes les clés et leur valeur par défaut ; un
préréglage (`config/ollama.yaml`…) commence par `extends: default.yaml` et ne redonne que ce qu'il change. On surcharge
une clé en ligne de commande avec `--set clé.pointée=valeur` (valeur lue en YAML) ; le menu de Godot envoie de même une
configuration complète au démarrage d'une partie. Le chargement (`filets/config.py`, `load_config` puis `normalize`)
fusionne ces couches, vérifie les bornes indiquées dans la colonne « Valeurs » et calcule les clés dérivées.

### 1.1 `run` : la partie

| Clé | Type | Défaut | Valeurs | Signification |
|---|---|---|---|---|
| `run.seed` | int | `42` | entier | Graine de tous les tirages : même graine et mêmes réglages, même partie (vallée, départs, météo, chance). |
| `run.seasons` | int | `10` | ≥ 1 | Nombre de saisons jouées. |
| `run.stop_on_collapse` | bool | `false` | | Arrêter la partie à la fin de la saison où un lac passe sous `lake.collapse_ratio`. |
| `run.stop_on_extinction` | bool | `true` | | Arrêter tout de suite quand un lac tombe à 0 t (il ne se repeuple jamais depuis 0). |
| `run.label` | str | nom du fichier | texte | Étiquette de la partie dans l'historique ; à défaut, le nom du fichier de configuration (`baseline`, `ollama`…). |

### 1.2 `population` : la vallée et ses habitants

| Clé | Type | Défaut | Valeurs | Signification |
|---|---|---|---|---|
| `population.villages` | int | `4` | 1 à 8 | Nombre de villages autour des lacs (au plus un par pêcheur). |
| `population.fishers` | int | `8` | ≥ 1 | Nombre de pêcheurs. Recalculé quand `custom` est donné. |
| `population.boat_mix` | dict | `{barque: 0.3, chaloupe: 0.5, cotre: 0.2}` | `{taille: part}` | Répartition des tailles de bateau dans la flotte ; le caractère de chaque pêcheur l'infléchit. |
| `population.random` | bool | `false` | | `true` : toute la vallée (villages, pêcheurs, flotte, lacs et leur poisson, patrouilles, `climate.event_rate`) est tirée de la seule graine ; les clés ci-dessus et `lake.lakes` sont alors ignorées. |
| `population.rule_fraction` | float | `0.25` | part | Part des pêcheurs qui suivent les règles de leur archétype au lieu d'un modèle de langage. `1.0` : partie sans modèle (témoin). Recalculée quand `custom` est donné. |
| `population.elder` | bool | `true` | | Présence de l'ancien, arbitre sans pouvoir qui tient les comptes et ouvre la veillée ; il ne pêche pas. |
| `population.elder_kind` | str | `llm` | `llm`, `rule` | L'ancien raisonne avec un modèle de langage ou suit des règles fixes. |
| `population.large_model_min_experience` | int | `15` | années | Années d'expérience à partir desquelles un pêcheur raisonne avec le grand modèle (`llm.tiers.grand`) plutôt qu'avec le petit. |
| `population.custom` | list | absent | fiches | Composition choisie à la main dans le menu. Chaque fiche : `first_name`, `hamlet`, `archetype`, `experience`, `wealth`, `debt_payment`, `kind` (`llm` ou `rule`), `tier` (`auto`, `grand`, `petit`). Remplace la génération ; vérifiée par `profiles.validate_custom`. |

### 1.3 `lake` : les lacs

| Clé | Type | Défaut | Valeurs | Signification |
|---|---|---|---|---|
| `lake.capacity` | float ou `auto` | `auto` | t | Capacité totale (stock maximal). `auto` = `capacity_per_fisher` × nombre de pêcheurs, pour garder le même stock par tête quand on change d'échelle. |
| `lake.capacity_per_fisher` | float | `12.5` | t par pêcheur | Base du calcul `auto`. |
| `lake.initial_ratio` | float | `1.0` | part | Stock au départ, en part de la capacité. |
| `lake.growth_rate` | float | `1.0` | r | Taux de repeuplement de la croissance logistique, appliquée une fois par saison. Le rendement durable maximal vaut r·K/4. |
| `lake.count` | int | `1` | 1 à 4 | Nombre de lacs ; les villages se partagent en blocs qui se suivent, un bloc par lac. |
| `lake.lakes` | list | `null` | fiches | Lacs décrits un à un : `name`, `capacity` (t, ou `auto` avec `richness`, multiplicateur de `capacity_per_fisher`), `stock_ratio` (part pleine au départ), `growth_rate`, `villages`. Remplace `count`. |
| `lake.collapse_ratio` | float | `0.05` | part | Sous ce ratio stock / capacité, un lac est déclaré effondré. |
| `lake.observation_noise` | float | `0.10` | part | Erreur relative de l'estimation du stock par un pêcheur. |
| `lake.capacity_resolved` | float | calculée | t | Clé dérivée (ne pas la donner) : la capacité totale retenue après `normalize`. |

### 1.4 `economy` : argent, bateaux, sorties

| Clé | Type | Défaut | Valeurs | Signification |
|---|---|---|---|---|
| `economy.price_per_tonne` | float | `100` | écus par t | Prix de vente du poisson. |
| `economy.upkeep_per_season` | float | `100` | écus par saison | Coût de la vie d'une famille, hors bateau. |
| `economy.boats.<taille>.capacity` | float | barque `4.0`, chaloupe `7.0`, cotre `11.0` | t par saison | Prise maximale d'un bateau sur la saison (sa cale). |
| `economy.boats.<taille>.upkeep` | float | barque `20`, chaloupe `50`, cotre `110` | écus par saison | Entretien du bateau, en plus de la vie. |
| `economy.min_catch` | float | `1` | t | Prise minimale visée d'une sortie : on ne part pas pour rien. |
| `economy.hold_fraction` | float | `0.5` | 0,05 à 1 | Part du poisson d'un lac que l'ensemble de ses bateaux peut prendre, partagée en proportion de leur cale. Un lac qui se vide laisse donc de moins en moins prendre. |
| `economy.travel_days` | float | `1.5` | 0 à 10 jours simulés | Jours de route, à l'aller, pour traverser toute la carte et pêcher dans un autre lac que le sien. Une sortie dure alors 1 + 2 × route jours, et la prise s'en ressent. |
| `economy.travel_cost` | float | `10` | 0 à 1000 écus par jour de mer | Coût de la route, à chaque sortie vers un autre lac. |
| `economy.outings` | int | `6` | ≥ 1 | Nombre de sorties qu'un agent à règles prévoit par défaut (le pêcheur décide lui-même combien il en fait). Sert aussi à calculer la cale d'une sortie (`boat_cap × 1,5 / outings × heures / 7`) et la marge de mesure par sortie. |
| `economy.luck` | float | `0.4` | écart-type | Chance : la prise de chaque sortie varie de ± `luck` autour de 1 (moitié forme de la saison, moitié forme du jour). `0` : seul le temps compte. |
| `economy.luck_streak` | float | `0.5` | part | Suite de la chance d'un jour à l'autre : un bon jour en annonce un autre. |

### 1.5 `scenario` : communication, conseil, contrôle

| Clé | Type | Défaut | Valeurs | Signification |
|---|---|---|---|---|
| `scenario.communication` | str | `valley` | `valley`, `hamlet`, `none` | Où l'on parle : au conseil de toute la vallée, à une veillée par village, ou nulle part (aucune règle ne peut alors être adoptée). |
| `scenario.council` | str | `delegates` | `delegates`, `all` | Au conseil de la vallée, un élu par village (choisi à chaque saison selon la confiance) ou tous les pêcheurs. |
| `scenario.catches_visible` | bool | `true` | | Les prises déclarées à l'ancien sont connues de toute la vallée (sinon du seul village). |
| `scenario.detection.patrol` | float | `0.9` | part | Chance que la patrouille repère une barque qu'elle croise. |
| `scenario.detection.patrol_error` | float | `0.12` | part | Erreur relative de la patrouille sur la charge mesurée. |
| `scenario.detection.witness` | float | `0.4` | part | Chance qu'un voisin pêchant dans la même zone voie une barque rentrer. |
| `scenario.detection.witness_error` | float | `0.3` | part | Erreur relative du témoin sur la charge estimée. |
| `scenario.detection.seen_leaving` | float | `0.3` | part | Chance que le village voie partir à l'aube la barque d'un pêcheur exclu de la pêche. |
| `scenario.detection.lifestyle` | float | `0.5` | part | Chance qu'un voisin remarque un train de vie trop large pour ce que le pêcheur déclare. |
| `scenario.detection.lake_error` | float | `0.03` | part de la capacité | Précision des comptes du lac tenus par l'ancien. |
| `scenario.detection.margin_t` | float | `0.3` | t | Écart minimal entre charge estimée et déclaration pour parler de mensonge. |
| `scenario.detection.margin_ratio` | float | `0.25` | part | Écart relatif minimal, en plus de `margin_t`. |
| `scenario.detection.proof` | float | `2.0` | poids | Poids d'indices à réunir pour que l'ancien établisse un mensonge (patrouille 3, témoin 1, départ vu 1, train de vie 0,5, comptes 0,5). |
| `scenario.patrol.enabled` | bool | `true` | | La patrouille fait partie de la partie (`false` : ni vote, ni capitaine, ni coût). |
| `scenario.patrol.count` | int | `1` | 0 à 4 | Nombre de patrouilles, chacune avec son capitaine et sa route. |
| `scenario.patrol.cost` | float | `15` | écus par pêcheur, par patrouille et par saison | Ce que chaque pêcheur paie quand une patrouille est en service. |
| `scenario.patrol.legs` | int | `3` | étapes par saison | Nombre d'étapes de la route (une zone du lac ou les talons d'un pêcheur). |
| `scenario.patrol.days` | float | `14` | jours simulés par saison | Jours de mer de la patrouille sur la saison. |
| `scenario.patrol.from_season` | int ou null | `null` | numéro de saison | Patrouille installée d'office dès cette saison, sans vote (pour comparer des parties) ; `null` : c'est au conseil de la voter. |
| `scenario.assembly_rounds` | int | `2` | ≥ 1 | Tours de parole par veillée. |
| `scenario.quiet_listeners` | bool | `true` | | À partir du 2e tour, seul reprend la parole celui qui a une raison de le faire (on lui parle, on le nomme, on conteste sa proposition) ; les autres donnent leur position au vote. |
| `scenario.proposal_merge_tolerance` | float | `0.75` | t | Deux quotas proposés à moins de cet écart sont une seule proposition. (Pour les autres types de règle, l'écart est fixé dans `filets/rules.py`, `VALUE_TOLERANCE`.) |
| `scenario.vote_tolerance` | float | `1.5` | t | Au vote de clôture, chacun vote pour la proposition la plus proche de ce qu'il a dit, à cet écart près. |
| `scenario.promise_tolerance` | float | `0.5` | t | Dépassement toléré au-dessus d'une promesse avant de la dire rompue. |
| `scenario.quota_tolerance` | float | `0.05` | t | Arrondi toléré au-dessus d'un quota adopté (un arrondi, pas une marge). |
| `scenario.scheduled_injections` | list | `[]` | fiches | Événements programmés, identiques pour toutes les configurations comparées. Fiche : `season`, `type` (`drought`, `announcement`, `set_communication`, `set_visibility`), plus `factor` (part du stock gardée, pour `drought`), `text` (pour `announcement`) ou `value`. |

### 1.6 `climate` : saisons de l'année et événements

| Clé | Type | Défaut | Valeurs | Signification |
|---|---|---|---|---|
| `climate.enabled` | bool | `true` | | Chaque saison de jeu est une saison de l'année (printemps, été, automne, hiver) qui change la pêche et le repeuplement. |
| `climate.event_rate` | float | `0.3` | part par saison | Probabilité d'un événement aléatoire, à partir de la 2e saison. Tirée de la graine si `population.random`. |
| `climate.disabled_events` | list | `[]` | `secheresse`, `tempete`, `banc`, `algues`, `crue`, `maladie` | Événements exclus du tirage. |

### 1.7 `time` : le temps simulé et son affichage

| Clé | Type | Défaut | Valeurs | Signification |
|---|---|---|---|---|
| `time.season_days` | float | `30` | jours simulés | Durée d'une saison. |
| `time.fishing_open_day` | float | `0.25` | jour simulé | Ouverture de la pêche (J0 06:00). |
| `time.fishing_close_day` | float | `20.0` | jour simulé | Aucune sortie ne commence au-delà ; une sortie commencée avant rentre normalement (sans dépasser `assembly_day`). |
| `time.assembly_day` | float | `25.75` | jour simulé | Ouverture de la veillée chez l'ancien (J25 18:00). |
| `time.assembly_close_day` | float | `29.0` | jour simulé | Clôture de la veillée. |
| `time.regrowth_day` | float | `29.9` | jour simulé | Repeuplement des lacs et bilan de la saison. |
| `time.departure_spread_days` | [float, float] | `[0.0, 4.0]` | jours après l'ouverture, 0 ≤ min ≤ max | Intervalle où se tire le jour de départ de chaque pêcheur ; son plan de saison (et sa première sortie) a ce jour pour horizon. Ancien nom accepté : `async_offset_days`. |
| `time.speech_minutes` | float | `20` | minutes simulées | Durée d'une réplique à la veillée (une seule personne parle à la fois). |
| `time.sim_hours_per_second` | float | `3` | heures simulées par s réelle | Rythme d'affichage à ×1. Ne règle que ce que montre l'interface : la latence d'un modèle n'a aucun effet sur le monde. |
| `time.idle_speedup` | float ou `inf` | `40` | facteur | Accélération de l'horloge d'affichage entre deux échéances ; `inf` = saut direct. |
| `time.fast` | bool | `false` | | Aucune attente d'affichage (parties répétées, tests). |

Les clés `time.mode`, `time.wait_for_ai`, `time.ballot_lead_days` et `time.assembly_turn_gap_days` n'existent plus : elles
sont acceptées et ignorées, avec un avertissement (il n'y a plus qu'un mode de temps, voir `docs/temps.md`).

### 1.8 `memory` et `rag` : mémoire des agents et recherche de contexte

| Clé | Type | Défaut | Valeurs | Signification |
|---|---|---|---|---|
| `memory.top_k` | int | `6` | souvenirs | Nombre de souvenirs remis à l'agent à chaque décision. |
| `memory.recency_decay_per_day` | float | `0.01` | par jour simulé | Perte de fraîcheur d'un souvenir par jour. |
| `memory.weights.recency` | float | `1.0` | poids | Poids de la fraîcheur dans le score d'un souvenir. |
| `memory.weights.importance` | float | `1.0` | poids | Poids de l'importance. |
| `memory.weights.relevance` | float | `1.5` | poids | Poids de la proximité avec la question du moment. |
| `rag.corpus_dir` | str | `corpus` | dossier | Documents du corpus (savoir de la vallée) cherchés pour le contexte. |
| `rag.top_k` | int | `3` | passages | Nombre de passages du corpus remis à l'agent. |
| `rag.lore_per_agent` | int | `4` | moments | Moments marquants de la partie gardés par agent ; le moins important part d'abord. |
| `rag.backend` | str | `bm25` | `bm25`, `pgvector` | Recherche par mots en mémoire, ou par le sens dans PostgreSQL + pgvector (repli sur BM25 si la base tombe). |
| `rag.min_score` | float | `0.0` | similarité cosinus | pgvector : score minimal d'un passage retenu. |
| `rag.embeddings.kind` | str | `hash` | `hash`, `ollama` | Calcul des vecteurs : hachage sans modèle (tests) ou modèle de plongement d'Ollama. |
| `rag.embeddings.dim` | int | `384` | dimensions | Taille des vecteurs (768 avec `embeddinggemma`). |
| `rag.embeddings.base_url` | str | `http://localhost:11434` | URL | `ollama` : adresse du serveur. |
| `rag.embeddings.model` | str | — | nom de modèle | `ollama` : modèle de plongement (`embeddinggemma` dans `config/data.yaml`). |
| `rag.embeddings.cpu` | bool | `true` | | `ollama` : calculer sur le processeur pour laisser la carte graphique aux modèles de langage. |

### 1.9 `storage` : historique et fichiers

| Clé | Type | Défaut | Valeurs | Signification |
|---|---|---|---|---|
| `storage.history` | str | `sqlite` | `sqlite`, `postgres` | Base de l'historique des parties : le fichier `output.history_db` ou PostgreSQL. |
| `storage.postgres.dsn` | str | `postgresql://filets:filets@127.0.0.1:19432/filets` | adresse | Connexion PostgreSQL ; la variable `FILETS_PG_DSN` l'emporte. |
| `storage.objects.kind` | str | `none` | `none`, `local`, `s3` | Stockage des fichiers bruts (corpus, archives des parties). |
| `storage.objects.endpoint` | str | — | `hôte:port` | `s3` : adresse du service (MinIO local : `127.0.0.1:19000`). |
| `storage.objects.bucket` | str | — | nom | `s3` : compartiment utilisé. |
| `storage.objects.secure` | bool | `false` | | `s3` : HTTPS ou HTTP. |
| `storage.objects.access_key`, `secret_key` | str | — | identifiants | `s3` : identifiants ; `FILETS_S3_ACCESS_KEY` et `FILETS_S3_SECRET_KEY` les remplacent hors du conteneur local. |
| `output.runs_dir` | str | `runs` | dossier | Un dossier par partie : journal des événements, résumé. |
| `output.history_db` | str | `data/history.db` | fichier | Base SQLite de l'historique. |

### 1.10 `llm` : les modèles de langage

| Clé | Type | Défaut | Valeurs | Signification |
|---|---|---|---|---|
| `llm.temperature` | float | `0.7` | ≥ 0 | Part de hasard dans les réponses des modèles. |
| `llm.max_tokens` | int | `350` | tokens | Longueur maximale d'une réponse. |
| `llm.reflection` | str | `complete` | `complete`, `rapide`, `adaptive` | Profil de réflexion : réponses libres et contexte complet (référence des expériences) ; une phrase courte par champ, environ deux fois plus rapide ; ou système 1 (réflexe chiffré, petit modèle) pour les prises de routine et système 2 sinon. |
| `llm.timeout_s` | float | `45` | s réelles | Délai d'attente d'une réponse, sauf réglage du fournisseur. |
| `llm.max_retries` | int | `3` | essais | Nouvelles tentatives après une réponse absente ou illisible. |
| `llm.json_mode` | bool | `true` | | Demander une réponse JSON. |
| `llm.tiers.<niveau>.provider` | str | `scripted` | nom d'un `llm.providers` | Fournisseur du niveau `grand`, `petit` ou `reflexe` (ce dernier seulement avec `ollama_open`). |
| `llm.tiers.<niveau>.model` | str | `scripted-grand`, `scripted-petit` | nom de modèle | Modèle appelé pour ce niveau (`qwen2.5:7b`, `tev1:0.8b`…). |
| `llm.providers.scripted.latency_s` | dict | `{grand: [1.0, 4.0], petit: [0.3, 1.2]}` | s réelles | Faux modèle : délai de réponse tiré dans l'intervalle, par niveau. |
| `llm.providers.scripted.latency_scale` | float | `1.0` | facteur | Faux modèle : multiplicateur des délais. |
| `llm.providers.scripted.incident_rates` | dict | `{out_of_role: 0.03, unparseable: 0.03, no_response: 0.02}` | part | Faux modèle : fréquence des incidents simulés (réponse hors rôle, illisible, absente). |
| `llm.providers.<nom>.base_url` | str | selon le fournisseur | URL | Adresse de l'API compatible OpenAI (Ollama, Groq, OpenRouter, Gemini, Mistral, GitHub). |
| `llm.providers.<nom>.api_key_env` | str ou null | `GROQ_API_KEY`… | nom de variable | Variable d'environnement qui porte la clé d'API ; `null` pour Ollama. |
| `llm.providers.<nom>.rpm` | int | `0` à `30` | requêtes par minute | Débit maximal ; `0` = sans limite. |
| `llm.providers.<nom>.timeout_s` | float | Ollama `240` | s réelles | Délai propre au fournisseur (un modèle local froid met du temps à se charger). |
| `llm.providers.<nom>.max_concurrency` | int | Ollama `4` | requêtes | Requêtes envoyées en même temps ; les autres attendent côté moteur (`ModelGate`). |
| `llm.providers.<nom>.json_schema` | bool | Ollama `true` | | Le serveur contraint la réponse au schéma demandé. |
| `llm.providers.<nom>.seed` | bool | Ollama `true` | | Envoyer une graine stable par partie, agent, saison et tour : même invite, même réponse. |
| `llm.providers.<nom>.local` | bool | Ollama `true` | | Fournisseur local : ses requêtes passent par la file `ModelGate`, qui les regroupe par modèle. |
| `llm.providers.ollama_s1.kind` | str | `systemone` | `systemone` | Client des modèles de décision « système 1 » (`POST /v1/systemone`, Ollama 0.40.4 ou plus). |

### 1.11 `bus` : le transport des événements

| Clé | Type | Défaut | Valeurs | Signification |
|---|---|---|---|---|
| `bus.kind` | str | `local` | `local`, `kafka` | Bus en mémoire dans le moteur, ou Kafka avec les services `bridge`, `indicators` et `store`. |
| `bus.bootstrap` | str | `127.0.0.1:19092` | `hôte:port` | Adresse du courtier Kafka (port 19092 pour ne pas gêner un autre projet sur 9092). |
| `bus.topics.events` | str | `filets.events` | topic | Tous les événements de la partie. |
| `bus.topics.indicators` | str | `filets.indicators` | topic | Indicateurs calculés (stock, Gini, part durable…). |
| `bus.topics.commands` | str | `filets.commands` | topic | Ordres du joueur et du menu vers le moteur. |
| `bus.topics.deadletter` | str | `filets.deadletter` | topic | Messages refusés par la validation. |
| `bus.topics.status` | str | `filets.status` | topic | État du moteur (salon, en cours, pause, vitesse), conservé une heure. |

### 1.12 Les préréglages (`config/*.yaml`)

| Fichier | Hérite de | Ce qu'il change |
|---|---|---|
| `baseline.yaml` | `default` | `population.rule_fraction: 1.0`, `elder_kind: rule` : partie témoin sans modèle de langage. |
| `data.yaml` | `default` | `rag.backend: pgvector` avec `embeddinggemma` (768 dimensions, sur processeur), `storage.history: postgres`, `storage.objects` en S3 (MinIO local). |
| `demo.yaml` | `lakes` | 3 saisons, graine 7, une annonce programmée à la saison 2 (la partie de la vidéo de démonstration). |
| `drought.yaml` | `default` | Une sécheresse à la saison 4 (`factor: 0.5`). |
| `groq.yaml` | `default` | Grand modèle `llama-3.3-70b-versatile` chez Groq, petit modèle `qwen2.5:1.5b` sur Ollama. |
| `hamlet.yaml` | `default` | `scenario.communication: hamlet` : une veillée par village. |
| `lakes.yaml` | `default` | 6 villages, 16 pêcheurs, 3 lacs, 2 patrouilles. |
| `large.yaml` | `default` | 4 villages, 18 pêcheurs (le lac garde 12,5 t par tête). |
| `no_comm.yaml` | `default` | `scenario.communication: none` : aucune veillée. |
| `ollama.yaml` | `default` | Ollama, `qwen2.5:7b` et `qwen2.5:1.5b` (qualité). |
| `ollama_fast.yaml` | `default` | Ollama, `qwen2.5:3b` et `qwen2.5:1.5b`, `llm.reflection: rapide`. |
| `ollama_open.yaml` | `ollama_fast` | `llm.reflection: adaptive` et un niveau `reflexe` : `tev1:0.8b` via `ollama_s1`. |
| `random.yaml` | `default` | `population.random: true` : la vallée vient de la graine seule. |

## 2. Variables d'environnement et ligne de commande

### 2.1 Variables d'environnement

| Variable | Lue par | Signification |
|---|---|---|
| `FILETS_PG_DSN` | `filets/vectors.py` (`postgres_dsn`) | Adresse PostgreSQL ; l'emporte sur `storage.postgres.dsn`. |
| `FILETS_S3_ACCESS_KEY`, `FILETS_S3_SECRET_KEY` | `filets/objects.py` | Identifiants du stockage S3 ; l'emportent sur `storage.objects.access_key` et `secret_key`. |
| `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `GITHUB_TOKEN` | `filets/llm.py`, d'après `llm.providers.<nom>.api_key_env` | Clé d'API du fournisseur ; le moteur refuse de démarrer si le fournisseur choisi n'a pas sa clé. |
| `GODOT_PATH` | `start.ps1` | Chemin de l'exécutable Godot (sinon le fichier `godot.path`, sinon le `PATH`). |

### 2.2 `python -m filets` : sous-commandes et options

Options communes à `serve` et `run` : `--config` (fichier YAML, défaut `config/default.yaml`), `--set clé=valeur`
(répétable, surcharge une clé), `--bus local|kafka` (= `bus.kind`).

| Sous-commande | Option | Défaut | Signification |
|---|---|---|---|
| `serve` | | | Ouvre le salon : la partie se lance depuis le menu de Godot. |
| | `--agents N` | | Nombre de pêcheurs de la composition proposée par le menu (= `population.fishers`). |
| | `--villages N` | | Nombre de villages proposé (= `population.villages`). |
| | `--seasons N` | | Nombre de saisons proposé (= `run.seasons`). |
| | `--seed N` | | Graine (= `run.seed`). |
| | `--mode sync\|async` | | Ancienne option : elle écrit `time.mode`, qui est ignorée. |
| | `--fast` | | `time.fast: true`. |
| | `--llm ID` | `scripted` | Moteur d'IA présélectionné dans le menu : `scripted`, `ollama_fast`, `ollama_open`, `ollama`, `groq`. |
| | `--no-ws` | | Ne pas ouvrir le pont WebSocket (avec Kafka, c'est le service `bridge` qui l'ouvre). |
| | `--ws-port N` | `8765` | Port du pont WebSocket et de l'API. |
| `run` | | | Lance une partie tout de suite, sans menu. Mêmes `--agents`, `--villages`, `--seasons`, `--seed`, `--mode`, `--fast`, `--ws-port`. |
| | `--ws` | | Ouvrir le pont WebSocket pour suivre la partie dans Godot. |
| | `--no-linger` | | Avec `--ws` : quitter à la fin au lieu de laisser la scène consultable. |
| | `--run-id ID` | généré | Nom du dossier de la partie dans `runs/`. |
| `replay RUN_ID` | `--speed F` | `1.0` | Rejoue une partie enregistrée ; `0` = sans attente. Aussi `--ws`, `--ws-port`, `--no-linger`. |
| `verify RUN_ID` | | | Vérifie le journal d'une partie : événements conformes aux schémas, numéros de séquence en ordre, temps simulé qui ne recule jamais, violations temporelles relevées par les indicateurs. |
| `batch` | `--config` (répétable), `--runs N` | `5` | Joue `N` parties par configuration, sans attente d'affichage, et range chacune dans l'historique SQLite. Aussi `--set`, `--agents`, `--mode`, `--seasons`, `--db` (défaut `data/history.db`). |
| `ingest [RUN_ID…]` | `--db`, `--pg [DSN]` | `data/history.db` | Range des parties passées dans l'historique SQLite, ou dans PostgreSQL avec `--pg` (sans adresse : `FILETS_PG_DSN` ou la configuration). |
| `schemas` | | | Écrit les schémas JSON (enveloppe, commandes, état, chaque type d'événement) dans `schemas/*.v1.json`. |
| `query [FICHIER.sql]` | `--db`, `--pg [DSN]` | `analysis/queries.sql` | Exécute les requêtes d'un fichier sur l'historique (pour PostgreSQL : `analysis/queries_pg.sql`). |
| `retrieval RUN_ID` | `--sample N` | `20` | Évalue la qualité de la recherche de contexte sur une partie passée. |
| `bench-reflexe RUN_ID` | `--limit N`, `--port N` | `0` (tout), `8765` | Compare le modèle réflexe et le grand modèle sur les invites d'une partie passée ; refuse de tourner si le salon répond sur ce port. |

### 2.3 `start.ps1` (et `start.cmd`)

| Paramètre | Signification |
|---|---|
| `-Light` | Démarrage léger : ni Kafka, ni PostgreSQL, ni Ollama (faux modèle), donc sans Docker. |
| `-Kafka`, `-Ollama`, `-Data` | Remettent une brique avec `-Light` (Kafka et ses services ; Ollama ; PostgreSQL + pgvector et S3). |
| `-OllamaProfile open\|fast\|quality` | Modèles Ollama : 3B + 1,5B + tev1 0,8B (défaut), 3B + 1,5B, ou 7B + 1,5B. |
| `-NoGodot`, `-NoEngine` | Ne lance pas Godot ; ne lance pas le moteur (il tourne déjà : services et Godot se rattachent à la partie en cours). |
| `-Ui` | Avec Kafka : l'interface web Kafka UI sur `http://localhost:8080`. |
| `-Auto` | Lance une partie tout de suite, sans menu (`python -m filets run`). |
| `-Agents`, `-Villages`, `-Seasons`, `-Mode` | Composition et durée proposées par le menu (mêmes sens que les options de `serve`). |
| `-Config FICHIER` | Configuration de base. |
| `-GodotPath CHEMIN` | Exécutable Godot. |
| `-Extra …` | Arguments passés tels quels au moteur, par exemple `--set time.sim_hours_per_second=1`. |

## 3. Variables du programme

Chaque classe (ou module de fonctions, dont les « variables » sont les constantes) a son tableau : nom exact, type tel
que le donnent les diagrammes de classes (`X?` = X ou rien), unité, rôle. Un nom qui commence par `_` est interne à sa
classe. Les zones et leur ordre sont ceux de l'affiche `FILETS-classes-A0.pdf`.

### Monde : vallée, lacs, pêcheurs, règles, conseil

#### `World` · `filets/world.py:205`

Le monde d'une partie : il tient la vallée (villages, lacs, pêcheurs, ancien), les règles votées, la confiance, les indices et l'état de la saison, et il applique la physique du jeu.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `boat_names` | `list` | `["barque", "chaloupe", "cotre"]` | Les classes de bateau, de la plus petite cale à la plus grande. C'est une propriété calculée sur `economy.boats`, pas un champ stocké. |
| `cfg` | `dict` | — | La configuration complète de la partie (`default.yaml` plus les réglages du menu). Elle est aussi copiée dans `config.json` du dossier de la partie. |
| `bus` | `any` | — | Le bus de messages (local ou Kafka, selon `bus.kind`). Le monde y publie les événements et l'état du moteur, et y lit les commandes de l'interface. |
| `run_id` | `str` | identifiant de partie | Nom de la partie en cours. Il sert de nom au dossier `runs/<run_id>` et marque chaque événement. |
| `engine_id` | `str` | texte, `run` par défaut | Identifie le processus moteur dans les messages d'état. |
| `lobby` | `bool` | `True` / `False` | Vrai si un salon (`serve`) peut lancer la partie suivante. Il est repris tel quel dans l'état envoyé à l'interface. |
| `advised_speed` | `float?` | vitesse ×, ou `None` | Vitesse de jeu conseillée avec le moteur d'IA choisi. `None` avec l'IA factice (`scripted`). Envoyée à l'interface dans l'état. |
| `ended` | `bool` | `True` / `False` | Passe à vrai à la toute fin de la partie, une fois l'état `ended` publié. |
| `T` | `any` | dict | La section `time` de la configuration : `season_days`, `fishing_open_day`, `fishing_close_day`, `assembly_day`, `speech_minutes`… (jours simulés). |
| `clock` | `SimClock` | — | L'horloge simulée de la partie (temps en jours depuis le début, pause, vitesse). |
| `ctl` | `GameControl` | — | Le pilotage de la partie : pause, vitesse, arrêt. Son `on_change` est branché sur `publish_status`. |
| `run_dir` | `any` | chemin | Dossier de la partie : `output.runs_dir` / `run_id`. On y écrit `config.json`, le journal des événements et `summary.json`. |
| `recorder` | `Recorder` | — | Écrit les événements dans le journal du dossier de la partie. Vaut `None` quand la partie n'est pas enregistrée. |
| `events` | `EventFactory` | — | Fabrique et publie les événements (numéro, temps simulé, texte du moment) sur le bus et dans le journal. |
| `capacity` | `any` | tonnes | Capacité totale de tous les lacs réunis (somme des capacités). Au départ elle vient de `lake.capacity_resolved`, puis elle est recalculée une fois les lacs créés. |
| `econ` | `any` | dict | La section `economy` de la configuration : prix de la tonne, entretien, bateaux, sorties, chance, voyage. |
| `scn` | `dict` | — | Copie de la section `scenario` de la configuration. Les commandes du joueur peuvent la modifier en cours de partie. |
| `comm` | `any` | `valley`, `hamlet`, `none` | Mode de veillée : un conseil de la vallée, une veillée par village, ou aucune. Initialisé par `scenario.communication`, changeable en cours de partie. |
| `visible` | `bool` | `True` / `False` | Les déclarations de prise sont-elles connues de toute la vallée (`scenario.catches_visible`) ? Sinon elles ne le sont que dans le village du pêcheur. |
| `objects` | `object` | magasin d'objets ou `None` | Le stockage des fichiers bruts et des archives de partie (`storage.objects` : local ou s3). Vaut `None` si le type est `none`. |
| `vectors` | `None` | `None` ou base de vecteurs | La base PostgreSQL + pgvector, créée seulement si `rag.backend` vaut `pgvector`. Reste `None` sinon (recherche par mots, BM25). |
| `memory_bank` | `None` | `None` ou banque de souvenirs | Stockage des souvenirs des agents dans pgvector. Reste `None` avec le backend BM25, où chaque agent garde ses souvenirs en mémoire. |
| `agents` | `dict` | `{id d'agent: Agent}` | Tous les personnages : les pêcheurs (`F01`, `F02`…) et l'ancien (`ANC`). Les capitaines de patrouille n'y sont pas, ils sont dans `patrol_agents`. |
| `fishers` | `list` | liste d'`Agent` | Les pêcheurs seulement (ceux dont le rôle est `pecheur`), dans l'ordre de leur création. |
| `elder` | `any` | `Agent` ou `None` | L'ancien, arbitre sans pouvoir, qui ne pêche pas. `None` si `population.elder` est faux. |
| `hamlets` | `list` | noms de villages | Les villages de la vallée, dans l'ordre de leur apparition chez les pêcheurs. |
| `lakes` | `dict` | `{nom du lac: Lake}` | Les lacs de la vallée. Il y en a un seul par défaut (`lake.count`). |
| `lake_of_hamlet` | `dict` | `{village: nom du lac}` | Le lac où pêchent les gens de chaque village. |
| `world_size` | `float` | largeurs de carte | Taille de la vallée. Elle grandit avec le nombre de villages et de lacs (entre 1,5 et 2,6). |
| `grid` | `int` | parcelles par côté | Nombre de parcelles de la maille des lacs sur un côté de la vallée (30 à la taille 1). |
| `village_xy` | `dict` | `{village: (x, y)}` entre 0 et 1 | Position de chaque village sur le sol de la vallée, en coordonnées normalisées. |
| `sectors` | `dict` | `{nom du lac: {village: [indices de parcelles]}}` | La rive de chaque village : les parcelles de son lac qui lui sont plus proches que de tout autre village du même lac. |
| `lake` | `any` | `Lake` | Le premier lac. C'est le seul dans une vallée de base, et le lac par défaut quand aucun n'est précisé. |
| `multi` | `any` | `True` / `False` | Vrai s'il y a plus d'un lac. Dans ce cas, les événements portent aussi le nom du lac. |
| `lake_fishers` | `dict` | `{nom du lac: nombre}` | Combien de pêcheurs ont leur village sur chaque lac. |
| `collapsed` | `set` | noms de lacs | Les lacs déjà signalés comme effondrés (stock sous `lake.collapse_ratio` de la capacité). Sert à ne signaler chaque effondrement qu'une fois. |
| `season_stock` | `dict` | `{nom du lac: tonnes}` | Le poisson de chaque lac à l'ouverture de la saison. Le même pour tous les pêcheurs, il fixe ce que la cale permet de prendre. |
| `zones` | `list` | noms de zones | Les zones de pêche : une rive par village, plus le large de chaque lac (`large`, ou `large-<lac>` s'il y a plusieurs lacs). |
| `delegates` | `any` | `True` / `False` | Vrai si le conseil est composé d'élus, un par village (`scenario.council` vaut `delegates`). Faux : tous les pêcheurs y siègent. |
| `reps` | `dict` | `{village: id du pêcheur élu}` | L'élu de chaque village au conseil de la vallée. Les pêcheurs le choisissent à chaque saison. |
| `last_council` | `Assembly?` | `Assembly` ou `None` | Le dernier conseil de la vallée. Les villageois absents en apprennent les décisions grâce à lui. |
| `boats` | `any` | `{classe: {capacity, upkeep}}` | Les bateaux de la configuration (`economy.boats`). `capacity` en tonnes par saison, `upkeep` en écus par saison. |
| `boat_cap` | `dict` | `{id de pêcheur: tonnes}` | La cale du bateau de chaque pêcheur : sa prise maximale par saison. |
| `lake_boats` | `dict` | `{nom du lac: tonnes}` | Somme des cales des bateaux de chaque lac. Elle sert à partager le poisson du lac entre les bateaux. |
| `hold_fraction` | `float` | part de 0 à 1 | Part du stock d'un lac que tous les bateaux ensemble peuvent prendre (`economy.hold_fraction`, 0,5 par défaut). |
| `travel_days` | `float` | jours | Jours de route pour traverser toute la carte, à l'aller (`economy.travel_days`, 1,5). |
| `travel_price` | `float` | écus par jour de mer | Coût de la route pour pêcher dans un autre lac (`economy.travel_cost`, 10). |
| `hold` | `dict` | `{id de pêcheur: tonnes}` | Ce que chaque pêcheur pourrait rapporter au mieux, lac plein : le minimum entre sa cale et sa part du lac. Sert à fixer `max_catch` et `min_catch`. |
| `boat_max` | `any` | tonnes | La plus grosse cale qui existe parmi les bateaux. Une promesse de prise ou une valeur proposée ne peut pas la dépasser. |
| `max_catch` | `any` | tonnes | La plus grosse valeur de `hold` : borne haute d'un quota proposé ou d'une promesse. |
| `min_catch` | `any` | tonnes | La prise minimale visée d'une sortie (`economy.min_catch`, 1), ramenée à la plus petite valeur de `hold` si elle est plus basse. Borne basse d'un quota proposé. |
| `router` | `LLMRouter` | — | Envoie les demandes aux modèles d'IA (grand, petit, narrateur) et compte leur usage. |
| `norms` | `list` | liste de `Norm` | Toutes les règles adoptées par le conseil, dans l'ordre d'adoption. On ne les supprime jamais. |
| `promises` | `dict` | `{(id de pêcheur, saison): (tonnes, id de l'événement de promesse)}` | Les promesses de prise faites à la veillée, rangées par la saison où elles s'appliquent (la suivante). |
| `promise_memories` | `dict` | `{(id de pêcheur, saison): souvenir}` | Le souvenir épinglé de chaque promesse en cours. Une nouvelle promesse pour la même saison le désépingle. |
| `reports` | `dict` | `{(id de pêcheur, saison): événement report}` | Le total que chaque pêcheur a déclaré de sa saison, bâti au bilan (somme de ses déclarations par sortie). Les autres le lisent (`known_catch`) une fois sa saison de pêche finie. Chaque sortie a aussi son propre événement `report`. |
| `lies` | `dict` | `{id de l'événement report: {agent, season, declared, landed, found_t, report_event_id, day}}` | Le livre des mensonges, sortie par sortie : une déclaration inférieure à la vraie prise d'au moins `MIN_LIE_T` (0,05 t) ; `day` est le jour de la sortie. `found_t` est prévu pour l'instant de la découverte, mais il reste à `None` : aucun code ne le renseigne. |
| `trust` | `dict` | `{id de l'observateur: {id d'un pêcheur: confiance 0 à 1}}` | La confiance de chaque agent envers chaque pêcheur, de 0 (aucune) à 1 (totale), 0,5 au départ. Chacun la révise lui-même à la veillée. |
| `detection` | `dict` | probabilités, erreurs, seuils | Les réglages de détection : les valeurs de `DETECTION` complétées par `scenario.detection` (probabilité de repérage, erreur d'estimation, marges, `proof`). |
| `live` | `dict` | `{id de pêcheur: Trip}` | La pêche en cours de chaque pêcheur, de son plan à son dernier retour (retirée par `finish_trip`). |
| `trips` | `dict` | `{saison: [pêche, …]}` | Les pêches closes de chaque saison. Chaque pêche est un dict `{agent, zone, landed, secret, patrol, patrol_by, event_id, breach, said, outs}` ; `landed` est la vraie prise de la saison en tonnes et `outs` la liste de ses sorties `{id, day, t, zone, landed, said, report_id}`. |
| `clues` | `list` | liste de dicts | Les indices recueillis sur les pêcheurs : le contenu de l'événement `clue` (nature, observateur, pêcheur visé, zone, estimation, public ou non) plus `season`, `t` et `event_id`. |
| `audits` | `dict` | `{saison: {drop, declared, gap, significant, t}}` | Les comptes du lac faits par l'ancien : baisse mesurée du poisson, total déclaré, écart, et si cet écart est jugé significatif. |
| `accusations` | `dict` | `{saison: [(instant, id de l'accusé, id de l'accusateur)]}` | Qui a accusé qui à la veillée, saison par saison. |
| `established` | `dict` | `{(id de pêcheur, saison): {value, t, how, secret, breach}}` | Ce que l'ancien tient pour établi : une triche prouvée. `value` est la prise estimée par les indices (pas la vérité), `how` le moyen de preuve. |
| `lie_rng` | `Random` | — | Générateur de hasard réservé à la détection (graine + 7), pour ne pas déplacer les autres tirages. |
| `_investigated_season` | `int` | numéro de saison | Dernière saison dont les indices ont déjà été recueillis, pour ne le faire qu'une fois par saison. |
| `_weighed_season` | `int` | numéro de saison | Dernière saison dont l'ancien a déjà pesé les preuves, pour ne le faire qu'une fois par saison. |
| `banned` | `dict` | `{id de pêcheur: saison}` | Les pêcheurs interdits de pêche par vote, avec la saison où l'interdiction a pris effet. |
| `patrol` | `dict?` | `{since, proposal_id, until?}` ou `None` | La patrouille du lac, si elle est installée : première saison, proposition qui l'a installée, et dernière saison si le conseil l'a retirée. |
| `patrol_cfg` | `dict` | `cost`, `legs`, `days`, `enabled`, `count`, `from_season` | Réglages de la patrouille : `PATROL` complété par `scenario.patrol`. |
| `patrol_count` | `any` | nombre | Nombre de patrouilles, limité au nombre de capitaines (`PATROL_CAPTAINS`, 4). Chacune a son capitaine et sa route. |
| `patrol_on` | `bool` | `True` / `False` | La patrouille fait-elle partie de cette partie ? Vrai si `scenario.patrol.enabled` est vrai et qu'il y a au moins une patrouille. |
| `patrol_legs` | `dict` | `{saison: [étape, …]}` | La route de la patrouille chaque saison. Chaque étape est `{zone, from_day, to_day, by, follow?}` (jours depuis le début de la saison, `by` : le capitaine). |
| `patrol_log` | `dict` | `{saison: [phrase, …]}` | Ce que la patrouille a relevé chaque saison, en phrases. Le capitaine les relit avant de choisir sa route suivante. |
| `patrol_agents` | `list` | liste d'`Agent` | Les capitaines de patrouille, un par patrouille. Ce sont des agents à part entière (IA ou règles) qui ne pêchent pas, ne siègent pas et ne votent pas. |
| `patrol_agent` | `Agent?` | `Agent` ou `None` | Le premier capitaine (identifiant `PAT`). `None` s'il n'y a pas de patrouille. |
| `climate` | `Climate` | — | Le climat : saison de l'année et événements en cours. |
| `conditions` | `any` | dict | Les conditions de la saison en cours (saison de l'année, facteurs `growth` et `yield`, événements, météo des jours). Remis à jour à chaque début de saison. |
| `season` | `int` | numéro de saison, 0 avant le début | La saison en cours. |
| `stop_requested` | `bool` | `True` / `False` | Un arrêt de la partie a été demandé (par le joueur, par un effondrement ou par une extinction). |
| `stopped_reason` | `str` | `completed`, `stop`, `collapse`, `extinction` | Pourquoi la partie s'est arrêtée. `completed` tant qu'aucune autre raison n'est posée. |
| `_pid` | `counter` | compteur à partir de 1 | Compteur des numéros de proposition de règle (`P1`, `P2`…). |
| `_xid` | `counter` | compteur à partir de 1 | Compteur des numéros de motion d'exclusion, de réautorisation ou de patrouille (`X1`, `X2`…). |
| `collapse_flagged` | `bool` | `True` / `False` | Vrai quand tous les lacs se sont effondrés et que c'est déjà signalé. Si `run.stop_on_collapse` est vrai, la partie s'arrête alors. |
| `obs_rng` | `Random` | — | Générateur de hasard (graine + 99) qui bruite l'estimation du lac pour l'ancien. Les pêcheurs utilisent leur propre générateur. |
| `assemblies` | `list` | liste d'`Assembly` | Les veillées de la saison en cours. Une seule pour le conseil de la vallée, une par village sinon, aucune si `comm` vaut `none`. |
| `rumors` | `list` | `[{text, season, t, event_id}]` | Les annonces faites par le joueur. Tous les agents les connaissent pendant la saison où elles sont faites et la suivante. |
| `thinking` | `list` | identifiants d'agents | Les agents dont une décision est en cours. L'ordonnanceur tient la liste à jour et elle est envoyée dans l'état du moteur. |
| `ai_providers` | `list` | noms de fournisseurs, triés | Les fournisseurs d'IA réellement utilisés par la partie. L'interface s'en sert pour adapter ses conseils. |
| `retriever` | `VectorRetriever` | — | Cherche dans le corpus et les moments marquants de la partie (RAG). Selon `rag.backend`, c'est une recherche par mots en mémoire ou par vecteurs dans pgvector. |

#### `Proposal` · `filets/world.py:111`

Une proposition de règle déposée à la veillée, qui peut être soutenue puis adoptée.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `id` | `str` | `P1`, `P2`… | Numéro de la proposition. |
| `author` | `str` | id d'agent | Celui qui l'a proposée en premier. |
| `quota` | `float` | tonnes, saisons ou nombre selon `kind` | La valeur de la règle : tonnes par pêcheur et par saison pour un quota, durée en saisons pour une réserve ou un repos, nombre de sorties, rang de la taille de bateau. |
| `t` | `float` | jours simulés | Instant du dépôt. |
| `event_id` | `str` | id d'événement | L'événement `proposal` qui l'a enregistrée. |
| `scope` | `str` | `valley`, `hamlet:<village>`, `lake:<lac>` | À qui s'appliquerait la règle. |
| `kind` | `str` | `quota`, `reserve`, `repos`, `sorties`, `bateau` | Le type de règle. |
| `target` | `str?` | zone, nom de lac ou `None` | Pour `reserve`, la zone réservée ; pour `repos`, le lac fermé ; sinon `None`. |
| `key` | `tuple` | `(kind, target)` ou `(kind, target, scope)` | Clé qui décide si deux propositions se rejoignent : même type, même cible et, pour une règle de lac, même portée. C'est une propriété calculée. |

#### `Sanction` · `filets/world.py:128`

Une motion soumise au vote du conseil : exclure un pêcheur, le réautoriser, ou installer ou retirer la patrouille.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `id` | `str` | `X1`, `X2`… | Numéro de la motion. |
| `author` | `str` | id d'agent | Celui qui l'a déposée. |
| `target` | `str` | id de pêcheur, ou chaîne vide | Le pêcheur visé. Vide pour la patrouille, qui ne vise personne. |
| `action` | `str` | `exclure`, `reautoriser`, `patrouille`, `fin_patrouille` | Ce que la motion demande. |
| `t` | `float` | jours simulés | Instant du dépôt. |
| `event_id` | `str` | id d'événement | L'événement `sanction_proposal` qui l'a enregistrée. |
| `votes` | `dict` | `{id du votant: True pour, False contre}` | Les voix déjà données. Le pêcheur visé et les non-pêcheurs ne votent pas. |

#### `Assembly` · `filets/world.py:141`

Une veillée : le conseil de la vallée ou celle d'un village, avec ce qui s'y dit, se propose et se vote.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `scope` | `str` | `valley` ou `hamlet:<village>` | Où se tient la veillée. |
| `participants` | `list` | ids d'agents | Ceux qui siègent : l'ancien, puis les élus (ou tous les pêcheurs). |
| `season` | `int` | numéro de saison | La saison qui vient de se jouer et dont on parle. |
| `close_t` | `float` | jours simulés | Instant de clôture de la veillée (`time.assembly_close_day`). |
| `utterances` | `list` | événements `utterance` | Les répliques dites, dans l'ordre. |
| `proposals` | `dict` | `{id de proposition: Proposal}` | Les propositions de règle sur la table. |
| `support` | `dict` | `{id d'agent: (id de proposition, instant, id d'événement)}` | Le soutien donné par chaque participant, au plus une proposition chacun. |
| `stated` | `dictstrtuple` | `{id d'agent: (type, cible, valeur, portée de lac)}` | Ce que chacun a dit vouloir : sa proposition ou sa promesse de quota. Au vote de clôture, on le rapproche de la proposition la plus proche. |
| `accused` | `list` | `[(instant, id de l'accusé)]` | Qui a été mis en cause pendant la veillée, et quand. |
| `sanctions` | `dict` | `{id de motion: Sanction}` | Les motions soumises au vote. |
| `mode` | `str` | `unique` | Ancien choix synchrone ou asynchrone, qui n'existe plus. Le champ vaut toujours `unique`. |
| `delegates` | `bool` | `True` / `False` | Vrai pour le conseil des élus, faux quand tous les pêcheurs siègent. |
| `closed` | `bool` | `True` / `False` | Vrai une fois la veillée clôturée. |
| `label` | `str` | texte | Le nom de la veillée en mots (« conseil de la vallée », « village de X »). C'est une propriété calculée. |

#### `Trip` · `filets/world.py:164`

La pêche d'un pêcheur pour une saison : son plan, puis chaque sortie qu'il décide l'une après l'autre (ouverte par `World.open_trip`, fermée par `World.finish_trip` à son dernier retour).

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `agent` | `Agent` | — | Le pêcheur. |
| `requested` | `float` | tonnes | La prise de saison visée, celle de son plan. |
| `decision` | `dict` | événement `decision` | La décision d'ouverture (le plan), avec sa charge utile. |
| `horizon` | `float` | jours simulés | Le moment de sa décision : il ne connaît rien de postérieur. |
| `declared` | `float?` | tonnes ou `None` | Ce qu'il comptait déclarer de la saison (intention du plan). `None` : la vérité. Chaque retour a sa propre déclaration (`report`). |
| `home` | `Lake` | — | Le lac de son village. |
| `secret` | `bool` | `True` / `False` | Vrai s'il est interdit de pêche et sort en cachette (il ne déclare rien). |
| `obs` | `dict` | — | Ce qu'il observait du lac à l'ouverture. |
| `view` | `dict` | `norms`, `reserved`, `closed`, `outings`, `boat_limit` | Les règles qui le touchent, relues à chaque sortie : zones réservées, lacs fermés, plafond de sorties, plafond de cale. |
| `ration` | `float` | part de 0 à 1 | Part de la prise visée qui est accordée. Vaut 1 sauf dans les tests. |
| `stock_at_action` | `float?` | tonnes | Le stock du lac sur lequel on calcule sa part (l'instantané d'ouverture de saison, à défaut). |
| `outs` | `list` | `[{day, hours, weather, luck, yield, lake, zone, cell, spot, route, tonnes, back, event_id, said…}]` | Les sorties déjà faites ou en cours, dans l'ordre : début de la pêche, durée, temps, chance, rendement, lac, zone, coin, route, prise, retour et ce qu'il en a déclaré. |
| `got` | `list` | tonnes, une par sortie faite | Ce que chaque sortie a vraiment rapporté, ajouté au fil de la saison. |
| `taken` | `dict` | `{nom du lac: tonnes}` | Ce qu'il a pris dans chaque lac cette saison (pour la part de chaque lac, `trip_left`). |
| `before` | `float?` | tonnes ou `None` | Stock du lac juste avant sa première sortie. |
| `after` | `float?` | tonnes ou `None` | Stock du lac juste après sa dernière sortie. |
| `breach` | `set` | types de règle | Les règles qu'une de ses sorties a enfreintes ; posées au bilan de la saison. |
| `done` | `bool` | `True` / `False` | Vrai quand il ne sortira plus cette saison (« plus cette saison », fermeture, veillée). |

#### `Norm` · `filets/world.py:188`

Une règle adoptée par le conseil.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `scope` | `str` | `valley`, `hamlet:<village>`, `lake:<lac>` | À qui la règle s'applique. |
| `quota` | `float` | tonnes, saisons ou nombre selon `kind` | La valeur de la règle (le nom vient des quotas, mais il sert à tous les types). |
| `effective_season` | `int` | numéro de saison | Première saison d'effet : celle qui suit la veillée. |
| `proposal_id` | `str` | `P1`… | La proposition adoptée. |
| `adopted_t` | `float` | jours simulés | Instant de l'adoption. |
| `event_id` | `str` | id d'événement | L'événement `norm_adopted`. |
| `supporters` | `list` | ids d'agents | Ceux qui l'ont soutenue. |
| `kind` | `str` | `quota`, `reserve`, `repos`, `sorties`, `bateau` | Le type de règle. |
| `target` | `str?` | zone, lac ou `None` | La zone réservée ou le lac au repos. |
| `until` | `int?` | numéro de saison ou `None` | Dernière saison d'effet pour les règles à durée (`reserve`, `repos`). `None` : sans fin. |
| `value` | `float` | comme `quota` | Autre nom de `quota` (propriété). |

#### `Agent` · `filets/agents.py:26`

Un personnage de la vallée (pêcheur, ancien ou capitaine de patrouille) avec son état dans la partie.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `profile` | `Profile` | — | Sa fiche : nom, village, caractère, bateau, type d'agent. |
| `memory` | `MemoryStore` | — | Ses souvenirs, rangés par importance et par ancienneté. |
| `rng` | `random.Random` | — | Son hasard à lui, tiré de la graine de la partie. Il bruite son estimation du lac et sert aux agents à règles. |
| `wealth` | `float` | écus | Sa fortune du moment. Elle monte avec les ventes et baisse avec l'entretien, les dettes et la route. |
| `offset_days` | `float` | jours simulés | Son jour de départ en pêche après l'ouverture, tiré dans `time.departure_spread_days`. |
| `catches` | `dict` | `{saison: tonnes}` | Ce qu'il a vraiment pêché chaque saison. |
| `last_decision` | `dict?` | événement `decision` ou `None` | Sa dernière décision. Elle est écrite à chaque décision, mais aucune lecture n'existe dans le code Python. |
| `stock_seen` | `list` | `[{season, phase, label, t, est, event_id}]` | Ce qu'il a constaté du lac, dans l'ordre : son estimation à chaque ouverture de pêche et chaque veillée. |
| `declared` | `dict` | `{saison: tonnes}` | Ce qu'il a déclaré à l'ancien chaque saison. |
| `outings` | `dict` | `{saison: [{day, weather, luck, yield}]}` | Table des sorties d'un agent à règles qui suit son plan par défaut (`World.outings`) : jour, météo, chance, rendement. Sert aux estimations et à `apply_catch` ; le pêcheur décide les siennes une à une. |
| `plans` | `dict` | `{saison: plan}` | Son plan de chaque saison (`decide_plan`) : prise totale, lieu, nombre de sorties prévu, déclaration prévue, première sortie. Une intention : elle guide ses décisions de sortie sans engager le moteur. |
| `prev` | `dict?` | observation ou `None` | Ce qu'il observait à sa décision de sortie précédente. `routing.outing_reasons` le compare à ce qu'il voit maintenant pour savoir si une raison de réfléchir est nouvelle. |
| `form_season` | `int` | numéro de saison | La saison pour laquelle `form` a été tirée. |
| `form` | `float` | de −2,5 à 2,5 | Sa forme de la saison. Elle se prolonge d'une saison à l'autre (`economy.luck_streak`) et fait sa chance. |
| `temper` | `float` | de 0,85 à 1,15 | Sa sévérité, tirée une fois. Plus de 1, il pardonne moins. |
| `lake_choice` | `dict` | `{saison: nom du lac}` | Le lac où il a pêché chaque saison, le sien ou un autre. |
| `spot` | `int?` | indice de parcelle ou `None` | Son coin de pêche habituel sur sa rive. |
| `spots` | `dict` | `{indice de parcelle: rendement}` | Ce que chaque coin de sa rive lui a rendu (1 : comme le lac). Il sert à garder ou changer de coin. |
| `id` | `str` | `F01`…, `ANC` | Son identifiant, repris de sa fiche (propriété). |
| `is_fisher` | `bool` | `True` / `False` | Vrai si son rôle est `pecheur` (propriété). |
| `archetype` | `str` | `ancienne_famille`, `nouveau_venu`, `taiseux`, `beau_parleur`, `ancien`, `patrouille` | Son caractère, repris de sa fiche (propriété). |

#### `Outcome` · `filets/agents.py:62`

Le résultat d'une décision ou d'une prise de parole d'un agent.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `value` | `float?` | tonnes ou `None` | La prise décidée pour une décision de pêche. `None` pour une réplique à la veillée. |
| `data` | `dict` | — | Les choix de l'agent : pour le plan, `plan` ; pour une sortie, `quand`, `duree`, `prise`, `lieu`, `lac`, `declaration` (de la sortie qui vient d'être débarquée) ; le contenu de sa réplique à la veillée. |
| `decision` | `dict` | événement `decision` | L'événement tracé pour cette décision. |
| `ok` | `bool` | `True` / `False` | Prévu pour indiquer une réussite. Il garde toujours sa valeur par défaut, vrai, et rien ne le lit dans le code. |

#### `agents` · `filets/agents.py`

Le module des fonctions de décision des agents (`decide_plan`, `decide_catch`, `speak`, `ballot`…).

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `PLACES` | `dict` | `{"rive": "rive", "large": "large", "rive voisine": "voisine"}` | Le « lieu » dit en mots par le pêcheur et le `place` que le moteur comprend. |

#### `Profile` · `filets/profiles.py:92`

La fiche d'un personnage : qui il est, d'où il vient, ce qu'il possède et comment il décide.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `id` | `str` | `F01`…, `ANC`, `PAT`, `PAT2`… | Identifiant unique. |
| `name` | `str` | texte | Nom complet, par exemple « Aldric d'Ostrel ». |
| `hamlet` | `str` | nom de village | Son village. Pour l'ancien, le village où il vit. |
| `archetype` | `str` | `ancienne_famille`, `nouveau_venu`, `taiseux`, `beau_parleur`, `ancien`, `patrouille` | Son caractère, qui fixe sa règle de décision s'il est un agent à règles. |
| `archetype_label` | `str` | texte | Le caractère en mots (« famille ancienne », « nouveau venu endetté »…). |
| `experience` | `int` | années de pêche | Elle règle le rendement (au-delà de 15 ans on gagne, en deçà on perd) et le choix du grand modèle quand elle atteint `population.large_model_min_experience`. |
| `debt_payment` | `float` | écus par saison | Ce qu'il rembourse à chaque saison. 0 pour la plupart des caractères, 120 pour le nouveau venu. |
| `wealth` | `float` | écus | Sa fortune de départ. |
| `traits` | `str` | texte | Description de son caractère, donnée à l'IA dans ses consignes. |
| `voice` | `str` | texte | Sa manière de parler. |
| `kind` | `str` | `llm`, `rule` | Décide-t-il avec une IA ou avec une règle de son caractère ? |
| `tier` | `str?` | `grand`, `petit` ou `None` | La taille du modèle d'IA qui le fait réfléchir. `None` pour un agent à règles. |
| `role` | `str` | `pecheur`, `ancien`, `patrouille` | Sa fonction dans la vallée. |
| `first_name` | `str` | texte | Son prénom. |
| `boat` | `str` | `barque`, `chaloupe`, `cotre`, ou chaîne vide | Sa taille de bateau. Vide pour l'ancien et les capitaines. |

#### `profiles` · `filets/profiles.py`

Le module de la population : constantes qui servent à générer les villages, les caractères, les bateaux et les prénoms.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `VILLAGE_NAMES` | `list` | 12 noms de villages | Les villages que la génération peut poser autour du lac, dans l'ordre. Les quatre premiers forment la vallée de base. |
| `HAMLETS` | `any` | 4 noms de villages | Les quatre premiers noms de `VILLAGE_NAMES`. Seuls les tests l'utilisent, le moteur n'en a plus besoin. |
| `BOAT_NAMES` | `tuple` | `("barque", "chaloupe", "cotre")` | Les classes de bateau, du plus petit au plus grand. Les chiffres sont dans `economy.boats`. |
| `DEFAULT_BOAT` | `str` | `chaloupe` | Le bateau d'une fiche qui n'en précise pas. |
| `DEFAULT_BOAT_MIX` | `dict` | `{classe de bateau: part}` | La répartition des bateaux quand `population.boat_mix` est absent : 0,3 barque, 0,5 chaloupe, 0,2 cotre. |
| `BOAT_TILT` | `dict` | `{caractère: {classe: poids}}` | Le caractère infléchit le tirage du bateau. Le nouveau venu a plus souvent une barque, l'ancienne famille un cotre. Le poids multiplie la part de `boat_mix`. |
| `FIRST_NAMES` | `list` | 48 prénoms | Les prénoms que la graine distribue aux pêcheurs. |
| `ARCHETYPES` | `dict` | `{caractère: {label, experience, debt_payment, wealth, traits, voice, summary}}` | Les quatre caractères de pêcheur. `experience` et `wealth` sont des intervalles (min, max) tirés au hasard. |
| `ORDER` | `list` | `ancienne_famille`, `nouveau_venu`, `taiseux`, `beau_parleur` | L'ordre dans lequel les caractères se succèdent quand on génère les pêcheurs. |
| `TIERS` | `tuple` | `("auto", "grand", "petit")` | Les valeurs permises pour la taille de modèle d'une fiche choisie à la main. |
| `KINDS` | `tuple` | `("llm", "rule")` | Les types d'agent permis : IA ou règles. |

#### `Lake` · `filets/lake.py:19`

Un lac : un stock de poisson qui croît selon une courbe logistique et qui est réparti sur des parcelles.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `stock` | `float` | tonnes | Le poisson du lac entier. En lecture, c'est `_stock`. En écriture, il fixe le stock d'un coup (sécheresse, tests) et ajuste toutes les parcelles dans la même proportion. |
| `name` | `any` | texte (`Vellmor`, `Orsane`…) | Le nom court du lac. |
| `label` | `any` | texte (« Lac de Vellmor ») | Le nom du lac tel qu'on le dit. |
| `capacity` | `float` | tonnes | Le stock du lac quand il est plein. |
| `parcels` | `list?` | `[{i, j, depth, share, luck}]` | Les parcelles du lac. Sans parcelles, le lac en reçoit une seule, ce qui ramène à un lac simple. Après création la liste n'est jamais vide. |
| `cap_cells` | `list` | tonnes, une par parcelle | Ce que chaque parcelle tient quand elle est pleine : capacité du lac × `share`. |
| `cells` | `list` | tonnes, une par parcelle | Le poisson de chaque parcelle en ce moment. |
| `_stock` | `any` | tonnes | Le stock total réel du lac, derrière la propriété `stock`. |
| `open_cells` | `list` | tonnes, une par parcelle | Le poisson de chaque parcelle à l'ouverture de la saison. Il sert à répartir les prises sans dépendre de l'ordre des retours. |
| `r` | `float` | taux de croissance | Le taux de repeuplement de la courbe logistique (`lake.growth_rate`). |
| `collapse_ratio` | `float` | part de 0 à 1 | Sous cette part de la capacité, le lac est jugé effondré (`lake.collapse_ratio`, 0,05). |
| `noise` | `float` | erreur relative | L'erreur d'estimation du stock par un pêcheur (`lake.observation_noise`, 0,10). Deux fois plus grande pour un lac lointain. |
| `collapsed` | `bool` | `True` / `False` | Initialisé à faux. Le code ne le change jamais : l'effondrement se lit avec `is_collapsed()` et le monde le suit dans `World.collapsed`. |

#### `Climate` · `filets/climate.py:54`

Le climat : la saison de l'année et les événements (sécheresse, tempête…) qui changent la pêche et le repeuplement.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `seed` | `int` | graine | La graine de la partie. Le climat tire ses hasards à part pour ne pas déplacer les autres. |
| `enabled` | `bool` | `True` / `False` | Le climat est-il actif (`climate.enabled`) ? Sinon tout vaut 1 et la météo est « ordinaire ». |
| `rate` | `float` | probabilité par saison | Chance qu'un événement arrive à une saison, à partir de la 2e (`climate.event_rate`, 0,3). |
| `off` | `set` | noms d'événements | Les événements désactivés (`climate.disabled_events`). |
| `rng` | `Random` | — | Le hasard du climat, tiré de la graine. |
| `active` | `list` | `[{kind, until}]` | Les événements en cours : le type et la dernière saison où ils agissent. |
| `cycle` | `any` | dict de `CYCLE` | La saison de l'année en cours (printemps, été, automne ou hiver) avec ses facteurs et son texte. |
| `growth` | `float` | facteur, 1 = normal | Le facteur de repeuplement de la saison : saison de l'année multipliée par les événements en cours. |
| `yield_` | `float` | facteur, 1 = normal | Le facteur de rendement de la pêche : saison de l'année multipliée par les événements en cours. |
| `new` | `str?` | nom d'événement ou `None` | L'événement arrivé au début de cette saison. |
| `by_season` | `dict` | `{saison: [noms d'événements]}` | Les événements en cours à chaque saison. La météo des jours en dépend. |

#### `rules` · `filets/rules.py`

Le module des types de règle que le conseil peut voter, et les mots pour les dire.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `KINDS` | `tuple` | `quota`, `reserve`, `repos`, `sorties`, `bateau` | Les cinq types de règle. Le moteur ne le lit pas ailleurs, les invites ont leur propre liste identique. |
| `TIMED` | `tuple` | `("reserve", "repos")` | Les règles à durée, qui s'éteignent d'elles-mêmes. |
| `TARGETED` | `tuple` | `("reserve", "repos")` | Les règles qui visent un lieu (une zone ou un lac). |
| `MAX_DURATION` | `int` | saisons, 3 | Durée maximale d'une réserve ou d'un repos. |
| `ALIASES` | `dict` | `{mot: type de règle}` | Les mots que les agents peuvent employer (« réserve », « sortie », « taille »…) et le type de règle qu'ils désignent. |
| `SHORT_H` | `float` | heures, 3 | Heures de pêche d'une sortie courte (la route d'un autre lac s'y ajoute). |
| `LONG_H` | `float` | heures, 7 | Heures de pêche d'une sortie longue. |
| `DAWN_H` | `float` | heure du jour, 5 | On ne pêche pas avant : une pêche qui tomberait de nuit commence à l'aube. |
| `DUSK_H` | `float` | heure du jour, 21 | On ne pêche pas après : de 21 h à 5 h, la nuit. |
| `DUREES` | `dict` | `{"courte": 3, "longue": 7}` | Les durées qu'un pêcheur peut choisir pour une sortie, en heures de pêche. |
| `QUAND` | `dict` | `{mot: délai en heures}` | Les mots du « quand » d'une prochaine sortie : « tout de suite » (0), « dans 3 heures », « dans 6 heures », « demain à l'aube » (`"aube"` : 5 h le lendemain), « dans 2 / 4 / 8 jours », « plus cette saison » (`None` : il ne sort plus). Un mot inconnu vaut « tout de suite ». |
| `VALUE_TOLERANCE` | `dict` | `{type: écart}` | L'écart de valeur sous lequel deux propositions du même type et de la même cible n'en font qu'une. Vaut 1 pour `sorties`, 0 pour les autres types. |

#### `lakes` · `filets/lakes.py`

Le module des lacs de la vallée : leur nombre, leur place sur la carte, leur forme et celle des villages.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `LAKE_NAMES` | `list` | `Vellmor`, `Orsane`, `Brémol`, `Ysaude` | Les noms que prennent les lacs, dans l'ordre. |
| `MAX_LAKES` | `int` | 4 | Nombre maximal de lacs : celui de `LAKE_NAMES`. |
| `LAKE_CENTERS` | `dict` | `{nombre de lacs: [(x, y)]}` | Le centre de chaque lac sur la carte (coordonnées de 0 à 1). La distance entre deux lacs est celle de leurs centres. |
| `LAKE_RADII` | `dict` | `{nombre de lacs: [(rayon x, rayon y)]}` | Les rayons des lacs dans le sol, gabarit autour duquel se dessine la maille. Ils reprennent ceux de l'interface Godot. |
| `ISO_LAKE_K` | `dict` | `{nombre de lacs: facteur}` | Facteur de passage entre le gabarit du lac et son dessin en vue isométrique. Il sert à placer les villages autour. |
| `SLOTS` | `dict` | `{emplacement: (x, y)}` | Les huit emplacements possibles d'un village autour d'un lac unique (`NW`, `NE`, `SE`, `SW`, `W`, `E`, `BL`, `BR`). |
| `LAYOUTS` | `dict` | `{nombre de villages: [emplacements]}` | Quels emplacements prennent les villages d'un lac unique, selon leur nombre (1 à 8). |
| `_PLAN_BOXES` | `dict` | `{nombre de lacs: dimensions}` | Demi-dimensions des lacs pour poser les villages sur la rive extérieure quand il y a plusieurs lacs. Une paire (x, y) ou une liste de paires, une par lac. |
| `GRID` | `int` | 30 parcelles | Nombre de parcelles par côté de la maille à la taille de vallée 1. Une vallée plus grande en a plus (`grid_of`). |

#### `world_module` · `filets/world.py`

Les constantes de `filets/world.py`, hors classes : confiance, détection, patrouille, météo des mots.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `TRUST_START` | `float` | confiance de 0 à 1, 0,5 | La confiance de départ de chaque agent envers chaque pêcheur. |
| `TRUST_STEP` | `float` | 0,1 | Le pas de la confiance. Un jugement la déplace de −3 à +3 pas. |
| `LOYAL` | `float` | confiance de 0 à 1, 0,8 | Seuil d'amitié : un témoin ne dénonce pas devant tous celui à qui il fait confiance à ce point. |
| `DETECTION` | `dict` | probabilités, erreurs, seuils | Réglages par défaut de la détection : chance de repérage (`patrol`, `witness`, `seen_leaving`, `lifestyle`), erreurs d'estimation, marges (`margin_t`, `margin_ratio`) et poids de preuve (`proof`). `scenario.detection` les surcharge. |
| `PATROL` | `dict` | `cost`, `legs`, `days`, `enabled`, `count` | Réglages par défaut de la patrouille : coût par pêcheur et par saison (15 écus), étapes (3), jours de mer (14), actif, nombre (1). `scenario.patrol` les surcharge. |
| `PATROL_CAPTAINS` | `list` | `Aubry`, `Berthe`, `Corentin`, `Dalia` | Les prénoms des capitaines de patrouille, dans l'ordre. Le premier a l'identifiant `PAT`. Ils limitent le nombre de patrouilles à 4. |
| `EVIDENCE` | `dict` | `{nature de l'indice: poids}` | Ce que chaque sorte d'indice pèse dans le jugement de l'ancien : patrouille 3, témoin 1, départ vu 1, train de vie 0,5, comptes 0,5. Un mensonge est établi quand le poids atteint `proof`. |
| `HOW` | `dict` | `{moyen: phrase}` | Comment une triche a été établie, en mots (patrouille, voisins, indices concordants). Sert aux souvenirs et aux annonces. |
| `MIN_LIE_T` | `float` | tonnes, 0,05 | Tolérance de mesure. En dessous, un écart entre prise et déclaration est un arrondi, pas un mensonge. |
| `PATROL_ACTIONS` | `tuple` | `("patrouille", "fin_patrouille")` | Les motions du conseil qui ne visent aucun pêcheur : installer ou retirer la patrouille. |
| `BREACH_WORD` | `dict` | `{infraction: phrase}` | Les infractions possibles (`quota`, `reserve`, `repos`, `sorties`, `bateau`) dites en mots. |
| `LOW_LAKE` | `float` | part de la capacité, 0,3 | Sous ce niveau du lac, le poisson est plus dur à prendre et le rendement baisse. |
| `SKILL_STEP` | `float` | rendement par année, 0,005 | Rendement gagné par année d'expérience au-delà de 15 ans, ou perdu en deçà. L'expérience compte de 0 à 40 ans. |
| `WEATHER_WORD` | `dict` | `{météo: expression}` | Le temps d'une sortie dit comme un pêcheur (`par temps calme`, `dans la tempête`…). Sert à raconter les sorties de la saison. |

### Temps : horloge, pilotage, saisons, veillées

#### `SimClock` · `filets/clock.py:60`

L'horloge simulée : le temps du jeu en jours depuis le début, avec sa pause et sa vitesse.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `rate` | `float` | jours simulés par seconde réelle | La vitesse d'affichage du moment : `base_rate` multiplié par la vitesse choisie par le joueur. C'est une propriété calculée. |
| `paused` | `bool` | `True` / `False` | Vrai si la partie est en pause (propriété calculée). |
| `season_days` | `float` | jours simulés (`time.season_days`, 30) | La durée d'une saison. |
| `base_rate` | `any` | jours simulés par seconde réelle à ×1 | `time.sim_hours_per_second` divisé par 24. |
| `speed` | `float` | de 0,05 à 64, 1 par défaut | Le facteur de vitesse choisi par le joueur. |
| `idle_speedup` | `float` | facteur (`time.idle_speedup`, 40) | Entre deux échéances, l'horloge d'affichage accélère de ce facteur. `inf` donne un saut direct. |
| `fast` | `bool` | `True` / `False` | Si vrai, aucune attente d'affichage : le temps saute à l'échéance suivante (`time.fast`). Sert aux essais répétés et aux tests. |
| `_now` | `float` | jours simulés | Le temps simulé courant, depuis le début de la partie. Il ne recule jamais. |
| `_wall0` | `any` | secondes réelles (horloge monotone) | L'instant réel où l'horloge a été créée. |
| `_paused_at` | `float?` | secondes réelles ou `None` | L'instant réel où la pause a commencé. `None` si la partie ne tourne pas en pause. |
| `_paused_total` | `float` | secondes réelles | Le temps total passé en pause, retiré du temps réel écoulé. |
| `in_flight` | `int` | nombre | Le nombre d'appels à l'IA en cours. Information seulement. |

#### `GameControl` · `filets/control.py:28`

Le pilotage d'une partie en cours : pause, vitesse, arrêt. L'ordonnanceur le consulte à chaque point de passage.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `paused` | `bool` | `True` / `False` | Vrai si la partie est en pause (propriété : le signal de marche est baissé). |
| `stopping` | `bool` | `True` / `False` | Vrai si l'arrêt a été demandé (propriété). |
| `clock` | `SimClock` | — | L'horloge pilotée. |
| `_run` | `Event` | levé = la partie avance | Signal asynchrone : levé quand la partie avance, baissé en pause. |
| `_stop` | `Event` | levé = arrêt demandé | Signal asynchrone levé par `request_stop`. |
| `on_change` | `CallableNone?` | fonction sans argument ou `None` | Fonction appelée à chaque changement (pause, reprise, vitesse, arrêt). Le monde y branche `publish_status` pour prévenir l'interface. |

#### `clock` · `filets/clock.py`

Le module de l'horloge : constantes pour dire l'heure en mots.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `PERIODS` | `tuple` | `((heure de fin, moment), …)` | Les moments de la journée tels qu'un villageois les dit : la nuit, le matin, à midi, l'après-midi, le soir. Le premier nombre est l'heure de fin, exclue. |

#### `SeasonScheduler` · `filets/scheduler.py:49`

L'ordonnanceur d'une saison : une file d'événements à dates précises (effets du monde et décisions d'agents) jouée dans l'ordre.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `TICK` | `float` | secondes réelles, 0,02 | Pause entre deux pas d'affichage du temps qui passe. |
| `w` | `any` | `World` | Le monde joué. |
| `c` | `any` | `SimClock` | L'horloge du monde. |
| `season` | `int` | numéro de saison | La saison que cet ordonnanceur joue. |
| `t0` | `any` | jours simulés | Le début de la saison sur l'horloge (`season_start`). |
| `q` | `list` | tas de `(instant, classe, clé, ordre, élément)` | La file de la saison : effets à appliquer et décisions à demander, classés par instant, puis par classe d'acteur, puis par clé tirée de la graine. |
| `seq` | `counter` | compteur croissant | Numéro d'arrivée, qui départage deux éléments de même rang dans la file. |
| `recit` | `asyncio.Future?` | tâche ou `None` | La tâche du récit du narrateur, lancée à la fin de la saison. Elle ne bloque pas la saison suivante. |
| `last` | `any` | secondes réelles (horloge monotone) | Le dernier instant réel compté pour l'affichage. La réflexion des agents n'en fait pas partie. |

#### `Decision` · `filets/scheduler.py:41`

Un appel d'agent attaché à un horizon : l'agent ne voit que ce qui s'est passé avant. Il ne prend pas de temps simulé.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `agent` | `str` | id d'agent | Qui décide. |
| `lag` | `float` | jours simulés | Le plus court délai avant que l'effet de la décision s'applique (`OUTING_LAG` : 3 h, la plus courte sortie). Il décide quelles décisions peuvent tourner en même temps. |
| `make` | `Callable` | fonction asynchrone sans argument | Lance l'appel à l'agent (IA ou règle). |
| `then` | `Callable` | fonction à un argument | Reçoit le résultat et en tire les effets dans le monde, dans l'ordre de la file. |

#### `Village` · `filets/scheduler.py:252`

La veillée d'un village ou du conseil, vue par l'ordonnanceur : qui a préparé quoi, qui a parlé, quelle heure il est dans la salle.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `s` | `any` | `SeasonScheduler` | L'ordonnanceur qui joue la saison. |
| `w` | `any` | `World` | Le monde. |
| `asm` | `any` | `Assembly` | La veillée jouée. |
| `t` | `any` | jours simulés | L'heure dans la salle : l'ouverture, puis la fin de chaque réplique. |
| `rounds` | `int` | tours de parole | Nombre de tours de parole par pêcheur (`scenario.assembly_rounds`, 2). |
| `duration` | `any` | jours simulés | Durée d'une réplique : `time.speech_minutes` (20 min) converti en jours. |
| `close_t` | `any` | jours simulés | L'heure de clôture de la veillée, reprise de `Assembly.close_t`. |
| `spoken` | `dict` | `{id d'agent: nombre de répliques}` | Combien de fois chaque participant a parlé. |
| `prepared` | `dict` | `{id d'agent: (réponse, horizon, tour, nombre de répliques connues, ids des propositions connues)}` | Les répliques déjà préparées et pas encore dites. Une réplique est refaite si, depuis, on s'est adressé à son auteur, on a concurrencé sa règle, ou elle redit ce qui vient d'être dit. Une **redite** : réplique dont au moins 85 % des mots, sur au moins 4, se retrouvent dans l'ordre dans une réplique déjà dite de la partie (`World.repeated_line`). |
| `done` | `bool` | `True` / `False` | Vrai quand plus personne n'a rien à dire, ou quand la salle n'a plus le temps. |

### Décisions : agents, règles d'archétype, routage, invites

#### `policies` · `filets/policies.py`

Module des règles de comportement des agents « à règles » : une table de réglages par caractère (archétype), sans appel à un modèle de langage.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `JUDGE` | `dict` | `{archétype: {fait: dixièmes de confiance}}`, de −3 à +3 | Table de jugement de chaque caractère. Pour chaque fait appris sur un pêcheur (`over_slight`, `over_big`, `within`, `lie`, `secret`, `broken`, `kept`, `accused_me`, `testified`, `stayed_away`), elle donne combien de dixièmes de confiance il gagne ou perd. Utilisée par `trust_rule`. |
| `EXCLUDE_BELOW` | `dict` | `{archétype: confiance de 0 à 1}` | Seuil sous lequel un agent à règles propose d'interdire de pêche un pêcheur. Le taiseux et l'ancien n'y sont pas : ils ne proposent jamais. Utilisée par `sanction_rule`. |
| `VOTE_EXCLUDE_BELOW` | `dict` | `{archétype: confiance de 0 à 1}` | Seuil sous lequel un agent à règles vote pour l'exclusion d'un pêcheur. Seul le taiseux y figure en plus des trois autres ; l'ancien n'y est pas et ne vote jamais l'exclusion. Utilisée par `sanction_vote`. |
| `REAUTHORIZE_FROM` | `dict` | `{archétype: confiance de 0 à 1}` | Confiance à partir de laquelle l'agent propose et vote de rendre le droit de pêcher à un exclu. Le nouveau venu et le taiseux pardonnent le plus vite. Valeur par défaut 0,5 dans le vote. |
| `PATROL_WANTS` | `dict` | `{archétype: nombre de mensonges ou sorties en cachette}` | Nombre de mensonges ou de sorties en cachette établis ces deux dernières saisons à partir duquel l'agent veut la patrouille du lac. Le taiseux n'y est pas : il n'en veut jamais. Utilisée par `patrol_vote`. |
| `KIN_SOFT` | `dict` | `{archétype: part de 0 à 1}` | Indulgence envers un voisin (« kin ») : part de la perte de confiance retirée quand le fautif est un proche. Utilisée dans `trust_rule`. |
| `GOSSIP` | `dict` | `{archétype: poids}` | Poids de la réputation du pêcheur dans la vallée (les on-dit) dans le jugement de l'agent. Le beau parleur y est le plus sensible, le taiseux presque pas. Utilisée dans `trust_rule`. |
| `LEAVE` | `dict` | `{archétype: rapport sans unité}` | Combien de fois mieux (en tonnes nettes de la route) doit être un autre lac pour que l'agent quitte le sien. La famille ancienne est la plus attachée à son lac (1,6), le nouveau venu la moins (1,15). Utilisée par `lake_choice_rule`. |

#### `routing` · `filets/routing.py`

Module qui choisit entre le réflexe (système 1, petit modèle, réponse courte) et la réflexion (système 2) pour chaque décision de prise.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `HEALTHY_RATIO` | `float` | part de 0 à 1 de la capacité du lac | Seuil de lac sain, fixé à 0,7. Sous 70 % de la capacité estimée, le lac « mérite qu'on y réfléchisse » et la décision passe en système 2. |
| `FALLING_RATIO` | `float` | part de 0 à 1 de la capacité du lac | Seuil de baisse, fixé à 0,04. Si le stock estimé a perdu plus de 4 % de la capacité depuis la dernière ouverture de la pêche, c'est un signal qui envoie la décision en système 2. |

#### `prompts` · `filets/prompts.py`

Module des textes d'invite (prompts) envoyés aux modèles de langage et des schémas JSON de leurs réponses, avec les longueurs de réponse permises.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `WORLD` | `str` | texte à trous `{villages}`, `{half}`, `{capacity}` | Description du monde pour une vallée à un seul lac : personne ne possède le lac, seuls comptent les accords des villages, le lac se refait mieux autour de la moitié de sa capacité. Placée en tête de l'invite système. |
| `STYLE` | `str` | texte | Consigne de style ajoutée à toute invite système : le modèle est le personnage, pas un assistant, il ne connaît que ce qui est écrit, et répond par un seul objet JSON. |
| `BRIEF_STYLE` | `str` | texte | Consigne ajoutée en mode bref (profils `rapide` et `adaptive`) : une phrase courte, 20 mots au plus, par champ de texte. |
| `BRIEF_MAX_TOKENS` | `dict` | `{nature de l'appel: tokens}` : `catch` 125, `plan` 150, `speak` 200 | Longueur de réponse permise en mode bref. La clé est la nature de la décision (prise ou parole à la veillée). Posée comme `max_tokens` dans l'indice de l'appel. |
| `REFLEX_MAX_TOKENS` | `int` | tokens (16) | Longueur de réponse permise au système 1 (réflexe) : un nombre seul. |
| `REFLEX_OUTING_SCHEMA` | `dict` | schéma JSON `{quand, duree, prise}` | Forme imposée au réflexe pour une décision de sortie : le « quand » (un mot de `rules.QUAND`), la durée (`courte` ou `longue`) et la prise visée (nombre). |
| `LIEUX` | `list` | `rive`, `large`, `rive voisine` | Les lieux qu'un pêcheur peut dire : sa rive, le large, la rive d'un autre village du même lac (en cachette). |
| `WHEN_HELP` | `str` | texte | L'aide donnée au pêcheur sur les durées et le « quand » : sortie courte 3 h, longue 7 h, pas de pêche de 21 h à 5 h, mots de `QUAND`. |
| `REFLEX_SCHEMA` | `dict` | schéma JSON `{"prise": nombre}` | Forme imposée à la réponse du réflexe : un objet avec le seul champ obligatoire `prise` (tonnes). |
| `PATROL_WHO` | `str` | texte | Présentation du capitaine de la patrouille du lac, utilisée à la place de celle d'un pêcheur dans l'invite système : il ne pêche pas, ne punit pas, mesure les charges et choisit sa route d'après les soupçons. |
| `WORLD_LAKES` | `str` | texte à trou `{lakes}` | Variante de `WORLD` pour une vallée à plusieurs lacs ; `{lakes}` est remplacé par la liste des lacs. |
| `RULE_KINDS` | `list` | `quota`, `reserve`, `repos`, `sorties`, `bateau` | Types de règle qu'un pêcheur peut proposer à la veillée. Ils forment les valeurs permises du champ `proposition_type` du schéma de parole (avec `None`). |
| `BALLOT_MAX_TOKENS` | `int` | tokens (10) | Longueur de réponse permise pour un bulletin de vote : un identifiant de proposition ou « aucune ». |
| `NARRATION_SCHEMA` | `dict` | schéma JSON `{"recit": texte ≤ NARRATION_WIDTH caractères}` | Forme imposée à la réponse du narrateur, qui raconte la saison au joueur. |
| `NARRATION_MAX_TOKENS` | `int` | tokens (260) | Longueur de réponse permise au narrateur. |
| `NARRATION_WIDTH` | `int` | caractères (800) | Longueur maximale du récit : 4 phrases courtes y tiennent ; au-delà, le récit est coupé à la dernière phrase complète (jamais au milieu d'un mot). |
| `NARRATION_TEMPERATURE` | `float` | température du modèle (0,3) | Température demandée pour le récit de la saison. Elle est basse pour que le récit reste fidèle aux faits, car un petit modèle enjolive à 0,7. |
| `SANCTION_MAX_TOKENS` | `int` | tokens (40) | Longueur de réponse permise pour le vote sur une exclusion ou une réautorisation (« oui » ou « non » par proposition). |
| `ELECTION_MAX_TOKENS` | `int` | tokens (10) | Longueur de réponse permise pour le vote qui élit l'élu d'un village. |
| `DEBRIEF_MAX_TOKENS` | `int` | tokens (70) | Longueur de base de la réponse du bilan d'un villageois absent du conseil. L'appelant la relève à `12 + 9 × nombre de pêcheurs` si c'est plus grand. |
| `DEBRIEF_SCHEMA` | `any` | schéma JSON `{"confiance": {identifiant: niveau}}` | Forme par défaut de la réponse du bilan (sans liste d'identifiants imposée) : la confiance envers chaque pêcheur après ce que l'ancien a rapporté du conseil. |
| `PATROL_MAX_TOKENS` | `int` | tokens (170) | Longueur de réponse permise au capitaine de la patrouille pour décider sa route de la saison. |

### Modèles de langage : routeur, clients, limiteurs

#### `LLMRouter` · `filets/llm.py:335`

Le routeur envoie chaque appel au bon fournisseur selon le niveau de modèle, publie un événement `llm_call` et compte les appels et les tokens.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `cfg` | `any` | dict : section `llm` de la configuration | Réglages du bloc `llm` (`temperature`, `max_tokens`, `timeout_s`, `max_retries`, `json_mode`, `tiers`, `providers`). |
| `clock` | `any` | horloge de la partie | Horloge du monde. Le routeur y ajoute 1 à `in_flight` pendant un appel et le retire après, pour dire qu'une réflexion est en cours. |
| `events` | `any` | journal d'événements | Journal où le routeur publie `llm_call` et dont il lit `run_id` pour fabriquer les identifiants d'appel. |
| `ctl` | `any` | contrôle de partie ou `None` | Contrôle de pause (`GameControl`). En pause, aucun nouvel appel ne part et aucune réponse n'entre dans le monde. `None` : pas de contrôle. |
| `clients` | `dict` | `{nom du fournisseur: client}` | Un client par fournisseur utilisé (`ScriptedClient`, `SystemOneClient` ou `OpenAICompatClient`), créé une fois à la construction d'après `llm.tiers` et `llm.providers`. |
| `tiers` | `any` | dict `{niveau: {provider, model}}` | Copie de `llm.tiers` : pour chaque niveau (`grand`, `petit`, `reflexe`…), le fournisseur et le modèle à utiliser. |
| `_n` | `int` | compteur, 0 au départ | Nombre d'appels lancés. Sert à numéroter les appels : `call_id = <run_id>-c00001`, etc. |
| `usage` | `Usage` | cumul de la partie | Compteurs d'appels, de tokens et de latence de toute la partie (coût, exigence E4). |

#### `LLMResult` · `filets/llm.py:30`

Le résultat d'un appel à un modèle de langage : le texte reçu, l'état de l'appel et ses mesures.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `text` | `str?` | texte JSON brut, ou `None` | Réponse du modèle, pas encore analysée. `None` si l'appel a échoué (délai dépassé, erreur, quota). |
| `status` | `str` | `ok`, `error`, `timeout`, `quota`, `cancelled` | Issue de l'appel. `quota` correspond à une erreur HTTP 429 ; `cancelled` n'est posé que dans l'événement d'un appel abandonné. |
| `prompt_tokens` | `int` | tokens | Tokens de l'invite envoyée. Donnés par le fournisseur, sinon estimés à la longueur du texte divisée par 4. |
| `completion_tokens` | `int` | tokens | Tokens de la réponse. Donnés par le fournisseur, sinon estimés à la longueur du texte divisée par 4. |
| `latency_s` | `float` | secondes réelles | Durée de l'appel, attente en file du fournisseur local comprise : c'est le temps que l'agent a réellement passé à réfléchir. |
| `retries` | `int` | nombre de nouvelles tentatives | Combien de fois l'appel a été retenté après une erreur 429 ou 5xx (au plus `llm.max_retries`). |
| `call_id` | `str` | `<run_id>-c00001` | Identifiant unique de l'appel, posé par le routeur. Il relie la décision à l'événement `llm_call`. |
| `model` | `str` | nom du modèle | Modèle utilisé, posé par le routeur d'après `llm.tiers`. |
| `provider` | `str` | nom du fournisseur | Fournisseur utilisé (`scripted`, `ollama`, `groq`…), posé par le routeur. |
| `tier` | `str` | niveau de modèle | Niveau demandé (`grand`, `petit`, `reflexe`…), posé par le routeur. |
| `detail` | `str` | texte | Précision sur l'échec (« timeout », « HTTP 429: … »). Vide quand tout va bien. |

#### `Usage` · `filets/llm.py:325`

Les compteurs de consommation de la partie : appels, tokens et temps passé à attendre les modèles.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `calls` | `int` | nombre d'appels | Appels terminés, quel que soit leur état. |
| `prompt_tokens` | `int` | tokens | Total des tokens d'invite envoyés. |
| `completion_tokens` | `int` | tokens | Total des tokens de réponse reçus. |
| `latency_s` | `float` | secondes réelles | Somme des durées de tous les appels. Elle ne donne pas le temps écoulé, car les appels se chevauchent. |
| `cancelled` | `int` | nombre d'appels | Appels abandonnés après leur départ, quand la réponse est devenue inutile. Ils comptent dans le coût, mais pas dans `calls`. |
| `by_tier` | `dict` | `{niveau: {"calls": n, "tokens": n}}` | Appels et tokens (invite plus réponse) par niveau de modèle. |
| `by_system` | `dict` | `{"S1" ou "S2": {"calls": n, "tokens": n}}` | Appels et tokens par système : S1 pour le réflexe, S2 pour la réflexion. Ce qui montre ce que la réflexion a coûté. |

#### `OpenAICompatClient` · `filets/llm.py:154`

Le client unique des fournisseurs à API compatible OpenAI (`/chat/completions`) : Ollama, Groq, OpenRouter, Gemini, Mistral, GitHub Models.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `name` | `str` | clé de `llm.providers` | Nom du fournisseur (`ollama`, `groq`…). |
| `json_schema` | `bool` | `True` ou `False` | Vrai si le fournisseur sait contraindre la réponse à un schéma JSON (Ollama : `json_schema: true`). La forme de la réponse est alors garantie. Sinon le client demande du JSON libre ou rien. |
| `seed` | `bool` | `True` ou `False` | Vrai si le fournisseur respecte la graine (Ollama : `seed: true`) : même invite, même réponse. La graine est ajoutée à la requête seulement dans ce cas. |
| `base_url` | `any` | adresse URL, sans `/` final | Adresse de base de l'API (`http://localhost:11434/v1` pour Ollama). On y ajoute `/chat/completions`. |
| `api_key` | `any` | chaîne, vide pour un fournisseur local | Clé d'API lue dans la variable d'environnement nommée par `api_key_env`. Une erreur est levée si la variable manque. Envoyée dans l'en-tête `Authorization`. |
| `limiter` | `RateLimiter` | requêtes par minute (`rpm`) | Limiteur de débit du fournisseur, réglé par son `rpm` (0 : pas de limite). |
| `cfg` | `dict` | section `llm` de la configuration | Réglages communs : `temperature` et `max_tokens` par défaut, `json_mode`, `max_retries`, `timeout_s`. |
| `gate` | `ModelGate` | ou `None` | File d'attente qui plafonne les requêtes simultanées et les regroupe par modèle, créée si `max_concurrency` est supérieur à 0. `None` sinon (pas de file de ce côté). |
| `http` | `AsyncClient` | client `httpx` asynchrone | Connexion HTTP réutilisée pour les requêtes. Délai : `timeout_s` du fournisseur, sinon `llm.timeout_s`. |

#### `SystemOneClient` · `filets/llm.py:250`

Le client des modèles de décision « système 1 » d'Ollama (`POST /v1/systemone`) : ils répondent à une question typée avec des probabilités, sans générer de texte.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `name` | `str` | clé de `llm.providers` | Nom du fournisseur (`ollama_s1`). |
| `url` | `any` | adresse URL | Adresse complète du service : l'adresse de base plus `/systemone`. |
| `cfg` | `dict` | section `llm` de la configuration | Réglages communs, dont `timeout_s` quand le fournisseur n'a pas le sien. |
| `gate` | `ModelGate` | ou `None` | File d'attente par modèle, créée si `max_concurrency` du fournisseur est supérieur à 0 ; `None` sinon. |
| `http` | `AsyncClient` | client `httpx` asynchrone | Connexion HTTP réutilisée. Délai : `timeout_s` du fournisseur (60 s dans la configuration par défaut). |

#### `ScriptedClient` · `filets/scripted.py:48`

Le faux modèle de langage : il ignore l'invite et répond à partir de la politique à règles, bruitée, avec des latences et des incidents simulés. Il ne produit aucun résultat scientifique.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `cfg` | `dict` | section du fournisseur `scripted` | Réglages du faux modèle : `latency_s` (fourchette `[min, max]` par niveau), `latency_scale` et `incident_rates` (part de 0 à 1 de sortie de rôle, de JSON illisible et d'absence de réponse). |
| `rng` | `Random` | générateur de nombres aléatoires | Tirages du faux modèle (latence, incidents, bruit), initialisé par la graine de la partie (`seed * 7919 + 13`), donc reproductible. |
| `scale` | `float` | multiplicateur, 1 par défaut | Facteur appliqué aux latences simulées (`latency_scale`). 0 supprime l'attente, 2 la double. |

#### `RateLimiter` · `filets/llm.py:44`

Le limiteur de débit d'un fournisseur : il espace les requêtes pour ne pas dépasser un nombre de requêtes par minute.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `interval` | `any` | secondes réelles entre deux requêtes | Écart minimal entre deux requêtes : 60 divisé par `rpm`. Vaut 0 si `rpm` vaut 0, et le limiteur est alors inactif. |
| `_next` | `float` | instant (horloge monotone, secondes) | Instant le plus tôt où la prochaine requête peut partir. Chaque appel le repousse d'un `interval`. |
| `_lock` | `Lock` | verrou asynchrone | Verrou qui évite que deux appels lisent et modifient `_next` en même temps. |

#### `ModelGate` · `filets/llm.py:61`

La file d'attente d'un fournisseur local : elle plafonne les requêtes simultanées et les regroupe par modèle, pour éviter de décharger et recharger les modèles dans la carte graphique.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `slots` | `int` | requêtes simultanées | Nombre maximal de requêtes en cours en même temps (`max_concurrency` du fournisseur, 4 pour Ollama). |
| `max_streak` | `int` | requêtes d'affilée (24 par défaut) | Plafond de requêtes servies à la suite pour un même modèle quand un autre attend. Il empêche qu'un modèle ne soit jamais servi. |
| `running` | `int` | nombre de requêtes | Requêtes en cours de traitement. |
| `active` | `str?` | nom du modèle, ou `None` | Modèle actuellement en service. `None` tant qu'aucune requête n'est partie. |
| `streak` | `int` | nombre de requêtes | Requêtes servies à la suite pour le modèle actif depuis le dernier changement de modèle. |
| `_seq` | `int` | compteur | Numéro d'arrivée donné à chaque requête mise en attente. Sert à servir en premier le modèle dont le plus ancien demandeur attend depuis le plus longtemps. |
| `waiting` | `dict` | `{modèle: file de (numéro d'arrivée, futur)}` | Requêtes en attente, rangées par modèle. Le futur est réveillé quand la requête peut partir. |
| `swaps` | `int` | nombre de changements | Nombre de fois où le modèle en service a changé. C'est une statistique. |

#### `llm` · `filets/llm.py`

Module des clients de modèles de langage ; ses constantes sont deux motifs qui détectent quand un modèle sort de son personnage.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `OUT_OF_ROLE` | `any` | expression régulière (insensible à la casse) | Reconnaît les phrases où le modèle sort de son rôle : « en tant qu'IA », « modèle de langage », « as an AI », mention d'OpenAI ou d'Anthropic… Utilisée par `detect_drift` pour repérer une dérive. |
| `ASSISTANT_POSTURE` | `any` | expression régulière (insensible à la casse) | Reconnaît le ton d'un assistant plutôt que d'un villageois : « il est important de », « développement durable », « n'hésitez pas », « je vous recommande ». Utilisée par `detect_drift`. |

#### `scripted` · `filets/scripted.py`

Module du faux modèle de langage ; ses constantes sont les phrases et les motifs avec lesquels il imite un habitant et réagit aux rumeurs.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `JUSTIF` | `dict` | `{archétype: liste de phrases}` | Justifications de prise toutes faites, par caractère. Le faux modèle en tire une au hasard (`ancien` n'y est pas : « Je fais au mieux. » par défaut). |
| `SCARCITY` | `any` | expression régulière | Reconnaît les mots de pénurie dans une rumeur (sécheresse, pénurie, vide, baisse, poison…). Si elle s'y trouve, le faux modèle réduit sa prise de 15 %. |
| `ACCUSATORY` | `any` | expression régulière | Reconnaît les mots d'accusation dans une rumeur (ment, triche, vole, trop pêché, fraude…). Le faux modèle s'en défend ou accuse selon qui est visé. |
| `ECHO` | `dict` | `{archétype: phrase à trou {r}}` | Phrase que chaque caractère dit à la veillée pour reprendre une rumeur ; `{r}` est remplacé par le texte de la rumeur. |

### Mémoire, RAG et vecteurs

#### `Memory` · `filets/memory.py:29`

Un souvenir d'un agent : un texte daté en temps simulé, avec son poids et ses règles de rappel.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `id` | `str` | `<agent>-m0001` | Identifiant du souvenir : l'identifiant de l'agent suivi d'un numéro. |
| `t` | `float` | jours simulés depuis le début de la partie | Moment où le souvenir a été formé. Il n'est jamais rappelé avant ce moment. |
| `text` | `str` | texte | Contenu du souvenir, écrit à la première personne. |
| `kind` | `str` | `peche`, `mensonge`, `rumeur`, `parole`, `promesse`, `accusation`, `sanction`, `conseil`, `patrouille`, `indice`, `evenement`, `bilan` | Nature du souvenir, posée par le monde au moment où il l'écrit. Elle permet par exemple d'écarter les rumeurs de la liste des souvenirs rappelés, car elles ont leur propre rubrique. |
| `importance` | `float` | de 0 à 1 | Poids du souvenir à la création. Plus il est grand, plus le souvenir remonte (la promesse vaut 0,9 à 1, la parole 0,4, le bilan 0,2 à 0,5). |
| `pinned` | `bool` | `True` ou `False` | Vrai pour un engagement (promesse, accusation reçue, sanction) : il remonte à chaque décision tant qu'il n'a pas expiré. |
| `expires_season` | `int?` | numéro de saison, ou `None` | Dernière saison où le souvenir épinglé reste actif. `None` : il n'expire pas. Les promesses, accusations et sanctions valent la saison suivante. |
| `source_event_id` | `str?` | identifiant d'événement, ou `None` | Événement du monde qui est à l'origine du souvenir (une prise, une parole). Sert à relier le souvenir à ce qui l'a causé. |
| `event_id` | `str?` | identifiant d'événement, ou `None` | Identifiant de l'événement `memory_write` qui a publié ce souvenir. Posé juste après la création. |

#### `MemoryStore` · `filets/memory.py:41`

La mémoire d'un agent : une liste de souvenirs avec un rappel qui combine récence, importance et pertinence (méthode de Park et al., 2023).

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `owner` | `str` | identifiant de l'agent | Agent à qui appartient la mémoire. Sert de préfixe aux identifiants des souvenirs. |
| `items` | `list` | liste de `Memory` | Tous les souvenirs de l'agent, dans l'ordre de création. |
| `decay` | `float` | par jour simulé | Vitesse à laquelle un souvenir perd de la récence (`memory.recency_decay_per_day`, 0,01). La récence vaut `exp(−decay × âge en jours)`. |
| `w` | `dict` | `{"recency", "importance", "relevance": poids}` | Poids des trois termes du score de rappel (`memory.weights` : 1,0 / 1,0 / 1,5). |
| `_n` | `int` | compteur | Nombre de souvenirs créés. Sert à numéroter les identifiants. |

#### `VectorMemory` · `filets/memory.py:104`

Une mémoire d'agent qui range aussi chaque souvenir dans pgvector, pour que la pertinence soit une similarité de sens ; si la base tombe, elle revient à BM25.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `bank` | `MemoryBank` | banque partagée de la partie | Banque de souvenirs commune à tous les agents. Chaque nouveau souvenir y est mis en attente d'écriture, tant qu'elle n'est pas dégradée. |

#### `MemoryBank` · `filets/memory.py:80`

Les souvenirs de la partie dans PostgreSQL et pgvector. L'écriture est différée et groupée.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `store` | `any` | `PgVectorStore` | Accès à la base où les souvenirs et leurs vecteurs sont écrits. |
| `embedder` | `any` | `HashEmbedder` ou `OllamaEmbedder` | Calculateur de vecteurs pour les textes (`rag.embeddings`). |
| `run_id` | `any` | identifiant de la partie | Partie à laquelle appartiennent les souvenirs. Il sépare les parties dans la base. |
| `pending` | `list` | liste de `(propriétaire, Memory)` | Souvenirs formés mais pas encore écrits. Toute recherche les écrit d'abord, en un seul calcul de vecteurs. Si l'écriture échoue, ils sont remis en attente. |
| `lock` | `Lock` | verrou asynchrone | Verrou qui empêche deux écritures simultanées de la file `pending`. |
| `degraded` | `bool` | `True` ou `False` | Vrai quand la base ou le modèle de plongement ne répond plus. Les mémoires se rabattent alors sur BM25 en mémoire et n'écrivent plus. |

#### `Passage` · `filets/rag.py:81`

Un passage du corpus ou un moment marquant de la partie (« lore ») que le RAG peut ramener dans l'invite d'un agent.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `id` | `str` | `<document>#<n° de paragraphe>` ou `lore:<événement>` | Identifiant du passage. |
| `title` | `str` | texte | Titre du document d'où vient le passage. Pour le lore : « Ce que la vallée sait ». |
| `text` | `str` | texte | Le paragraphe, avec les valeurs du monde (prix, capacité) déjà remplacées. |
| `visible_to` | `list` | liste de noms de hameaux, ou `["all"]` | Qui peut voir le passage. « all » : tout le monde ; sinon seuls les hameaux listés. |
| `sim_time` | `float` | jours simulés | Date du passage. Il n'est jamais rendu avant ce moment, par cohérence temporelle (les documents anciens ont une date négative). |
| `tokens` | `list` | liste de mots racinisés | Mots du titre et du texte, sans mots vides, pour l'index BM25. |
| `agent` | `str` | identifiant d'agent, vide pour le corpus fixe | Agent que le moment marquant caractérise. |
| `importance` | `float` | de 0 à 1 (0 pour le corpus fixe) | Poids du moment marquant. Au-delà de `rag.lore_per_agent` passages par agent, le moins important part d'abord. |
| `source` | `str` | `corpus` ou `lore` | Origine du passage : document fixe du corpus, ou moment marquant de la partie en cours. |

#### `BM25` · `filets/rag.py:54`

L'index de recherche par mots (BM25) : il note chaque document selon les mots de la requête qu'il contient.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `docs` | `list` | liste de listes de mots | Les documents indexés, chacun déjà découpé en mots. |
| `k1` | `any` | réel, 1,4 par défaut | Réglage de saturation de la fréquence d'un mot : au-delà de quelques répétitions, un mot de plus compte de moins. |
| `b` | `any` | de 0 à 1, 0,75 par défaut | Réglage de normalisation de la longueur : un document long est pénalisé. |
| `N` | `int` | nombre de documents | Taille de l'index. |
| `avgdl` | `any` | mots par document | Longueur moyenne des documents, 0 si l'index est vide. |
| `idf` | `dict` | `{mot: poids}` | Poids de rareté de chaque mot : un mot rare dans le corpus pèse plus. |
| `tfs` | `list` | liste de compteurs `{mot: occurrences}` | Pour chaque document, combien de fois chaque mot y apparaît. |

#### `Retriever` · `filets/rag.py:136`

Le moteur de recherche du corpus en mémoire (backend `rag.backend: bm25`) : il découpe les documents en passages, ajoute le lore de la partie et cherche par BM25 en respectant les droits de visibilité.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `passages` | `list` | liste de `Passage` | Passages du corpus fixe (`rag.corpus_dir`), un par paragraphe, plus les registres de marché des villages qui n'en ont pas d'écrit. |
| `files` | `dict` | `{identifiant de document: chemin du fichier}` | Fichier source de chaque document du corpus. |
| `lore` | `list` | liste de `Passage` | Moments marquants de la partie en cours, en mémoire seulement. Au plus `rag.lore_per_agent` par agent. |
| `_all` | `any` | liste de `Passage` | Corpus fixe et lore ensemble : ce que l'index BM25 couvre. |
| `bm25` | `BM25` | ou `None` | Index BM25 de `_all`, reconstruit à chaque ajout de lore. `None` si aucun passage. |

#### `VectorRetriever` · `filets/rag.py:204`

Le moteur de recherche par le sens (backend `rag.backend: pgvector`) : les mêmes passages que `Retriever`, rangés avec leur vecteur dans PostgreSQL. Il se rabat sur BM25 si la base tombe.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `local` | `Retriever` | moteur BM25 de secours | Moteur en mémoire. Il fournit les passages, garde le lore, et répond quand la base est perdue. |
| `passages` | `any` | liste de `Passage` | Passages du corpus fixe, partagés avec `local`. |
| `by_id` | `dict` | `{identifiant: Passage}` | Permet de retrouver un passage à partir de l'identifiant renvoyé par la base. |
| `store` | `any` | `PgVectorStore` | Base de vecteurs où sont rangés les passages et le lore. |
| `embedder` | `any` | `HashEmbedder` ou `OllamaEmbedder` | Calculateur de vecteurs des passages et des requêtes. |
| `objects` | `any` | stockage objet, ou `None` | Stockage des fichiers sources du corpus (`storage.objects`). `None` : kind `none`, rien n'y est envoyé. |
| `min_score` | `any` | similarité cosinus de 0 à 1 (`rag.min_score`, 0,0) | Similarité minimale pour qu'un passage soit gardé. |
| `corpus` | `any` | empreinte de 16 caractères hexadécimaux | Empreinte (SHA-1 raccourci) du corpus rendu, valeurs comprises. Une partie avec le même corpus ne recalcule pas les vecteurs. |
| `degraded` | `bool` | `True` ou `False` | Vrai quand la recherche vectorielle a échoué. Les recherches suivantes passent alors par BM25. |
| `run_id` | `str` | identifiant de la partie, vide au départ | Partie dont le lore est rangé dans la base. Posé par le monde. Il sert à effacer ce lore en fin de partie. |
| `_new` | `list` | liste de `Passage` | Lore ajouté mais pas encore vectorisé ni écrit dans la base. |
| `_gone` | `set` | ensemble d'identifiants de passages | Lore retiré par le plafond par agent, à effacer de la base à la prochaine recherche. |

#### `rag` · `filets/rag.py`

Module de recherche dans le corpus ; ses constantes sont la liste des mots vides et des variantes de texte pour les registres de marché.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `STOP` | `set` | ensemble de mots français sans accents | Mots vides (« le », « de », « et »…) ignorés à l'indexation et à la recherche, car ils ne portent pas de sens. |
| `REGISTER_VARIANTS` | `list` | 3 phrases à trous `{v}` (village) et `{market}` | Phrases d'ambiance pour le registre de marché d'un village sans registre écrit. L'une des trois est choisie d'après le nom du village (CRC32 modulo 3), donc toujours la même pour un village donné. |

#### `HashEmbedder` · `filets/vectors.py:34`

Un calculateur de vecteurs sans modèle (sac de mots haché), pour les tests et le mode par défaut `rag.embeddings.kind: hash`.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `dim` | `int` | nombre de dimensions (384) | Taille des vecteurs (`rag.embeddings.dim`). Chaque mot est haché vers l'une de ces cases. |
| `name` | `str` | `hash-<dim>` | Nom de l'embedder, enregistré avec chaque vecteur pour ne pas mélanger deux calculateurs. |

#### `OllamaEmbedder` · `filets/vectors.py:57`

Un calculateur de vecteurs qui appelle un modèle de plongement d'Ollama (`rag.embeddings.kind: ollama`), par défaut sur le processeur pour garder la carte graphique aux modèles de langage.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `url` | `str` | adresse URL | Adresse de l'API `/api/embed` d'Ollama (le suffixe `/v1` de l'adresse de base est retiré). |
| `model` | `any` | nom du modèle (`embeddinggemma`) | Modèle de plongement utilisé (`rag.embeddings.model`). |
| `dim` | `any` | nombre de dimensions (768 pour `embeddinggemma`) | Taille attendue des vecteurs (`rag.embeddings.dim`). Une autre taille reçue est une erreur. |
| `name` | `any` | `ollama:<modèle>` | Nom de l'embedder, enregistré avec chaque vecteur. |
| `options` | `dict` | `{"num_gpu": 0}` ou `{}` | Option envoyée à Ollama : `num_gpu: 0` force le calcul sur le processeur (`cpu: true`), vide pour utiliser la carte graphique. |
| `batch` | `any` | textes par requête (32) | Nombre de textes envoyés à Ollama en une seule requête. |
| `cache_max` | `any` | nombre de textes (50 000) | Taille maximale du cache. Au-delà, les entrées les plus anciennes sont retirées. |
| `cache` | `OrderedDict` | `{texte: vecteur}` | Cache des vecteurs déjà calculés, qui évite de recalculer un même texte. |
| `http` | `AsyncClient` | client `httpx` asynchrone | Connexion HTTP vers Ollama (délai 120 s par défaut, 3 s pour se connecter). |

#### `PgVectorStore` · `filets/vectors.py:134`

La base PostgreSQL avec l'extension pgvector, qui range les passages du corpus, le lore de partie et les souvenirs avec leurs vecteurs.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `dsn` | `any` | adresse de connexion PostgreSQL | Adresse de la base : la variable `FILETS_PG_DSN`, sinon `storage.postgres.dsn`. |
| `embedder` | `any` | `HashEmbedder` ou `OllamaEmbedder` | Calculateur de vecteurs dont la base lit la dimension et le nom. |
| `dim` | `any` | nombre de dimensions | Taille des vecteurs de l'embedder. Elle entre dans le nom des tables, pour que deux tailles ne se mélangent pas. |
| `model` | `any` | nom de l'embedder | Nom de l'embedder, enregistré avec chaque ligne et utilisé en filtre pour ne comparer que des vecteurs du même calculateur. |
| `chunks` | `any` | nom de table `rag_chunks_<dim>` | Table des passages du corpus fixe. |
| `memories` | `any` | nom de table `rag_memories_<dim>` | Table des souvenirs des agents. |
| `lore` | `str` | nom de table `rag_lore_<dim>` | Table des moments marquants de chaque partie. |
| `pool` | `None` | pool de connexions, ou `None` | Pool de connexions asyncpg. `None` tant que la base n'est pas ouverte (`open`) ou après sa fermeture. |

### Salon, bus et API HTTP / WebSocket

#### `Engine` · `filets/engine.py:304`

La boucle du salon : le moteur attend les commandes, prépare puis joue les parties l'une après l'autre et annonce son état.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `base_cfg` | `dict` | configuration fusionnée | La configuration de base (`config/default.yaml` et ses surcharges). Chaque partie en dérive sa propre configuration avec les choix du menu. |
| `bus` | `any` | `LocalBus` ou `KafkaBus` | Le bus par lequel le moteur publie son état et reçoit les commandes. Il dépend de `bus.kind`. |
| `quiet` | `bool` | `True` / `False` | Si vrai, le moteur n'écrit rien dans la console (pas d'affichage des événements ni du résumé). |
| `engine_id` | `str?` | 8 caractères hexadécimaux | Identifiant de ce moteur, donné à l'appel ou tiré au hasard. Il est joint à chaque état publié. |
| `catalog` | `any` | dict du menu | Ce dont le menu de démarrage a besoin (options, limites, composition de base). Il est remplacé quand une vallée est générée. |
| `state` | `str` | `idle`, `starting`, `running`, `paused`, `ended` | État du salon. Le moteur ne positionne lui-même que `idle`, `starting` et `ended`. |
| `error` | `str?` | texte ou `None` | Dernier refus ou échec de préparation, que l'interface affiche. Il est vidé dès qu'une nouvelle demande commence. |
| `end_reason` | `str?` | texte ou `None` | Raison de la fin de la dernière partie, ou « erreur : … » si elle s'est arrêtée sur une exception. |
| `last_run_id` | `str?` | identifiant de run | Identifiant de la dernière partie lancée. Il est publié comme `run_id` dans l'état. |
| `final_status` | `dict` | dict d'état | Dernier état de la partie terminée. Il est republié tant que le salon reste à `ended`. |
| `detail` | `str?` | texte ou `None` | Ce que le moteur fait pendant la préparation (par exemple le chargement d'un modèle). Évite que l'interface croie le moteur mort. |
| `world` | `None` | objet `World` ou `None` | La partie en cours de jeu. Elle vaut `None` hors partie. |
| `pub` | `IndicatorPublisher?` | objet ou `None` | Calculateur d'indicateurs interne, créé seulement avec un bus local. Avec Kafka, c'est le service d'indicateurs qui s'en charge, donc `None`. |

#### `LocalBus` · `filets/bus.py:50`

Le bus en mémoire (`bus.kind: local`), sans broker, avec la même interface que Kafka.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `_subs` | `dict` | `{topic: [fonctions]}` | Les abonnés en processus de chaque topic. Chaque message publié leur est transmis. |
| `_commands` | `queue.Queue` | file de dicts | Les commandes reçues, en attente d'être lues par `poll_commands`. |
| `counts` | `dict` | `{topic: nombre de messages}` | Combien de messages ont été publiés sur chaque topic depuis la création du bus. |

#### `KafkaBus` · `filets/bus.py:106`

Le bus Kafka (`bus.kind: kafka`) : le moteur y écrit les événements et y lit les commandes.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `topics` | `dict` | `{clé: nom du topic}` | Les noms de topics de `bus.topics` (par exemple `events` vers `filets.events`). Un topic absent du dict n'est pas écrit. |
| `producer` | `Producer` | objet confluent_kafka | Le producteur Kafka. Il est idempotent et attend l'accusé de tous les réplicas. |
| `_subs` | `dict` | `{topic: [fonctions]}` | Les abonnés en processus (calcul local, console), prévenus à chaque publication. |
| `_commands` | `queue.Queue` | file de dicts | Les commandes lues sur le topic des commandes par le fil de lecture, en attente de `poll_commands`. |
| `_stop` | `Event` | drapeau | Levé par `close` pour arrêter le fil de lecture des commandes. |
| `_thread` | `None` | `Thread` ou `None` | Le fil qui lit les commandes. Il vaut `None` si `consume_commands` est faux. |
| `commands_ready` | `Event` | drapeau | Levé quand le lecteur de commandes a reçu sa partition. Avant, une commande serait perdue : le moteur n'annonce son salon qu'après. |
| `consumer` | `Consumer` | objet confluent_kafka | Le lecteur du topic des commandes. Il n'existe que si `consume_commands` est vrai. |

#### `bus` · `filets/bus.py`

Le module du transport des événements : constantes sur les topics Kafka et la reprise de lecture.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `TOPIC_KEYS` | `tuple` | `events`, `indicators`, `commands`, `deadletter`, `status` | Les cinq clés de topics du jeu, celles de `bus.topics`. |
| `RETENTION_MS` | `dict` | `{clé de topic: millisecondes}` | Durée de conservation propre à un topic. Seul `status` y figure : une heure (3 600 000 ms). |
| `DEFAULT_RETENTION_MS` | `any` | millisecondes | Durée de conservation des autres topics : 7 jours (604 800 000 ms). |
| `_SCAN_CHUNK` | `int` | nombre de messages | Taille d'une tranche (2000) lue en remontant depuis la fin du topic pour retrouver le dernier `run_start`. |
| `OFFSET_BEGINNING` | `any` | `-2` | Valeur spéciale d'offset qui veut dire « lire le topic depuis son tout début ». |

#### `PublisherBus` · `filets/aio.py:103`

Une façade minimale (`publish`) sur un producteur aiokafka, pour le code synchrone des services (les indicateurs).

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `producer` | `any` | `AIOKafkaProducer` | Le producteur aiokafka qui envoie réellement les messages. |
| `topics` | `any` | `{clé: nom du topic}` | Les noms de topics de `bus.topics`. Un message pour un topic inconnu est ignoré. |
| `queue` | `asyncio.Queue` | tuples `(topic, valeur en octets, clé en octets)` | Les messages déposés par `publish` et pas encore envoyés. Une tâche les envoie dans l'ordre. |
| `_worker` | `any` | `asyncio.Task` | La tâche qui vide la file et envoie chaque message au broker. Elle est annulée à la fermeture. |

#### `aio` · `filets/aio.py`

Le module Kafka asynchrone des services (pont, indicateurs, historique).

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `_SCAN_CHUNK` | `int` | nombre de messages | Taille d'une tranche (2000) lue en remontant depuis la fin du topic des événements pour retrouver le dernier `run_start`. |

#### `Hub` · `filets/api.py:173`

Ce que tous les clients partagent : catalogue, dernier état, historique du run en cours et abonnés WebSocket.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `catalog` | `dict?` | dict ou `None` | Le catalogue du menu, relu depuis le dernier message de catalogue. `None` tant qu'aucun n'est connu. C'est une propriété. |
| `status` | `dict?` | dict ou `None` | Le dernier état publié par le moteur, relu depuis le dernier message d'état. `None` tant que le moteur ne s'est pas annoncé. C'est une propriété. |
| `on_command` | `Callable` | fonction (dict), éventuellement asynchrone | Ce qui reçoit une commande venue d'un client, pour la transmettre au moteur (publication sur le topic `commands`). |
| `clients` | `set` | ensemble de `WebSocket` | Les connexions WebSocket ouvertes, qui reçoivent chaque message diffusé. |
| `buffer` | `list` | liste de textes JSON | L'historique du run en cours (événements et indicateurs, tels qu'envoyés), rejoué aux clients qui se connectent en retard. Vidé à chaque `run_start`. |
| `buffer_max` | `int` | nombre de messages | Taille maximale de `buffer` (60 000 par défaut). Au-delà, les plus anciens sont jetés. |
| `loop` | `asyncio.AbstractEventLoop?` | boucle ou `None` | La boucle asyncio du concentrateur. Elle sert à pousser des messages depuis d'autres fils. `None` avant `start_hub`. |
| `queue` | `asyncio.Queue?` | tuples `(topic, type, run_id, ident, texte JSON)` | Les messages reçus par `push`, en attente d'être mémorisés puis diffusés dans l'ordre. |
| `_pump_task` | `asyncio.Task?` | tâche ou `None` | La tâche qui vide `queue`, met à jour l'historique et diffuse aux clients. |
| `_lock` | `Lock` | verrou asyncio | Empêche qu'un client reçoive le direct avant l'historique : la diffusion et la connexion d'un client ne se chevauchent pas. |
| `_catalog_msg` | `any` | texte JSON ou `None` | Le dernier message de catalogue tel qu'envoyé aux clients. Il est rediffusé seulement s'il change. |
| `last_status` | `str?` | texte JSON ou `None` | Le dernier message d'état, rejoué à chaque nouveau client. Seul le dernier est gardé. |
| `current_run` | `str?` | identifiant de run | Le run en cours, pris au dernier `run_start`. Il sert à écarter les indicateurs d'un autre run. |
| `_seen_indicators` | `set` | ensemble de textes `run_id\|trigger\|source_event_id` | Les indicateurs déjà reçus pour ce run. Un indicateur republié (service relancé) est ignoré. |

#### `ApiServer` · `filets/api.py:422`

Le concentrateur et son serveur HTTP/WebSocket (FastAPI et uvicorn), dans la boucle asyncio de l'appelant.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `port` | `int` | numéro de port | Le port réellement ouvert (utile si on a demandé le port 0). C'est une propriété. |
| `host` | `any` | adresse IP | L'adresse d'écoute, `api.host` (127.0.0.1 par défaut : l'API n'a aucune authentification). |
| `_port` | `any` | numéro de port | Le port demandé au démarrage. 0 veut dire « un port libre ». |
| `runs` | `any` | `LocalRuns` ou `None` | La source des runs enregistrés, servie par `/api/runs`. Sans elle, ces routes répondent 501. |
| `memories` | `any` | `PgMemories` ou `None` | La recherche dans la mémoire collective (`rag.backend: pgvector`). `None` sinon, et la route répond 501. |
| `app` | `FastAPI?` | application ou `None` | L'application FastAPI, créée au démarrage. |
| `_server` | `_Server?` | serveur uvicorn ou `None` | Le serveur uvicorn qui écoute. Il sert aussi à lire le port ouvert et à demander l'arrêt. |
| `_serve_task` | `asyncio.Task?` | tâche ou `None` | La tâche qui fait tourner le serveur. Elle est attendue à l'arrêt. |

#### `LocalRuns` · `filets/api.py:80`

Les runs du dossier `runs/` : un dossier par run, lu par les routes `/api/runs`.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `dir` | `Path` | chemin de dossier | Le dossier des runs, `output.runs_dir` (`runs/` par défaut), dans lequel chaque run a son sous-dossier. |

#### `PgMemories` · `filets/api.py:134`

La mémoire collective des runs dans PostgreSQL + pgvector (`rag.backend: pgvector`), interrogée par le sens.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `cfg` | `dict` | configuration | La configuration complète, qui donne l'adresse de la base et le modèle de vectorisation (`rag`). |
| `store` | `None` | `PgVectorStore` ou `None` | Le magasin de vecteurs. Il s'ouvre à la première question et se referme à l'arrêt, d'où `None` avant et après. |
| `lock` | `Lock` | verrou asyncio | Évite d'ouvrir la connexion deux fois si deux questions arrivent en même temps. |

#### `Command` · `filets/api.py:46`

Le corps de la requête `POST /api/commands` : une commande pour le moteur.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `model_config` | `ConfigDict` | réglage pydantic | Accepte des champs en plus de `type` (`value`, `text`, `factor`, `config`) et fournit les exemples de la page `/docs`. |
| `type` | `Literal` | `drought`, `set_communication`, `set_visibility`, `announcement`, `pause`, `resume`, `set_speed`, `set_mode`, `stop`, `start_game`, `new_game`, `generate_world` | La nature de la commande. Une autre valeur est refusée. |

#### `Accepted` · `filets/api.py:55`

La réponse (code 202) de `POST /api/commands` quand la commande a été transmise au moteur.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `accepted` | `bool` | toujours `True` | Le client lit ici que la commande a bien été transmise. Les refus sortent en erreur HTTP (422, 503). |
| `type` | `str` | un des types de commande | Le type de la commande acceptée, renvoyé tel que reçu. |

#### `Health` · `filets/api.py:60`

La réponse de `GET /api/health` : un contrôle rapide de l'API.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `status` | `str` | `ok` | Toujours `ok` : le client y lit que l'API répond. |
| `clients` | `int` | nombre de connexions | Combien de clients WebSocket sont connectés en ce moment. |
| `run_id` | `str?` | identifiant ou `None` | Le run en cours vu par l'API, ou `None` si aucun `run_start` n'est passé. |
| `engine_state` | `str?` | `idle`, `starting`, `running`, `paused`, `ended` ou `None` | L'état du moteur dans son dernier message. `None` si le moteur ne s'est pas encore annoncé. |

#### `RunSummary` · `filets/api.py:67`

Une ligne de la liste `GET /api/runs` : le résumé d'un run enregistré, lu dans son `summary.json`.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `run_id` | `str` | identifiant | Le nom du dossier du run. |
| `finished` | `bool` | `True` / `False` | Vrai si le run a un `summary.json`, donc s'il est terminé. Les champs suivants sont vides sinon. |
| `reason` | `str?` | texte ou `None` | Pourquoi la partie s'est arrêtée (par exemple fin des saisons ou effondrement). |
| `seasons_completed` | `int?` | nombre de saisons | Combien de saisons ont été jouées. |
| `final_stock` | `float?` | tonnes | Le stock de poisson restant dans les lacs à la fin. |
| `capacity` | `float?` | tonnes | La capacité maximale du ou des lacs. À rapporter à `final_stock`. |
| `llm_calls` | `int?` | nombre d'appels | Combien d'appels au modèle d'IA pendant la partie. |
| `wall_s` | `float?` | secondes réelles | Durée réelle de la partie. |
| `by_system` | `dict?` | `{"S1": {calls, tokens}, "S2": {calls, tokens}}` | Les appels et les jetons selon le système de réflexion : S1 (réflexe) et S2 (réflexion). |

#### `api` · `filets/api.py`

Le module de l'API REST et WebSocket de FILETS.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `RUN_ID` | `any` | expression régulière | Format permis d'un identifiant de run dans une URL : lettres, chiffres, point, tiret ou tiret bas, commençant par un caractère alphanumérique. Il évite d'aller lire hors du dossier des runs. |

### Événements, indicateurs et stockage

#### `EventFactory` · `filets/events.py:35`

La fabrique d'événements d'un run : elle numérote, valide, publie et enregistre chaque événement.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `run_id` | `str` | identifiant de run | Le run auquel appartiennent les événements. Il entre dans leur `event_id`. |
| `clock` | `SimClock` | horloge de la partie | Donne le temps simulé, l'étiquette de saison et le temps réel écoulé de chaque événement. |
| `bus` | `any` | `LocalBus` ou `KafkaBus` | Où les événements sont publiés (topic `events`, ou `deadletter` s'ils sont invalides). |
| `recorder` | `Recorder?` | enregistreur ou `None` | Écrit chaque événement dans `events.jsonl`. `None` si la partie n'enregistre pas. |
| `seq` | `int` | numéro d'ordre | Compteur des événements émis. Chaque événement reçoit le suivant, et son `event_id` est `<run_id>-` suivi de ce numéro sur 6 chiffres. |
| `index` | `dict` | `{event_id: événement}` | Tous les événements émis, pour retrouver les sources d'une décision et vérifier la cohérence du temps. |
| `when` | `None` | fonction ou `None` | Fonction qui écrit un instant en toutes lettres (`World.when`). Quand elle est définie, elle remplit `sim_text`. Sinon, l'horloge s'en charge. |
| `deadletters` | `int` | nombre d'événements | Combien d'événements non conformes au schéma ont été écartés vers `deadletter`. |
| `renamed` | `dict` | `{identifiant provisoire: identifiant définitif}` | Pour les événements mis en attente : nom provisoire (`<run_id>-p1`) vers nom définitif. Sert à corriger les références. |
| `_tmp` | `int` | compteur | Compteur des identifiants provisoires donnés aux événements mis en attente. |

#### `Recorder` · `filets/events.py:14`

Écrit tous les événements d'un run dans `runs/<run_id>/events.jsonl`, source du rejeu.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `run_dir` | `Path` | chemin de dossier | Le dossier du run (`output.runs_dir` puis `<run_id>`). Il est créé s'il n'existe pas. |
| `_f` | `any` | fichier texte ouvert | Le fichier `events.jsonl`, ouvert en ajout. Une ligne JSON par événement. |

#### `IndicatorPublisher` · `filets/pipeline.py:16`

Met les indicateurs sous forme de messages, mesure leur décalage, les publie et les écrit dans un journal du run.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `engine` | `IndicatorEngine` | calculateur | Le calculateur qui transforme les événements en indicateurs. Il reçoit `scenario.quota_tolerance`. |
| `bus` | `any` | bus ou `PublisherBus` | Où les indicateurs sont publiés (topic `indicators`). |
| `runs_dir` | `any` | `Path` | Le dossier des runs (`output.runs_dir`, rapporté à la racine du projet). Le journal du run y est écrit. |
| `journal` | `bool` | `True` / `False` | Si vrai (par défaut), chaque indicateur est aussi écrit dans un fichier du run. |
| `journal_name` | `str` | `indicators.jsonl` par défaut | Nom du fichier journal. Un rejeu écrit toujours dans `indicators_replay.jsonl`. |
| `_f` | `None` | fichier ouvert ou `None` | Le fichier journal du run en cours. Il est rouvert, vidé, à chaque `run_start`. |
| `_run` | `None` | identifiant de run ou `None` | Le run dont le journal est ouvert. |
| `lags` | `list` | secondes réelles | Pour chaque indicateur, le temps entre la publication de l'événement source et son calcul. Mesure le retard du service. |

#### `IndicatorEngine` · `filets/indicators.py:36`

Calcule les indicateurs à partir des seuls événements d'un run (stock, normes, respect des règles, coût des IA). Tout est remis à zéro à chaque `run_start`.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `tol` | `float` | tonnes | Marge ajoutée à un quota avant de parler de dépassement (`scenario.quota_tolerance`, 0,05 t). |
| `run_id` | `None` | identifiant ou `None` | Le run suivi, pris au `run_start`. `None` avant. Un événement d'un autre run est ignoré. |
| `skipped` | `int` | nombre d'événements | Événements ignorés parce qu'ils sont arrivés sans le `run_start` de leur run. |
| `capacity` | `float` | tonnes | Capacité du lac (`lake.capacity` du `run_start`). Sert à calculer la part de stock. |
| `msy` | `float` | tonnes par saison | Prise durable maximale du lac (`sustainable_yield` du `run_start`). |
| `fishers` | `dict` | `{id du pêcheur: fiche}` | Les pêcheurs du `run_start` (fiche d'agent), dont la richesse est mise à jour à chaque vente et fin de saison. |
| `stock` | `float` | tonnes | Stock de poisson courant, mis à jour par `lake_update` et `season_end`. |
| `season` | `int` | numéro de saison | La saison en cours, prise au dernier `season_start`. |
| `catches` | `dict` | `{saison: {pêcheur: tonnes}}` | Les tonnes débarquées par chaque pêcheur, cumulées par saison. |
| `catch_ids` | `dict` | `{saison: [event_id]}` | Les événements de prise de chaque saison. Ce sont les sources de l'indicateur de fin de saison. |
| `fished` | `dict` | `{saison: {pêcheur: nom du lac}}` | Le lac où chaque pêcheur a pêché dans la saison. Une règle de lac ne vise que ceux qui y ont pêché. |
| `norms` | `list` | liste de dicts | Les règles adoptées à la veillée (événements `norm_adopted`), avec l'`event_id` de l'adoption. |
| `breaches` | `dict` | `{saison: {pêcheur: ensemble de types de règle}}` | Les infractions aux règles de pêche (zone réservée, repos, sortie, taille de bateau) relevées dans les prises. |
| `promise_outcomes` | `list` | liste de dicts | Les bilans de promesses (`promise_outcome`) : promis, débarqué, tenue ou non. |
| `incidents` | `dict` | `{type d'incident: nombre}` | Combien d'incidents de chaque type ont été signalés. |
| `llm` | `dict` | `{calls, tokens, latency_s, errors, cancelled}` | Totaux des appels au modèle : nombre, jetons, latence en secondes réelles, erreurs, appels annulés. |
| `by_system` | `dict` | `{"S1": {calls, tokens}, "S2": {calls, tokens}}` | Les mêmes totaux séparés entre S1 (réflexe) et S2 (réflexion). |
| `events_by_id` | `dict` | `{event_id: {sim_time, type}}` | Le temps simulé et le type de chaque événement vu. Sert à vérifier qu'une décision n'utilise rien de postérieur à son horizon d'information. |
| `temporal_violations` | `int` | nombre | Informations utilisées alors qu'elles dataient d'après l'horizon de la décision, ou incidents du même nom. Doit rester à 0. |
| `staleness` | `list` | parts de la capacité (0 à 1) | Pour chaque prise, l'écart de stock entre l'observation et l'action, divisé par la capacité. Mesure le retard de l'information. |
| `utterances` | `int` | nombre de paroles | Combien de paroles ont été dites. |
| `accusations` | `int` | nombre | Combien d'accusations ont été portées. |
| `history` | `list` | liste de dicts | Les valeurs de l'indicateur de fin de saison, une par saison terminée. |
| `last_values` | `dict` | dict de valeurs | Les valeurs du dernier indicateur calculé. |
| `collapsed` | `bool` | `True` / `False` | Vrai quand la vallée est effondrée, c'est-à-dire quand tous ses lacs le sont. |
| `lakes` | `dict` | `{nom du lac: {label, capacity, stock, collapsed}}` | Le détail par lac. Il n'est rempli que s'il y a plus d'un lac, sinon il reste vide. |
| `lake_catch` | `dict` | `{saison: {nom du lac: tonnes}}` | Les prises de chaque saison réparties par lac. |

#### `schemas` · `filets/schemas.py`

Le module du contrat d'événements : schémas JSON des événements, des commandes et de l'état du moteur.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `SCHEMA_VERSION` | `int` | `1` | Version du contrat, écrite dans chaque événement. Un événement d'une autre version est refusé. |
| `NUM` | `dict` | schéma JSON | Un nombre. |
| `NUM_OR_NULL` | `dict` | schéma JSON | Un nombre ou `null`. |
| `STR` | `dict` | schéma JSON | Un texte. |
| `STR_OR_NULL` | `dict` | schéma JSON | Un texte ou `null`. |
| `INT` | `dict` | schéma JSON | Un entier. |
| `BOOL` | `dict` | schéma JSON | Un booléen. |
| `IDS` | `dict` | schéma JSON | Une liste de textes, typiquement des identifiants. |
| `RETRIEVED` | `dict` | schéma JSON | Les passages retrouvés par la recherche de mémoire pour une décision. Chacun a `id`, `source` (`corpus`, `memory`, `pinned`, `rumor`, `lore`), `score`, `sim_time` et éventuellement `text`. |
| `ENVELOPE` | `any` | schéma JSON | L'enveloppe commune à tous les événements : type, version, `event_id`, `run_id`, `seq`, temps simulé, saison, temps réel, acteur, `payload`. Le client la lit sur chaque événement. |
| `PAYLOADS` | `dict` | `{type d'événement: schéma}` | Le schéma du contenu (`payload`) de chaque type d'événement (`run_start`, `catch`, `indicator`…). Un type absent est refusé. |
| `COMMAND_TYPES` | `list` | liste de textes | Les types de commandes permis : injections, pilotage (pause, vitesse…) et salon (`start_game`, `new_game`, `generate_world`). |
| `COMMAND` | `any` | schéma JSON | Une commande : un `type` de la liste, avec `value`, `text`, `factor` ou `config` selon le cas. |
| `STATUS` | `any` | schéma JSON | Le message d'état du moteur : `state`, `engine_id`, `wall_clock`, puis run, mode, vitesse, pause, saison, `catalog`, etc. L'interface y lit s'il faut montrer le menu. |

#### `HistoryStore` · `filets/store.py:76`

L'historique des parties dans SQLite (`storage.history: sqlite`, fichier `output.history_db`).

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `db` | `any` | connexion `sqlite3` | La connexion à la base. Les tables `runs`, `events` et `indicators` et les vues d'analyse y sont créées à l'ouverture. |

#### `PgHistoryStore` · `filets/pgstore.py:71`

L'historique des parties dans PostgreSQL (`storage.history: postgres`), avec écriture groupée.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `pending` | `int` | nombre de lignes | Combien de lignes (événements, runs, indicateurs) attendent d'être écrites. C'est une propriété. |
| `dsn` | `str` | adresse PostgreSQL | L'adresse de connexion (`storage.postgres.dsn`, ou la variable `FILETS_PG_DSN`). |
| `pool` | `None` | pool asyncpg ou `None` | Les connexions à la base. Il est ouvert par `open` et remis à `None` à la fermeture. |
| `_events` | `list` | tuples de 11 valeurs | Les lignes d'événements en attente d'écriture dans la table `events`. |
| `_runs` | `list` | `[("start" ou "end", valeurs)]` | Les créations et clôtures de runs en attente, dans l'ordre. Un `end` suit toujours son `start`. |
| `_indicators` | `list` | tuples de 9 valeurs | Les lignes d'indicateurs en attente d'écriture dans la table `indicators`. |

#### `_SqliteAsync` · `filets/services/store.py:26`

La base SQLite présentée avec la même interface que `PgHistoryStore`, pour le service d'historique.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `db` | `HistoryStore` | objet | La base SQLite sous-jacente. |
| `add_event` | `any` | méthode | Raccourci vers `HistoryStore.add_event`, qui ajoute un événement. |
| `add_indicator` | `any` | méthode | Raccourci vers `HistoryStore.add_indicator`, qui ajoute un indicateur. |

#### `LocalObjects` · `filets/objects.py:36`

Un dossier qui imite un magasin d'objets (`storage.objects.kind: local`) : la clé est le chemin relatif.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `root` | `Path` | chemin de dossier | Le dossier racine (`storage.objects.root`, `data/objects` par défaut). Aucune clé ne peut en sortir. |
| `where` | `str` | chemin | Le même dossier en texte, cité dans les messages d'erreur. |

#### `S3Objects` · `filets/objects.py:76`

Un magasin d'objets compatible S3 (`storage.objects.kind: s3`), par exemple MinIO.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `bucket` | `str` | nom du seau | Le seau où sont rangés les objets (`storage.objects.bucket`). Il est créé s'il n'existe pas. |
| `where` | `str` | URL `http(s)://point d'accès/seau` | Où se trouve le stockage, cité dans les messages d'erreur. |
| `client` | `Minio` | client asynchrone | Le client miniopy-async qui parle au service S3. |

#### `objects` · `filets/objects.py`

Le module du stockage objet des fichiers bruts (corpus et archives de parties).

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `RUN_FILES` | `tuple` | `events.jsonl`, `indicators.jsonl`, `config.json`, `summary.json` | Les fichiers d'une partie déposés dans le magasin d'objets, sous la clé `runs/<run_id>/<fichier>`. |

### Services, configuration, ligne de commande, banc

#### `config` · `filets/config.py`

Le module qui charge la configuration YAML, avec héritage et surcharges.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `ROOT` | `any` | `Path` | La racine du projet (le dossier au-dessus du paquet `filets`). Les chemins relatifs de la configuration (`runs/`, `data/`, `config/`) s'y rapportent. |

#### `catalog` · `filets/catalog.py`

Le module du catalogue envoyé au menu de démarrage : une seule source pour les options et les limites.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `LIMITS` | `dict` | `{nom: [minimum, maximum]}` | Les bornes de chaque réglage du menu (villages, pêcheurs, lacs, saisons, graine, capacité en tonnes, taux de repeuplement…). Le moteur y vérifie les demandes. |
| `SPEEDS` | `list` | multiplicateurs de vitesse (0,0625 à 16) | Les vitesses de jeu proposées. Les lentes laissent à une IA locale le temps de répondre. |
| `LLM_OPTIONS` | `list` | liste de dicts `{id, label, config, async_speed, reflection, detail}` | Les moteurs d'IA proposés (`scripted`, `ollama_fast`, `ollama_open`, `ollama`, `groq`), avec leur fichier de configuration et la vitesse conseillée. |
| `REFLECTIONS` | `list` | `rapide`, `adaptive`, `complete` | Les modes de réflexion des IA, avec leur description pour le menu. |
| `MODES` | `list` | `unique`, `sync`, `async` | Les modes de temps connus. Elle ne sert plus qu'à valider d'anciennes demandes : le catalogue ne la publie plus. |
| `COMMUNICATIONS` | `list` | `valley`, `hamlet`, `none` | Les formes de communication entre pêcheurs : conseil de la vallée, par village, interdite. |
| `COUNCILS` | `list` | `delegates`, `all` | Qui va au conseil de la vallée : un élu par village, ou tous les pêcheurs. |
| `FLEETS` | `list` | `petits`, `mixte`, `gros` | Les flottes de la vallée générée. Chacune donne la répartition des bateaux (`barque`, `chaloupe`, `cotre`), `mixte` suivant `population.boat_mix`. |

### Interface Godot (scripts GDScript et shader)

#### `Main` · `godot/scripts/main.gd:8`

Scène principale : construit toute l'interface, reconstruit l'état du monde à partir des événements du moteur et envoie les ordres du joueur.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `ws` | `Variant` | instance de `ws_client.gd` | Le client WebSocket vers le moteur. Il est créé au démarrage, avec l'option `--url=`. Absent en mode démo. |
| `world` | `Variant` | instance de `world_view.gd` | La carte isométrique de la vallée, à gauche de l'écran. Un clic sur un pêcheur appelle `_select`. |
| `chart` | `Variant` | instance de `chart.gd` | Le graphique des courbes par saison, sous les cartes d'indicateurs. |
| `menu` | `Variant` | instance de `start_menu.gd` | Le menu de démarrage, affiché par-dessus toute l'interface. |
| `legend` | `Control` | instance de `legend.gd` | La légende en bas de l'écran, sous la barre « INTERVENIR ». Elle liste les villages, les types de modèle et les couleurs d'interaction. |
| `run` | `Dictionary` | `{id, mode, capacity, replay}` | Les données de la partie en cours, remplies au début du run. `capacity` est la capacité du lac en tonnes et `replay` vaut `true` pour un rejeu. |
| `agents` | `Dictionary` | `{id d'agent: fiche}` | Une fiche par agent (`info`, `catches`, `promises`, `memories`, `last_decision`, `wealth`, `reputation`, `trust_from`, etc.). Elle est remplie au début du run puis mise à jour à chaque événement. |
| `WS` | `Script` | constante, `ws_client.gd` | Le script du client WebSocket, chargé une fois. |
| `WorldView` | `Script` | constante, `world_view.gd` | Le script de la carte. |
| `Chart` | `Script` | constante, `chart.gd` | Le script du graphique. |
| `Legend` | `Script` | constante, `legend.gd` | Le script de la légende. |
| `StartMenu` | `Script` | constante, `start_menu.gd` | Le script du menu de démarrage. |
| `SPEEDS` | `Array` | `[0.0625 … 16.0]` (facteurs de vitesse) | Les vitesses proposées par les boutons de la barre de pilotage. Un bouton « Max » s'y ajoute. |
| `INCIDENT_LABELS` | `Dictionary` | `{nom technique: libellé français}` | Traduit les types d'incident du moteur (`out_of_role`, `quota`, `missed_window`…) pour le fil des interactions. |
| `BREACH_WORD` | `Dictionary` | `{type d'infraction: texte}` | Traduit les infractions aux règles (`quota`, `reserve`, `repos`, `sorties`, `bateau`) en texte lisible. |
| `KPI_SUB` | `Dictionary` | `{clé de carte KPI: sous-titre}` | Le sous-titre par défaut de chaque carte d'indicateur. Il est remis en place au début d'un run. |
| `lbl_run` | `Label` | texte | Étiquette en haut à droite de l'en-tête, avant l'état de connexion. Elle montre l'id du run, le nombre de pêcheurs et « REJEU » si c'est un rejeu. Avant cela : « en attente d'un run… ». |
| `lbl_clock` | `Label` | texte, toujours masqué | Ancienne horloge de l'en-tête. Elle est cachée (l'horloge est sur la carte) et gardée pour compatibilité. |
| `lbl_status` | `Label` | texte | Le cadre arrondi tout à droite de l'en-tête. Il affiche l'état de la connexion au moteur (« ● connecté », « ○ déconnecté »), vert ou rouge. |
| `ind_labels` | `Dictionary` | `{clé de carte KPI: Label}` | La grosse valeur de chaque carte d'indicateur du tableau de bord (stock, norme, promesses, accord, conformité, incidents…). |
| `feed` | `RichTextLabel` | texte BBCode | Le fil de l'onglet « Interactions » du panneau de droite. Il montre les événements de la partie, saison après saison. |
| `narration` | `RichTextLabel` | texte BBCode | L'onglet « Récit du narrateur ». Le narrateur y raconte chaque saison, suivi de la ligne « En chiffres » : chiffres exacts ajoutés au récit par le code (`World.narrator_figures`), jamais écrits par le modèle. |
| `trust_view` | `RichTextLabel` | texte BBCode | Le contenu de l'onglet « Confiance » : jauges de confiance, vraies prises et déclarations. |
| `trust_dirty` | `bool` | `true` / `false` | Indique que l'onglet Confiance doit être redessiné. Le test est refait toutes les 0,2 s, sauf pendant un rattrapage. |
| `trust_mode` | `String` | `"avg"` \| `"from"` | `"avg"` donne la confiance moyenne que les autres accordent à chacun. `"from"` donne la confiance qu'un personnage accorde aux autres. |
| `trust_observer` | `String` | id d'agent, ou `""` | Le personnage dont on lit la confiance en mode `"from"`. C'est le dernier agent sélectionné. |
| `trust_who` | `OptionButton` | liste de prénoms | La liste déroulante de l'onglet Confiance, à droite des deux boutons de mode. Elle sert à choisir le personnage observé et n'est visible qu'en mode `"from"`. |
| `feed_only_selected` | `CheckBox` | coché / non coché | La case « Seulement l'agent sélectionné », en haut de l'onglet Interactions. Cochée, le fil ne garde que les lignes de l'agent choisi. |
| `inspector` | `RichTextLabel` | texte BBCode | L'onglet « Agent » : la fiche détaillée du personnage sélectionné. |
| `rules_view` | `RichTextLabel` | texte BBCode | L'onglet « Règles » : propositions en cours, règles en vigueur et historique des règles adoptées. |
| `tabs` | `TabContainer` | onglets | Le conteneur à onglets du panneau de droite : Interactions, Récit du narrateur, Confiance, Agent, Règles. Un clic sur un agent ouvre l'onglet Agent. |
| `comm_opt` | `OptionButton` | `"valley"` \| `"hamlet"` \| `"none"` | La liste « Communication » de la barre « INTERVENIR » : conseil de la vallée, par village, interdite. Le choix envoie `set_communication` au moteur. |
| `vis_check` | `CheckButton` | `true` / `false` | L'interrupteur « Déclarations publiques » de la barre « INTERVENIR ». Il envoie `set_visibility` (scénario `catches_visible`). |
| `lbl_weather` | `Label` | texte, par ex. « Temps : tempête » | Étiquette de la barre « INTERVENIR » donnant le temps du jour sur le lac. Elle est rouge pour une tempête, orange pour un temps agité, grise sinon. |
| `weather_days` | `Array` | liste de textes, un par jour de pêche | Le temps de chaque jour de pêche de la saison en cours, publié au début de la saison. |
| `weather_season` | `int` | numéro de saison, 0 = aucune | La saison à laquelle correspond `weather_days`. |
| `lbl_patrol` | `Label` | texte | Étiquette de la barre « INTERVENIR » : « Patrouille : aucune », « dès la saison N » ou « en route vers… ». Elle est masquée si le scénario désactive la patrouille. |
| `patrol_texts` | `Dictionary` | `{capitaine: route en texte}` | La route de chaque patrouille cette saison. Elle est vidée à chaque nouvelle saison. |
| `lake_labels` | `Dictionary` | `{nom du lac: nom en toutes lettres}` | Par exemple « Lac d'Orsane ». Elle est remplie à partir de la liste des lacs du run. |
| `patrol_text_season` | `int` | numéro de saison | La saison des routes gardées dans `patrol_texts`. Elle sert à les effacer quand la saison change. |
| `patrol_installed` | `bool` | `true` / `false` | Vaut `true` si le conseil a voté la patrouille. Remis à `false` à chaque nouvelle partie. |
| `reps` | `Dictionary` | `{village: id du pêcheur élu}` | L'élu de chaque village au conseil de la vallée. L'inspecteur y lit la mention « élu au conseil ». |
| `rumor_edit` | `LineEdit` | texte libre | Le champ de la barre « INTERVENIR » (« Faire courir une rumeur dans la vallée… »). Le bouton « Diffuser » ou la touche Entrée l'envoie comme `announcement`. |
| `Demo` | `Script` | constante, `demo.gd` | Le script du lecteur de la vidéo de démonstration, chargé une fois. |
| `demo_path` | `String` | chemin ou vide | L'option `--demo=scénario.json`. Non vide : aucune connexion au moteur, et `Main` crée un `Demo` et le démarre. |
| `feed_groups` | `Dictionary` | clé -> `{"agg": cumul, "line": ligne du fil}` | Les groupes du fil des interactions : une ligne par pêcheur et par jour (les retours de pêche s'y regroupent). Vidée au `run_start` et au-delà de 600 groupes. |
| `feed_lines` | `Array` | `[{"text": BBCode, "ids": [id d'agent]}]` | Toutes les lignes du fil. Elle est coupée à 1200 lignes quand elle dépasse 1500. |
| `proposals` | `Dictionary` | `{id de proposition: {author, quota, supporters, scope, text}}` | Les propositions de règle de la veillée en cours. Elle est vidée à la fin de la veillée. |
| `norms` | `Array` | liste d'événements `norm_adopted` | L'historique de toutes les règles adoptées. |
| `norms_now` | `Array` | liste de règles | Les règles en vigueur, une par portée, type et cible. Une règle adoptée remplace celle qui a les mêmes. |
| `selected` | `String` | id d'agent, ou `""` | L'agent choisi par un clic sur la carte. Il sert à l'inspecteur, au filtre du fil et à la vue de confiance. |
| `inspector_dirty` | `bool` | `true` / `false` | Indique que l'onglet Agent doit être redessiné. |
| `feed_dirty` | `bool` | `true` / `false` | Indique que le fil de l'onglet Interactions doit être redessiné. |
| `catching_up` | `int` | nombre de messages | Nombre de messages de l'historique qui restent à rejouer à la connexion. Tant qu'il est positif, la carte n'est pas animée et les onglets ne sont pas redessinés. |
| `t0_ms` | `int` | millisecondes | Heure de démarrage du programme (`Time.get_ticks_msec`). Sert aux délais des options de capture. |
| `n_events` | `int` | compteur | Nombre d'événements reçus. Sert au bilan de `--selftest`. |
| `n_indicators` | `int` | compteur | Nombre de messages d'indicateurs reçus. Sert au bilan de `--selftest`. |
| `last_sim_label` | `String` | texte de date simulée, « — » au départ | La dernière date simulée publiée par le moteur (`sim_label`). Elle sert à dater les lignes du fil et les souvenirs. |
| `selftest` | `float` | secondes réelles, -1 = désactivé | Option `--selftest=SECONDES` : après ce délai le programme imprime un bilan et quitte. |
| `shot_path` | `String` | chemin de fichier PNG | Option `--shot=` : capture d'écran enregistrée à la fin du selftest. |
| `shots` | `Array` | secondes réelles | Option `--shots=4,9,15` : les instants de capture. La liste est vidée au fur et à mesure. |
| `shot_dir` | `String` | chemin de dossier | Option `--shotdir=` : le dossier où l'on range les captures de `shots`. |
| `autostart` | `float` | secondes réelles, -1 = désactivé | Option `--autostart=` : délai avant de lancer automatiquement la partie proposée par le menu, pour les essais. |
| `view_zoom` | `float` | facteur de zoom, 1.0 = aucun | Option `--zoom=` : zoom de la carte sur son centre, pour les captures. Remis à 1.0 une fois appliqué. |
| `view_mesh` | `bool` | `true` / `false` | Option `--mesh` : montre les mailles de la carte pour les captures. |
| `autostart_at` | `float` | secondes réelles depuis le démarrage, -1 = non fixé | L'instant où `autostart` se déclenchera, calculé quand le catalogue est reçu. |
| `menu_shot` | `String` | chemin de fichier PNG | Option `--menu-shot=` : capture du menu de démarrage une fois affiché. |
| `catalog` | `Dictionary` | catalogue publié par le moteur | Le catalogue des options du menu (villages, profils, modèles). Il est transmis au menu. |
| `engine` | `Dictionary` | topic `status` | Le dernier état publié par le moteur : `state`, `speed`, `fast`, `season`, `seasons`, `thinking`, `controls`, `lobby`, `detail`, `error`. |
| `engine_seen_ms` | `int` | millisecondes (`Time.get_ticks_msec`) | L'instant d'arrivée du dernier `status`. Le moteur le répète toutes les 2 s, d'où un détecteur de silence (8 s, 150 s au démarrage). |
| `engine_state` | `String` | `""` \| `"idle"` \| `"starting"` \| `"running"` \| `"paused"` \| `"ended"` | L'état du moteur. `""` signifie inconnu ou déconnecté. |
| `ws_ok` | `bool` | `true` / `false` | Vaut `true` quand la connexion WebSocket est ouverte. |
| `last_error` | `String` | texte, ou `""` | La dernière erreur publiée par le moteur. Sert à ne pas afficher deux fois la même dans le menu. |
| `transport` | `PanelContainer` | — | La barre de pilotage sous l'en-tête : pause, vitesses, « N en réflexion », progression, arrêt. Elle n'est visible que si le moteur propose des commandes et n'est pas inactif. |
| `btn_pause` | `Button` | « Pause » / « Reprendre » | Le premier bouton de la barre de pilotage. Il met la partie en pause ou la reprend (raccourci Espace). |
| `btn_stop` | `Button` | « Arrêter la partie » | Bouton de la barre de pilotage, visible pendant la partie. Il ouvre la boîte de confirmation d'arrêt. |
| `btn_stop_top` | `Button` | « Arrêter la partie » | Le même arrêt, en haut à droite, par-dessus le menu de démarrage. Masqué au départ. |
| `stop_dlg` | `ConfirmationDialog` | — | La boîte « Arrêter la partie ? Elle ne pourra pas être reprise. ». Si on confirme, l'ordre `stop` part au moteur. |
| `btn_new` | `Button` | « Nouvelle partie » | Bouton de la barre de pilotage, visible quand la partie est finie et que le moteur accepte une nouvelle partie. Il rouvre le menu. |
| `speed_buttons` | `Dictionary` | `{vitesse (float) ou "max": Button}` | Les boutons de vitesse de la barre de pilotage. Celui de la vitesse active est enfoncé, et tous sont grisés hors partie. |
| `lbl_progress` | `Label` | texte | Sur la barre de pilotage : « Saison N / M · date », ou le détail de préparation du moteur. |
| `lbl_thinking` | `Label` | « N en réflexion » | Sur la barre de pilotage : le nombre d'agents dont une décision est en cours (`status.thinking`). |
| `end_overlay` | `Control` | — | La carte de fin de partie, centrée par-dessus la carte de la vallée. Elle laisse passer les clics et se ferme avec le bouton qui masque la carte de fin. |
| `end_title` | `Label` | « Partie terminée » / « Partie arrêtée » | Le titre de la carte de fin de partie. |
| `end_text` | `Label` | texte | Le corps de la carte de fin : la raison de l'arrêt, la date simulée et le stock final. |
| `end_new` | `Button` | « Nouvelle partie » | Le bouton de la carte de fin de partie. Il n'est visible que si le moteur accepte une nouvelle partie. |
| `ind_sub` | `Dictionary` | `{clé de carte KPI: Label}` | La ligne de détail sous la valeur de chaque carte d'indicateur (par ex. « 12 sur 20 la respectent »). |
| `ind_title` | `Dictionary` | `{clé de carte KPI: Label}` | Le titre de chaque carte d'indicateur. Celui du stock passe de « STOCK DU LAC » à « STOCK DES LACS » avec plusieurs lacs. |
| `end_status` | `Dictionary` | topic `status` à la fin | Le dernier état du moteur à la fin de la partie (`end_reason`, `sim_label`, `lobby`). Il sert à écrire le texte de fin. |
| `_acc` | `float` | secondes réelles | Compteur de temps pour le rafraîchissement des onglets (fil, inspecteur, confiance), toutes les 0,2 s. |

#### `Demo` · `godot/scripts/demo.gd:4`

Lecteur de la vidéo de démonstration (lancé avec `--demo=scénario.json`, et `--write-movie` pour enregistrer) : rejoue un journal dans `main._on_event` au rythme du scénario, pilote la caméra, les mailles, l'onglet et l'inspecteur, lit la voix et affiche le sous-titre. Il compte en temps de vidéo, pas en horloge réelle.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `main` | `Variant` | instance de `main.gd` | La scène principale, que le lecteur pilote (`main._on_event`, onglet, inspecteur). Réglé par `start`. |
| `beats` | `Array` | liste de temps du scénario | Les temps du scénario (`beats`), lus dans le fichier `--demo=`. |
| `events` | `Array` | événements du journal | Le journal de la partie rejoué, lu ligne à ligne. |
| `next_ev` | `int` | indice | Le prochain événement à rejouer. |
| `inds` | `Array` | indicateurs | Les indicateurs (cartes KPI, courbes), rejoués au même temps simulé. |
| `next_ind` | `int` | indice | Le prochain indicateur à rejouer. |
| `chunks` | `Array` | phrases | Le sous-titre découpé en phrases (deux lignes au plus chacune). |
| `bi` | `int` | indice de temps, -1 avant le premier | Le temps en cours. |
| `bt` | `float` | secondes de vidéo | L'horloge du temps en cours. |
| `dur` | `float` | secondes de vidéo | Durée à l'écran du temps en cours : la voix plus une pause. |
| `t_end` | `float` | jours simulés | Fin de la portion de partie couverte par ce temps. |
| `sched` | `Array` | `[instant de lecture, 0 événement ou 1 indicateur, indice]` | Le plan de lecture du temps en cours, dans l'ordre. |
| `pace` | `Dictionary` | réglages de rythme du scénario | Le rythme de lecture (temps de vidéo par temps simulé). |
| `elapsed` | `float` | secondes de vidéo | Le temps de vidéo écoulé depuis le début (temps de VIDÉO, pas d'horloge réelle). |
| `player` | `AudioStreamPlayer` | — | Le lecteur de la voix. |
| `sub` | `Label` | — | Le sous-titre. |
| `band` | `PanelContainer` | — | Le bandeau qui porte le sous-titre. |
| `title` | `ColorRect` | — | L'écran-titre du début. |
| `narr_len` | `float` | secondes | Durée de la voix du temps en cours. |
| `narr_left` | `float` | secondes | Ce qu'il reste de la voix à lire. |
| `end_left` | `float` | secondes, -1 avant la fin | Compte à rebours de l'écran de fin. |
| `sched_i` | `int` | indice | La prochaine ligne du plan de lecture `sched`. |
| `cam_off_from` | `Vector2` | décalage | Le décalage de la caméra au départ du mouvement. |
| `cam_to_ground` | `Vector2` | point du sol, (0,5 ; 0,5) au centre | Le point du sol visé par la caméra. |
| `TITLE_S` | `float` | constante, 3 s | Durée de l'écran-titre. |
| `CAM_S` | `float` | constante, 1,3 s | Durée d'un mouvement de caméra. |
| `cam_t` | `float` | 0 à 1 | Avancement du mouvement de caméra en cours (1 : terminé). |
| `cam_from` | `Vector2` | (zoom, _) | Le zoom de départ du mouvement de caméra. |
| `cam_to_zoom` | `float` | facteur | Le zoom visé. |
| `base_dir` | `String` | chemin | Le dossier du scénario, d'où l'on retrouve le journal et la voix. |

#### `WsClient` · `godot/scripts/ws_client.gd:3`

Client WebSocket vers le pont du moteur : reçoit les messages JSON `{topic, data}`, envoie les commandes du joueur et se reconnecte seul.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `url` | `String` | adresse WebSocket, `ws://127.0.0.1:8765` par défaut | L'adresse du moteur. L'option `--url=` du programme la remplace. |
| `MAX_PER_FRAME` | `int` | 3000 messages par image | Le nombre maximal de messages lus à chaque image, pour que l'interface reste fluide. |
| `_ws` | `WebSocketPeer` | — | La connexion WebSocket en cours. Elle est recréée à chaque nouvel essai. |
| `_state` | `int` | état de `WebSocketPeer`, -1 au départ | Le dernier état de connexion connu. Il sert à n'émettre `status_changed` que lors d'un changement. |
| `_retry` | `float` | secondes réelles | Compte à rebours avant le prochain essai de reconnexion (2 s après une fermeture). |

#### `Chart` · `godot/scripts/chart.gd:3`

Graphique par saison : stock du lac (aire bleue), indice de norme partagée (or) et part des promesses tenues (vert).

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `stock` | `Array` | fractions de 0 à 1, une par saison, -1 = pas de valeur | La part de la capacité du lac restante à la fin de chaque saison (`stock_ratio`). |
| `norm` | `Array` | de 0 à 1, une par saison, -1 = pas de valeur | L'indice de norme partagée (`norm_index`) par saison. Courbe or. |
| `kept` | `Array` | de 0 à 1, une par saison, -1 = pas de valeur | La part des promesses tenues (`promise_kept_rate`) par saison. Courbe verte. |
| `C_LAKES` | `Array` | 4 couleurs (bleu, violet, turquoise, rose) | Les couleurs des courbes quand il y a plusieurs lacs : une par lac, en tournant. |
| `C_STOCK` | `Color` | `#4fb3d9` (bleu) | La couleur de la courbe et de l'aire du stock. |
| `C_NORM` | `Color` | `#f2b23a` (or) | La couleur de la courbe de l'indice de norme. |
| `C_KEPT` | `Color` | `#58d08a` (vert) | La couleur de la courbe des promesses tenues. |
| `live_stock` | `float` | fraction de 0 à 1, -1 = aucun | Le stock en cours de saison, reçu à la fin d'une veillée. Il est dessiné comme un point bleu sur le graphique, avec un seul lac. |
| `lakes` | `Dictionary` | `{nom du lac: [fractions de 0 à 1 par saison]}` | Avec plusieurs lacs : le stock de chaque lac par saison. Il remplace alors la courbe unique du stock. |

#### `Legend` · `godot/scripts/legend.gd:3`

Légende dessinée en bas de l'écran avec les mêmes pions que la carte : villages, types de modèle et couleurs d'interaction.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `villages` | `Array` | liste de noms de villages | Les villages affichés dans la légende, chacun avec son pion coloré. Par défaut Ostrel, Bramois, Tilque, Hennad, puis ceux du run. |

#### `MenuMap` · `godot/scripts/menu_map.gd:3`

Aperçu de la vallée dans le menu de démarrage : hameaux, lacs et pêcheurs, que l'on peut glisser d'un hameau à l'autre.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `fishers` | `Array` | liste de `{hamlet, first_name, kind, tier, experience, archetype}` | Les pêcheurs de la partie à préparer (`population.fishers` en nombre). Chaque pion est dessiné autour de son hameau. |
| `hamlets` | `Array` | liste de noms de villages | Les villages de la vallée, dans l'ordre de la carte. Par défaut `WV.DEFAULT_HAMLETS`. |
| `selected` | `int` | indice dans `fishers`, -1 = aucun | Le pêcheur sélectionné. Son pion est surligné et son prénom affiché. |
| `WV` | `Script` | constante, `world_view.gd` | Le script de la carte du jeu. Il fournit la disposition des villages, la forme du lac et la position de l'ancien. |
| `lakes` | `Array` | liste de `{name, label, villages}` | Les lacs du catalogue. Le nombre de lacs fixe le dessin et chacun porte son nom. |
| `elder_on` | `bool` | `true` / `false` | Vaut `true` si l'ancien est présent (`population.elder`). Sa cabane et son pion sont alors dessinés. |
| `elder_kind` | `String` | `"llm"` \| `"rule"` | Le type de l'ancien (`population.elder_kind`), qui donne l'aspect de son pion. |
| `large_min` | `int` | années d'expérience | Le seuil à partir duquel un pêcheur reçoit le grand modèle (`population.large_model_min_experience`, 15 par défaut). Sert à choisir la taille du pion. |
| `_hover` | `int` | indice dans `fishers`, -1 = aucun | Le pêcheur sous la souris. Son prénom s'affiche en infobulle. |
| `_drag` | `int` | indice dans `fishers`, -1 = aucun | Le pêcheur que l'on est en train de glisser. |
| `_drag_pos` | `Vector2` | px, repère local du contrôle | La position de la souris pendant le glissement. Le pion s'y dessine. |
| `_drag_target` | `String` | nom de hameau, ou `""` | Le hameau le plus proche de la souris pendant le glissement. Il est entouré d'un arc doré. |
| `_t` | `float` | secondes réelles | Temps écoulé, pour animer les pions du menu. |

#### `Art` · `godot/scripts/art.gd:4`

Direction artistique partagée : palette, polices et dessin des pions, pour que les couleurs veuillent dire la même chose partout.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `BG` | `Color` | `#0d1220` | Le fond de l'écran (bleu nuit). |
| `PANEL` | `Color` | `#141b2d` | Le fond des panneaux et des cartes. |
| `PANEL_2` | `Color` | `#1b2439` | Un fond de panneau plus clair : cadre de connexion et boutons. |
| `LINE` | `Color` | blanc à 8 % d'opacité | La couleur des filets et des bordures fines. |
| `INK` | `Color` | `#e9ecf5` | La couleur du texte principal. |
| `MUTED` | `Color` | `#8f97b2` | La couleur du texte secondaire et des libellés discrets. |
| `PAPER` | `Color` | `#fbf6ea` (crème) | Le fond des bulles de dialogue sur la carte et des valeurs flottantes. |
| `PAPER_INK` | `Color` | `#2a2420` | La couleur du texte écrit sur les bulles de papier. |
| `TALK` | `Color` | `#7f95ff` (bleu-violet) | La couleur des paroles (carte, fil et légende). |
| `SUPPORT` | `Color` | `#58d08a` (vert) | La couleur des soutiens. Elle sert aussi au voyant « connecté ». |
| `ACCUSE` | `Color` | `#ff6a5c` (rouge) | La couleur des accusations. Elle sert aussi au voyant « déconnecté » et à la tempête. |
| `PROPOSAL` | `Color` | `#f2b23a` (or) | La couleur des propositions et de l'indice de norme. |
| `PROMISE` | `Color` | `#e7c27a` | La couleur des promesses. Elle sert aussi aux bandeaux de saison et de fin de run. |
| `INCIDENT` | `Color` | `#f39c4a` (orange) | La couleur des incidents, du bouton de sécheresse et de certains bandeaux. |
| `INJECT` | `Color` | `#ffd166` (jaune) | La couleur des interventions du joueur (rumeur, changement de communication) dans les bandeaux de la carte. |
| `HAMLET` | `Dictionary` | `{nom de village: couleur}` | La couleur de chacun des 12 villages connus, de Ostrel à Dunac. Un pêcheur prend la couleur de son village. |
| `ELDER` | `Color` | `#e2bd6a` (or pâle) | La couleur de l'ancien. |
| `ARCH_LABEL` | `Dictionary` | `{id d'archétype: libellé français}` | Les archétypes en toutes lettres : famille ancienne, nouveau venu, taiseux, beau parleur, l'ancien. Utilisé dans le menu de démarrage. |
| `_fonts` | `Dictionary` | `{type de police: Font}` | Cache des polices chargées, partagé par tous les scripts (clé spéciale `__radial` pour une texture). |

#### `WorldView` · `godot/scripts/world_view.gd:15`

Dessine la carte isométrique de la vallée (sol en shader, décor, pions, lacs, bulles, bandeaux, veillée) et la fait vivre à partir des événements du moteur.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `agents` | `Dictionary` | id du pêcheur -> `{id, info, home, pos, path, hold, heading, wake_t, fishing}` (plus `rep`, `landed` plus tard) | Un pion par habitant. `info` est la fiche venue du moteur, `home` et `pos` sont des points du sol (0 à 1). Vidé à chaque nouvelle partie. |
| `selected` | `String` | id d'agent, ou vide | Le pêcheur sélectionné dans l'inspecteur (réglé par `main.gd`). Son pion est mis en valeur et son nom reste affiché. |
| `seen_outing` | `bool` | vrai ou faux | Le journal contient des événements `outing` : la barque sort alors à chacun, et plus au `catch` de bilan. |
| `animate` | `bool` | vrai ou faux | Faux pendant le rattrapage d'un journal (`hello.buffered`) : plus de trajets, de liens ni de marques, et la lumière saute à sa valeur. |
| `paused` | `bool` | vrai ou faux | Vrai quand la partie est en pause. La carte affiche alors la pastille de pause dans le cadran du temps. |
| `thinking` | `Array` | liste d'ids d'agents | Les agents dont l'IA est en train de réfléchir. Chacun reçoit une bulle « … » au-dessus du pion. |
| `DEFAULT_HAMLETS` | `Array` | 4 noms de villages | Noms utilisés quand le moteur n'envoie pas de villages : Ostrel, Bramois, Tilque, Hennad. |
| `SLOTS` | `Dictionary` | nom d'emplacement -> `Vector2` (0 à 1) | Les 8 places possibles d'un village autour du lac (NW, NE, SE, SW, W, E, BL, BR), en coordonnées du sol. |
| `LAYOUTS` | `Dictionary` | nombre de villages (1 à 8) -> liste d'emplacements | Quels emplacements de `SLOTS` on prend selon le nombre de villages, avec un seul lac. |
| `ELDER_POS` | `Vector2` | sol, 0 à 1 | Place de départ de la maison de l'ancien (0,5 ; 0,115). La vraie place est recalculée dans `elder_pos`. |
| `LAKE_C` | `Vector2` | sol, 0 à 1 | Centre de la carte (0,5 ; 0,535) : centre du lac s'il est seul et valeur de repli du centre du conseil. |
| `LAKE_R` | `Vector2` | sol, 0 à 1 | Rayons du lac unique de base (0,29 ; 0,245). Déclarée mais jamais lue ailleurs dans le script : les rayons viennent de `LAKE_BOXES`. |
| `MAX_LAKES` | `int` | 4 | Nombre maximum de lacs affichés (clé `lake.count`, 1 à 4). |
| `LAKE_BOXES` | `Dictionary` | nombre de lacs -> liste de `[centre, rayons]` | Gabarits des lacs (centre et rayons dans le sol) pour 1, 2, 3 ou 4 lacs. Servent quand le moteur ne donne pas les parcelles. |
| `ROOM` | `Rect2` | fraction de la fenêtre | Le rectangle de la scène de veillée à l'écran : position (0,045 ; 0,105), taille (0,91 ; 0,85). |
| `RING_R` | `Vector2` | sol, 0 à 1 | Rayon minimal de l'anneau du conseil autour des lacs. Il est divisé par `world_k`. |
| `ISO_LAKE_K` | `Dictionary` | nombre de lacs -> facteur | Agrandissement des lacs dans le sol isométrique par rapport au plan du menu (de 1,1 à 1,2). |
| `LOTS_PER_W` | `int` | lots par largeur de carte (24) | Nombre de lots à maisons par largeur ; `n_lots` = ce nombre × `world_k`. |
| `ZOOM_MAX` | `float` | facteur (4,0) | Zoom maximal de la caméra. |
| `MARGIN_K` | `float` | fraction du cadre (0,3) | Épaisseur de la marge de forêt autour du losange, en parts de la taille du cadre. |
| `LAND_SPEED` | `float` | sol par seconde (0,45) | Vitesse de marche des pions sur terre. Elle est divisée par `world_k` pour rester la même à l'écran. |
| `WATER_SPEED` | `float` | sol par seconde (0,30) | Vitesse des barques sur l'eau (même division par `world_k`). |
| `DUSK` | `Color` | couleur `#ff7a3d` | Orange du crépuscule, posé en voile léger sur la carte quand le jour tombe. |
| `NIGHT` | `Color` | couleur `#081028` | Bleu nuit, voile qui assombrit la carte quand il fait nuit. |
| `BOAT_SCALE` | `Dictionary` | `barque` 0,78 ; `chaloupe` 1,0 ; `cotre` 1,3 | Taille du dessin du bateau selon le type de bateau du pêcheur. |
| `terrain` | `ColorRect` | calque du fond | Le rectangle qui porte le shader `valley.gdshader` : prairie, rive et lacs. Plus bas que tous les autres calques de la carte. |
| `decor` | `Control` | calque fixe | Calque dessiné une fois : chemins, places, pontons, roseaux, arbres, maisons. |
| `under` | `Control` | calque | Calque sous les pions : poissons, sillages des barques, éclaboussures. |
| `shade` | `Control` | calque | Calque de la lumière du jour : voile d'aube, de crépuscule et de nuit. |
| `lights` | `Control` | calque additif | Lumières ajoutées (fenêtres, feux, lanternes, lucioles), en mélange additif. |
| `over` | `Control` | calque plein écran | Calque qui ne suit pas la caméra : bulles, cadran du temps et de la jauge, bandeaux, mini-carte. |
| `mat` | `ShaderMaterial` | — | Le matériau du shader de la vallée. Le script y pousse `px_size`, `iso_o`, `iso_ab`, `world_k`, `lake_mask`, `lake_n`, `grid`, `mesh` et `dry`. |
| `order` | `Array` | ids d'agents | Les ids des pions dans l'ordre d'arrivée (le moteur envoie l'ancien dans sa liste). Vidé à chaque nouvelle partie. |
| `stock_ratio` | `float` | 0 à 1 | Le stock du lac divisé par sa capacité. Règle le nombre de poissons, la couleur et le remplissage de la jauge. Pour plusieurs lacs, chaque lac a son `ratio`. |
| `stock_t` | `float` | tonnes | Le stock de poisson du lac, tiré de l'événement `lake_update`. Affiché dans la jauge sous la forme « stock / capacité t ». |
| `capacity` | `float` | tonnes | La capacité totale du lac, passée à `reset_world` (clé `lake.capacity`). Sert de dénominateur à `stock_ratio`. |
| `collapsed` | `bool` | vrai ou faux | Vrai après l'événement `lake_collapsed`. Le lac n'est plus repeuplé en poissons et la jauge change de texte. |
| `hovered` | `String` | id d'agent, ou vide | Le pêcheur sous la souris. Son étiquette s'agrandit (nom et archétype) et le curseur devient une main. |
| `time_scale` | `float` | 0 à 3 | Vitesse des animations, réglée par `main.gd` sur celle de la partie. 0 fige tout (pause, ou IA en réflexion). |
| `effects` | `Array` | liste de dictionnaires `{kind, a, ttl, max, ...}` ; `kind` = `link`, `wave`, `mark`, `float` | Les effets courts : courbes de parole, onde « à tous », étiquettes au-dessus d'un pion, gains qui s'envolent. Chacun s'éteint quand `ttl` atteint 0. |
| `bubbles` | `Dictionary` | id de l'auteur -> `{text, ttl, to, born}` | Les bulles de parole actives (texte coupé à 120 caractères, 6 s de vie). |
| `badges` | `Dictionary` | id de l'auteur -> texte | La pastille dorée d'une proposition au-dessus de son auteur (identifiant et début du texte). |
| `rules` | `Array` | liste de règles `{scope, kind, target, ...}` | Les règles en vigueur (`norms_in_force`, `norm_adopted`). Les réserves et les repos se dessinent sur la carte. |
| `cur_season` | `int` | numéro de saison, à partir de 1 | La saison en cours, lue dans chaque événement. Sert à éteindre les règles dont `until_season` est passé. |
| `_proposal_author` | `Dictionary` | id de proposition -> id d'auteur | Mémoire de qui a fait chaque proposition, pour attacher le soutien et le vote à l'auteur. Remplie par `remember_proposal`. |
| `season_days` | `float` | jours simulés | Durée d'une saison (clé `time.season_days`, 30 par défaut). Sert aux horloges et aux étapes de patrouille. |
| `sim_time` | `float` | jours simulés (la partie entière est le jour, la décimale l'heure) | L'horloge du monde, lue dans chaque événement. Elle règle le jour et la nuit, l'heure du cadran et la patrouille. |
| `light` | `float` | 0 (nuit) à 1 (plein jour) | La lumière du jour, qui suit en douceur l'heure simulée. Plafonnée à 0,12 pendant une veillée. |
| `phase` | `String` | `""`, `Pêche`, `Au village`, `Veillée`, `Repeuplement` | La phase du jour, affichée en pastille dans le cadran du temps. |
| `assembly_scope` | `String` | `""` \| `valley` \| `hamlet` | Vide hors veillée. `valley` : conseil de la vallée (la scène de veillée s'ouvre). `hamlet` : veillée de village (un feu s'allume). |
| `hamlet_pos` | `Variant` | `Dictionary` village -> `Vector2` (sol, 0 à 1) | La place de chaque village. Elle vient de `layout` puis de `run_start.map.hamlets` quand le moteur l'a posée. |
| `lakes` | `Array` | liste de `{c, r, name, label, capacity, ratio, cells}` | Les lacs de la carte : centre et rayons (sol), nom, étiquette, capacité en tonnes, part pleine. Un seul lac par défaut. |
| `iso_o` | `Vector2` | px | Le coin nord du losange du sol, dans le calque du monde. Poussé aussi dans le shader. |
| `iso_a` | `float` | px | La demi-largeur du losange du sol (largeur de la fenêtre × `world_k` / 2). |
| `iso_b` | `float` | px | La demi-hauteur du losange (`iso_a` × `iso_sq`). |
| `iso_sq` | `float` | 0,5 | Écrasement du sol à l'écran (2:1), le même quelle que soit la fenêtre. |
| `iso_ex` | `Vector2` | vecteur unitaire | L'axe x du sol à l'écran. L'axe y en est le symétrique. |
| `cam` | `Control` | — | Le conteneur de tous les calques du monde. Sa position (`cam_off`) et son échelle (`zoom`) font défiler et zoomer la carte. |
| `top` | `Control` | calque | Calque au-dessus des lumières et sous `over` : mailles (touche G), panneaux, feux, liens, pions, marques. |
| `zoom` | `float` | de `zoom_min` à `ZOOM_MAX` | Le zoom actuel de la caméra (molette). |
| `zoom_min` | `float` | 0,05 à 1 | Le plus petit zoom : toute la vallée tient alors dans le cadre. Recalculé selon la taille de la fenêtre. |
| `cam_off` | `Vector2` | px écran | Le décalage de la caméra : position du calque du monde dans la fenêtre. Borné pour ne pas sortir de la carte. |
| `council_c` | `Variant` | `Vector2`, sol 0 à 1 | Le centre de la veillée de la vallée : la moyenne des centres des lacs. |
| `council_r` | `Variant` | `Vector2`, sol 0 à 1 | Les rayons de l'anneau du conseil, au moins `RING_R / world_k`, élargis pour entourer tous les lacs. |
| `elder_pos` | `Variant` | `Vector2`, sol 0 à 1 | La place de la maison de l'ancien : au nord de l'anneau du conseil. |
| `world_k` | `float` | 1 à 4 | La taille de la vallée en largeurs de carte (`run_start.map.size`, 1,5 par défaut). |
| `PARCELS` | `int` | 10 à 200 (30 par défaut par largeur) | Le nombre de parcelles des lacs par côté (`run_start.map.grid`). Un nom en majuscules mais une variable, qui change selon la partie. |
| `n_lots` | `int` | lots par côté | La maille des maisons : 24 × `world_k`, au moins 8. |
| `n_steps` | `int` | pas par côté | La maille des pas des personnages : 5 pas par lot. |
| `world` | `Vector2` | px | La taille du calque du monde : le losange plus la marge de forêt. |
| `dragging` | `bool` | vrai ou faux | Vrai pendant que le joueur fait glisser la carte (clic droit ou milieu). |
| `glide` | `bool` | vrai ou faux | Vrai quand la caméra glisse vers `glide_to` (vers la veillée), jusqu'à ce que le joueur reprenne la main. |
| `glide_to` | `Vector2` | px écran | Le décalage de caméra visé par le glissement. |
| `mini_drag` | `bool` | vrai ou faux | Vrai pendant un glisser sur la mini-carte (en bas à droite) pour déplacer la caméra. |
| `show_mesh` | `bool` | vrai ou faux | Touche G : affiche les mailles du monde (parcelles des lacs, lots, pas). Transmis au shader (`mesh`). |
| `lake_cells` | `Array` | par lac : liste de `{c: Vector2i, luck, rel}` | Les parcelles de chaque lac : coordonnée, chance de pêche (`luck`) et poisson relatif au lac (`rel`). |
| `parcel_lake` | `PackedInt32Array` | indice de lac, -1 = terre | Pour chaque parcelle (`PARCELS` × `PARCELS`), le lac auquel elle appartient. |
| `field` | `PackedFloat32Array` | 0 (terre) à 1 (large) | Le champ d'eau fin (`n_steps` × `n_steps`), rive à 0,5. Barques, pions et maisons s'y repèrent. |
| `mask_img` | `Image` | RGBA8, une parcelle par pixel | L'image des lacs lue par le shader : R eau, G poisson, B lac, A profondeur. |
| `walk` | `AStarGrid2D` | — | La grille de chemin des personnages à pied : l'eau et les maisons sont des obstacles. |
| `sail` | `AStarGrid2D` | — | La grille de chemin des barques : seule l'eau est libre. |
| `hamlet_lake` | `Dictionary` | nom de village -> indice de lac | Le lac où pêche chaque village (`lake_info[].villages`). |
| `patrol_routes` | `Dictionary` | capitaine -> liste d'étapes `{zone, from_day, to_day}` | La route de chaque patrouille cette saison (événement `patrol_route`). |
| `patrol_season` | `int` | numéro de saison | La saison des routes de patrouille gardées. Au changement de saison, les routes sont effacées. |
| `salon_ids` | `Array` | ids d'agents | Les participants à la veillée de la vallée (l'ancien en premier), assis dans la scène à part. |
| `salon` | `Control` | plein écran | La scène de la veillée, par-dessus la carte assombrie. Visible seulement pendant un conseil de vallée. |
| `btn_salon_min` | `Button` | texte « Réduire (Échap) » | Bouton en haut à droite de la scène de veillée, qui la replie sur la carte. |
| `btn_salon_open` | `Button` | texte « Rouvrir la veillée » | Bouton en bas au centre de la carte, visible quand la veillée est réduite. |
| `_salon_draw` | `bool` | vrai ou faux | Vrai seulement pendant le dessin de la scène de veillée : les positions des pions sont alors leurs sièges. |
| `hamlet_fires` | `Array` | noms de villages | Les villages qui tiennent veillée : un feu est dessiné chez chacun. |
| `dry` | `float` | 0 à 1 | Intensité de la sécheresse. Elle décroît avec le temps et pâlit l'herbe dans le shader (`dry`). |
| `t` | `float` | secondes réelles ajustées par `time_scale` | Le temps d'animation de la carte, qui sert aux oscillations et à la durée de vie des bandeaux. |
| `banners` | `Array` | liste de `{title, sub, col, ttl, max, born}` | Les bandeaux d'annonce (2 au plus : début de saison, ouverture de la pêche, etc.). Un seul s'écoule à la fois. |
| `deco` | `Dictionary` | clés `trees`, `houses`, `stand`, `docks`, `paths`, `reeds`, `flies` | Le décor généré : arbres, maisons, pontons par village, chemins, roseaux, lucioles. |
| `fish` | `Array` | liste de `{p, ang, sp, a, dying, len, wig, k}` | Les poissons dessinés dans l'eau. Leur nombre suit le stock du lac. |
| `wakes` | `Array` | liste de `{p, ttl, max, h}` | Les sillages derrière les barques, d'une durée de 1,3 s. |
| `splashes` | `Array` | liste de `{p, ttl, max, r}` | Les éclaboussures (poisson qui saute, filet jeté). |

#### `StartMenu` · `godot/scripts/start_menu.gd:10`

Le menu « Nouvelle partie » : on y règle le monde, l'IA et les pêcheurs, puis il envoie la demande de partie (`build_config`) au moteur.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `catalog` | `Dictionary` | clés `defaults`, `limits`, `hamlets`, `lakes`, `archetypes`, `boats`, `llm_options`, `reflections`, `speeds`, `fleets`, `communications`, `councils`, `base_population`, `generation` | Le catalogue envoyé par le moteur. Tout le menu s'en nourrit : rien n'est recopié dans le script. |
| `fishers` | `Array` | liste de `{first_name, hamlet, archetype, experience, wealth, debt_payment, kind, tier, boat}` | La liste des pêcheurs en cours d'édition. Elle devient `population.fishers`. |
| `map` | `Control` | instance de `menu_map.gd` | La petite carte de la colonne de droite (« Disposition dans la vallée ») : on y glisse un pêcheur d'un village à l'autre. |
| `cancelled` | `signal` | — | Émis quand le joueur clique sur « Annuler ». |
| `MenuMap` | `Script` | `res://scripts/menu_map.gd` | Le script de la mini-carte du menu, préchargé pour créer `map`. |
| `W_IDX` | `int` | px (40) | Largeur de la colonne du numéro F01, F02… dans la liste des pêcheurs. |
| `W_NAME` | `int` | px (96) | Largeur de la colonne « Prénom ». |
| `W_HAMLET` | `int` | px (94) | Largeur de la colonne « Village ». |
| `W_ARCH` | `int` | px (130) | Largeur de la colonne « Archétype ». |
| `W_BOAT` | `int` | px (84) | Largeur de la colonne « Bateau ». |
| `W_EXP` | `int` | px (58) | Largeur de la colonne « Expérience ». |
| `W_WEALTH` | `int` | px (70) | Largeur de la colonne « Avoir (écus) ». |
| `W_DEBT` | `int` | px (58) | Largeur de la colonne « Dette/saison ». |
| `W_BRAIN` | `int` | px (96) | Largeur de la colonne « Cerveau ». |
| `W_DEL` | `int` | px (28) | Largeur du bouton « × » qui retire un pêcheur. |
| `BRAINS` | `Array` | 4 triplets `[libellé, kind, tier]` | Les choix de la colonne « Cerveau » : IA auto, IA grand, IA petit (`kind` `llm`) et Règles (`kind` `rule`). |
| `selected` | `int` | indice dans `fishers`, -1 = aucun | Le pêcheur choisi : sa ligne est surlignée, sa fiche s'affiche à droite. |
| `capacity_auto` | `bool` | vrai ou faux | Vrai tant que le joueur n'a pas fixé le stock du lac : il suit alors 12,5 t par pêcheur. Envoyé comme `lake.capacity` = `null` si vrai. |
| `speed_touched` | `bool` | vrai ou faux | Vrai dès que le joueur a choisi lui-même la vitesse. Sinon le menu propose celle qui convient au moteur d'IA. |
| `reflection_touched` | `bool` | vrai ou faux | Vrai dès que le joueur a choisi lui-même la réflexion. Sinon le menu suit la réflexion conseillée par le moteur d'IA. |
| `can_cancel` | `bool` | vrai ou faux | Vrai si le menu est ouvert par-dessus une partie : le bouton « Annuler » est alors visible. |
| `engine_state` | `String` | `""`, `idle`, `ended`, `starting`, ou autre (partie en cours) | L'état du moteur annoncé par `set_engine`. Il décide si « Démarrer la partie » est actif. |
| `engine_detail` | `String` | texte libre | Le détail donné par le moteur pendant la préparation (par exemple le chargement du modèle). Affiché en haut à droite. |
| `engine_online` | `bool` | vrai ou faux | Faux : le moteur est injoignable, le voyant en haut à droite devient rouge et le démarrage est bloqué. |
| `busy` | `bool` | vrai ou faux | Vrai entre le clic sur « Démarrer » et la réponse du moteur. Le bouton affiche « Préparation de la partie… ». |
| `busy_since` | `int` | ms (`Time.get_ticks_msec`) | L'instant où `busy` est devenu vrai. Après 12 s sans réponse, une erreur « le moteur n'a pas répondu » s'affiche. |
| `_rows` | `Array` | liste de dictionnaires de widgets `{panel, name, hamlet, arch, exp, wealth, debt, boat, brain, del}` | Les contrôles de chaque ligne de pêcheur, pour les mettre à jour sans tout reconstruire. |
| `_updating` | `bool` | vrai ou faux | Vrai quand le script règle lui-même un contrôle, pour éviter que ses signaux ne relancent un calcul. |
| `_pending_generation` | `String` | `""` ou `g<ms>` | L'identifiant de la demande de vallée en attente de réponse. Vide s'il n'y en a pas. |
| `_pending_since` | `int` | ms | L'instant d'envoi de cette demande. Au-delà de 5 s, on la croit perdue. |
| `_pending_params` | `Dictionary` | villages, pêcheurs, graine, etc. | Les nombres de la demande en cours, pour savoir s'ils ont changé depuis. |
| `_regenerate` | `bool` | vrai ou faux | Vrai si les nombres ont changé pendant l'attente : on redemande une vallée dès que la précédente est servie. |
| `_gen_timer` | `Timer` | 0,5 s | Laisse finir de régler villages, pêcheurs, graine ou lacs avant de demander la nouvelle vallée au moteur. |
| `sheet` | `PanelContainer` | — | Le grand panneau sombre qui contient tout le menu. |
| `lbl_engine` | `Label` | — | L'étiquette en haut à droite : « moteur prêt », « moteur injoignable », « en attente du moteur… » ou le détail de préparation. |
| `spin_seasons` | `SpinBox` | saisons, 1 à 50 | Colonne de gauche, « Saisons ». Règle `run.seasons`. |
| `spin_seed` | `SpinBox` | 0 à 999999 | Colonne de gauche, « Graine ». Règle `run.seed`. Le changer régénère la vallée. |
| `spin_rounds` | `SpinBox` | 1 à 3 | Colonne de gauche, « Tours de parole ». Règle `scenario.assembly_rounds`. |
| `spin_capacity` | `SpinBox` | tonnes, 10 à 1000 | Colonne de gauche, « Stock max ». Règle `lake.capacity` (un lac). Masqué avec plusieurs lacs. |
| `btn_cap_auto` | `Button` | texte « Auto » | À droite du stock max. Remet le stock du lac en automatique (`lake.capacity` = auto). |
| `spin_growth` | `SpinBox` | 0,1 à 2,0 | Colonne de gauche, « Repeuplement ». Règle `lake.growth_rate`. Masqué avec plusieurs lacs. |
| `btn_growth_default` | `Button` | texte « Normal » | À droite du repeuplement. Remet `lake.growth_rate` à sa valeur par défaut. |
| `chk_stop_empty` | `CheckButton` | vrai ou faux | « Arrêter si le lac est vide ». Règle `run.stop_on_extinction`. |
| `lbl_cap_hint` | `Label` | — | Texte d'aide sous les réglages du lac : stock auto ou manuel, rendement durable, ce que les bateaux peuvent ramener. |
| `opt_comm` | `OptionButton` | `valley` \| `hamlet` \| `none` | Colonne de gauche, « Veillées ». Règle `scenario.communication`. |
| `opt_council` | `OptionButton` | `delegates` \| `all` | Colonne de gauche, « Conseil ». Règle `scenario.council` (un élu par village, ou tous). |
| `chk_climate` | `CheckButton` | vrai ou faux | « Saisons de l'année et événements ». Règle `climate.enabled`. |
| `chk_patrol` | `CheckButton` | vrai ou faux | « Patrouille du lac ». Règle `scenario.patrol.enabled` ; décoché, le menu envoie 0 patrouille. |
| `spin_events` | `SpinBox` | %, 0 à 100 | Colonne de gauche, « Événements ». Règle `climate.event_rate` (valeur divisée par 100). |
| `spin_luck` | `SpinBox` | %, 0 à 60 | Colonne de gauche, « Chance à la pêche ». Règle `economy.luck` (valeur divisée par 100). |
| `spin_villages` | `SpinBox` | 1 à 8 | Colonne du centre, « Villages ». Règle `population.villages`. Le changer régénère la vallée. |
| `spin_fishers` | `SpinBox` | 1 à 24 | Colonne du centre, « Pêcheurs ». Règle `population.fishers`. Le changer régénère la vallée. |
| `opt_fleet` | `OptionButton` | liste du catalogue (`fleets`), `mixte` par défaut | Colonne du centre, « Flotte ». Choisit la répartition des tailles de bateaux de la vallée générée (`population.boat_mix`). |
| `btn_other` | `Button` | texte « Autre vallée » | Colonne du centre, visible en mode aléatoire : tire une nouvelle graine, donc une autre vallée. |
| `opt_genmode` | `OptionButton` | `params` (Paramétrée) \| `random` (Aléatoire) | Colonne du centre, « Vallée ». Règle `population.random`. En aléatoire, tout est tiré de la graine. |
| `spin_lakes` | `SpinBox` | 1 à 4 | Colonne du centre, « Lacs ». Règle `lake.count`. Le changer régénère la vallée. |
| `spin_patrols` | `SpinBox` | 1 à 4 | Colonne de gauche, à droite de « Patrouille du lac ». Règle `scenario.patrol.count` (le menu envoie 0 si la patrouille est décochée). |
| `spin_hold` | `SpinBox` | %, 5 à 100 | Colonne de gauche, « Part prenable ». Règle `economy.hold_fraction` (valeur divisée par 100). |
| `row_cap` | `Control` | ligne | La ligne « Stock max » et son bouton Auto. Cachée quand chaque lac se règle à part. |
| `row_growth` | `Control` | ligne | La ligne « Repeuplement » et son bouton Normal. Cachée quand chaque lac se règle à part. |
| `row_travel` | `Control` | ligne | La ligne « Route », visible seulement avec plusieurs lacs. |
| `spin_travel_days` | `SpinBox` | jours, 0 à 10 | Ligne « Route » de la colonne de gauche. Règle `economy.travel_days`. |
| `spin_travel_cost` | `SpinBox` | écus, 0 à 1000 | Ligne « Route ». Règle `economy.travel_cost` (écus par jour de mer). |
| `lakes_box` | `VBoxContainer` | — | Le tableau « un lac par ligne » (stock max, stock au départ, repeuplement), à gauche. Visible avec plusieurs lacs ou en vallée aléatoire. |
| `lakes_state` | `Array` | liste de `{name, label, villages, capacity, cap_cat, n_cat, stock_ratio, growth_rate}` | L'état des lacs réglés dans le menu. Il devient `lake.lakes` à l'envoi. |
| `lake_spins` | `Array` | liste de `{cap, stock, growth}` (SpinBox) | Les trois champs de chaque ligne de `lakes_box`. |
| `btn_generate` | `Button` | texte « Générer la vallée » | Colonne du centre. Demande au moteur de régénérer villages, pêcheurs et bateaux. |
| `chk_visible` | `CheckButton` | vrai ou faux | « Les déclarations à l'ancien sont lues à toute la vallée ». Règle `scenario.catches_visible`. |
| `opt_llm` | `OptionButton` | ids du catalogue (`llm_options`) | Colonne du centre, « Moteur d'IA ». Choisit le fournisseur et le modèle (fichier de configuration du moteur d'IA). |
| `lbl_llm_desc` | `Label` | — | Texte sous la ligne d'IA : description du moteur d'IA choisi. |
| `opt_reflection` | `OptionButton` | `complete` \| `rapide` \| `adaptive` | Colonne du centre, « Réflexion ». Règle `llm.reflection`. |
| `lbl_reflection_desc` | `Label` | — | Texte sous la ligne d'IA : description de la réflexion choisie. |
| `opt_speed` | `OptionButton` | nombres du catalogue (× 1/16 à × plusieurs) ou `max` | Colonne du centre, « Vitesse au départ ». Vitesse de la partie au lancement (clé `speed` de la demande). |
| `lbl_speed_hint` | `Label` | — | Texte sous la ligne d'IA : « Modifiable à tout moment pendant la partie. » |
| `chk_elder` | `CheckButton` | vrai ou faux | « Maître Oswin, l'ancien (arbitre) ». Règle `population.elder`. |
| `opt_elder` | `OptionButton` | « Cerveau : IA » (`llm`) \| « Cerveau : règles » (`rule`) | Sous la case de l'ancien. Règle `population.elder_kind`. Grisé si l'ancien est décoché. |
| `rows_box` | `VBoxContainer` | — | La liste défilante des lignes de pêcheurs, au centre. |
| `lbl_count` | `Label` | nombre | À droite du titre « Les pêcheurs » : le nombre de pêcheurs. |
| `lbl_lake` | `Label` | — | À droite du titre « Les pêcheurs » : résumé du lac (stock, rendement durable maximal par saison). |
| `btn_add` | `Button` | texte « + Ajouter un pêcheur » | Ajoute un pêcheur au village le moins peuplé. Désactivé à la limite du catalogue (24). |
| `detail` | `RichTextLabel` | texte BBCode | La « Fiche » de la colonne de droite : détail du pêcheur sélectionné. |
| `lbl_error` | `Label` | texte, rouge | Message d'erreur en bas à gauche du menu (prénom manquant, moteur muet, refus du moteur). |
| `btn_start` | `Button` | texte « Démarrer la partie » | Bouton vert en bas à droite. Envoie `build_config()`. Grisé si le moteur est occupé ou injoignable. |
| `btn_cancel` | `Button` | texte « Annuler » | En bas à droite. Ferme le menu sans lancer de partie ; visible seulement si `can_cancel`. |

#### `Valley` · `godot/shaders/valley.gdshader:6`

Le shader du sol de la vallée : prairie, forêt hors du losange, rive, eau animée et lacs, calculés à partir de l'image des parcelles.

| Variable | Type | Unité ou valeurs | Signification |
|---|---|---|---|
| `lake_mask` | `sampler2D` | texture, R eau, G poisson, B lac, A profondeur | L'image des lacs envoyée par `world_view.gd` (`mask_img` agrandie). La rive est là où R vaut 0,5 ; le vert dit le poisson de la parcelle. |
| `lake_n` | `int` | 1 à 4 | Nombre de lacs, poussé par le script, mais jamais lu dans le shader. Variable sans effet visible aujourd'hui. |
| `grid` | `int` | parcelles par côté | La maille des lacs (`PARCELS`). Sert à tracer le filigrane des parcelles quand `mesh` est vrai. |
| `mesh` | `bool` | vrai ou faux | Touche G : affiche les parcelles en filigrane sur le sol. |
| `px_size` | `vec2` | px | La taille du calque du monde (`world`). Convertit les coordonnées de l'écran en pixels du calque. |
| `iso_o` | `vec2` | px | Le coin nord du losange du sol (même valeur que `iso_o` du script). |
| `iso_ab` | `vec2` | px | La demi-largeur et la demi-hauteur du losange (`iso_a`, `iso_b`). |
| `world_k` | `float` | 1 à 4 | La taille de la vallée en largeurs de carte. Les bruits du sol (rive, herbe, collines) s'étendent avec elle. |
| `dry` | `float` | 0 à 1 | La sécheresse : fait virer l'herbe au jaune paille et ternit les fleurs et l'eau. |
| `t_offset` | `float` | secondes | Décalage ajouté au temps du shader (`TIME`) pour l'animation de l'eau. Jamais réglé par le code : reste à 0. |
