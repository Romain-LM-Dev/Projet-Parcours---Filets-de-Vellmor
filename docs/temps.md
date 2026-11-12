# Le temps de FILETS : un seul mode

Spécification de la fusion des modes synchrone et asynchrone (décisions de l'utilisateur, 4 novembre 2026). Elle remplace
`SyncRunner` et `AsyncRunner` par un seul ordonnanceur. Le schéma des dépendances d'une saison sert de référence.

## Les trois décisions

1. **Réfléchir ne prend pas de temps ; agir en prend.** Une décision (IA ou règle) est instantanée dans le monde : l'horloge
   simulée ne bouge pas pendant qu'une IA réfléchit, et aucune action n'est plus jamais perdue parce qu'une IA a été lente.
   Une action, elle, dure : une sortie en mer (de 3 à 7 heures de pêche, jamais la nuit, voir [peche.md](peche.md)), la route vers un autre lac, une prise de parole.
2. **Le poisson ne va pas forcément au premier arrivé.** La cale (`hold_of`) et le rendement du coin (`fill_near`) restent
   calculés sur l'instantané d'ouverture de la saison (`season_stock`, `open_cells`). Chaque sortie retire son poisson du lac à
   son retour (le stock baisse au fil de la saison, ce que voient les observations suivantes).
3. **La veillée se déroule au fil de l'eau.** Les répliques se préparent en parallèle ; une seule personne parle à la fois ;
   une réplique peut répondre à une autre ou non (voir « La veillée »).

## L'ordonnanceur

Une simulation à événements discrets.

- **Action** : `(t, ordre, acteur, effet, durée)`. Elle commence à `t` (temps simulé, en jours) ; ses effets dans le monde
  s'appliquent à `t + durée`. File de priorité sur `(t, classe, clé)` : `classe` fixe l'ordre des acteurs à instant égal (monde,
  lacs, pêcheurs, patrouille, conseil), `clé` est tirée de la graine (`random.Random(f"{seed}|order|{season}|{id}")`).
- **Décision** : un appel d'agent (IA ou règle) de durée nulle, attaché à un instant `h` (son horizon : il ne voit que ce qui
  s'est passé avant `h`). L'horloge ne dépasse jamais l'horizon d'une décision demandée et pas encore rendue.
- **Parallèle** : toutes les décisions dont l'horizon tombe dans un même intervalle calme (aucun effet appliqué au monde entre
  leurs horizons) sont demandées ensemble et tournent en même temps, dans la limite de la carte graphique (`ModelGate`). Dès
  qu'un effet s'applique entre deux horizons, la seconde décision attend la première : c'est une chaîne.
- **Déterminisme** : les résultats s'appliquent dans l'ordre de la file (temps simulé, classe, clé), jamais dans l'ordre où
  les modèles répondent. À graine égale et faux LLM, deux parties donnent le même journal.
- **Affichage** : en dehors des décisions en cours, l'horloge avance au rythme d'affichage (`sim_hours_per_second`, vitesse
  choisie, accélération quand rien ne se passe) ; elle ne fait que montrer ce que la file contient. Pause, vitesse et arrêt
  agissent comme aujourd'hui.

## La saison

1. **Avant la saison** (inchangé, en parallèle) : débrief des absents, élection par village, route de chaque patrouille.
2. **Ouverture** (jour `fishing_open_day`) : climat, événements, instantané d'ouverture de chaque lac.
3. **Départs** : chaque pêcheur a un jour de départ tiré de la graine dans `departure_spread_days` (ancien
   `async_offset_days`, défaut [0, 4]). Son plan de saison (grand modèle) a pour horizon son jour de départ ; il porte aussi sa
   première sortie.
4. **Sorties** : le pêcheur décide chacune, à l'ouverture puis à chaque retour : quand (un délai en heures, « demain à l'aube »,
   « plus cette saison »), où (lac, zone), combien, courte (3 h) ou longue (7 h) ; `economy.outings` n'est plus qu'un nombre par défaut
   pour les agents à règles. Pas de pêche de 21 h à 5 h (elle attend l'aube), plusieurs sorties par jour sont possibles, la route d'un
   autre lac s'ajoute à l'aller et au retour. Le poisson (cale par sortie, coin sur l'instantané d'ouverture) sort du lac au retour ;
   la décision suivante est prise à cet instant et déclare la sortie qui vient de finir (`report`). Aucune sortie ne commence après
   `fishing_close_day`. Quand il ne ressort plus, bilan et vente ; les indices (patrouille passée dans sa zone ce jour-là, témoins du
   retour) sont réunis par sortie au soir de la veillée.
5. **Veillée** (de `assembly_day` à `assembly_close_day`) : voir plus bas. Les veillées de villages différents sont
   indépendantes et se déroulent en parallèle.
6. **Fin** (jour `regrowth_day`) : repeuplement de chaque lac (après toutes ses prises), bilans, lore, puis le récit du
   narrateur. Le récit ne bloque pas la préparation de la saison suivante (il ne change rien au monde).

## La veillée

- Ouverture : enquête de l'ancien et relation des indices (une action, avant toute parole).
- **Préparation** : chaque participant qui a quelque chose à dire prépare sa réplique sur le compte rendu tel qu'il est
  (décisions en parallèle). Une réplique peut viser quelqu'un (`destinataire`) ou tous.
- **Prise de parole** : une seule personne parle à la fois ; une réplique dure `speech_minutes` (défaut 20 minutes simulées).
  Ordre de parole : d'abord une personne à qui l'on vient de s'adresser, puis celles qui ont le moins parlé ce soir, puis la clé
  tirée de la graine ; jamais deux répliques de suite du même orateur s'il reste quelqu'un d'autre de prêt. Un message vide
  est un silence : le tour passe, sans bulle ni `utterance` (seule la `decision` le note). Un message qui n'est qu'un nom de
  champ ou un gabarit (« message », « <ta réplique> ») est une réponse illisible (repli), pas une réplique.
- **Chaîne** : si, entre la préparation d'une réplique et son tour, quelqu'un s'est adressé à son auteur (ou a proposé une
  règle sur laquelle il voulait se prononcer), il la prépare de nouveau sur le nouveau compte rendu. Sinon elle reste valable :
  les répliques qui ne se répondent pas ne s'attendent pas.
- Au plus `assembly_rounds` répliques par participant. Ensuite, les bulletins (en parallèle), puis le vote de clôture.

## Ce qui disparaît, ce qui reste compatible

- Disparaissent : `SyncRunner`, `AsyncRunner`, `Assembly.independent`, `ballot_lead_days`, `wait_for_ai`, les fenêtres ratées
  dues à une IA lente (l'incident `missed_window` reste dans le schéma pour les anciens journaux).
- `time.mode` et la commande `set_mode` sont acceptés et ignorés (un avertissement dans le journal du moteur) ; `run_start.mode`
  vaut `"unique"` (le schéma l'accepte en plus de `sync`/`async` pour les anciens journaux).
- L'interface retire le choix Synchrone / Asynchrone et montre plutôt qui réfléchit en ce moment.

## Choix faits là où la spécification laissait une marge

- **Départ et sorties** : `time.departure_spread_days` donne le décalage de chaque pêcheur après `fishing_open_day` ; ses sorties sont
  celles qu'il décide (voir [peche.md](peche.md)), espacées comme il l'entend. Dans un autre lac, l'aller et le retour (`route` jours) s'ajoutent
  à la pêche ; une sortie qui rentrerait après la veillée n'a pas lieu. La route se paie en écus (`economy.travel_cost`) à chaque sortie.
- **Lot de décisions** : une décision porte un délai minimal avant son effet (`lag`, la plus courte sortie : 3 heures, pour une décision de sortie) ; le lot s'arrête à la première
  dont l'horizon dépasse ce délai. Leurs événements (`decision`, `llm_call`…) sortent dans l'ordre de la file (mis en attente par
  `EventFactory.defer`, numérotés à `flush`), pas dans l'ordre des réponses.
- **Veillée** : toutes les répliques sont préparées d'abord à l'ouverture (`assembly_day`), sur la salle vide. Une réplique, quand elle
  est dite, dure `time.speech_minutes` (20) et ses effets (parole, proposition, soutien…) s'appliquent à sa fin ; `utterance.heard` est
  ce que son auteur savait en la préparant. Prochain orateur : celui à qui la dernière réplique s'adressait (s'il a une réplique prête
  et n'est pas l'orateur précédent), sinon le moins entendu ce soir, puis la clé de la graine (`{graine}|order|{saison}|{village}|{agent}`) ;
  la réplique suivante d'un orateur n'est préparée qu'une fois la précédente dite (elle voit « ce que tu as déjà dit »). Une réplique prête est **préparée de nouveau** si, depuis, on
  s'est adressé à son auteur (`destinataire`), on l'a nommé ou accusé, ou une autre règle a concurrencé la sienne. Après avoir parlé,
  chacun prépare sa réplique suivante seulement s'il en a une raison (`World.has_reason_to_speak`, `scenario.quiet_listeners`), au plus
  `assembly_rounds` répliques. Plus de parole après `assembly_close_day`.
- **Villages** : les veillées avancent de front (leurs décisions partent ensemble) mais leurs effets s'appliquent village par village, dans
  l'ordre des assemblées. Puis les bulletins de ceux qui n'ont rien soutenu, en parallèle, et le vote de clôture à `assembly_close_day`.
- **Redites** : une réplique qui en répète une déjà dite dans la partie (`World.repeated_line` : 85 % des mots de la plus courte, au moins 4) est
  redemandée UNE fois au même modèle ; si elle se répète encore, il se tait. Une proposition de règle identique à celle qui vaudra déjà à la saison
  suivante pour sa portée n'ouvre ni proposition ni soutien. Deux répliques préparées en même temps ne se voient pas : si, à son tour, une réplique
  prête redit ce qui vient d'être dit, elle est préparée de nouveau (elle voit alors l'autre). Le contrôle des redites ne vaut que pour les vrais
  modèles (le faux LLM redit ses phrases toutes faites par construction). Un silence passe le tour sans clore la veillée : les autres répliques prêtes
  restent à dire.
