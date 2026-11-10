# Diagrammes UML de FILETS

22 diagrammes Mermaid, que GitHub affiche directement. Chacun est précédé d'un paragraphe qui dit comment le lire et suivi
des emplacements dans le code (`fichier:ligne`). Ils sont tirés de la lecture du code au 10 novembre 2026 ; un numéro de
ligne peut s'être décalé d'une ou deux lignes depuis.

Pour une vue d'ensemble avant le détail : [docs/architecture.md](../architecture.md) (les blocs et leurs liens) et
[docs/temps.md](../temps.md) (le temps : un seul ordonnanceur, réfléchir ne prend pas de temps, la veillée au fil de l'eau).

## Par où commencer

1. [Cas d'utilisation](cas-utilisation.md) : qui fait quoi avec le jeu (le joueur, puis les acteurs de la simulation), et un
   tableau de 26 cas.
2. [Séquences](sequences.md) : cinq scénarios dans l'ordre du temps.
3. [Communication](communication.md) : trois de ces scénarios, vus comme des messages numérotés entre objets.
4. Les classes, partie par partie (ci-dessous).

## Classes

| Partie | Fichier | Diagrammes |
|---|---|---|
| Le monde, le temps, les règles et les lacs | [classes-monde.md](classes-monde.md) | le modèle du monde ; horloge, pause, saisons et veillées ; règles et lacs |
| Les décisions, les modèles, la mémoire et le RAG | [classes-decisions.md](classes-decisions.md) | agents, règles et routage ; routeur, clients et limiteurs ; mémoire, RAG et vecteurs |
| L'infrastructure | [classes-infrastructure.md](classes-infrastructure.md) | salon, API et bus ; événements, indicateurs et stockage ; services, configuration, catalogue, ligne de commande |
| L'interface Godot | [classes-godot.md](classes-godot.md) | qui possède qui ; le rôle d'`Art` ; `Main` en détail |

## Scénarios

| Scénario | Séquence | Communication |
|---|---|---|
| (a) Démarrer une partie depuis le menu | [sequences.md](sequences.md) | [communication.md](communication.md) |
| (b) La décision de prise d'un pêcheur | [sequences.md](sequences.md) | [communication.md](communication.md) |
| (c) La veillée au fil de l'eau | [sequences.md](sequences.md) | |
| (d) Une injection du joueur : la rumeur | [sequences.md](sequences.md) | [communication.md](communication.md) |
| (e) Le rejeu d'une partie | [sequences.md](sequences.md) | |

## Conventions

- **Modules.** Un fichier Python fait de fonctions (sans classe), comme `agents.py`, `policies.py`, `llm.py` ou `api.py`, est
  dessiné comme une classe marquée `<<module>>`. Les routes de l'API y sont écrites comme des pseudo-méthodes
  (`GET api_health`).
- **Scripts Godot.** Chaque script est une classe qui hérite de son nœud Godot (`extends Control`…).
- **Cas d'utilisation et communication.** Mermaid n'a pas ces deux types : les cas sont un graphe avec les acteurs reliés à des
  ovales, la communication un graphe dont les flèches portent des messages numérotés (1, 1.1, 2…).
- **Simplifications.** Seules les méthodes principales figurent (8 au plus par classe ; `World` en a bien davantage). Le pont
  Kafka est fusionné avec l'API, les services `indicators` et `store` ne sont pas dessinés dans les séquences, et le rejeu est
  montré avec le bus local.

## Vérifier un diagramme

`npx -y @mermaid-js/mermaid-cli@11.4.2 -i docs/uml/<fichier>.md -o /tmp/out.md` dessine tous les blocs d'un fichier et
échoue sur une erreur de syntaxe.
