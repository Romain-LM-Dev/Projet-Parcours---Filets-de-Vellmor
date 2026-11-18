# FILETS : descriptif de la solution

Ce document présente le projet FILETS : ce que fait la solution développée et comment elle est construite. Il décrit le projet en général, avec ses réglages et leurs valeurs par défaut (source : `config/default.yaml` et le [dictionnaire](../uml/dictionnaire.md)). Il complète les vidéos du projet et se lit seul ; sa dernière partie décrit la partie de démonstration qu'elles montrent.

## 1. En bref

FILETS est une simulation de société. Des pêcheurs se partagent un lac qui se repeuple. Ils pêchent, vendent, se retrouvent le soir chez l'ancien, proposent des règles, promettent, s'accusent, et tiennent parole ou non. Chaque pêcheur est un agent qui décide de ses actes : quand sortir, où, combien prendre, ce qu'il déclare en rentrant, ce qu'il dit et vote à la veillée.

Un agent a un « cerveau » : un modèle de langage (IA), ou une règle fixe propre à son caractère. Le moteur ne décide jamais à sa place : il compte et applique la physique du monde (cale du bateau, poisson du lac, temps, durée des trajets).

Chaque décision, chaque parole et chaque prise sont enregistrées en événements, mesurées par des indicateurs calculés en flux, et rejouables sans appeler de modèle. Le projet sert ainsi de laboratoire pour étudier comment des IA coopèrent, se mentent, se surveillent et se donnent des règles. C'est un projet de la dominante IABD (intelligence artificielle et big data) : modèles de langage, mémoire par recherche de contexte (RAG), flux de données Kafka, indicateurs en direct.

> **Limite à connaître.** Par défaut, les agents utilisent un *faux LLM* (`scripted`) : il imite des réponses à partir de règles bruitées et sert à développer et à tester sans clé ni carte graphique. Aucun résultat scientifique ne doit en être tiré : il faut de vrais modèles (Ollama, ou une API) pour les expériences.

## 2. Le principe d'une partie

Une partie dure `run.seasons` saisons (10 par défaut). Une saison dure 30 jours simulés et suit une saison de l'année (printemps, été, automne, hiver, dans cet ordre ; la partie commence au printemps).

| Moment | Ce qui se passe |
|---|---|
| avant J0 | chaque village choisit son élu ; le capitaine de la patrouille, s'il y en a une, décide sa route |
| J0, 06:00 | ouverture de la pêche : plan de saison de chaque pêcheur, puis sorties |
| J20 | fermeture : aucune sortie ne commence plus ; une sortie commencée rentre normalement |
| J25, 18:00 | veillée chez l'ancien : indices, débat, propositions |
| J29 | fin de la veillée, vote de clôture |
| J29,9 | repeuplement des lacs, bilan de la saison, récit du narrateur |

Ces jours se règlent dans `time.*` (`season_days`, `fishing_close_day`, `assembly_day`, `assembly_close_day`, `regrowth_day`). Le poisson ne se renouvelle bien que si le lac n'est pas vidé : la vallée doit trouver des règles et les faire respecter, alors que chacun a intérêt à pêcher plus et peut mentir.

Fin de partie : après la dernière saison, ou tout de suite si tous les lacs tombent à 0 t (`run.stop_on_extinction: true` par défaut). Arrêter à l'effondrement (lac sous 5 % de sa capacité, `lake.collapse_ratio`) est possible, mais désactivé par défaut (`run.stop_on_collapse: false`).

## 3. Le monde

### 3.1 La vallée

La vallée est générée à partir d'une graine (`run.seed`, 42 par défaut) : mêmes paramètres et même graine donnent la même vallée. Ce qui se règle :

| Réglage | Défaut | Valeurs |
|---|---|---|
| `population.villages` | 4 | 1 à 8 (au plus un par pêcheur) |
| `population.fishers` | 8 | au moins 1 (24 au plus dans le menu) |
| `population.boat_mix` | barque 0,3 ; chaloupe 0,5 ; cotre 0,2 | part de chaque taille de bateau |
| `lake.count` | 1 | 1 à 4 lacs |
| `population.random` | non | oui : villages, pêcheurs, flotte, lacs, poisson et patrouilles sont tirés de la seule graine |
| `population.custom` | absent | composition choisie à la main (une fiche par pêcheur) ; remplace la génération |

Chaque pêcheur a sa propre suite de tirages : ajouter un pêcheur ne change pas les autres fiches. Les villages sont posés autour de leur lac, et chacun a une rive. Les lacs peuvent être décrits un à un (`lake.lakes` : nom, capacité, part pleine au départ, repeuplement, villages).

Préréglages de vallée : `default` (4 villages, 8 pêcheurs), `large` (4 villages, 18 pêcheurs), `lakes` (6 villages, 16 pêcheurs, 3 lacs, 2 patrouilles), `random` (tout tiré de la graine).

### 3.2 Les mailles

La vallée se découpe en trois grilles, chacune adaptée à ce qu'elle porte :

- **les lacs : 30 × 30 parcelles.** Chaque lac est une tache de parcelles au bord ondulé. Chaque parcelle a son poisson (plus au fond qu'au bord) et sa chance. Une barque pêche autour de sa parcelle : elle vide d'abord celle-ci, puis ses voisines. Chaque pêcheur choisit son coin sur la rive de son village, d'après son expérience ;
- **les maisons : 24 × 24 lots**, un obstacle chacune ;
- **les personnages : 120 × 120 pas**, avec recherche de chemin. Les barques ne vont que sur l'eau.

### 3.3 Le lac

Le stock suit une croissance logistique appliquée une fois par saison : `stock + r × stock × (1 − stock/K)`. Elle est la plus forte à moitié plein, où le lac regagne `r·K/4` par saison (rendement durable maximal).

| Réglage | Défaut | Sens |
|---|---|---|
| `lake.capacity` | `auto` | capacité K en tonnes, ou `auto` = 12,5 t × nombre de pêcheurs |
| `lake.initial_ratio` | 1,0 | stock de départ, en part de K (le lac part plein) |
| `lake.growth_rate` | 1,0 | taux de repeuplement r (0,1 à 2 dans le menu) |
| `lake.collapse_ratio` | 0,05 | sous ce ratio, le lac est effondré |
| `lake.observation_noise` | 0,10 | erreur relative d'un pêcheur qui estime le stock |

Un lac à 0 ne se repeuple jamais, puisque la croissance part du stock : sous 50 kg, il est tenu pour éteint. L'effondrement (sous 5 %) est un seuil de mesure : un lac effondré peut encore se refaire.

### 3.4 Le climat et les événements

Chaque saison de l'année change ce que rapporte la pêche et la vitesse de repeuplement :

| Saison | Pêche | Repeuplement |
|---|---|---|
| printemps | × 1,00 | × 1,3 |
| été | × 1,15 | × 1,1 |
| automne | × 1,00 | × 0,9 |
| hiver | × 0,75 | × 0,7 |

À partir de la 2e saison, un événement survient avec la probabilité `climate.event_rate` (0,3) : sécheresse, tempête, banc de poissons, algues, crue, maladie des poissons (`climate.disabled_events` en exclut). Le temps de chaque jour (calme, ordinaire, agité, tempête) est tiré pour tout le lac, avec une inertie ; un mauvais jour pèse plus sur une barque que sur un cotre. Le climat se désactive avec `climate.enabled: false`.

### 3.5 La chance

Chaque pêcheur a sa chance, qui varie autour de 1 d'un écart-type `economy.luck` (0,4) : moitié forme de la saison (qui se prolonge d'une saison à l'autre, `economy.luck_streak`), moitié forme de la sortie. Avec `economy.luck: 0`, seul le temps compte. Le tirage est propre au pêcheur et à la saison : l'ordre des retours n'y change rien.

### 3.6 L'économie et les bateaux

Le poisson se vend 100 écus la tonne ; le coût de la vie est de 100 écus par saison, plus l'entretien du bateau ; un nouveau venu part avec 120 écus de dette par saison.

| Bateau | Prise maximale par saison | Entretien par saison |
|---|---|---|
| barque | 4 t | 20 écus |
| chaloupe | 7 t | 50 écus |
| cotre | 11 t | 110 écus |

La prise d'un pêcheur ne dépasse ni la cale de son bateau ni sa part du poisson de son lac : au plus `economy.hold_fraction` (0,5) du stock, partagé entre les bateaux du lac en proportion de leur cale. Un lac qui se vide laisse donc prendre de moins en moins. Une sortie rapporte au moins `economy.min_catch` (1 t).

### 3.7 Les trajets entre lacs

Avec plusieurs lacs, un pêcheur peut pêcher dans un autre lac que celui de son village. La route est une contrainte appliquée par le moteur : `economy.travel_days` (1,5 jour pour traverser toute la carte, à l'aller) s'ajoute à l'aller et au retour de chaque sortie, et `economy.travel_cost` (10 écus par jour de mer) se paie à chaque sortie. Le pêcheur pêche alors au large du lac visé. Le moteur ne pose aucun seuil : c'est le pêcheur qui décide s'il vaut la peine d'y aller.

## 4. Les habitants

### 4.1 Les archétypes

Quatre archétypes se répartissent en cycle dans les villages. Chacun a une expérience, un avoir et une dette types (modifiables), une façon de parler et des priorités que les modèles reçoivent dans leur consigne.

| Archétype | Expérience type | Dette par saison | Trait |
|---|---|---|---|
| famille ancienne | 22 à 40 ans | 0 | prudente, tient à sa réputation |
| nouveau venu endetté | 1 à 5 ans | 120 écus | pense à la saison en cours |
| taiseux | 12 à 25 ans | 0 | discret ; peut relever ses filets en cachette |
| beau parleur | 8 à 20 ans | 0 | éloquent, propose des règles, pêche peu |

L'**ancien** est un arbitre sans pouvoir (`population.elder`, présent par défaut) : il ne pêche pas, tient les comptes du lac, relate les indices et ouvre la veillée. Il ne sanctionne pas et ne vote pas de sanction ; à la veillée, il parle et peut proposer une règle, mais son soutien ne compte pas dans l'adoption. Il est une IA ou suit des règles (`population.elder_kind` : `llm` par défaut, ou `rule`).

### 4.2 Les cerveaux

| Cerveau | Ce qui décide |
|---|---|
| IA auto | un modèle de langage, dont la taille dépend de l'expérience : grand à partir de 15 ans (`population.large_model_min_experience`), petit en dessous ; jamais selon une catégorie sociale |
| IA grand / IA petit | un modèle de langage de la taille imposée |
| Règles | aucune IA : une règle fixe propre à l'archétype, la même pour une situation donnée |

Part d'agents à règles par défaut : `population.rule_fraction` = 0,25, tirée au sort, en ligne de commande (`run`). Dans le menu de démarrage, la vallée proposée met tous les pêcheurs en « IA auto » : c'est au joueur de passer certains en « Règles ». Avec `rule_fraction: 1.0` (préréglage `baseline`), la partie n'a aucun modèle de langage.

Les agents à règles servent de témoin : ils séparent l'effet « IA » de l'effet « profil ». Ils servent aussi de règle de repli : un pêcheur à IA dont le modèle ne répond pas, ou répond de façon inexploitable, joue la règle de son archétype à la place, et l'incident est compté.

Principe : chaque acte d'un agent vient de sa réflexion (modèle) ou de la règle de son archétype. Le moteur compte et applique la physique ; il ne pose aucun seuil de comportement.

## 5. Les modèles d'IA

### 5.1 Les niveaux

| Niveau | Rôle | Obligatoire |
|---|---|---|
| grand | plan de saison, sorties quand la situation change, paroles de veillée, récit (par défaut) | oui |
| petit | mêmes tâches pour les agents moins expérimentés ; bulletins de vote en l'absence de réflexe | oui |
| réflexe | décisions de routine et bulletins : un choix typé avec ses probabilités, sans texte | non (`llm.tiers.reflexe`) |
| narrateur | récit de fin de saison ; sans ce niveau, le grand modèle | non (`llm.tiers.narrateur`) |

### 5.2 Fournisseurs et préréglages

Les fournisseurs déclarés sont Ollama (local, sans clé), Groq, OpenRouter, Gemini, Mistral et GitHub Models ; les offres en ligne parlent le format OpenAI et un seul client gère limite de débit, reprises sur erreur 429 et comptage des tokens. Les clés se donnent par variables d'environnement (`.env.example`).

| Préréglage (menu) | Fichier | Modèles |
|---|---|---|
| faux LLM de test (défaut) | `default.yaml` | `scripted`, déterministe, sans clé ni GPU |
| Ollama · rapide (recommandé sur 6 Go) | `ollama_fast.yaml` | Qwen 2.5 3B (grand) et 1,5B (petit) ; réflexion `rapide` |
| Ollama · rapide + réflexes open | `ollama_open.yaml` | idem, plus `tev1:0.8b` en réflexe ; réflexion `adaptive` |
| Ollama · qualité | `ollama.yaml` | Qwen 2.5 7B (grand) et 1,5B (petit), nettement plus lent |
| Groq (API gratuite) | `groq.yaml` | `llama-3.3-70b-versatile` (grand) chez Groq, `qwen2.5:1.5b` (petit) sur Ollama |

Avant de lancer, le moteur vérifie que le serveur répond, que les modèles réellement utilisés par la partie sont installés et que la clé d'API est présente. Un niveau se règle dans `llm.tiers.<niveau>` (fournisseur et modèle). Les parties à vraie IA sur un PC portable sont limitées par la carte graphique, qui peut chauffer et ralentir les réponses.

### 5.3 Trois profils de réflexion

`llm.reflection` : `complete` (réponses libres, contexte entier, profil de référence des expériences), `rapide` (une phrase courte par champ, contexte allégé, réponse bornée, environ deux fois plus rapide) ou `adaptive` (système 1 / système 2, ci-dessous).

### 5.4 L'aiguillage système 1 / système 2

Avec `adaptive`, le code (`filets/routing.py`) choisit pour chaque décision de pêche entre :

- le **système 1**, le réflexe : la situation est de routine (lac à plus de 70 % et qui ne baisse pas, engagement ou règle à suivre, aucune rumeur, finances correctes), ou, pour une sortie, rien n'a changé depuis la décision précédente. Un contexte de quelques lignes, une réponse d'un nombre ; le modèle de réflexe s'il existe, sinon le petit modèle ;
- le **système 2**, la réflexion : tout le reste (première saison, lac qui baisse, rumeur, événement, finances tendues, interdit de pêche, règle nouvelle, indice contre lui…), avec la justification avant le nombre.

Les paroles de la veillée sont toujours du système 2 ; les bulletins sont du système 1. Chaque appel et chaque décision portent leur système (`S1` ou `S2`) et leur niveau, et les indicateurs comptent appels et tokens par système.

### 5.5 Le contrôle des réponses

La forme de la réponse est imposée au fournisseur (schéma JSON avec Ollama ; question typée pour le réflexe). Une graine stable est envoyée par partie, agent, saison, nature et tour. Les réponses sont ensuite contrôlées :

| Cas | Traitement |
|---|---|
| réponse absente ou illisible | nouvelles tentatives (`llm.max_retries`, 3), puis règle de repli ; incident |
| valeur hors bornes (prise sous le minimum, quota hors limites) | ramenée dans les bornes ; incident `invalid_value` |
| réponse hors rôle ou posture d'assistant | action conservée, incident signalé |
| réplique déjà dite dans la partie | une seconde demande au même modèle ; si elle se répète, l'agent se tait |

Toute décision qui retombe sur la règle de repli est marquée `fallback`. Rien n'est perdu en silence.

## 6. Une saison de pêche

1. **Le plan.** À l'ouverture, chaque pêcheur fait son plan de saison (toujours le grand modèle pour une IA, la règle de l'archétype sinon) : ce qu'il compte prendre, où, ce qu'il compte déclarer, sa première sortie.
2. **Les sorties.** À l'ouverture puis à chaque retour, il décide la prochaine : quand (« dans 3 heures », « demain à l'aube », « plus cette saison »), où (sa rive, le large, la rive d'un autre village, un autre lac), combien, et courte (3 h de pêche) ou longue (7 h). On ne pêche pas de 21 h à 5 h ; plusieurs sorties le même jour sont possibles ; aucune ne commence après la fermeture (J20).
3. **La physique.** Une sortie rapporte selon le temps du jour, la chance, la saison de l'année, l'événement en cours, l'expérience du pêcheur (±0,5 % par année d'écart à 15 ans) et la difficulté d'un lac bas (sous 30 % de la capacité). Elle ne dépasse pas la cale de son bateau. Le poisson sort du lac au retour.
4. **La déclaration.** À chaque retour, le pêcheur déclare la sortie à l'ancien : il peut dire vrai ou cacher une part, sortie par sortie. Seuls lui et le joueur connaissent la vraie prise. Une IA décide de sa déclaration en même temps que sa sortie suivante ; les agents à règles suivent leur caractère (le taiseux et le nouveau venu cachent parfois une part ; la famille ancienne et le beau parleur disent vrai).
5. **Les indices.** Le soir de la veillée, les indices de la saison sont réunis. Un mensonge se découvre sur des indices, pas au hasard :

| Indice | Poids | Réglage |
|---|---|---|
| patrouille (mesure la charge à ±12 %) | 3 | `scenario.detection.patrol` (0,9) |
| témoin voisin (charge à ±30 %) | 1 | `witness` (0,4) |
| départ vu (barque d'un interdit de pêche) | 1 | `seen_leaving` (0,3) |
| train de vie | 0,5 | `lifestyle` (0,5) |
| comptes du lac tenus par l'ancien (à ±3 % de la capacité) | 0,5 | `lake_error` (0,03) |

6. **L'enquête de l'ancien.** À l'ouverture de la veillée, l'ancien relate ce que les indices établissent. Un mensonge est établi quand le poids cumulé atteint `proof` (2,0) et que l'estimation dépasse la déclaration de plus de 25 % et de `margin_t` (0,3 t, ramené à la taille d'une sortie). Les indices s'additionnent d'une sortie à l'autre : un menteur répété est bien plus facile à établir qu'un menteur d'une fois. L'ancien peut se tromper : il juge sur des estimations. Un témoin sans reproche dit ce qu'il a vu, sauf contre un ami (confiance de 0,8 et plus) ; qui a triché se tait.

## 7. La veillée et le conseil

### 7.1 Qui parle

`scenario.communication` : `valley` (le conseil de la vallée, par défaut), `hamlet` (une veillée par village) ou `none` (aucune veillée, donc aucune règle possible). `scenario.council` : `delegates` (un élu par village, par défaut) ou `all` (tous les pêcheurs). Avec des élus, seuls les élus et l'ancien parlent et votent.

Avant chaque saison, chaque village élit son représentant : chaque pêcheur vote, par sa propre réflexion (IA) ou selon sa règle (en qui il a le plus confiance), pour celui des siens qu'il juge le plus apte. Le moteur ne fait que compter. Un interdit de pêche ne peut pas être élu. Les villageois absents du conseil en apprennent ensuite les décisions par l'ancien et jugent à leur tour.

### 7.2 La parole

- Les répliques se préparent en parallèle ; **une seule personne parle à la fois**, et une réplique dure `time.speech_minutes` (20 minutes simulées) ;
- celui à qui l'on vient de s'adresser répond en priorité ; une réplique dépassée par la discussion est préparée de nouveau ;
- chacun a au plus `scenario.assembly_rounds` répliques (2 par défaut) ; dès le 2e tour, seul reprend la parole celui qui a une raison (`scenario.quiet_listeners`) ;
- une réplique qui répète ce qui a déjà été dit est redemandée une fois, puis l'agent se tait (contrôle des redites, vrais modèles seulement).

Une réplique peut proposer une règle, en soutenir une, promettre, accuser, proposer d'interdire un pêcheur de pêche ou de le réautoriser, et proposer d'installer ou de retirer la patrouille.

### 7.3 Les cinq sortes de règles

| Type | Contenu | Portée possible |
|---|---|---|
| quota | tonnes par pêcheur et par saison | vallée ou village |
| réserve | une zone interdite (rive d'un village ou large d'un lac), pour 1 à 3 saisons | vallée ou village |
| repos | un lac fermé à la pêche, pour 1 à 3 saisons | vallée ou village |
| sorties | nombre maximal de sorties par saison | vallée ou village |
| bateau | taille de bateau maximale | vallée ou village |

Avec plusieurs lacs, un quota, un nombre de sorties ou une taille de bateau peuvent aussi ne valoir que pour un seul lac (portée `lake:<nom>`) ; une réserve et un repos visent déjà une zone ou un lac. Deux propositions ne se rejoignent que du même type et de la même cible ; pour les quotas, deux valeurs à moins de `scenario.proposal_merge_tolerance` (0,75 t) sont la même proposition. Respecter une règle reste le choix de chaque agent ; une violation se voit par la patrouille et les témoins.

### 7.4 L'adoption

À la clôture, chaque agent qui n'a soutenu aucune proposition remplit un bulletin (une question à choix : une proposition ou « aucune »). Les agents à règles votent pour la proposition la plus proche de leur quota, à `scenario.vote_tolerance` (1,5 t) près ; qui n'a rien dit de chiffré s'abstient. Une proposition soutenue par **au moins la moitié des pêcheurs présents** (pour une règle d'un seul lac : des pêcheurs de ce lac ; le soutien de l'ancien ne compte pas) devient une règle, valable dès la saison suivante.

### 7.5 Les sanctions et la patrouille

- **Interdiction de pêche.** Un pêcheur propose d'interdire un autre de pêche, ou de le réautoriser. Les autres présents (sauf le visé) votent ; avec au moins la moitié des voix, la décision vaut dès la saison suivante. Un interdit ne déclare plus rien : il reste à quai ou pêche en cachette, au large.
- **Patrouille.** Un agent (le capitaine, une IA ou un agent à règles) décide sa route : `scenario.patrol.count` patrouilles (1 par défaut, 0 à 4), chacune avec `legs` étapes (3) et `days` jours de mer (14). Elle mesure les barques qu'elle croise. Elle n'a aucun pouvoir de punir. Le conseil la vote ou la retire ; elle coûte `scenario.patrol.cost` écus (15) à chaque pêcheur par saison. `scenario.patrol.enabled: false` la supprime de la partie ; `from_season` l'installe sans vote, pour comparer des parties.

## 8. Confiance, mémoire et RAG

### 8.1 La confiance

Chaque agent a une confiance envers chaque pêcheur, de 0 à 1, à 0,5 au départ. Le moteur ne la fixe pas : chaque agent dit lui-même ce que ce qu'il apprend change pour lui (de −3 à +3, par pas de 0,1) : une IA dans sa réplique, un agent à règles selon son caractère. Le jugement pèse la gravité d'un mensonge, le voisinage, la chance, les dettes, ce qu'il pensait déjà du pêcheur et son tempérament. Chaque jugement est un événement `trust`, et la réputation d'un pêcheur est la moyenne de la confiance des autres. La confiance oriente les réactions : on ne dénonce pas un ami, on ne soutient pas qui l'on ne croit plus.

### 8.2 Ce que l'agent retient

- **Une mémoire personnelle** : des souvenirs datés (prises, promesses, accusations, règles, paroles, rumeurs). Un souvenir n'est jamais retrouvé avant son instant simulé : un agent n'agit pas sur une information qu'il n'avait pas encore (vérifié par les indicateurs de violation temporelle) ;
- **des engagements épinglés** (promesse faite, accusation reçue) : ils reviennent à chaque décision tant qu'ils sont d'actualité ;
- **un carnet** court dans chaque décision : ses vraies prises et ce qu'il a déclaré, ses engagements, sa confiance envers les autres ;
- **un corpus** fictif de la vallée (`corpus/`, 9 documents : comptes de marché, coutumes de la veillée, dires des anciens, observations du lac…) ;
- **le lore de la partie** : les moments marquants, `rag.lore_per_agent` (4) par agent, le moins important partant d'abord.

### 8.3 Comment c'est retrouvé

| Réglage | Défaut | Sens |
|---|---|---|
| `memory.top_k` | 6 | souvenirs remis à l'agent à chaque décision |
| `memory.weights` | récence 1, importance 1, pertinence 1,5 | poids du score d'un souvenir |
| `memory.recency_decay_per_day` | 0,01 | perte de fraîcheur par jour simulé |
| `rag.top_k` | 3 | passages du corpus remis à l'agent |
| `rag.backend` | `bm25` | `bm25` ou `pgvector` |

Par défaut (`bm25`), la pertinence se mesure par mots, en mémoire : aucun service, aucun calcul de vecteur. Avec `rag.backend: pgvector` (préréglage `data.yaml`), corpus et souvenirs sont rangés dans PostgreSQL avec leur vecteur et cherchés par le sens (similarité cosinus, `rag.min_score`). Les vecteurs viennent d'un modèle de plongement d'Ollama (`embeddinggemma`, 768 dimensions, calculé sur le processeur pour laisser la carte graphique aux modèles de langage) ; le mode `hash` (384 dimensions, sans modèle) sert aux tests. Les droits (village, instant simulé) sont appliqués dans la requête. Si la base tombe en cours de partie, la recherche se rabat sur BM25 : aucune décision n'est privée de contexte. Avec pgvector, les souvenirs de tous les agents d'une partie forment une mémoire collective interrogeable par le sens (`GET /api/runs/{id}/memories?q=…`).

Chaque décision enregistre ce qui a été retrouvé pour la prendre : la décision est traçable.

## 9. Le narrateur

À la fin de chaque saison, un narrateur extérieur et omniscient écrit le récit : il sait la vérité, mensonges non découverts compris. Il reçoit au plus 10 faits relevés dans le journal (les lacs en mots, mensonges, sorties en cachette, dépassements) et aucun tonnage ni pourcentage. Le code vérifie que le récit n'invente aucun nombre (seconde demande, sinon retrait des phrases fautives), coupe à la dernière phrase complète et ajoute les chiffres exacts sur une ligne « En chiffres : … ». Sans IA, le récit reprend simplement les faits. Le récit est un événement (`narration`), rejoué comme les autres, et ne change rien au monde.

## 10. Le temps simulé

Le temps du monde est simulé, en jours ; chaque événement porte `sim_time` (le moment dans le monde) et `processed_at` (le moment réel). Un **ordonnanceur à événements** mène chaque saison ([temps.md](../temps.md)) :

- **réfléchir ne prend pas de temps, agir en prend.** Une décision est instantanée dans le monde ; une sortie, un trajet et une prise de parole durent. La lenteur d'une IA ne fait perdre aucune sortie et ne change pas le monde ;
- les décisions qu'aucun effet ne sépare partent **en parallèle** vers les modèles (limite : la carte graphique) ;
- les effets s'appliquent dans l'ordre de la file (temps simulé, classe d'acteur, clé tirée de la graine), jamais dans l'ordre où les modèles répondent ;
- l'horloge d'affichage avance à `time.sim_hours_per_second` (3 h par seconde réelle), accélérée de `idle_speedup` (40) quand rien ne se passe. Elle ne règle que ce que montre l'interface.

**Déterminisme.** À graine et réglages égaux, avec le faux LLM, deux parties donnent le même journal. Avec de vrais modèles, une graine stable est envoyée aux fournisseurs qui la respectent (Ollama), mais rien ne garantit des réponses identiques d'une partie à l'autre.

## 11. Le joueur

Le joueur prépare la partie dans le menu de démarrage de Godot tant que le moteur est en salon (`serve`) :

| Rubrique | Ce qu'on règle |
|---|---|
| durée et hasard | nombre de saisons, graine |
| la vallée | veillées (vallée, par village, interdites), conseil (élus ou tous), tours de parole (1 à 3), prises connues de tous ou non, ancien présent ou non |
| le lac | stock maximal (10 à 1000 t, ou auto), repeuplement, arrêt si le lac est vide |
| vallée, lacs, patrouilles | paramétrée ou aléatoire, 1 à 4 lacs, 1 à 4 patrouilles ou aucune |
| saisons et hasard | saisons de l'année, événements et leur fréquence, chance |
| moteur d'IA et réflexion | faux LLM, Ollama rapide ou qualité, Groq ; profil de réflexion |
| pêcheurs | 1 à 24 : prénom, village, archétype, bateau, expérience, avoir, dette, cerveau ; génération de la vallée d'après la graine |
| vitesse | de × 1/16 à × 16, ou maximale |

Pendant la partie, une barre de pilotage permet **pause**, **vitesse**, **arrêt** (écran de fin, puis nouvelle partie) et des **interventions** : des boutons injectent des événements dans la partie en cours, dont une rumeur (« Diffuser ») et une sécheresse. Une rumeur est tracée dans la décision des IA qui l'ont lue ; les agents à règles n'y réagissent pas, ce qui permet d'en mesurer l'effet sur les IA. Des interventions peuvent aussi être programmées dans la configuration (`scenario.scheduled_injections`) pour comparer des parties.

**Ligne de commande** (`python -m filets …`) :

| Commande | Rôle |
|---|---|
| `serve` | ouvre le salon (menu de Godot, API sur le port 8765) |
| `run` | lance une partie tout de suite, enregistrée dans `runs/<id>/` |
| `replay <id>` | rejoue une partie sans aucun appel de modèle, recalcule et compare les indicateurs |
| `verify <id>` | vérifie schémas, ordre, monotonie du temps, violations temporelles |
| `batch` | parties répétées (graines successives), moyenne et écart-type par configuration |
| `query`, `ingest`, `retrieval`, `schemas`, `bench-reflexe` | requêtes sur l'historique, import, qualité de la recherche de contexte, export des schémas, banc du modèle réflexe |

Toute clé de configuration se surcharge avec `--set clé=valeur`. L'**API** (FastAPI, port 8765, écoute locale seulement, sans authentification) offre un WebSocket pour Godot et du REST : `/api/health`, `/api/status`, `/api/catalog`, `POST /api/commands`, `/api/runs`, `/api/runs/{id}`, `/api/runs/{id}/events`, `/api/runs/{id}/memories`. Elle est documentée sur `/docs`.

## 12. Les données

- **Les événements.** Chaque geste est un événement JSON avec la même enveloppe (`event_id`, `run_id`, `seq`, `sim_time`, `processed_at`, `actor`, `payload`) et un schéma versionné par type (45 fichiers dans `schemas/`, exportés par `python -m filets schemas`). Un événement non conforme va dans la file des messages refusés et un incident le dit.
- **Le journal.** Le moteur écrit lui-même `runs/<id>/events.jsonl` avant et indépendamment de Kafka : la partie est complète et rejouable même si un service tombe.
- **Kafka.** Avec `--bus kafka`, les événements transitent par Apache Kafka (un nœud en mode KRaft, via Docker Compose) :

| Sujet | Contenu |
|---|---|
| `filets.events` | tous les événements (une partition, ordre total, conservés 7 jours) |
| `filets.indicators` | indicateurs calculés |
| `filets.commands` | ordres du joueur et du menu vers le moteur |
| `filets.status` | état du moteur (salon, en cours, pause, vitesse), conservé une heure |
| `filets.deadletter` | messages refusés par la validation |

Trois services asynchrones : `indicators` (calcule en flux, se place sur le dernier `run_start` : démarré avant, pendant ou après la partie, il aboutit aux mêmes chiffres), `store` (historique) et `bridge` (API et WebSocket). Sans Kafka, un bus local en mémoire a la même interface : aucun service à lancer.

- **Les indicateurs.** Calculés en flux, chacun avec la liste des événements qui l'ont produit et ses effectifs (« 6 sur 9 la respectent »).

| Indicateur | Sens |
|---|---|
| `stock_ratio` | stock en part de la capacité (par lac avec plusieurs lacs) |
| `norm_agreement` | part des pêcheurs qui ont soutenu la règle qui les concerne |
| `norm_compliance` | part des pêcheurs soumis à une règle dont la vraie prise la respecte (à 0,05 t près) |
| `norm_index` | accord × conformité, entre 0 et 1 |
| `catch_cv` | dispersion des prises (coordination sans norme) |
| `promises`, `promises_kept` | promesses faites et tenues ; écart promis / pêché |
| inégalité des avoirs | indice de Gini |
| `incidents_total` et par type | réponses des modèles à problème |
| `llm_calls`, `llm_tokens` (et `_s1`, `_s2`) | appels et tokens, au total et par système |
| `temporal_violations` | décisions qui auraient utilisé une information venue du futur |
| `mean_staleness_ratio` | écart entre le lac observé et le lac au moment où la prise s'applique |
| `rules_in_force`, `rule_kinds`, `rule_breachers` | règles en vigueur, leurs types, nombre d'infractions |

- **Le stockage.** L'historique des parties est dans SQLite (`data/history.db`, par défaut) ou PostgreSQL 17 (`storage.history: postgres`), avec des vues typées et des requêtes d'analyse reproductibles. Avec `config/data.yaml`, PostgreSQL porte aussi le RAG (pgvector) et un stockage objet S3 (MinIO en local) garde les documents du corpus et l'archive de chaque partie.
- **Le rejeu.** `replay` rejoue une partie depuis son journal, avec le bus local ou avec Kafka, sans appeler de modèle ; `verify` en contrôle la cohérence.

## 13. L'interface Godot

L'interface (Godot 4.7, GDScript) reçoit la partie du moteur par WebSocket. Elle affiche et ne décide rien. Elle dessine la vallée entièrement en code, en vue isométrique :

- **la carte** : caméra libre (zoom à la molette, glissement, flèches), mini-carte, mailles affichables (touche G), lacs dont l'eau et le nombre de poissons visibles suivent le stock de chaque parcelle ;
- **les personnages** : les pêcheurs partent de leur village, sortent en barque jusqu'à leur coin de pêche et rentrent ; couleur = village ou archétype, rond = IA, carré = agent à règles ; le jour et la nuit suivent l'heure simulée ;
- **la veillée** : la salle de l'ancien s'ouvre par-dessus la carte, les participants en cercle, avec bulles, flèches de destinataire, propositions et soutiens ;
- **des bandeaux** pour les moments clés (saison, règle adoptée, sécheresse, effondrement) ;
- **des onglets** : interactions (fil filtrable), récit du narrateur, confiance (jauge par pêcheur, interdits, mensonges établis), fiche d'agent (profil, modèle, plan, dernière décision et ce qui a été retrouvé pour la prendre, mémoire), règles ;
- **la barre de pilotage** : pause, vitesse, interventions, qui est en réflexion ;
- cartes d'indicateurs et courbes par saison.

## 14. Qualité et documentation

- **Tests** : 605 tests automatisés collectés par pytest (moteur Python, et interface Godot lancée sans fenêtre ; les tests Kafka et Godot sont ignorés si les outils sont absents), dont l'audit des indicateurs recalculés à part depuis les événements bruts. Compte du 2026-11-18, commande `.venv/Scripts/python -m pytest --collect-only -q`.
- **Diagrammes UML** : près de cent diagrammes Mermaid (cas d'utilisation, séquences, communication, classes), réunis dans [un PDF](../uml/FILETS-diagrammes-UML.pdf), et [une affiche A0](../uml/FILETS-classes-A0.pdf) de toutes les classes.
- **Dictionnaire** : [chaque paramètre de configuration](../uml/dictionnaire.md) (type, défaut, valeurs, sens), la ligne de commande, puis les variables de chaque classe.
- **Spécifications** : [l'architecture](../architecture.md), [le temps](../temps.md) et [la pêche](../peche.md).
- **Licence** : source-available non commerciale ([LICENSE.md](../../LICENSE.md)).

## 15. Pile technique

| Partie | Technologie |
|---|---|
| Moteur de simulation | Python 3.13, asyncio (ordonnanceur à événements discrets) |
| API | FastAPI sur uvicorn, REST et WebSocket |
| Modèles d'IA | Ollama en local (Qwen 2.5 1,5B, 3B, 7B ; `tev1:0.8b` pour les réflexes ; `embeddinggemma` pour les plongements) ; Groq, OpenRouter, Gemini, Mistral, GitHub Models en ligne |
| Flux de données | Apache Kafka (aiokafka, confluent-kafka), bus local en mémoire |
| Stockage | SQLite ; PostgreSQL 17 + pgvector (asyncpg) ; stockage objet S3 (MinIO, miniopy-async) |
| Interface | Godot 4.7 (GDScript), WebSocket vers le moteur |
| Lancement | Docker Compose ; scripts PowerShell `install` et `start` sous Windows |

## 16. La démonstration

La partie de démonstration est celle que montrent les vidéos du projet : une vraie partie de trois saisons, jouée par des modèles de langage en local, puis rejouée depuis son journal pour être filmée. Elle suit les règles décrites plus haut ; seules les données ci-dessous lui sont propres.

### 16.1 La partie

- **Réglages** : `config/demo_ia.yaml` (graine 7, trois saisons de 30 jours, conseil de la vallée formé de délégués des villages),
  journal dans `runs/demo_ia`. Au début de la deuxième saison, le scénario lance une rumeur : « Un marchand de la ville achète tout
  le poisson le double du prix, mais seulement cette saison. »
- **Calcul** : environ 20 minutes sur un PC portable (carte graphique RTX 3060, 6 Go), modèles servis par Ollama.
- **La vallée** : trois lacs et six villages, deux par lac, plus la maison de l'ancien.

| Lac | Capacité | Villages |
|---|---|---|
| Vellmor | 62 t | Ostrel, Bramois |
| Orsane | 62 t | Tilque, Hennad |
| Brémol | 75 t | Varenne, Corbel |

#### Les habitants

Seize pêcheurs et un ancien. Douze pêcheurs sont des agents IA (six sur le grand modèle, six sur le petit) ; quatre sont des
**agents à règles** : sans modèle de langage, ils suivent la règle fixe de leur caractère (combien pêcher, quand sortir, quoi
dire), et servent de témoin pour comparer avec les agents IA. L'ancien est un agent IA.

| Pêcheur | Village | Caractère | Décide avec |
|---|---|---|---|
| Perrine | Corbel | taiseux | IA, grand modèle |
| Albane | Tilque | ancienne famille | IA, grand modèle |
| Mathis | Ostrel | ancienne famille | IA, grand modèle |
| Isaure | Hennad | ancienne famille | IA, grand modèle |
| Elwen | Tilque | taiseux | IA, grand modèle |
| Hugo | Bramois | ancienne famille | IA, grand modèle |
| Sylvain | Bramois | nouveau venu | IA, petit modèle |
| Inès | Varenne | beau parleur | IA, petit modèle |
| Eulalie | Hennad | nouveau venu | IA, petit modèle |
| Gildas | Bramois | nouveau venu | IA, petit modèle |
| Pierrick | Corbel | beau parleur | IA, petit modèle |
| Capucine | Varenne | nouveau venu | IA, petit modèle |
| Gwenaëlle | Corbel | beau parleur | règles |
| Lucien | Tilque | taiseux | règles |
| Arnaud | Varenne | beau parleur | règles |
| Maëlle | Ostrel | taiseux | règles |
| Maître Oswin (l'ancien) | Bramois | ancien | IA, grand modèle |

#### Les modèles

| Modèle | Rôle | Appels |
|---|---|---|
| tev1 0,8B | les décisions de routine et les votes (modèle de décision : il choisit une option et donne sa probabilité) | 151 |
| Qwen 2.5 3B | le grand modèle : plans de saison, sorties quand la situation change, paroles de veillée | 137 |
| Qwen 2.5 1,5B | le petit modèle, pour les mêmes décisions des pêcheurs qui y sont rattachés | 81 |
| Qwen 2.5 7B | le récit de fin de saison | 3 |

### 16.2 Le déroulé

- **Saison 1.** Les pêcheurs sortent sur leurs lacs, certains sur ceux des autres. À la veillée, l'ancien établit un mensonge
  d'Arnaud, à tort : Arnaud avait déclaré toute sa pêche, les témoins avaient surestimé sa barque. Isaure accuse Arnaud et demande
  qu'on l'interdise de pêche ; Arnaud (agent à règles) demande la même chose contre elle ; les deux demandes sont refusées.
  Parmi les propositions (5,5 t, 2 t, 3 t par pêcheur, une zone réservée au large de Vellmor), la vallée adopte 3 t par pêcheur
  à partir de la saison 2, et vote une patrouille.
- **Saison 2.** La rumeur circule. Vellmor attire des pêcheurs de toute la vallée ; huit pêcheurs dépassent les 3 t. La
  patrouille prend Maëlle et Sylvain à déclarer moins que leur pêche. À la veillée, Gildas propose une règle pour le seul lac de
  Vellmor, Elwen une zone réservée au large ; la règle de Gildas est adoptée (un peu plus de 2 t par pêcheur à Vellmor, dès la
  saison 3). Maëlle (agent à règles), prise par la patrouille, propose de la retirer : le retrait passe, à trois voix sur six.
- **Saison 3.** Vellmor continue de baisser, de 46 à 33 t, pendant que Brémol reste plein. Les témoins prennent Sylvain et
  Lucien à mentir ; Albane accuse Capucine à tort. Quatre propositions sont sur la table (un repos d'une saison du lac de Vellmor
  proposé par Capucine, au plus trois sorties par saison, un quota plus strict pour toute la vallée proposé par l'ancien, un
  quota de 3,5 t) : aucune n'est adoptée.

### 16.3 Ce qu'elle montre

- Les agents IA décident seuls : ils proposent, soutiennent, accusent, promettent, et leurs paroles changent d'une veillée à
  l'autre ; les agents à règles, eux, répètent les choix de leur caractère, ce qui permet de les comparer.
- Les mensonges se paient de façon inégale : sur cinq mensonges établis, un est une erreur de l'ancien ; la patrouille en prend
  deux, puis elle est retirée par un vote où l'un des pêcheurs pris a voté contre elle.
- Le lac le plus fréquenté baisse le plus (Vellmor : 26, puis 38, puis 39 sorties par saison ; de 62 à 33 t). La règle de la
  vallée est dépassée par la moitié des pêcheurs dès sa première saison ; une règle propre au lac suit, puis les propositions se
  dispersent.
- Les limites des modèles restent visibles et comptées : l'erreur de l'ancien, des répliques maladroites du petit modèle, et 75
  réponses invalides traitées comme incidents.

### 16.4 Les chiffres

| Mesure | Valeur |
|---|---|
| Sorties en mer | 254, autant de déclarations à l'ancien |
| Témoignages | 197 |
| Mensonges établis | 5 : Arnaud à tort (saison 1) ; Maëlle et Sylvain, par la patrouille (saison 2) ; Sylvain et Lucien, par les témoins (saison 3) |
| Veillées | 3 ; 30 répliques, 11 propositions de règle |
| Règles adoptées | 2 : 3 t par pêcheur pour la vallée (dès la saison 2) ; un peu plus de 2 t au lac de Vellmor (dès la saison 3) |
| Votes de sanction | patrouille installée (saison 1) puis retirée (saison 2) ; deux demandes d'interdiction de pêche rejetées |
| Pêché / déclaré | 172,9 t pêchées, 165,3 t déclarées sur les trois saisons |
| Appels aux modèles | 372, pour 1 014 094 tokens ; 75 incidents traités |
| Mémoire et confiance | 668 souvenirs écrits, 275 changements de confiance |
| Stocks des lacs | Vellmor 62 → 33 t, Orsane 62 → 55 t, Brémol 75 → 73 t |
