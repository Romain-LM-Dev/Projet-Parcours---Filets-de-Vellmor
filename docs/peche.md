# La pêche décidée par le pêcheur

Spécification (décisions de l'utilisateur, 10 novembre 2026). Elle complète [temps.md](temps.md) : l'ordonnanceur, « réfléchir
ne prend pas de temps, agir en prend », restent la base. Elle remplace la prise de saison répartie par le moteur en sorties
fixes : c'est le pêcheur qui décide **s'il** sort, **quand**, **où**, **combien** et **ce qu'il déclare**, par nécessité ou par
envie. Le moteur ne fait qu'appliquer la physique (cale, poisson du lac, météo, durée) et compter.

## Le plan de la saison

À l'ouverture de la pêche, chaque pêcheur réfléchit à sa saison (système 2, le grand modèle ; un agent à règles, sa règle) :
ce qu'il compte prendre en tout, où, ce qu'il compte déclarer, et sa première sortie (quand). Le plan est une intention : il
n'engage pas le moteur, il guide les décisions suivantes et figure dans la mémoire du pêcheur.

## Une sortie, une décision

À l'ouverture, puis à chaque retour, le pêcheur décide sa **prochaine sortie** :

- **quand** : un délai (« dans 2 heures », « demain à l'aube », « dans 3 jours ») ou « plus cette saison » ; il peut ressortir
  le jour même ou ne plus sortir du tout ;
- **où** : le lac et la zone (sa rive, le large, la rive d'un autre village en cachette) ; le coin précis reste la règle de son
  expérience (`spot_of`) ;
- **combien** il vise pour cette sortie, et **courte ou longue** : une sortie courte dure 3 heures de pêche, une longue 7 ; la
  route s'y ajoute (aller et retour vers un autre lac, en heures) ; la nuit, on ne pêche pas (de 21 h à 5 h) ;
- **ce qu'il déclare** de cette sortie à son retour (voir plus bas).

Chaque décision reçoit tout le contexte : sa mémoire et le RAG, ce qu'il voit du lac, la météo du jour, ce qu'il a déjà pris
cette saison, son plan, les règles qui le visent (quota de saison, réserves, repos, sorties, bateau), les rumeurs, ses dettes.

**Qui décide (routage système 1 / système 2).** Le plan de saison est toujours une réflexion du grand modèle. Une décision de
sortie est confiée au réflexe (tev1) quand rien n'a changé depuis sa décision précédente ; elle revient au grand modèle dès
qu'une raison de réfléchir apparaît : un temps qui change de catégorie (tempête, calme), une rumeur ou un événement nouveau, une
règle nouvelle, le lac qui baisse nettement, un quota de saison presque atteint ou dépassé, une accusation ou un indice contre
lui, un plan rempli ou impossible. Les raisons réutilisent `routing.reasons_to_think`. Un agent à règles décide par la règle
de son archétype.

## La physique d'une sortie

- **Durée** : heures de pêche choisies, plus la route ; l'action commence à la date choisie (ou au plus tôt à l'aube si c'est la
  nuit) et s'achève à son retour. Plusieurs sorties par jour sont possibles.
- **Prise** : la cible de la sortie, multipliée par le rendement du moment (météo, chance, coin de pêche, expérience), dans la
  limite de la **cale** du bateau pour une sortie et de ce que le lac contient autour de la parcelle. La part du poisson de la
  saison (`hold_fraction` partagée entre les bateaux du lac, calculée sur l'instantané d'ouverture) reste un plafond de saison.
  La prise retire son poisson du lac à la fin de la sortie (événement `outing`).
- **Règles** : le quota reste **par pêcheur et par saison** (il se compare au total de la saison, sortie après sortie) ; la règle
  `sorties` plafonne le nombre de sorties de la saison ; réserve, repos et bateau s'appliquent à chaque sortie. Les respecter
  reste la décision du pêcheur ; une sortie qui les enfreint porte `breach`.
- **Fermeture** : aucune sortie ne commence après `fishing_close_day` ; une sortie commencée avant rentre normalement.

## Déclarer à chaque retour

Au retour de chaque sortie, le pêcheur déclare cette sortie à l'ancien (événement `report`, une fois par sortie). Il peut dire
vrai ou cacher une part, sortie par sortie : mentir un peu une fois, ou souvent, ou beaucoup.

- Le moteur garde chaque écart (taille, date, sortie) ; un mensonge est une décision du pêcheur (la tolérance d'arrondi de
  0,05 t reste la seule limite).
- Les **indices** naissent par sortie : un voisin de la même zone voit la barque rentrer chargée, la patrouille contrôle une
  sortie si elle passe là ce jour-là, les comptes du lac à la veillée comparent le total déclaré à ce qui manque.
- Le **jugement** reste celui des autres agents : à la veillée et en fin de saison, chacun pèse ce qu'il sait (combien de fois, de
  combien, contre qui, ce qu'il a vu lui-même) selon son caractère et sa confiance ; l'ancien établit un mensonge sur indices.
  Le moteur ne fixe aucun barème de sanction : un menteur répété et un menteur d'une fois ne sont pas jugés pareil parce que
  les agents voient la différence, pas parce que le moteur la calcule.
- Le fil d'interactions regroupe les retours (une ligne par pêcheur et par jour) pour rester lisible.

## Ce qui change ailleurs

- `economy.outings` ne fixe plus le nombre de sorties : il devient le nombre de sorties qu'un agent à règles prévoit par défaut.
- Les invites : le plan de saison (comme la décision de prise actuelle) et la décision de sortie (courte, même contexte).
- Le narrateur et les indicateurs comptent par sortie et par saison (prises, déclarations, écarts).
- Godot : une barque par sortie (déjà sur `outing`), l'intention du pêcheur (« ressort demain à l'aube ») dans l'inspecteur.
