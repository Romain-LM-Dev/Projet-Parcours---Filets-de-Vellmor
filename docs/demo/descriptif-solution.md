# FILETS : descriptif de la solution

Ce document accompagne la vidéo sans voix off [FILETS-demo-sans-voix.mp4](FILETS-demo-sans-voix.mp4) (4 min 50, 1920x1080, sans
son ni sous-titres). Il décrit ce qu'on voit à l'écran, puis la solution développée. La même vidéo existe avec voix off :
[FILETS-demo.mp4](FILETS-demo.mp4) (son texte : [script-video-longue.md](script-video-longue.md)).

## 1. En bref

FILETS est une simulation de société jouée par des intelligences artificielles. Seize pêcheurs et un ancien vivent dans une
vallée de trois lacs. Chacun est un agent qui décide seul : quand sortir pêcher, où, combien prendre, ce qu'il déclare en
rentrant, ce qu'il dit et vote le soir à la veillée. Personne n'écrit leur comportement à l'avance : les décisions viennent de
modèles de langage qui tournent en local, sur la carte graphique d'un PC portable, et de règles propres à chaque caractère.

Le projet sert de laboratoire : chaque décision, chaque parole et chaque prise sont enregistrées, mesurées et rejouables, pour
étudier comment des IA coopèrent, se mentent, se surveillent et se donnent des règles. Il illustre la dominante IABD
(intelligence artificielle et big data) : des modèles de langage, une mémoire par recherche sémantique (RAG), un flux de données
en continu et des indicateurs calculés en direct.

## 2. La vidéo sans voix : ce qu'on voit

La vidéo rejoue une vraie partie de trois saisons (`runs/demo_ia`), jouée par les modèles locaux. Les moments sont donnés à une
seconde près ; « S1, jour 26 » est la saison et le jour de jeu affichés en haut à gauche de la carte.

| Vidéo | Partie | À l'écran | Ce que ça montre |
|---|---|---|---|
| 0:00 | | Carte de titre | « FILETS. Une vallée où chaque personnage est une IA. » |
| 0:03 | S1, jour 1 | Toute la vallée | Les trois lacs (Vellmor, Orsane, Brémol), les six villages et la maison de l'ancien, reliés par des chemins. En haut, les jauges de stock des lacs ; à droite, les indicateurs. |
| 0:13 | S1, jour 1 | La carte | La vallée en vue isométrique, à la manière d'un jeu de stratégie : caméra qui zoome et glisse, mini-carte en bas à droite. Les pions sont les pêcheurs (couleur : caractère ; anneau doré : grand modèle ; carré : agent à règles). |
| 0:25 | S1, jour 2 | Mailles visibles | Le monde découpé en cases : chaque case de lac porte son poisson et sa chance, les maisons bloquent le passage, les trajets se calculent sur cette grille. |
| 0:36 | S1, jour 3 | Zoom sur Ostrel, fil des interactions | Les premières barques partent. À droite, le fil des interactions : chaque sortie, chaque prise, chaque déclaration à l'ancien, avec ce que le pêcheur a vraiment pêché. |
| 0:47 | S1, jour 7 | La carte | La saison de pêche : les barques vont et viennent, sur leur lac ou sur un autre (le trajet se paie). Les jauges des lacs baissent. |
| 0:59 | S1, jour 12 | La carte, indicateurs | Les cartes d'indicateurs se mettent à jour en direct : stock des lacs, appels aux modèles, tokens, incidents, violations temporelles. |
| 1:08 | S1, jour 17 | Inspecteur : Mathis | La fiche d'un agent : son caractère, son modèle, son argent, sa confiance envers les autres, son plan de saison et sa dernière décision avec sa justification. |
| 1:19 | S1, jour 20 | Fil des interactions | La pêche ferme. Les témoignages arrivent : tel voisin a vu telle barque rentrer avec environ tant de tonnes. |
| 1:28 | S1, jour 26 | Salon de la veillée | La veillée chez l'ancien s'ouvre : les élus des villages autour du feu. Dans le fil, l'ancien établit un mensonge d'Arnaud… à tort (« ACCUSÉ À TORT »). Les bulles sont les répliques écrites par les IA. |
| 1:44 | S1, jour 26 | Salon de la veillée | Les propositions de règle (étiquettes jaunes : 2 t, 3 t, 5,5 t par pêcheur, zone réservée), les soutiens, Isaure qui demande d'interdire Arnaud de pêche, et Arnaud qui lui retourne la demande. |
| 2:00 | S1, jour 30 | Onglet « Règles » | Le vote : la règle de 3 t par pêcheur pour toute la vallée est adoptée, une patrouille est installée, personne n'est interdit. |
| 2:16 | S1, jour 30 | Onglet « Récit du narrateur » | Le récit de la saison, écrit par un modèle de langage, suivi des chiffres exacts calculés par le programme. |
| 2:26 | S2, jour 1 | Toute la vallée | Saison deux. Le joueur a lancé une rumeur (un marchand paierait le poisson le double) ; la barre du bas permet d'intervenir (sécheresse, communication, rumeur). |
| 2:38 | S2, jour 11 | Onglet « Confiance » | Ce que chacun pense des autres : la confiance que chaque agent accorde, d'après ce qu'il a vu et entendu. |
| 2:45 | S2, jour 17 | La carte, fil | La patrouille fait sa tournée sur la carte. Le lac de Vellmor attire des pêcheurs de toute la vallée. |
| 2:55 | S2, jour 26 | Salon de la veillée | La patrouille a pris Maëlle et Sylvain à mentir. Nouvelles propositions : une règle pour le seul lac de Vellmor, une zone réservée au large. |
| 3:13 | S2, jour 26 | Salon de la veillée | La règle de Vellmor est adoptée ; Maëlle, prise par la patrouille, propose de la retirer, et le retrait passe à trois voix sur six. |
| 3:28 | S3, jour 1 | Toute la vallée | Troisième saison : la règle de Vellmor s'applique ; le lac continue de baisser, Brémol reste plein. |
| 3:39 | S3, jour 10 | La carte | Les sorties de la dernière saison, toutes enregistrées. |
| 3:50 | S3, jour 18 | La carte | Les dernières sorties avant la fermeture de la pêche (jour 20) ; les courbes montrent les saisons passées. |
| 4:00 | S3, jour 26 | Salon de la veillée | Dernière veillée : Sylvain et Lucien pris à mentir par les témoins, un repos du lac de Vellmor proposé, une accusation injuste. |
| 4:22 | S3, jour 26 | Onglet « Règles » | Quatre propositions sur la table, aucune adoptée. |
| 4:34 | S3, jour 30 | Toute la vallée, récit | La vallée à la fin de la partie et le récit de la dernière saison. |
| 4:47 | | Carte de fin | « Dominante IABD. Intelligence artificielle et big data. » |

## 3. La solution développée

### 3.1 Le principe

Une partie dure plusieurs saisons de trente jours. Chaque saison : les pêcheurs préparent leur plan, pêchent pendant vingt jours
et déclarent chaque retour à l'ancien ; le soir de la veillée, les élus des villages débattent et votent des règles ; puis les
lacs se repeuplent et un narrateur raconte la saison. Le poisson ne se renouvelle bien que si les lacs ne sont pas vidés : la
vallée doit trouver d'elle-même des règles et les faire respecter, alors que chacun a intérêt à pêcher plus et peut mentir.

### 3.2 Le monde

- **La vallée** est tirée au hasard (graine) en restant cohérente : lacs, villages, chemins, rives, décor. On peut en tirer une
  autre depuis le menu. Dans la partie filmée : trois lacs (Vellmor 62 t, Orsane 62 t, Brémol 75 t de capacité), deux villages
  par lac (Ostrel et Bramois, Tilque et Hennad, Varenne et Corbel) et la maison de l'ancien.
- **Les mailles** : le monde est une grille. Chaque case de lac a son poisson et sa chance (un coin trop pêché rend moins), les
  maisons bloquent le passage, les trajets sont calculés sur la grille.
- **Le lac** se repeuple selon une croissance qui est la plus forte autour de la moitié de sa capacité. Climat et saisons de
  l'année jouent sur les prises ; des événements peuvent survenir.
- **Les bateaux** ont des cales de tailles différentes ; aller pêcher sur un autre lac prend du temps et coûte de l'argent.

### 3.3 Les habitants

- **Seize pêcheurs**, chacun d'un caractère : ancienne famille, nouveau venu, beau parleur, taiseux. Chaque caractère a ses
  priorités et sa façon de parler, que les modèles reçoivent dans leur consigne.
- La plupart sont des **agents IA** ; quelques-uns sont des **agents à règles** (un comportement fixe par caractère), pour
  comparer. L'**ancien** (Maître Oswin) reçoit les déclarations, recoupe les témoignages et préside la veillée.
- Chaque action d'un agent vient de sa propre réflexion (modèle de langage) ou de la règle de son caractère : le moteur ne
  décide jamais à sa place ; il compte, vérifie et applique la physique du monde.

### 3.4 Les modèles d'IA

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

### 3.5 Une saison

1. **Le plan** : chaque pêcheur fixe ce qu'il compte prendre et ce qu'il compte déclarer.
2. **Les sorties** : à l'ouverture puis à chaque retour, il décide quand ressortir, où (son lac ou un autre, rive ou large),
   combien prendre, sortie courte (3 h) ou longue (7 h) ; personne ne pêche la nuit. Le poisson sort du lac au retour.
3. **Les déclarations** : à chaque retour, il déclare sa pêche à l'ancien ; il peut mentir.
4. **Les indices** : les voisins voient les barques rentrer et estiment leur charge ; la patrouille, si elle a été votée,
   contrôle une zone. L'ancien recoupe ces indices avec les déclarations et établit les mensonges, parfois à tort.

### 3.6 La veillée et les règles

- Les villages élisent leurs délégués au **conseil de la vallée** ; les absents en sont informés ensuite.
- Les répliques se préparent en même temps, mais **une seule personne parle à la fois** (vingt minutes de jeu par réplique) ;
  celui à qui l'on s'adresse répond en priorité, et une réplique dépassée par la discussion est préparée de nouveau. Une IA qui
  répète ce qui a déjà été dit est relancée une fois, puis se tait.
- Une réplique peut proposer une règle, en soutenir une, promettre, accuser, demander d'interdire un pêcheur de pêche, ou
  d'installer ou de retirer la patrouille.
- **Cinq sortes de règles** : un quota par pêcheur, une zone réservée, un repos du lac, un nombre de sorties, une taille de
  bateau ; chacune peut viser toute la vallée, un village ou un seul lac. Une règle passe avec au moins la moitié des pêcheurs
  présents.

### 3.7 Confiance, mémoire et RAG

- **La confiance** : chaque agent juge lui-même, après ce qu'il voit et entend, ce que ses voisins valent ; cette confiance
  pèse sur la façon dont il reçoit leurs paroles et leurs témoignages.
- **La mémoire** : chaque agent garde ses souvenirs (prises, promesses, accusations, règles) sous forme de vecteurs, et retrouve
  ceux qui comptent pour la décision en cours par leur sens (recherche sémantique). C'est le principe du RAG : le modèle répond à
  partir de documents retrouvés pour lui, ici ses propres souvenirs et les faits marquants de la partie.

### 3.8 Le narrateur

À la fin de chaque saison, un narrateur extérieur, qui sait tout (même les mensonges non découverts), écrit le récit à partir
des faits relevés par le programme. Il ne reçoit aucun tonnage : les chiffres exacts sont calculés par le code et ajoutés au
récit, et un récit qui invente un nombre est corrigé.

### 3.9 Le temps simulé

Le moteur est une simulation à événements discrets : réfléchir ne prend pas de temps dans le jeu, agir en prend (une sortie, un
trajet, une réplique). Les décisions qui ne dépendent pas les unes des autres partent en même temps vers les modèles ; leurs
effets s'appliquent toujours dans l'ordre du temps de jeu, jamais dans l'ordre où les modèles répondent. À graine égale, avec le
faux modèle des tests, deux parties donnent le même journal ; avec de vrais modèles, les réponses peuvent varier d'une partie à l'autre.

### 3.10 Le joueur

Le joueur prépare la partie dans un menu (vallée, pêcheurs, modèles, réglages), puis observe et intervient : sécheresse,
communication entre villages, déclarations publiques ou non, rumeur, vitesse, pause et arrêt. La rumeur de la partie filmée
(« un marchand paierait le poisson le double ») est l'une de ces interventions.

### 3.11 Les données

- Chaque geste devient un **événement** (JSON, schéma vérifié), enregistré dans le journal de la partie.
- En version complète, les événements passent par **Kafka** (sujets des événements, des commandes, des indicateurs, de l'état
  et des messages en erreur), comme dans les plateformes de données ; des services les consomment.
- Les **indicateurs** se calculent en continu : part du stock, norme partagée, accord déclaré, conformité, promesses tenues,
  dispersion des prises, appels, tokens, incidents, violations temporelles.
- **PostgreSQL avec pgvector** garde l'historique et la mémoire vectorielle ; un **stockage objet** (MinIO) garde les fichiers.
- Une partie se **rejoue** depuis son journal, avec le bus local ou avec Kafka. La vidéo elle-même rejoue le journal de la partie filmée.

### 3.12 L'interface

L'interface Godot 4.7 dessine la vallée entièrement en code, en vue isométrique : caméra libre (zoom, glissement), mini-carte,
mailles affichables, salon de la veillée avec ses bulles, jauges des lacs, cartes d'indicateurs et courbes par saison, onglets
(interactions, récit du narrateur, confiance, fiche d'agent, règles) et barre d'interventions. Elle reçoit la partie du moteur
par WebSocket.

### 3.13 Qualité et documentation

- 583 tests automatisés (moteur Python et interface Godot sans fenêtre), dont le rejeu identique d'une partie.
- 97 diagrammes UML (cas d'utilisation, séquences, communication, classes) et un dictionnaire de tous les paramètres et
  variables, réunis dans [un PDF](../uml/FILETS-diagrammes-UML.pdf).
- Les spécifications du temps ([temps.md](../temps.md)), de la pêche ([peche.md](../peche.md)) et de l'architecture
  ([architecture.md](../architecture.md)).

## 4. La partie filmée en chiffres

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

## 5. Pile technique

| Partie | Technologie |
|---|---|
| Moteur de simulation | Python 3.13, asyncio (ordonnanceur à événements discrets) |
| Modèles d'IA | Ollama en local : Qwen 2.5 (1,5B, 3B, 7B), tev1 0,8B |
| Flux de données | Apache Kafka (et un bus local pour jouer sans Docker) |
| Stockage | PostgreSQL 17 + pgvector, stockage objet MinIO |
| Interface | Godot 4.7 (GDScript), WebSocket vers le moteur |
| Lancement | Docker Compose, scripts PowerShell `install` et `start` |
| Vidéos | Godot Movie Maker, voix edge-tts, montage ffmpeg |
