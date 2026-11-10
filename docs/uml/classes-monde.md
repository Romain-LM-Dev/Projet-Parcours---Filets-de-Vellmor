# Le monde et le temps

Cette partie du moteur Python décrit **ce qui existe dans la simulation** : le monde (`World`), ses lacs, ses pêcheurs,
les règles votées et le conseil du soir, puis **la façon dont le temps s'écoule** (horloge, pause, saisons, veillées).
`World` est le chef d'orchestre : il possède presque tout le reste. Lecture : un losange plein (`*--`) veut dire « possède et
fait vivre », un losange vide (`o--`) « garde une référence », une flèche pointillée (`..>`) « utilise ».

## 1. Le modèle du monde

```mermaid
classDiagram
    class World {
        +dict cfg
        +str run_id
        +dict agents
        +dict lakes
        +list norms
        +list assemblies
        +Climate climate
        +apply_catch(agent, requested, decision, horizon)
        +plan_trip(agent, requested, decision, horizon)
        +finish_trip(trip) dict
        +applicable_norm(agent, season, horizon, lake) Norm
        +rules_for(agent, season, horizon, lake) dict
        +open_assemblies(season, close_t, mode) list
        +close_sanctions(asm)
    }
    class Lake {
        +str name
        +float capacity
        +list cells
        +float r
        +bool collapsed
        +take(amount, at) float
        +regrow(rate_factor) float
        +shock(factor) float
        +observe(rng) float
        +is_collapsed() bool
    }
    class Agent {
        +Profile profile
        +MemoryStore memory
        +float wealth
        +dict catches
        +dict declared
        +dict lake_choice
        +float form
        +float temper
    }
    class Profile {
        +str id
        +str hamlet
        +str archetype
        +str kind
        +str tier
        +str role
        +str boat
        +float debt_payment
    }
    class Trip {
        +Agent agent
        +float requested
        +Lake lake
        +Lake home
        +str zone
        +list outs
        +list got
    }
    class Norm {
        +str scope
        +float quota
        +str kind
        +str target
        +int effective_season
        +int until
        +list supporters
    }
    class Proposal {
        +str id
        +str author
        +float quota
        +str kind
        +str scope
        +key() tuple
    }
    class Sanction {
        +str id
        +str author
        +str target
        +str action
        +dict votes
    }
    class Assembly {
        +str scope
        +list participants
        +int season
        +float close_t
        +list utterances
        +dict proposals
        +dict sanctions
        +bool closed
    }
    class Climate {
        +bool enabled
        +list active
        +dict by_season
        +begin(season) dict
        +calendar(season, n_days) list
        +day_factor(label, season, boat) float
        +yield_for(boat) float
    }
    class MemoryStore

    World "1" *-- "1..*" Lake : lakes
    World "1" *-- "1..*" Agent : agents
    World "1" *-- "1" Climate
    World "1" *-- "0..*" Norm : norms
    World "1" *-- "0..*" Assembly : assemblies
    Agent "1" *-- "1" Profile
    Agent o-- MemoryStore : memory
    Assembly "1" *-- "0..*" Proposal : proposals
    Assembly "1" *-- "0..*" Sanction : sanctions
    Norm ..> Proposal : issue d une proposition adoptee
    World ..> Trip : cree via plan_trip
    Trip o-- Agent
    Trip o-- Lake
```

`Proposal`, `Sanction`, `Assembly`, `Trip` et `Norm` sont de simples `dataclass` rangées dans `world.py` ; `Agent` est dans
`agents.py` et `Profile` dans `profiles.py`. Un `Norm` est une `Proposal` devenue règle après le vote du conseil
(il garde son `proposal_id`). `Lake` stocke le poisson par parcelle (`cells`) et applique la physique (prise, repousse, choc).

**Pour aller plus loin**
- `filets/world.py:213` (`World`), `:111` (`Proposal`), `:128` (`Sanction`), `:141` (`Assembly`), `:164` (`Trip`), `:196` (`Norm`)
- `filets/lake.py:19` (`Lake`) ; `filets/agents.py:25` (`Agent`) ; `filets/profiles.py:92` (`Profile`)
- `filets/climate.py:54` (`Climate`)

## 2. Le temps : horloge, pause, saisons et veillées

`SimClock` compte le temps simulé (en jours) et sa vitesse ; `GameControl` y ajoute la pause et l'arrêt. À chaque saison,
`World` crée un `SeasonScheduler` : une file d'événements datés (départs en mer, décisions des agents, repousse du lac). Le
soir, une `Village` joue la veillée d'un village (ou du conseil de la vallée) : qui parle, qui prépare sa réponse, jusqu'à
la clôture de l'`Assembly`.

```mermaid
classDiagram
    class World {
        +SimClock clock
        +GameControl ctl
        +Climate climate
    }
    class SimClock {
        +float season_days
        +float speed
        +bool fast
        +set_speed(speed) float
        +pause()
        +resume()
        +now() float
        +advance_wall(dt_wall, next_due, busy)
        +season_of(t) int
        +season_start(season) float
    }
    class GameControl {
        +SimClock clock
        +bool paused
        +bool stopping
        +pause() bool
        +resume() bool
        +set_speed(speed) float
        +request_stop()
    }
    class StopRun {
        <<exception>>
    }
    class SeasonScheduler {
        +World w
        +int season
        +float t0
        +list q
        +at(t, cls, ident, item)
        +open_season()
        +depart(agent, outing, horizon)
        +regrowth()
        +play()
    }
    class Decision {
        +str agent
        +float lag
        +make()
        +then(result)
    }
    class Village {
        +Assembly asm
        +float t
        +int rounds
        +dict spoken
        +dict prepared
        +bool done
        +prep_jobs() list
        +pick() str
        +speak(aid) bool
    }
    class Assembly

    World "1" *-- "1" SimClock
    World "1" *-- "1" GameControl
    GameControl o-- SimClock
    GameControl ..> StopRun : leve a l arret
    World ..> SeasonScheduler : un par saison
    SeasonScheduler o-- World
    SeasonScheduler ..> Decision : file d appels d agents
    SeasonScheduler ..> Village : une par assemblee
    Village o-- Assembly
    Village o-- SeasonScheduler
```

Le scheduler et les veillées ne décident rien : ils ordonnent les appels (`agents.decide_catch`, `speak`, `ballot`, voir
`classes-decisions.md`) et appliquent leurs résultats via `World`.

**Pour aller plus loin**
- `filets/clock.py:60` (`SimClock`) ; `filets/control.py:28` (`GameControl`), `:24` (`StopRun`)
- `filets/scheduler.py:46` (`SeasonScheduler`), `:38` (`Decision`), `:233` (`Village`)
- `filets/world.py:2995` : une saison = un `SeasonScheduler(...).play()`

## 3. Les règles et les lacs (modules de fonctions)

`rules.py` et `lakes.py` ne contiennent aucune classe : ce sont des **modules de fonctions** pures, représentés ici avec
`<<module>>`. `rules.py` définit les cinq types de règle que le conseil peut voter ; `lakes.py` fabrique la géographie
(mailles, parcelles de chaque lac, positions des villages, distances).

```mermaid
classDiagram
    class rules {
        <<module>>
        +tuple KINDS
        +tuple TIMED
        +tuple TARGETED
        +dict VALUE_TOLERANCE
        +kind_of(raw) str
        +plural(n, word) str
        +words(kind, value, place, boat, cap) str
    }
    class lakes {
        <<module>>
        +int GRID
        +grid_of(size) int
        +world_size(villages, lakes) float
        +village_positions(hamlets, lake_index, n_lakes) dict
        +lake_parcels(n_lakes, seed, size) list
        +lake_distance(n_lakes, i, j, days_per_map) float
        +split_villages(hamlets, n) list
        +resolve_lakes(L, hamlets, fishers) list
        +random_valley(seed) dict
    }
    class World
    class Lake

    World ..> rules : rules_for, rule_words
    World ..> lakes : construit ses lacs
    World "1" *-- "1..*" Lake
    lakes ..> Lake : donne les parcelles
```

**Pour aller plus loin**
- `filets/rules.py:1` (types de règle, docstring) ; `:28` `kind_of`, `:36` `words`
- `filets/lakes.py:118` (`lake_parcels`), `:211` (`resolve_lakes`), `:254` (`random_valley`)
- `filets/world.py:46` (`from . import prompts, rules`) et `:55` (imports de `lakes`)
