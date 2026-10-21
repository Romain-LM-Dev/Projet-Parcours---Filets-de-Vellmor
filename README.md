# FILETS — la tragédie des communs autour du lac de Vellmor

Projet *Mondes Vivants* (5A IABD, EIGSI Casablanca). Des pêcheurs incarnés par des LLM gratuits
se partagent un lac qui se repeuple. Ils pêchent, vendent, se retrouvent le soir chez l'ancien,
proposent des règles, promettent, s'accusent… et tiennent parole ou non. Les événements du monde
transitent par **Apache Kafka**, les indicateurs sont calculés en flux et la scène **Godot**
montre tout en direct.

> **Premier build.** La chaîne complète fonctionne de bout en bout. Par défaut, les agents
> utilisent un *faux LLM* (`scripted`) qui imite des réponses à partir de règles bruitées : il sert
> à développer et tester sans clé ni GPU. **Aucun résultat scientifique ne doit en être tiré** :
> passez à Ollama ou à une API gratuite (`config/ollama.yaml`, `config/groq.yaml`) pour les vraies
> expériences.

```
 Moteur Python ──► Kafka (filets.events) ──► service d'indicateurs ──► Kafka (filets.indicators)
  (salon, agents,       │                                                        │
   lac, horloge)        ├──► service d'historique ──► PostgreSQL (ou SQLite)    │
    │   ▲  │            └──────────────► API FastAPI (REST + WebSocket) ◄────────┘
    │   │  └─ Kafka (filets.status : état du moteur) ──►│  ▲
    │   └──── Kafka (filets.commands : démarrer, pause, vitesse, mode, injections) ◄──┘
    ├─ catalogue (menu)                                 Godot (menu, scène, pilotage, inspecteur)
    ├─ Ollama : Qwen (réflexion), tev1 (décisions simples), embeddinggemma (plongements)
    └─ RAG : PostgreSQL + pgvector (corpus, souvenirs) · stockage objet S3 (documents, archives des parties)
```

Pour comprendre comment les morceaux se parlent (architecture, horloge, communication et mémoire, tokens, bibliothèques
asynchrones, stockage) : [docs/architecture.md](docs/architecture.md).

## Démarrage rapide

Sous Windows, deux scripts font tout (voir `install.ps1` et `start.ps1`, ou leurs lanceurs `.cmd`) :

```powershell
.\install.cmd                 # une fois : Python 3.13, .venv, dépendances, tests, Kafka, modèles Ollama (3B et 1,5B ; -Quality ajoute
                              # le 7B, -Open le modèle de décision tev1, -Data PostgreSQL + pgvector, S3 et embeddinggemma)
.\start.cmd                   # tout : Kafka et ses services, Ollama (Qwen + tev1), PostgreSQL + pgvector et S3, Godot,
                              # le moteur en salon (Docker Desktop est lancé au besoin) ; on règle la partie dans le menu
.\start.cmd -Light            # léger, sans Docker ni Ollama : le moteur seul avec le faux LLM
.\start.cmd -OllamaProfile quality   # Ollama « qualité » (7B + 1,5B) : meilleur, mais bien plus lent
.\stop.cmd                    # ferme le moteur, les services et les conteneurs (les données sont gardées)
```

À la main, sans Kafka :

```bash
pip install -r requirements.txt
python -m pytest -q                                  # tests de cohérence (les tests Kafka et Godot sont ignorés si absents)
python -m filets serve                               # salon + API sur :8765 (WebSocket pour Godot, REST : http://localhost:8765/docs)
python -m filets run --mode async --ws               # ou : partie immédiate, sans menu
```

Ouvrez `godot/project.godot` dans **Godot 4.3+** et lancez la scène (F5) : un menu de démarrage s'affiche
si le moteur est en salon. Cliquez sur un pêcheur pour l'inspecter ; les boutons du bas injectent des
événements dans la partie en cours. Sans Godot, la console suffit : chaque prise, parole, règle adoptée
ou promesse trahie s'y affiche.

## Le menu de démarrage

Au lancement, Godot propose le menu **Nouvelle partie** tant que le moteur est en salon (`serve`) :

| Réglage | Détail |
|---|---|
| Temps du monde | **Synchrone** (tous agissent ensemble) ou **Asynchrone** (chacun à son rythme, le temps suit le temps réel) |
| Durée et hasard | nombre de saisons, graine (un même réglage et une même graine rejouent la même partie avec le faux LLM) |
| La vallée | veillées (toute la vallée, par hameau, interdites), **tours de parole** par veillée (1 à 3, 2 par défaut), prises connues de tous ou non, l'ancien (présent ou non, IA ou règles) |
| Le lac | **stock max** : la limite du stock, de 10 à 1000 t, ou *Auto* (12,5 t par pêcheur, qui suit alors le nombre de pêcheurs). C'est 100 % de la jauge : le lac part plein et ne la dépasse jamais. **Repeuplement** : le taux `r` du lac, de 0,1 à 2 par saison (1 = normal). Le menu rappelle ce que le lac renouvelle (`r·K/4` par saison) face à ce que les barques peuvent ramener. **Arrêter si le lac est vide** (coché par défaut) |
| Moteur d'IA | faux LLM de test, **Ollama · rapide** (3B + 1,5B, recommandé), Ollama · qualité (7B + 1,5B) ou Groq ; le moteur vérifie avant de lancer (Ollama joignable, modèles présents, clé d'API) |
| Réflexion | **Adaptative (système 1 / 2)** : un réflexe d'un nombre pour les prises de routine, la réflexion pour le reste ([détail](docs/architecture.md)). **Rapide** (une phrase courte, contexte allégé, réponse bornée : environ deux fois plus rapide) ou **Complète** (réponses libres, contexte entier : le profil de référence des expériences) |
| Pêcheurs | de 1 à 24 : prénom, hameau, archétype, expérience, avoir, dette par saison, « cerveau » (IA auto/grand/petit, ou règles) |
| Disposition | un aperçu de la vallée : on glisse un pêcheur d'un hameau à l'autre ; **Composition de base** rétablit les huit pêcheurs par défaut, tous en « IA auto » |
| Vitesse | vitesse au départ (× 1/16 à × 16, ou maximale). En asynchrone avec une vraie IA, le menu propose la vitesse qui lui convient (× ¼ pour Ollama rapide, × 1/8 pour le 7B) et prévient si on choisit plus vite |

**Limite du stock du lac.** Le réglage fixe la capacité `K` du modèle logistique : le stock part de `K` (`lake.initial_ratio = 1`) et
ne la dépasse jamais, et la jauge, `stock_ratio` et tous les pourcentages s'y rapportent. Un petit lac s'épuise vite avec beaucoup
de pêcheurs ; un grand ne ressent presque pas la pêche. Le seuil d'effondrement (`lake.collapse_ratio`, 5 % de `K`) reste dans la
configuration YAML.

**Taux de repeuplement.** `r` est le taux de la croissance logistique, appliquée une fois par saison : `stock + r × stock × (1 − stock/K)`.
Le lac se refait le plus vite à moitié plein, où il regagne `r·K/4` (le rendement durable maximal, affiché dans le menu). Avec `r = 0,3`
une pêche excessive se paie pendant de nombreuses saisons ; avec `r = 2` le lac se remplit presque en une saison (au-delà, la suite
logistique oscille, d'où la limite). `lake.growth_rate` dans le YAML, `lake.growth_rate` dans la demande du menu.

**Fin de partie quand le lac est vide.** Un lac tombé à 0 ne se repeuple jamais (la croissance part du stock). Dès qu'il passe sous
50 kg (`lake.EXTINCT_BELOW`, il s'affiche « 0.0 t »), la partie s'arrête **tout de suite**, même en pleine saison, avec la raison
`extinction` (`run_end`, écran de fin « Le lac est à sec », bandeau et ligne « LAC À SEC » dans le fil). La case du menu, ou
`run.stop_on_extinction: false` dans le YAML (`--set run.stop_on_extinction=false`), permet de continuer quand même. Différent de
`run.stop_on_collapse` (lac sous 5 %, arrêt à la fin de la saison, désactivé par défaut) : un lac effondré peut encore se refaire.

**Le cerveau d'un pêcheur** (colonne « Cerveau », et réglage de l'ancien) dit qui décide de sa prise et de ses paroles :

| Cerveau | Ce qui décide |
|---|---|
| **IA · auto** | un modèle de langage ; le moteur choisit sa taille d'après l'**expérience** : grand modèle à partir de 15 ans de pêche (`population.large_model_min_experience`), petit en dessous, jamais d'après une catégorie sociale (A5) |
| **IA · grand** / **IA · petit** | un modèle de langage, de la taille imposée |
| **Règles** | aucune IA : une règle fixe propre à l'archétype (`filets/policies.py`), la même pour une situation donnée |

Avec Ollama « rapide », « grand » est `qwen2.5:3b` et « petit » `qwen2.5:1.5b` (avec « qualité » : `qwen2.5:7b` et `qwen2.5:1.5b`) ;
avec le faux LLM de test, le grand est simplement plus fiable (moins de bruit) et plus lent que le petit. Un pêcheur « IA » dont le modèle ne répond pas, ou répond de façon inexploitable,
joue sa règle à la place (incident `règle de repli`). Les agents à règles servent de témoin (A6) : ils séparent l'effet « IA » de l'effet « profil ».

Changer l'archétype d'un pêcheur reprend les valeurs types de cet archétype (expérience, avoir, dette), toujours modifiables ensuite.
Tant qu'on n'a pas fixé le stock max à la main, la capacité du lac suit le nombre de pêcheurs (12,5 t chacun). Le moteur valide la
demande ; en cas de refus (Ollama éteint, clé absente…), le menu reste ouvert avec le message.

## Piloter la partie

Une barre au-dessus de la carte commande la partie en cours (touche **Espace** pour la pause) :

* **Pause / Reprendre** : le monde se fige complètement (temps simulé, appels aux IA, événements). Un appel déjà parti dont la réponse
  arrive pendant la pause attend la reprise. Le temps de pause n'est pas compté dans `processed_at`.
* **Vitesse** × 1/16 … × 16, ou **Max** (aucune attente d'affichage). En asynchrone, la vitesse change aussi le poids de la réflexion
  des IA dans le temps du monde : c'est un paramètre du modèle de temps (C5), tracé dans le journal par un événement `injection`.
  **Plus on va vite, plus l'IA paraît lente** : le monde avance pendant qu'elle réfléchit, et la veillée peut se fermer sans elle.
  Quand c'est le cas (asynchrone, vraie IA, vitesse au-dessus de celle que le moteur d'IA peut suivre), un bouton orange
  **Ralentir (× ¼)** apparaît ; un compteur indique les répliques et sorties perdues depuis le début de la saison. Si, même à la
  vitesse conseillée, au moins deux se perdent dans la saison, le bouton propose la vitesse du dessous.
* **Temps** Synchrone / Asynchrone : le changement s'applique **au début de la saison suivante** (annoncé tout de suite).
  Chaque `season_start` porte le mode dans lequel la saison est jouée.
* **Arrêter la partie** (deux clics) : immédiat, même pendant la réflexion d'une IA ; le run est clos avec la raison `stop`.
  Un écran de fin propose alors **Nouvelle partie**.

## Avec Kafka (configuration de référence)

```powershell
.\start.cmd -Ui                                      # broker, 3 services (fenêtres séparées), Godot, moteur en salon
```

ou à la main :

```bash
docker compose up -d                                 # broker KRaft sur 127.0.0.1:19092
python -m filets.services.indicators                 # terminal 1 : indicateurs en flux
python -m filets.services.store                      # terminal 2 : historique (SQLite ; PostgreSQL avec --config config/data.yaml)
python -m filets.services.bridge                     # terminal 3 : API FastAPI (ws://localhost:8765/ws pour Godot, REST sur /api)
python -m filets serve --bus kafka                   # terminal 4 : le moteur en salon (ou : run --bus kafka)
```

`docker compose --profile ui up -d` ajoute Kafka UI sur http://localhost:8080 pour regarder les topics.
Les topics sont `filets.events`, `filets.indicators`, `filets.commands`, `filets.deadletter` et `filets.status`
(l'état du moteur, conservé une heure).

**Démarrage dans n'importe quel ordre.** Les services d'indicateurs et le pont se placent d'eux-mêmes sur le dernier
`run_start` du topic : démarrés avant, pendant ou après la simulation, ils reconstituent le run en cours et aboutissent
aux mêmes chiffres. Le moteur n'annonce son salon (`idle`) qu'une fois son consommateur de commandes prêt, si bien
qu'un « Démarrer » cliqué trop tôt n'est pas perdu.

## Commandes

| Commande | Rôle |
|---|---|
| `python -m filets serve [--bus local\|kafka] [--mode …] [--agents N] [--seasons S] [--llm ollama] [--no-ws]` | **salon** : attend `start_game` du menu de Godot, joue la partie, puis une autre ; `--mode/--agents/--seasons/--llm` règlent les valeurs proposées par le menu |
| `python -m filets run [--agents N] [--mode sync\|async] [--seasons S] [--config …] [--set clé=valeur]` | lance un run tout de suite, l'enregistre dans `runs/<id>/` |
| `python -m filets replay <id> [--speed 4] [--ws]` | rejoue un run **sans aucun appel LLM**, recalcule et compare les indicateurs |
| `python -m filets verify <id>` | schémas, ordre, monotonie du temps simulé, violations temporelles |
| `python -m filets batch --config A.yaml --config B.yaml --runs 5` | runs répétés (graines successives), tableau moyenne ± écart-type, archivage SQLite |
| `python -m filets query [analysis/queries.sql]` | requêtes reproductibles sur l'historique ; `query analysis/queries_pg.sql --pg` sur PostgreSQL |
| `python -m filets retrieval <id> --sample 20` | échantillon de décisions et de ce qui a été retrouvé, à annoter (F2) |
| `python -m filets ingest [--pg]` | importe les runs enregistrés dans SQLite, ou dans PostgreSQL (`--pg`) |
| `python -m filets schemas` | exporte les schémas d'événements dans `schemas/` |

Exemples : `--set scenario.communication=hamlet`, `--set scenario.catches_visible=false`,
`--set population.rule_fraction=0.5`, `--set time.sim_hours_per_second=1`.

## Choisir ses modèles (tous gratuits)

Deux niveaux, `grand` et `petit`, attribués selon **l'expérience de pêche** du profil
(`large_model_min_experience`, 15 ans par défaut), jamais selon une catégorie sociale (A5).

```bash
ollama pull qwen2.5:3b && ollama pull qwen2.5:1.5b          # réglage rapide (recommandé sur 6 Go de mémoire graphique)
python -m filets run --config config/ollama_fast.yaml --agents 6
ollama pull qwen2.5:7b                                      # réglage qualité : meilleur, bien plus lent
python -m filets run --config config/ollama.yaml --agents 6
```

Depuis le menu de démarrage, choisir « Ollama · rapide » (ou « qualité ») suffit. Avant de lancer, le moteur vérifie que le serveur
répond et que les modèles **réellement utilisés par la partie** sont installés (un pêcheur à IA « petit » n'exige pas le grand
modèle ; un ancien à IA, si), puis les charge en mémoire pour que la première saison ne commence pas par des appels qui attendent
le chargement. Le délai d'un appel Ollama est de 240 s (`llm.providers.ollama`). La `latency_s` enregistrée compte toute l'attente,
c'est le temps que l'agent a passé à réfléchir.

**Pourquoi les réflexions des IA ralentissaient le jeu, et ce qui a changé.** Sur une carte de 6 Go, Ollama sert **une requête à la
fois** et ne garde pas deux gros modèles en mémoire :

* *Échanges de modèle.* Alterner 7B et 1,5B coûte une trentaine de secondes à chaque passage de l'un à l'autre. Le réglage
  « rapide » prend un grand modèle de 3B qui **tient avec le 1,5B** dans la carte : plus aucun échange. En plus, une file
  d'attente (`ModelGate`, dans `filets/llm.py`) sert toutes les requêtes d'un modèle avant de passer à l'autre, au lieu de suivre
  l'ordre d'arrivée (au plus 24 de suite, pour que personne n'attende indéfiniment).
* *Longueur des réponses.* Un 7B produit environ 17 tokens par seconde, un 3B une soixantaine, un 1,5B une centaine : la génération
  coûte plus que la lecture du prompt. La **réflexion rapide** (`llm.reflection: rapide`) demande une phrase courte par champ, allège
  le contexte (8 dernières prises, 4 souvenirs, 2 documents, 8 dernières répliques) et borne la réponse (110 tokens pour une prise,
  150 pour une réplique, contre 350). `complete` reste le profil de référence des expériences : à utiliser pour les mesures.
* *Appels devenus inutiles.* En asynchrone, quand la pêche ou la veillée se ferme, les IA qui réfléchissent encore ont raté leur
  tour. Leur appel est **abandonné à cet instant** (événement `llm_call` de statut `cancelled`, compté à part des erreurs) au lieu
  d'attendre une réponse qui ne servirait plus : c'est ce qui faisait traîner la fin de chaque saison.

**« Réplique perdue » n'est pas une panne.** En asynchrone, le temps du monde suit le temps réel : pendant qu'une IA locale réfléchit
30 s, la veillée (78 heures simulées, soit 26 s réelles à 3 h/s et à × 1) avance et se ferme. L'IA qui n'a pas fini a raté sa fenêtre :
le fil affiche `RÉPLIQUE PERDUE` (ou `SORTIE PERDUE` pour la pêche) avec le tour concerné, et l'incident `missed_window` est
enregistré. Plus on va vite, plus l'IA paraît lente ; c'est pourquoi le menu propose une vitesse de départ par moteur d'IA
(× ¼ pour Ollama rapide, × 1/8 pour le 7B) et le jeu un bouton **Ralentir**. En **synchrone**, la lenteur d'une IA n'a aucun effet
sur le temps du monde : rien n'est jamais perdu.

**Sur un portable, la carte graphique chauffe.** Une partie longue avec Ollama la maintient à 100 % : vers 88 °C la fréquence tombe
(mesuré : de 2100 MHz à 210–580 MHz) et chaque réponse met 5 à 10 fois plus de temps qu'à froid. Les IA paraissent alors « lentes »
sans que rien ne soit cassé : brancher le secteur, soulever l'arrière du portable, ou ralentir le monde (asynchrone) y change plus que
n'importe quel réglage du jeu. `nvidia-smi --query-gpu=temperature.gpu,clocks.sm --format=csv` montre l'état de la carte.

Réglages du serveur Ollama (variables d'environnement, non appliquées par le jeu) : `OLLAMA_FLASH_ATTENTION=1` et
`OLLAMA_KV_CACHE_TYPE=q8_0` réduisent la mémoire du contexte ; `OLLAMA_NUM_PARALLEL=1` est déjà la valeur la plus sûre sur 6 Go.

**Un modèle de décision open à côté de Qwen (« Ollama · rapide + réflexes open », `config/ollama_open.yaml`).** Les choix simples
(une prise de routine, un bulletin de vote) n'ont pas besoin d'un texte : `tev1:0.8b` (Together AI, affiné à partir de Qwen 3.5,
0,8 Go) y répond par une question typée sur `POST /v1/systemone` d'Ollama, en un ou deux tokens avec les probabilités de chaque
réponse. Qwen garde la réflexion et les paroles. Il demande **Ollama 0.40.4 ou plus** (`winget upgrade Ollama.Ollama`, Ollama
fermé) puis `ollama pull tev1:0.8b` ; sans lui, la partie se lance quand même et ces décisions passent par Qwen 1,5B. Détails :
[docs/architecture.md § 4](docs/architecture.md#4-économie-de-tokens--système-1-et-système-2).

Pour une API (Groq, OpenRouter `:free`, Gemini, Mistral, GitHub Models) : copiez `.env.example` en
`.env`, exportez la clé, et adaptez `config/groq.yaml`. Toutes ces offres parlent le format OpenAI ;
un seul client gère limite de débit, reprises sur 429 et comptage des tokens. Vérifiez quotas et noms
de modèles au démarrage du projet : ils changent souvent, et certaines offres gratuites réutilisent
les données envoyées.

## Le monde

Une **saison** dure 30 jours simulés :

| Moment | Ce qui se passe |
|---|---|
| J0 06:00 | ouverture de la pêche : chaque pêcheur estime le stock (±10 %) et décide de sa prise |
| J20 | fermeture : une décision encore en cours est abandonnée et la sortie est perdue (`missed_window`, « sortie perdue ») |
| J25 18:00 | veillée chez l'ancien (toute la vallée, par hameau, ou aucune) : 1 à 3 tours de parole (2 par défaut) ; une parole pas prête à la fermeture est une « réplique perdue » |
| J29 | fin de veillée : une proposition soutenue par **au moins la moitié des pêcheurs présents** devient règle pour la saison suivante |
| J29 21:36 | repeuplement logistique, bilan, promesses tenues ou trahies |

Lac : capacité `12,5 t × nombre de pêcheurs` (même stock par tête quand on change d'échelle) ou limite choisie dans le menu,
croissance logistique de taux `r` (1 par défaut, réglable dans le menu), rendement durable maximal `r·K/4` par saison, atteint quand on
ramène le lac à la moitié de sa capacité. Économie : 100 écus la tonne, 150 écus de coût de la vie
par saison, 120 écus de dette pour les nouveaux venus, une sortie rapporte entre 1 t et la capacité du lac divisée par deux fois le nombre de pêcheurs (6,25 t pour 100 t et 8 pêcheurs : à eux tous, la moitié du lac au plus), et jamais plus que la barque (10 t).

Population (cycle de quatre archétypes de la fiche, répartis dans les quatre hameaux) :
famille ancienne prudente, nouveau venu endetté, taiseux qui relève ses filets en cachette, beau
parleur qui pêche peu ; plus **l'ancien**, arbitre sans pouvoir. Une part `rule_fraction` des
pêcheurs (tirée au sort) suit des règles fixes (A6).

Le menu de démarrage propose ces mêmes pêcheurs (mêmes prénoms, hameaux, archétypes, expérience et avoir que la composition
par défaut du moteur), mais tous réglés sur « IA auto » : c'est au joueur de passer certains en « Règles ». Lancé en ligne de
commande (`run`), le moteur garde ses 25 % d'agents à règles. Le menu permet de modifier la composition :
la liste choisie est transmise au moteur (`population.custom`, une fiche par
pêcheur : prénom, hameau, archétype, expérience, avoir, dette, cerveau). Elle remplace alors la génération ;
le nombre de pêcheurs, la capacité du lac et la part d'agents à règles en sont déduits, et le tout est enregistré dans
`runs/<id>/config.json` (la partie reste reproductible).

## Les IA voient le lac

Constat sur des parties réelles : le lac passait de 100 % à 0 % et les pêcheurs à IA demandaient toujours 5 à 7 t chacun (la prise
moyenne ne dépendait pas du stock), en disant « le lac semble bien rempli » avec un stock de 0 t. Le stock n'était qu'une ligne parmi
dix dans le contexte, sans repère ni tendance, et de vieilles paroles de la veillée le contredisaient. Ce que reçoit maintenant
chaque décision (`prompts.py`, `world.observe`) :

* **L'état du lac, en tête du contexte** : tonnes, pourcentage de la capacité et niveau en mots (plein, bien rempli, à peu près à
  moitié plein, bas, très bas, presque vide, **vide : il n'y a plus de poisson**), repéré par rapport à la moitié de la capacité où le
  lac se repeuple le mieux (le savoir des anciens figure aussi dans le texte du monde).
* **Ce que l'agent a constaté jusqu'ici** : la suite de SES propres estimations (ouverture de chaque pêche, chaque veillée) et la
  tendance (« il a beaucoup baissé », « il reste vide »). Rien d'inventé ni du futur (C6) ; chaque chiffre se rattache à la décision
  qui l'a porté (`used_event_ids`).
* **Un rappel juste avant la question** (les petits modèles lisent surtout la fin) : le niveau du lac, puis, quand il ne suffit plus
  à remplir toutes les barques, le partage qui en découle (« vous êtes 8 pêcheurs, il reste 40 t : si chacun en prenait 5, il n'en
  resterait plus du tout »), puis le repère des anciens en tonnes (« il y a 0 tonne au-dessus de la moitié du lac (50 t) »). Sans cette
  dernière ligne, les petits modèles lisaient « la moitié, 50 tonnes » comme un quota de prise.
* **Des souvenirs datés** : une parole de la veillée d'il y a deux saisons ne passe plus pour l'état du lac d'aujourd'hui.
* **Une réponse contrainte** : avec Ollama, la réponse est imposée par un schéma JSON (`llm.providers.ollama.json_schema`), la
  justification (ce que l'agent constate du lac et en conclut) AVANT la prise, de sorte que le nombre s'écrit à la suite de ce
  raisonnement. Sans cela, les petits modèles oubliaient souvent le champ « prise » et la décision retombait sur la règle de repli, qui
  tient compte du stock : il faut toujours compter les décisions en repli (`decision.fallback`) quand on mesure l'effet d'un prompt.
* **Les agents à règles ne demandent jamais plus que le lac qu'ils voient**, mais **une sortie rapporte toujours au moins `economy.min_catch` (1 t)** : on ne revient jamais bredouille. Une IA qui demande moins est ramenée à ce minimum (incident `invalid_value`), et un quota ou une promesse sous ce minimum vaut ce minimum.

## Le vote des règles

Avant, aucune règle n'était jamais adoptée : trois veillées avaient produit 41 propositions (7,0 ; 7,3 ; 7,4 ; 7,5 ; 4,2 ; 4,3…), les voix
dispersées. Maintenant, deux quotas à moins de `scenario.proposal_merge_tolerance` (0,75 t) sont la même proposition, et à la clôture un
**vote** compte ce que chacun a dit : qui n'a soutenu aucune proposition vote pour la plus proche de son quota proposé ou promis, à
`scenario.vote_tolerance` (1,5 t) près ; qui n'a rien dit de chiffré s'abstient. Chaque voix est un événement `support`. Une proposition
soutenue par au moins la moitié des pêcheurs présents (4 sur 8) devient une règle.

**Le bulletin.** Beaucoup de pêcheurs à IA ne disent aucun chiffre et ne soutiennent rien : ils s'abstenaient, et des propositions
manquaient le seuil d'une voix. Avant la clôture, chaque pêcheur à IA qui n'a rien soutenu remplit donc un **bulletin** : une
question de quelques lignes (les propositions, leurs soutiens, l'état du lac), posée au petit modèle, dont la réponse est contrainte
à l'identifiant d'une proposition ou « aucune » (10 tokens au plus, `llm_call` de nature `vote`, système 1). En asynchrone les
bulletins se remplissent 6 h avant la fin de la veillée (`time.ballot_lead_days`) : une IA trop lente perd sa voix, comme sa réplique.
Avec le faux LLM, qui ne sait pas répondre à un bulletin, on compte ce que chacun a dit.

Mesuré avec Ollama (3B + 1,5B, 8 pêcheurs, 6 saisons) : trois règles de 1,5 t adoptées (7, 7 puis 8 pêcheurs sur 8, accord 88 %), là où
il n'y en avait aucune. Mais la conformité reste faible (12 à 25 % des pêcheurs respectent la règle qu'ils ont votée) : on vote 1,5 t et
on pêche 4 à 10 t, l'écart entre ce qu'on dit et ce qu'on fait que le jeu étudie ; le lac s'est épuisé à la saison 6 et la partie s'est
arrêtée (« le lac est à sec »).

Pour resserrer les comportements (l'un pêchait 0 t, l'autre 10 t au même moment), chaque pêcheur reçoit aussi un résumé de ce que les
autres ont pris la saison dernière (« entre 2 et 6 t, 4,0 t pour le pêcheur du milieu »), et les règles adoptées servent de repère commun.

## Les annonces du joueur ont un effet

La barre du bas diffuse une **rumeur** (« Diffuser ») dans la vallée. C'est une injection : événement `injection`, souvenir de type
`rumeur` chez chaque habitant, bandeau « Une rumeur court » et ligne `RUMEUR` dans le fil. Ce qui la rend efficace :

* **Elle figure dans chaque décision à IA** (prise et parole, rubrique « Rumeurs qui courent dans la vallée »), pendant la saison de
  l'annonce et la suivante, puis elle est oubliée. Avant, elle n'était qu'un souvenir parmi d'autres, retrouvé par la mémoire dans
  moins d'une décision sur trois : elle se perdait parmi les prises, les promesses et les paroles de la veillée.
* **Elle est tracée.** L'onglet *Agent* liste ce qui a été retrouvé pour décider, et la rumeur y apparaît avec l'étiquette
  `[rumeur]` (source `rumor` dans `decision.retrieved`, identifiant = celui de l'événement d'injection : traçabilité F6).
* **Le faux LLM y réagit**, sinon une annonce serait sans effet en mode test : un mot de pénurie (« sécheresse », « plus de poisson »…)
  réduit les prises de 15 % ; une rumeur accusatrice qui nomme un pêcheur (« Inès ment sur ce qu'elle ramène ») fait accuser cette personne
  à la veillée par les caractères combatifs, la fait se défendre, et la rend sobre (−20 %) ; toute autre rumeur est relayée dans les paroles.
* **Les agents à règles restent sourds** : ils servent de témoin (A6), c'est ce qui permet de mesurer l'effet de la rumeur sur les IA.

## Ce qu'on observe : les interactions

Chaque prise de parole est un événement `utterance` (qui parle, à qui, ce qu'il a entendu avant),
et ses effets sont des événements séparés : `proposal`, `support`, `promise`, `accusation`,
`norm_adopted`, puis `promise_outcome` au bilan. Dans Godot :

* **bulle** au-dessus de celui qui parle, **flèche bleue** vers son destinataire, onde s'il parle à tous ;
* **badge doré** `P3 · 2 t` sur l'auteur d'une proposition, **lien vert** de chaque soutien vers l'auteur ;
* **flèche rouge** pour une accusation ; étiquettes « promesse trahie » / « parole tenue » au bilan ;
* onglet **Interactions** : le fil complet, filtrable sur l'agent sélectionné ;
* onglet **Agent** : profil, modèle, avoir, prises, promesses (annoncé vs réel), dernière décision
  avec son horizon d'information, sa justification ou la règle appliquée, et **tout ce qui a été
  retrouvé** pour décider (engagements épinglés, souvenirs, archives, rumeurs), puis la mémoire complète ;
* onglet **Règles** : propositions sur la table et historique des règles adoptées.

## La scène Godot

Vue de dessus de la vallée, dessinée entièrement en code (aucune image externe) :

* **le lac** est un shader : son eau se trouble et se couvre d'herbiers quand le stock passe sous la
  moitié, et **le nombre de poissons qu'on voit nager suit le stock** ; la prairie jaunit après une sécheresse ;
* **les pêcheurs** partent de leur hameau, prennent le ponton, sortent en barque jusqu'à leur coin de
  pêche, jettent le filet (« +3,2 t »), puis rentrent ;
* **le jour et la nuit** suivent l'heure simulée. La veillée se tient le soir : la carte s'assombrit,
  les fenêtres et les feux s'allument, et **la salle de l'ancien** s'ouvre par-dessus la carte, les
  participants assis en cercle autour du foyer. Les bulles s'y placent sans se chevaucher ;
* **les bandeaux** annoncent les moments clés : saison, ouverture de la pêche, veillée, règle adoptée,
  pas d'accord, sécheresse, effondrement ;
* l'horloge (soleil ou lune, phase en cours) est en haut à gauche, la jauge du lac (avec le repère de
  la moitié) en bas ; survoler un pion affiche son nom complet et son archétype.

Les pions et les liens gardent partout le même code : couleur = archétype, rond = agent LLM (anneau
épais doré = grand modèle), carré = agent à règles ; bleu = parole, vert = soutien, rouge =
accusation, or = proposition. La légende en bas de l'écran est dessinée avec les mêmes fonctions que
la carte. Le fil d'interactions reprend ces couleurs (noms des pêcheurs, étiquettes par type).

Polices : Nunito (interface) et Alegreya (titres), licence SIL OFL, fichiers dans `godot/fonts/`.

Test hors réseau de la vue (rejoue un run enregistré et vérifie l'état de la scène) :

```bash
godot --headless --path godot -s res://tests/feed_test.gd -- --events=$PWD/runs/<id>/events.jsonl
```

Captures automatiques d'un run en direct : `godot --path godot -- --shots=4,12,20 --shotdir=/tmp`.

Tests hors fenêtre de l'interface principale (fil des interactions, répliques perdues, annonces, bouton « Ralentir ») et du menu :

```bash
godot --headless --path godot -s res://tests/main_feed_test.gd -- --events=$PWD/runs/<id>/events.jsonl
godot --headless --path godot -s res://tests/menu_test.gd -- --catalog=/chemin/catalog.json   # (pytest le lance et valide la demande)
```

## Indicateurs (contexte commun, B1–B3)

Pour FILETS, le *contexte commun* est une **norme de prélèvement partagée** :

* `norm_agreement` : part de **tous** les pêcheurs qui ont soutenu la règle qui les concerne (hameau d'abord, vallée sinon) ;
* `norm_compliance` : part des pêcheurs soumis à une règle dont la prise la respecte (tolérance 0,5 t) ;
* `norm_index = accord × conformité` ∈ [0, 1].

Sans accord déclaré, l'indice vaut 0 même si tout le monde pêche par hasard la même chose : cette
coordination sans norme se lit à part dans `catch_cv` (dispersion des prises). Le témoin
`config/no_comm.yaml` (aucune veillée) donne un indice nul par construction, ce qui permet de
vérifier que l'indicateur distingue bien les deux situations (B3).

Également calculés en flux : stock / capacité, promesses tenues et écart promis/pêché, inégalité
des avoirs (Gini), incidents par type, appels et tokens LLM, violations de cohérence temporelle,
obsolescence moyenne (écart entre le lac observé et le lac au moment où la prise s'applique), et
décalage entre un événement et l'indicateur qu'il produit (`lag_s`, C7). Chaque indicateur porte la
liste des événements bruts qui l'ont produit (F6).

**Des chiffres vérifiables.** Chaque pourcentage est publié avec ses effectifs (`norm_supporters`, `norm_compliers`,
`norm_concerned`, `fishers`, `promises_kept`, `promises`) : Godot affiche « 6 sur 9 la respectent » sous « 67 % ».
Le stock en % est toujours `stock / capacité` du run en cours (`capacity` est publié avec l'indicateur) : il reste
entre 0 et 100 %.

**Garde-fous.** Les indicateurs ne se calculent qu'à partir du `run_start` du run en cours (capacité du lac, liste des
pêcheurs) : un événement qui arrive sans lui, ou d'un autre run, est ignoré plutôt que de produire des chiffres faux.
Les services Kafka reprennent donc au dernier `run_start` du topic, et le pont n'envoie à Godot que les indicateurs
du run affiché. `tests/test_indicators_audit.py` recalcule chaque indicateur à part, depuis les événements bruts, pour
des parties synchrones, asynchrones, par hameau, sans communication et à règles, et exige le même résultat.

## Le temps (C3–C6)

Chaque événement porte `sim_time` (moment dans le monde) et `processed_at` (moment réel).

* **Synchrone** : à chaque pas, tous les agents observent le même instantané ; le temps simulé ne
  bouge pas pendant qu'ils réfléchissent ; les actions s'appliquent ensemble (rationnement au
  prorata si la demande dépasse le stock). À la veillée, chaque tour est un pas : on n'entend que
  les tours précédents.
* **Asynchrone** : le temps simulé suit le temps réel (`sim_hours_per_second`, 3 h/s par défaut).
  Chaque pêcheur a son propre rythme ; sa prise s'applique au lac *tel qu'il est quand il a fini
  de réfléchir*. À la veillée, chacun parle dès qu'il est prêt et n'entend que ce qui a été dit
  avant. Quand personne ne réfléchit, l'horloge accélère (`idle_speedup`) : nul n'est désavantagé.

`sim_hours_per_second` convertit la latence d'un modèle en durée dans le monde : c'est un
paramètre du modèle de temps dont l'effet doit être mesuré. Aucun agent ne peut utiliser une
information postérieure à son horizon : mémoire, archives, paroles et propositions sont filtrées,
et toute violation est détectée et comptée.

**Changer de mode en cours de partie.** Chaque saison est jouée par l'une des deux orchestrations, choisie à son début :
c'est la frontière où elles parlent de la même chose (le calendrier d'une saison est identique). Une demande de changement
est donc appliquée à la saison suivante ; le journal garde la demande (`injection set_mode`) et le mode réel de chaque
saison (`season_start.mode`), et le temps simulé reste monotone à travers la bascule (vérifié par `filets verify`).
La pause et la vitesse sont tracées de la même façon (`injection pause|resume|set_speed|stop`).

## Données (F1–F6)

| Donnée | Où | Pourquoi |
|---|---|---|
| Flux d'événements | Kafka `filets.events` (1 partition, clé = acteur, 7 jours) | ordre total pour le rejeu et les indicateurs ; consommateurs indépendants |
| Indicateurs | Kafka `filets.indicators` | la scène et l'historique les consomment sans recalcul |
| État du moteur | Kafka `filets.status` (1 heure) | salon, partie en cours, pause, vitesse, mode : ce que la barre de pilotage affiche ; seul le dernier message compte |
| État courant du monde | mémoire du moteur | lu et écrit à chaque décision, latence nulle |
| Run rejouable | `runs/<id>/events.jsonl` + `config.json` | source unique du rejeu sans LLM (E3) |
| Historique des runs | SQLite `data/history.db`, ou **PostgreSQL** (`config/data.yaml`), vues typées | requêtes analytiques reproductibles entre runs (F5) ; JSONB indexé et écriture concurrente avec PostgreSQL |
| Base de connaissances | `corpus/*.md`, index BM25 en mémoire, ou **PostgreSQL + pgvector** (`config/data.yaml`) | BM25 : coût nul, scores explicables (F2) ; pgvector : recherche par le sens, vecteurs gardés d'une partie à l'autre ; accès par hameau et par date dans les deux cas |
| Souvenirs des agents | mémoire du moteur, ou **pgvector** (`config/data.yaml`) | mémoire collective d'une partie interrogeable par le sens (`GET /api/runs/{id}/memories?q=…`) |
| Fichiers bruts | `runs/<id>/`, et un **stockage objet S3** avec `config/data.yaml` | documents du corpus et archive de chaque partie, hors de la machine de jeu |
| Événements invalides | Kafka `filets.deadletter` | isolés sans arrêter la simulation (F4) |

Les schémas versionnés de chaque type d'événement sont dans `schemas/` (source : `filets/schemas.py`).

**PostgreSQL + pgvector et stockage objet (`config/data.yaml`).** `docker compose --profile data up -d` démarre PostgreSQL 17 avec
pgvector (sur 127.0.0.1:19432) et le stockage objet MinIO (S3 sur 127.0.0.1:19000, console sur http://127.0.0.1:19001 ; tout
service S3 convient). FILETS utilise des ports 19xxx (Kafka sur 19092) et non les ports standard, qu'un autre projet ou un
PostgreSQL installé peuvent tenir : les deux tournent en même temps, chacun avec ses conteneurs, ses volumes et ses identifiants.
`ollama pull embeddinggemma` installe le modèle de plongement (multilingue, 768 dimensions, calculé sur le processeur pour laisser
la carte graphique aux LLM). Puis `python -m filets serve --config config/data.yaml` (c'est ce que fait `.\start.cmd`). Si la base tombe en
cours de partie, la recherche se rabat sur BM25 en mémoire et la partie continue. Tout se fait en asynchrone (asyncpg,
miniopy-async, aiokafka, httpx). Voir [docs/architecture.md § 6](docs/architecture.md#6-stockage--postgresql--pgvector-et-stockage-objet).

## Arborescence

```
filets/            moteur : world.py (calendrier, sync/async), control.py (pause, vitesse, mode, arrêt),
                   engine.py (le salon : validation de la demande, vérification des IA, parties successives),
                   catalog.py (ce que propose le menu), agents.py, prompts.py, policies.py, profiles.py,
                   memory.py, rag.py, llm.py, routing.py, scripted.py, indicators.py, console.py, cli.py,
                   api.py (FastAPI), aio.py (aiokafka), vectors.py (plongements, pgvector), pgstore.py (historique
                   PostgreSQL), store.py (historique SQLite), objects.py (stockage objet S3)
filets/services/   services Kafka asynchrones : indicators, bridge (API FastAPI), store (PostgreSQL ou SQLite)
godot/             projet Godot 4 : main.gd (interface, barre de pilotage, inspecteur), start_menu.gd (menu de démarrage),
                   menu_map.gd (aperçu de la vallée du menu), world_view.gd (scène), art.gd (palette, pions), chart.gd,
                   legend.gd, shaders/valley.gdshader, fonts/, tests/ (feed_test.gd, menu_test.gd, main_feed_test.gd)
install.ps1, start.ps1, stop.ps1 (et .cmd)   installation, démarrage et arrêt sous Windows
corpus/            base de connaissances fictive de la vallée
config/            default, baseline (sans LLM), no_comm, hamlet, drought, ollama (7B), ollama_fast (3B),
                   ollama_open (3B + tev1), groq, data (PostgreSQL + pgvector, stockage objet)
docs/              architecture.md : architecture, temps, communication, tokens, asynchrone, stockage
schemas/           schémas JSON versionnés des événements
analysis/          requêtes SQL du rapport (queries.sql pour SQLite, queries_pg.sql pour PostgreSQL)
runs/              runs enregistrés (un exemple fourni)
tests/             tests de cohérence
```

## Ce qui reste à faire

* Brancher de vrais modèles et calibrer les prompts (sortie de rôle, posture d'« assistant
  prudent », agents trop conciliants : cf. pistes de la fiche).
* Évaluer la récupération (`filets retrieval`) : comparer BM25 et pgvector sur les mêmes décisions annotées.
* Valider le modèle de décision tev1 sur une vraie partie (Ollama 0.40.4) : part des réflexes, confiance, écart aux prises de Qwen.
* Mesure d'énergie (CodeCarbon pour Ollama, EcoLogits pour les API) à ajouter au bilan de coût.
* Le protocole expérimental : hypothèses, 5 runs × 2 configurations au moins, baseline (E1, E2).
* Exploiter les mesures déjà instrumentées pour l'excellence : décalage événement → indicateur sous
  charge (C7) et comparaison de deux tailles de population (`--agents`, C8).
