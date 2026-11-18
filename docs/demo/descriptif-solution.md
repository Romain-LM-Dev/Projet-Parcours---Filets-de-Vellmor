# FILETS : descriptif de la solution

Ce document présente le projet FILETS : ce que fait la solution développée et comment elle est construite. Il complète les vidéos du projet, avec ou sans voix off, et peut se lire seul.

## 1. En bref

FILETS est une simulation de société jouée par des intelligences artificielles. Seize pêcheurs et un ancien vivent dans une
vallée de trois lacs. Chacun est un agent qui décide seul : quand sortir pêcher, où, combien prendre, ce qu'il déclare en
rentrant, ce qu'il dit et vote le soir à la veillée. Personne n'écrit leur comportement à l'avance : les décisions viennent de
modèles de langage qui tournent en local, sur la carte graphique d'un PC portable, et de règles propres à chaque caractère.

Le projet sert de laboratoire : chaque décision, chaque parole et chaque prise sont enregistrées, mesurées et rejouables, pour
étudier comment des IA coopèrent, se mentent, se surveillent et se donnent des règles. Il illustre la dominante IABD
(intelligence artificielle et big data) : des modèles de langage, une mémoire par recherche sémantique (RAG), un flux de données
en continu et des indicateurs calculés en direct.

## 2. La solution développée

### 2.1 Le principe

Une partie dure plusieurs saisons de trente jours. Chaque saison : les pêcheurs préparent leur plan, pêchent pendant vingt jours
et déclarent chaque retour à l'ancien ; le soir de la veillée, les élus des villages débattent et votent des règles ; puis les
lacs se repeuplent et un narrateur raconte la saison. Le poisson ne se renouvelle bien que si les lacs ne sont pas vidés : la
vallée doit trouver d'elle-même des règles et les faire respecter, alors que chacun a intérêt à pêcher plus et peut mentir.

### 2.2 Le monde

- **La vallée** est tirée au hasard (graine) en restant cohérente : lacs, villages, chemins, rives, décor. On peut en tirer une
  autre depuis le menu. Dans la partie filmée : trois lacs (Vellmor 62 t, Orsane 62 t, Brémol 75 t de capacité), deux villages
  par lac (Ostrel et Bramois, Tilque et Hennad, Varenne et Corbel) et la maison de l'ancien.
- **Les mailles** : le monde est une grille. Chaque case de lac a son poisson et sa chance (un coin trop pêché rend moins), les
  maisons bloquent le passage, les trajets sont calculés sur la grille.
- **Le lac** se repeuple selon une croissance qui est la plus forte autour de la moitié de sa capacité. Climat et saisons de
  l'année jouent sur les prises ; des événements peuvent survenir.
- **Les bateaux** ont des cales de tailles différentes ; aller pêcher sur un autre lac prend du temps et coûte de l'argent.

### 2.3 Les habitants

- **Seize pêcheurs**, chacun d'un caractère : ancienne famille, nouveau venu, beau parleur, taiseux. Chaque caractère a ses
  priorités et sa façon de parler, que les modèles reçoivent dans leur consigne.
- La plupart sont des **agents IA** ; quelques-uns sont des **agents à règles** (un comportement fixe par caractère), pour
  comparer. L'**ancien** (Maître Oswin) reçoit les déclarations, recoupe les témoignages et préside la veillée.
- Chaque action d'un agent vient de sa propre réflexion (modèle de langage) ou de la règle de son caractère : le moteur ne
  décide jamais à sa place ; il compte, vérifie et applique la physique du monde.

### 2.4 Les modèles d'IA

Quatre modèles tournent en local avec Ollama, sur la carte graphique d'un PC portable (RTX 3060, 6 Go), sans serveur ni
abonnement :

| Modèle | Rôle | Dans la partie filmée |
|---|---|---|
| tev1 0,8B | Les décisions de routine et les votes : il choisit une option et donne sa probabilité, sans écrire de texte | 151 appels |
| Qwen 2.5 3B | La réflexion des pêcheurs expérimentés et de l'ancien : plan de saison, sorties quand la situation change, paroles de veillée | 137 appels |
| Qwen 2.5 1,5B | La même chose pour les pêcheurs moins expérimentés | 81 appels |
| Qwen 2.5 7B | Le récit de fin de saison | 3 appels |

À chaque décision, un aiguillage choisit entre le réflexe (rien n'a changé : le petit modèle de décision) et la réflexion
(quelque chose a changé : un modèle de langage). Les réponses sont contrôlées : une réponse illisible, hors rôle ou hors bornes
est un incident, traité par une règle de repli ou une seconde demande.

### 2.5 Une saison

1. **Le plan** : chaque pêcheur fixe ce qu'il compte prendre et ce qu'il compte déclarer.
2. **Les sorties** : à l'ouverture puis à chaque retour, il décide quand ressortir, où (son lac ou un autre, rive ou large),
   combien prendre, sortie courte (3 h) ou longue (7 h) ; personne ne pêche la nuit. Le poisson sort du lac au retour.
3. **Les déclarations** : à chaque retour, il déclare sa pêche à l'ancien ; il peut mentir.
4. **Les indices** : les voisins voient les barques rentrer et estiment leur charge ; la patrouille, si elle a été votée,
   contrôle une zone. L'ancien recoupe ces indices avec les déclarations et établit les mensonges, parfois à tort.

### 2.6 La veillée et les règles

- Les villages élisent leurs délégués au **conseil de la vallée** ; les absents en sont informés ensuite.
- Les répliques se préparent en même temps, mais **une seule personne parle à la fois** (vingt minutes de jeu par réplique) ;
  celui à qui l'on s'adresse répond en priorité, et une réplique dépassée par la discussion est préparée de nouveau. Une IA qui
  répète ce qui a déjà été dit est relancée une fois, puis se tait.
- Une réplique peut proposer une règle, en soutenir une, promettre, accuser, demander d'interdire un pêcheur de pêche, ou
  d'installer ou de retirer la patrouille.
- **Cinq sortes de règles** : un quota par pêcheur, une zone réservée, un repos du lac, un nombre de sorties, une taille de
  bateau ; chacune peut viser toute la vallée, un village ou un seul lac. Une règle passe avec au moins la moitié des pêcheurs
  présents.

### 2.7 Confiance, mémoire et RAG

- **La confiance** : chaque agent juge lui-même, après ce qu'il voit et entend, ce que ses voisins valent ; cette confiance
  pèse sur la façon dont il reçoit leurs paroles et leurs témoignages.
- **La mémoire** : chaque agent garde ses souvenirs (prises, promesses, accusations, règles) sous forme de vecteurs, et retrouve
  ceux qui comptent pour la décision en cours par leur sens (recherche sémantique). C'est le principe du RAG : le modèle répond à
  partir de documents retrouvés pour lui, ici ses propres souvenirs et les faits marquants de la partie.

### 2.8 Le narrateur

À la fin de chaque saison, un narrateur extérieur, qui sait tout (même les mensonges non découverts), écrit le récit à partir
des faits relevés par le programme. Il ne reçoit aucun tonnage : les chiffres exacts sont calculés par le code et ajoutés au
récit, et un récit qui invente un nombre est corrigé.

### 2.9 Le temps simulé

Le moteur est une simulation à événements discrets : réfléchir ne prend pas de temps dans le jeu, agir en prend (une sortie, un
trajet, une réplique). Les décisions qui ne dépendent pas les unes des autres partent en même temps vers les modèles ; leurs
effets s'appliquent toujours dans l'ordre du temps de jeu, jamais dans l'ordre où les modèles répondent. À graine égale, avec le
faux modèle des tests, deux parties donnent le même journal ; avec de vrais modèles, les réponses peuvent varier d'une partie à l'autre.

### 2.10 Le joueur

Le joueur prépare la partie dans un menu (vallée, pêcheurs, modèles, réglages), puis observe et intervient : sécheresse,
communication entre villages, déclarations publiques ou non, rumeur, vitesse, pause et arrêt. La rumeur de la partie filmée
(« un marchand paierait le poisson le double ») est l'une de ces interventions.

### 2.11 Les données

- Chaque geste devient un **événement** (JSON, schéma vérifié), enregistré dans le journal de la partie.
- En version complète, les événements passent par **Kafka** (sujets des événements, des commandes, des indicateurs, de l'état
  et des messages en erreur), comme dans les plateformes de données ; des services les consomment.
- Les **indicateurs** se calculent en continu : part du stock, norme partagée, accord déclaré, conformité, promesses tenues,
  dispersion des prises, appels, tokens, incidents, violations temporelles.
- **PostgreSQL avec pgvector** garde l'historique et la mémoire vectorielle ; un **stockage objet** (MinIO) garde les fichiers.
- Une partie se **rejoue** depuis son journal, avec le bus local ou avec Kafka. La vidéo elle-même rejoue le journal de la partie filmée.

### 2.12 L'interface

L'interface Godot 4.7 dessine la vallée entièrement en code, en vue isométrique : caméra libre (zoom, glissement), mini-carte,
mailles affichables, salon de la veillée avec ses bulles, jauges des lacs, cartes d'indicateurs et courbes par saison, onglets
(interactions, récit du narrateur, confiance, fiche d'agent, règles) et barre d'interventions. Elle reçoit la partie du moteur
par WebSocket.

### 2.13 Qualité et documentation

- 583 tests automatisés (moteur Python et interface Godot sans fenêtre), dont le rejeu identique d'une partie.
- 97 diagrammes UML (cas d'utilisation, séquences, communication, classes) et un dictionnaire de tous les paramètres et
  variables, réunis dans [un PDF](../uml/FILETS-diagrammes-UML.pdf).
- Les spécifications du temps ([temps.md](../temps.md)), de la pêche ([peche.md](../peche.md)) et de l'architecture
  ([architecture.md](../architecture.md)).

## 3. Pile technique

| Partie | Technologie |
|---|---|
| Moteur de simulation | Python 3.13, asyncio (ordonnanceur à événements discrets) |
| Modèles d'IA | Ollama en local : Qwen 2.5 (1,5B, 3B, 7B), tev1 0,8B |
| Flux de données | Apache Kafka (et un bus local pour jouer sans Docker) |
| Stockage | PostgreSQL 17 + pgvector, stockage objet MinIO |
| Interface | Godot 4.7 (GDScript), WebSocket vers le moteur |
| Lancement | Docker Compose, scripts PowerShell `install` et `start` |
| Vidéos | Godot Movie Maker, voix edge-tts, montage ffmpeg |
## 4. La démonstration

La démonstration est une vraie partie de trois saisons, jouée par les modèles locaux sur le PC portable (environ 20 minutes de
calcul), avec la configuration `config/demo_ia.yaml` et son journal `runs/demo_ia`. La vallée compte trois lacs et six villages ;
parmi les seize pêcheurs, douze sont des agents IA (six sur le grand modèle, six sur le petit) et quatre des agents à règles ;
l'ancien est un agent IA.

### 4.1 Le déroulé de la partie

- **Saison 1.** Les pêcheurs sortent sur leurs lacs, certains sur ceux des autres. À la veillée, l'ancien établit un mensonge
  d'Arnaud, à tort : Arnaud avait tout déclaré, les témoins avaient surestimé sa barque. Isaure demande qu'on l'interdise de
  pêche, Arnaud lui retourne la demande ; les deux sont refusées. Parmi les propositions (2 t, 3 t, 5,5 t par pêcheur, une zone
  réservée), la vallée adopte 3 t par pêcheur pour la saison suivante, et vote une patrouille.
- **Saison 2.** Le joueur lance une rumeur : un marchand paierait le poisson le double. Le lac de Vellmor attire des pêcheurs de
  toute la vallée ; huit pêcheurs dépassent les 3 t. La patrouille prend Maëlle et Sylvain à mentir. La veillée adopte une règle
  pour le seul lac de Vellmor (un peu plus de 2 t par pêcheur), puis Maëlle, prise par la patrouille, propose de la retirer : le
  retrait passe, à trois voix sur six.
- **Saison 3.** Vellmor continue de baisser (de 46 à 33 t), pendant que Brémol reste plein. Les témoins prennent Sylvain et Lucien
  à mentir ; Albane accuse Capucine à tort. Quatre propositions sont sur la table (un repos du lac de Vellmor, un nombre de
  sorties, deux quotas) : aucune n'est adoptée.

### 4.2 Ce qu'elle montre

- Les agents ne suivent pas un scénario : ils mentent, se font prendre, s'accusent, parfois à tort, et votent des règles qui
  les contraignent ; certains votent aussi contre le contrôle qui les a pris.
- Le lac le plus fréquenté baisse le plus : la règle de la vallée ne suffit pas, celle d'un seul lac vient ensuite, et les
  propositions finissent par se disperser.
- Les limites des modèles restent visibles et mesurées : l'ancien se trompe, certaines répliques du petit modèle sont
  maladroites, et chaque réponse invalide est comptée comme incident.

### 4.3 La partie en chiffres

| Mesure | Valeur |
|---|---|
| Durée | 3 saisons de 30 jours ; environ 20 minutes de calcul sur le PC portable |
| Sorties en mer | 254, autant de déclarations à l'ancien |
| Témoignages | 197 |
| Mensonges établis | 5 (dont 1 à tort : Arnaud en saison 1) ; Maëlle et Sylvain pris par la patrouille en saison 2, Sylvain et Lucien par les témoins en saison 3 |
| Veillées | 3, 30 répliques, 11 propositions de règle |
| Règles adoptées | 2 : 3 t par pêcheur pour la vallée (dès la saison 2), un peu plus de 2 t au lac de Vellmor (dès la saison 3) |
| Votes de sanction | patrouille installée (saison 1) puis retirée (saison 2) ; deux demandes d'interdiction rejetées |
| Appels aux modèles | 372, pour 1 014 094 tokens ; 75 réponses contrôlées et traitées comme incidents |
| Mémoire | 668 souvenirs écrits, 275 changements de confiance |
| Stocks des lacs | Vellmor 62 → 33 t, Orsane 62 → 55 t, Brémol 75 → 73 t |
