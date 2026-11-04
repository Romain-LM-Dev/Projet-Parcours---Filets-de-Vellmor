# Le temps de FILETS : un seul mode

Spécification de la fusion des modes synchrone et asynchrone (décisions de l'utilisateur, 4 novembre 2026). Elle remplace
`SyncRunner` et `AsyncRunner` par un seul ordonnanceur. Le schéma des dépendances d'une saison sert de référence.

## Les trois décisions

1. **Réfléchir ne prend pas de temps ; agir en prend.** Une décision (IA ou règle) est instantanée dans le monde : l'horloge
   simulée ne bouge pas pendant qu'une IA réfléchit, et aucune action n'est plus jamais perdue parce qu'une IA a été lente.
   Une action, elle, dure : une sortie en mer, la route vers un autre lac, une prise de parole.
2. **Le poisson ne va pas forcément au premier arrivé.** La cale (`hold_of`) et le rendement du coin (`fill_near`) restent
   calculés sur l'instantané d'ouverture de la saison (`season_stock`, `open_cells`). Chaque sortie retire son poisson du lac au
   moment où elle a lieu (le stock baisse au fil de la saison, ce que voient les observations suivantes).
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
   `async_offset_days`, défaut [0, 4]). Sa décision de prise a pour horizon son jour de départ.
4. **Sorties** : la décision fixe la prise visée, le lac, la déclaration. Les sorties (`economy.outings`, d'un jour chacune)
   s'étalent de son départ à la fermeture ; s'il va dans un autre lac, la route ajoute ses jours à l'aller et au retour. Chaque
   sortie applique sa part de prise à sa fin (cale et coin sur l'instantané d'ouverture). Aucune sortie n'est planifiée après
   `fishing_close_day`. Le retour (dernière sortie) déclenche vente et déclaration, puis les indices (patrouille passée dans sa
   zone ce jour-là, témoins).
5. **Veillée** (de `assembly_day` à `assembly_close_day`) : voir plus bas. Les veillées de villages différents sont
   indépendantes et se déroulent en parallèle.
6. **Fin** (jour `regrowth_day`) : repeuplement de chaque lac (après toutes ses prises), bilans, lore, puis le récit du
   narrateur. Le récit ne bloque pas la préparation de la saison suivante (il ne change rien au monde).

## La veillée

- Ouverture : enquête de l'ancien et relation des indices (une action, avant toute parole).
- **Préparation** : chaque participant qui a quelque chose à dire prépare sa réplique sur le compte rendu tel qu'il est
  (décisions en parallèle). Une réplique peut viser quelqu'un (`destinataire`) ou tous.
- **Prise de parole** : une seule personne parle à la fois ; une réplique dure `speech_minutes` (défaut 20 minutes simulées).
  Ordre de parole : d'abord une personne à qui l'on vient de s'adresser, puis les autres selon la clé tirée de la graine.
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
