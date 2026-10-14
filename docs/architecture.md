# FILETS — architecture, temps, communication

Ce document explique comment les morceaux du jeu se parlent. Le détail des réglages est dans le [README](../README.md).

## 1. Architecture

```
 Godot (menu, scène, pilotage)                       Ollama (ou Groq…)
        │  ▲                                                ▲
        │  │ WebSocket JSON {"topic", "data"}               │ HTTP, API compatible OpenAI (JSON)
        ▼  │                                                │
   service « bridge » ◄──── Kafka ────► MOTEUR PYTHON ──────┘
        ▲                  (topics)      (monde, agents, horloge)
        │                     │
        │          ┌──────────┴───────────┐
        │   service « indicators »   service « store »
        │   (calcule en flux)         (SQLite : historique)
        └── relaie événements, indicateurs, état et catalogue à Godot
```

| Processus | Rôle |
|---|---|
| **Moteur** (`python -m filets serve`) | Le « salon » : attend `start_game`, joue la partie (lac, pêcheurs, veillées, normes), appelle les IA, publie tout ce qui arrive. Il tourne dans un seul processus asyncio. |
| **indicators** | Lit `filets.events`, recalcule les indicateurs (stock en % de la capacité, norme, promesses, tokens par système…) et les publie. Il se place seul sur le dernier `run_start` : démarré avant, pendant ou après la partie, il aboutit aux mêmes chiffres. |
| **store** | Range les runs terminés dans SQLite (`data/history.db`) pour les requêtes d'analyse. |
| **bridge** | Seul point d'entrée de Godot : serveur WebSocket sur `:8765`. Relaie `events`, `indicators`, `status` et `catalog` vers Godot, et les commandes de Godot vers `filets.commands`. Il garde le dernier état et le catalogue, et rejoue le début d'un run à un client qui arrive en retard. |
| **Godot** | Affiche, ne décide rien : menu, carte de la vallée, fil des interactions, inspecteur d'agent, barre de pilotage. |
| **Ollama** | Serveur de modèles locaux. Seul le moteur lui parle. |

Sans Kafka (`serve` seul, ou les tests), un bus en mémoire (`LocalBus`) a la même interface et le moteur ouvre lui-même le pont : c'est le mode des essais rapides. Kafka est la configuration de référence.

### Godot et Ollama : il n'y a pas de lien direct

Godot n'appelle jamais un modèle. Le chemin d'une décision de pêcheur :

1. le moteur construit le contexte de l'agent (son état du lac, sa mémoire, ce qu'il sait des autres…) ;
2. il envoie une requête HTTP `POST /v1/chat/completions` à Ollama, avec un schéma JSON qui impose la forme de la réponse ;
3. la réponse (un JSON) est validée, devient un événement `decision`, puis `catch` ;
4. ces événements partent sur Kafka, le pont les relaie à Godot, qui les dessine (une barque sort, « +3,2 t », une ligne dans le fil).

Dans l'autre sens, ce que fait le joueur dans Godot (démarrer, pause, vitesse, rumeur, sécheresse…) est une **commande** JSON : Godot → pont → `filets.commands` → moteur, qui la lit toutes les 50 ms, la valide et la tient pour un événement `injection`.

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
* le **système 1** (§ 4) réduit le temps de réflexion lui-même.

## 3. Communication et mémoire

### Ce qui circule : des événements JSON

Tout fait du monde est un événement avec la même enveloppe (`event_id`, `run_id`, `seq`, `sim_time`, `processed_at`, `actor`, `payload`) et un `payload` décrit par un schéma JSON (`schemas/*.json`, exportés par `python -m filets schemas`). Les natures : `decision`, `utterance`, `proposal`, `support`, `promise`, `accusation`, `norm_adopted`, `catch`, `sale`, `lake_update`, `llm_call`, `incident`, `injection`, `memory_write`…

### La veillée

Chaque tour de parole est un événement `utterance` (qui parle, à qui, ce qu'il a entendu avant). Ses effets sont des événements séparés :

* une **proposition** de quota ; deux quotas à moins de 0,75 t l'un de l'autre sont la même proposition (celui qui propose la deuxième la soutient) ;
* un **soutien**, une **promesse**, une **accusation** ;
* le **vote de clôture** : chaque pêcheur à IA qui n'a soutenu aucune proposition remplit un **bulletin** (question de quelques lignes au petit modèle, réponse contrainte : l'identifiant d'une proposition ou « aucune ») ; à défaut de réponse, il vote pour la proposition la plus proche de ce qu'il a dit vouloir (à 1,5 t près), ou s'abstient s'il n'a rien dit de chiffré ;
* une proposition soutenue par **plus de la moitié des pêcheurs présents** devient une **règle** (`norm_adopted`) pour la saison suivante.

### Mémoire personnelle et collective

* **Personnelle** : chaque agent a son flux de souvenirs datés (`MemoryStore`). À chaque décision, il retrouve les plus utiles par **récence, importance et pertinence** (BM25 sur le texte). Ses **engagements** (une promesse faite, une accusation reçue) sont épinglés : ils reviennent à chaque décision tant qu'ils sont d'actualité, même s'il compte les trahir. Il garde aussi la suite de ses propres constats du lac (`stock_seen`) pour en voir la tendance.
* **Collective** : ce que tout le monde peut savoir. Les règles adoptées, les prises que le marché rend visibles, ce qui s'est dit à la veillée, les rumeurs du joueur (présentes dans chaque décision, deux saisons), et un **corpus** de récits et de comptes (`corpus/`, retrouvé par pertinence). Rien n'est retrouvé avant son instant : un agent n'agit jamais sur une information qu'il n'avait pas encore (C6, vérifié).

### Pas de perte d'information

* **Journal d'abord.** Chaque événement est écrit dans `runs/<id>/events.jsonl` par le moteur lui-même, avant et indépendamment de Kafka : même si un service tombe, la partie est complète et rejouable (`python -m filets replay <id>`, sans aucun appel d'IA).
* **Kafka comme intergiciel.** Producteur `acks=all` et idempotent, une seule partition pour `filets.events` (ordre total garanti), conservation 7 jours (une heure pour l'état du moteur). Les services lisent à leur rythme et reprennent au dernier `run_start`.
* **Validation partout.** Un événement non conforme à son schéma n'est jamais perdu en silence : il va dans `filets.deadletter` et un `incident` le dit. Il en est de même d'une commande invalide.
* **Vérification.** `python -m filets verify <id>` contrôle les schémas, l'ordre, la monotonie du temps simulé et l'absence d'information venue du futur.
* **Communication avec les IA : JSON.** Requêtes et réponses sont du JSON sur l'API compatible OpenAI (Ollama, Groq, OpenRouter, Gemini, Mistral…), avec une limite de débit, des reprises et le décompte des tokens de chaque appel (`llm_call`).

## 4. Économie de tokens : système 1 et système 2

Chaque appel à un modèle coûte du temps, de l'énergie, et des tokens facturés sur une API. Le profil `llm.reflection: adaptive` répartit l'effort, comme Kahneman oppose le réflexe et la réflexion :

| | Système 1 — réflexe | Système 2 — réflexion |
|---|---|---|
| Quand | prise de **routine** : lac à plus de 70 % et qui ne baisse pas, un engagement ou une règle à suivre, aucune rumeur, finances correctes | tout le reste : première saison, lac qui baisse ou sous 70 %, rumeur, finances tendues, rien pour guider ; **toutes les paroles de la veillée** |
| Contexte | une dizaine de lignes (≈ 150 tokens) | contexte complet allégé (≈ 1 500 à 2 000 tokens) |
| Réponse | un nombre : `{"prise": 3.5}` (16 tokens au plus) | la justification (ce que l'agent constate du lac), puis le nombre |
| Modèle | le petit (le moins cher) | celui de l'agent |

Chaque `llm_call` et chaque `decision` porte son système (`S1` / `S2`) et les indicateurs comptent appels et tokens par système (`llm_calls_s1`, `llm_tokens_s2`…), si bien qu'on peut dire ce que la réflexion a coûté et ce que le réflexe a épargné. Les profils `rapide` et `complete` passent tout en système 2 (`complete` reste le profil de référence des expériences).

**Fiabilité des données.** La forme de la réponse est imposée au fournisseur par un schéma JSON (Ollama : décodage contraint, aucun champ oublié, textes bornés) ; une graine stable par partie, agent, saison, nature et tour est envoyée (même configuration, mêmes réponses) ; toute décision qui retombe sur la règle de repli est marquée `fallback` et signalée par un incident, donc comptée.
