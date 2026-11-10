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

## Choix faits (brief 1 : le plan, les sorties, la physique)

Ce que la spécification laissait ouvert, tel que le moteur le fait.

- **La cale d'une sortie** (`World.cale_of`) : `boat_cap × 1,5 / economy.outings × heures / 7`. Le `boat_cap` actuel est la prise maximale d'un
  bateau pour toute la saison ; une sortie longue (7 h) en porte donc un sixième plus une marge de moitié (une chaloupe de 7 t : 1,75 t), une
  courte (3 h) 3/7 de cela. Pourquoi : les bateaux ne changent pas, le total d'une saison reste borné comme avant (par `boat_cap` et par
  `hold_fraction`, dans `World.trip_left`), et la marge laisse une bonne journée rapporter plus que la moyenne. Plafonds de la prise d'une
  sortie : sa cible × rendement × coin, la cale, ce qui reste de la part du lac (le moindre de `hold_of` sur l'instantané d'ouverture et de
  `boat_cap`, moins ce qu'il a pris), et le poisson de la parcelle.
- **Le plan et la première sortie** : le plan est une décision `decision_type: "plan"` (toujours le grand modèle ; une règle pour un agent à
  règles), à l'horizon du jour de départ du pêcheur. Il porte aussi la première sortie : « quand » (`premiere_sortie`), la cible
  (`prise_saison` ÷ le nombre de sorties prévu), le lac et le lieu, une sortie longue. Il n'y a donc pas de seconde décision à l'ouverture. Les
  décisions suivantes sont `decision_type: "catch"`, une par retour, et lisent le plan (`agent.plans`, son résumé dans le contexte et la
  mémoire).
- **Les mots du « quand »** (`rules.QUAND`) : « tout de suite », « dans 3 heures », « dans 6 heures », « demain à l'aube », « dans 2 jours »,
  « dans 4 jours », « dans 8 jours », « plus cette saison ». Un mot inconnu vaut « tout de suite ». Une prise visée sous 50 kg vaut « plus cette
  saison » (rien à prendre). Un agent à règles (et le faux LLM) répartit ce qui reste à prendre sur les sorties qui lui restent et place la
  suivante pour que toutes tiennent avant la fermeture.
- **La nuit** : on ne pêche pas de 21 h à 5 h ; la pêche commence à `t + délai + route`, et si cet instant tombe de nuit ou si la pêche
  finirait après 21 h, elle commence à l'aube suivante (`World.fishing_start`). La route d'un autre lac se fait de nuit comme de jour.
  Plusieurs sorties le même jour sont donc possibles (5 h–8 h, 8 h–15 h…).
- **Fermeture, veillée** : une sortie ne part pas après `fishing_close_day` et ne doit pas rentrer après `assembly_day` ; sinon elle n'a pas
  lieu et la pêche s'achève (bilan, vente, déclaration au dernier retour : la déclaration reste celle de la saison, voir le brief 2).
- **Le poisson sort du lac au retour** (début de la pêche + heures + route retour), événement `outing` à cet instant (`day` : début de la pêche,
  `hours`). La route coûte `economy.travel_cost` × 2 × jours à chaque sortie faite (et non plus à la saison).
- **Chance** : la forme de la saison (tirée une fois, prolongée d'une saison à l'autre) et la forme de la sortie, tirée pour son numéro dans la
  saison (`World.outing_row`) : plus de suite d'une sortie à l'autre. `World.outings` ne sert plus qu'à `apply_catch` (la saison d'un coup, pour
  les tests et les estimations).
- **Règles** : le quota (comparé au cumul, `quota_left` dans le contexte), les réserves, le repos, la taille de bateau et le nombre de sorties
  ne bloquent pas le moteur ; une sortie qui les enfreint est notée, le `breach` est posé au bilan de la saison. La règle `sorties` est un
  plafond du nombre de sorties de la saison (celui qu'un agent à règles prévoit s'il l'observe).
- **Qui décide, et pourquoi** (`routing.outing_reasons`) : une décision de sortie compare ce que le pêcheur voit à ce qu'il voyait à sa décision
  précédente (`agent.prev`). Une raison déjà présente alors n'en est plus une (le lac « sous 70 % » depuis le plan ne réveille plus personne) ;
  sont nouvelles : un temps qui change de catégorie (tempête, calme, ordinaire), une rumeur ou un événement, une règle, un indice, un lac qui
  baisse de plus de 4 % de la capacité depuis la dernière décision, un quota presque atteint (80 %) ou dépassé, un plan rempli ou impossible
  à tenir avant la fermeture. L'événement `decision` porte `system` (S1 : tev1 si le palier `reflexe` existe, sinon le petit modèle ; S2) et
  `routing` (les raisons). Hors profil `adaptive`, tout est S2. Le réflexe répond trois questions typées (`quand`, `duree`, `prise`) et garde
  le lac et le lieu du plan.
- **Le lieu** : `rive`, `large`, `rive voisine` (la rive d'un autre village du même lac, tirée de la graine). Dans un autre lac : toujours le
  large de ce lac. Un agent à règles garde le lac de son plan pendant toute la saison.
- **L'ordonnanceur** : le plus court délai avant qu'une décision de sortie change le monde est la plus courte sortie (3 h) ; les décisions dont
  les horizons tiennent dans cet intervalle partent ensemble. À instant égal, les décisions passent après tous les effets : elles voient le
  poisson qui vient d'être pris. « Plus cette saison » met fin à la pêche à l'instant de la décision.
- **Le catch** (bilan de saison) : sa zone, son lac, son coin et son `spot` sont ceux de la dernière sortie (le coin qu'il retrouvera à la
  saison suivante) ; `requested` est la prise de saison du plan ; `outings` liste chaque sortie (jour, heures, temps, chance, rendement, coin,
  lac, zone, tonnes).
- **Le faux LLM** décide les sorties comme un agent à règles de son archétype, puis varie, par un tirage tiré de la graine de la décision
  (`hint["seed"]`) : sortie courte une fois sur trois (et souvent la suivante le jour même), délais inégaux, bruit sur la cible.
- **Équilibre** (config `default.yaml` / `lakes.yaml`, faux LLM, 3 saisons, total pêché par saison) : avant 34,5 / 34,6 / 22,8 t et
  61,2 / 73,1 / 50,9 t ; après 33,3 / 32,9 / 25,4 t et 61,2 / 67,3 / 58,3 t. Même ordre de grandeur.
