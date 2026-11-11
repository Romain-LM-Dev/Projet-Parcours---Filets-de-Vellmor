# Le monde et le temps

Cette partie du moteur Python décrit **ce qui existe dans la simulation** : le monde (`World`), ses lacs, ses pêcheurs, les règles
votées et le conseil du soir, puis **la façon dont le temps s'écoule** (horloge, pause, saisons, veillées). `World` est le chef
d'orchestre : il possède presque tout le reste.

Comment lire les diagrammes : `+` public, `-` interne (nom commençant par `_`). Un losange plein (`*--`) veut dire « possède et fait
vivre », un losange vide (`o--`) « garde une référence », `<|--` l'héritage, `..>` « utilise ». Quand le code n'annote pas le type
d'un attribut, il est déduit de la valeur affectée (`any` si on ne peut pas savoir) ; `X?` veut dire « X ou rien » ; les types
génériques sont réduits à leur base (`dict`, `list`). Les méthodes `async` ne sont pas marquées. Rien n'est volontairement omis :
l'union des vues de `World` couvre toutes ses définitions (147 : 146 méthodes plus la propriété `boat_names`, montrée comme attribut).

## 1. `World` : structure, attributs et utilitaires

Tous les attributs de `World` (l'état de la partie) et les petites méthodes de service : identité des agents, noms, mémoire, lore,
stock des lacs. Les autres vues de `World` (sections 2 à 9) détaillent ses méthodes par domaine ; ici on voit de quoi il est fait.

```mermaid
classDiagram
    class World {
        +list boat_names
        +dict cfg
        +any bus
        +str run_id
        +str engine_id
        +bool lobby
        +float? advised_speed
        +bool ended
        +any T
        +SimClock clock
        +GameControl ctl
        +any run_dir
        +Recorder recorder
        +EventFactory events
        +any capacity
        +any econ
        +dict scn
        +any comm
        +bool visible
        +object objects
        +None vectors
        +None memory_bank
        +dict agents
        +list fishers
        +any elder
        +list hamlets
        +dict lakes
        +dict lake_of_hamlet
        +float world_size
        +int grid
        +dict village_xy
        +dict sectors
        +any lake
        +any multi
        +dict lake_fishers
        +set collapsed
        +dict season_stock
        +list zones
        +any delegates
        +dict reps
        +Assembly? last_council
        +any boats
        +dict boat_cap
        +dict lake_boats
        +float hold_fraction
        +float travel_days
        +float travel_price
        +dict hold
        +any boat_max
        +any max_catch
        +any min_catch
        +LLMRouter router
        +list norms
        +dict promises
        +dict promise_memories
        +dict reports
        +dict lies
        +dict trust
        +dict detection
        +dict trips
        +dict live
        +list clues
        +dict audits
        +dict accusations
        +dict established
        +Random lie_rng
        -int _investigated_season
        -int _weighed_season
        +dict banned
        +dict? patrol
        +dict patrol_cfg
        +any patrol_count
        +bool patrol_on
        +dict patrol_legs
        +dict patrol_log
        +list patrol_agents
        +Agent? patrol_agent
        +Climate climate
        +any conditions
        +int season
        +bool stop_requested
        +str stopped_reason
        -counter _pid
        -counter _xid
        +bool collapse_flagged
        +Random obs_rng
        +list assemblies
        +list rumors
        +list thinking
        +list ai_providers
        +VectorRetriever retriever
        +__init__(cfg, bus, run_id, record, engine_id, lobby, advised_speed)
        +heal_event_ids(renamed) None?
        +incident(agent, itype, detail, handled_by, call_id)
        +remember(agent, text, kind, importance, pinned, expires_season, source_event_id, t)
        +add_lore(agent, text, source_event_id, scope, importance)
        +name(aid) str
        +lake_of(agent) Lake
        +lake_stock() float
        +stocks() dict
        +first_name(aid) str
    }
    class Lake
    class Agent
    class Climate
    class Norm
    class Assembly
    class SimClock
    class GameControl
    class EventFactory
    class Recorder
    class LLMRouter
    class Retriever
    class VectorRetriever
    class MemoryBank
    class Bus
    World "1" *-- "1..*" Lake : lakes
    World "1" *-- "1..*" Agent : agents
    World "1" *-- "1" Climate : climate
    World "1" *-- "0..*" Norm : norms
    World "1" *-- "0..*" Assembly : assemblies
    World "1" *-- "1" SimClock : clock
    World "1" *-- "1" GameControl : ctl
    World "1" *-- "1" EventFactory : events
    World "1" *-- "0..1" Recorder : recorder
    World "1" *-- "1" LLMRouter : router
    World "1" *-- "1" Retriever : retriever
    World ..> VectorRetriever : variante pgvector
    World "1" o-- "0..1" MemoryBank : memory_bank
    World o-- Bus : bus
```

Sections suivantes : une vue de `World` par domaine.

**Pour aller plus loin**
- `filets/world.py:205` (`World`)
- `filets/agents.py:26` (`Agent`)
- `filets/lake.py:19` (`Lake`)

## 2. `World` : lacs, zones et déplacements

Où l'on pêche : les zones (rive d'un village, large), les parcelles, les options de lac qu'un pêcheur peut envisager, le coût du trajet et la mise à jour du stock d'un lac. Vue réduite à ce domaine : `World` y est montré sans ses attributs (voir la section 1).

```mermaid
classDiagram
    class World {
        +large_zone(lake) str
        +zone_lake(zone) Lake
        +zone_label(zone) str
        +distance(a, b) float
        +travel_cost(days) float
        +lake_options(agent, est, horizon) list
        +hold_of(agent, stock, lake) float
        -_parcel_dist(p, hamlet) float
        +spot_of(agent, lake, zone, season, avoid) int
        +lake_cells()
        +lake_update(cause, delta, lake)
        +fished_lake(agent, season) Lake
        +zone_place(zone) str
        +hot_zone(agent) tuple?
        +secret_zone(agent) str
    }
```


## 3. `World` : règles et normes

Les règles votées (quota, réserve, repos, sorties, bateau) : quelle règle s'applique à quel pêcheur, comment on la dit en mots, comment une proposition est lue et rapprochée d'une autre. Vue réduite à ce domaine : `World` y est montré sans ses attributs (voir la section 1).

```mermaid
classDiagram
    class World {
        +norm_for_scope(scope, season, horizon, kind, target) Norm?
        +applicable_norm(agent, season, horizon, lake) Norm?
        +rules_for(agent, season, horizon, lake) dicttupleNorm
        +rule_view(agent, season, horizon, lake) dict
        +rule_words(kind, value, target) str
        +norm_words(n) str
        +proposal_words(pr) str
        +resolve_target(kind, raw, agent) str?
        -_support(agent, asm, pid, u)
        +read_proposal(d, agent) tuple?
        +proposal_scope(d, kind, asm) str
        +scope_words(scope) str
        +scope_of(scope) str
        -_similar_proposal(asm, kind, target, q, scope) Proposal?
    }
```


## 4. `World` : pêche, sorties et météo

Le déroulement physique de la pêche de saison : jours de sortie, météo, ouverture de la pêche (`open_trip`, d'après le plan que le pêcheur a décidé), puis, pour chaque sortie qu'il décide, départ (`start_outing`, `fishing_start` : pas de pêche la nuit), cale du bateau (`cale_of`), prise (`outing_row`), retour (`land_outing`), déclaration de ce retour (`report_outing`) et bilan de saison (`finish_trip`). Le moteur ne fait que compter et appliquer la physique ; le plan, le moment, le lieu, la quantité et la déclaration de chaque sortie viennent de la décision du pêcheur. Vue réduite à ce domaine : `World` y est montré sans ses attributs (voir la section 1).

```mermaid
classDiagram
    class World {
        +world_text(agent) str
        +beyond_declared(estimate, said, outing) bool
        +upkeep(agent, season) float
        +weather(season) list
        +outing_days(agent, route) list
        +outing_row(agent, season, day, lake, stock, k) dict
        +outings(agent, season, stock, lake) list
        +note_lake(agent, season, horizon, est, purpose, rnd)
        +observe(agent, horizon, purpose, assembly, rnd)
        +cale_of(agent, hours) float
        +trip_left(agent, trip, lake, stock) float
        +fishing_start(t, hours) float
        +open_trip(agent, requested, decision, horizon, declared, ration, stock_at_action) Trip?
        +start_outing(trip, spec, now) dict?
        +note_plan(agent, out) None?
        +land_outing(trip, out) float
        +report_outing(trip, out, declared) dict?
        +apply_catch(agent, requested, decision, horizon, ration, stock_at_action, declared, lake_name) dict
        +leg_cost(days) float
        +finish_trip(trip) dict
    }
```


## 5. `World` : indices, mensonges, confiance et sanctions

Ce que chacun sait ou croit des autres : rumeurs, prises connues, mensonges et triche (livre des mensonges établis : `lie_words`, `lie_lines`), réputation, enquête et preuves, faits de confiance, carnet de l'agent et dossier remis avant les sanctions. Vue réduite à ce domaine : `World` y est montré sans ses attributs (voir la section 1).

```mermaid
classDiagram
    class World {
        +active_rumors(horizon) list
        +named_fishers(texts) list
        +fisher_ref(raw) str?
        +can_see(observer, subject) bool
        +known_catch(aid, season, horizon) float?
        +lied(aid, season) bool
        +cheated(aid, season) bool
        +reputation(subject) float
        +judge(observer, changes, source_event_id)
        +investigate(season)
        +weigh_evidence(season)
        +establish(a, season, trip, said, est, clues, flagged)
        +lie_words(outs, n) str
        +lie_lines(agent, horizon, season) list
        +clue_text(c, viewer) str
        +clue_lines(agent, horizon, season) list
        +trust_facts(agent, season, horizon, since) dict
        +trust_context(agent, season) dict
        +trust_obs(agent) dict
        +promise_lines(agent, season, horizon) list
        +known_catches(agent, horizon, season) tuple
        +carnet(agent, horizon) list
        -_clue_suspect(agent, season, horizon) str?
        -_overfisher(agent, last, season) str?
        +debrief(season)
        +debrief_lines(agent, asm, facts) list
        +sanction_brief(observer, target, season, none) str
    }
```


## 6. `World` : patrouille

La patrouille du lac : coût, couverture des zones, planning des tournées, soupçons, règle de répartition, rapport, et les textes que voient les agents. Vue réduite à ce domaine : `World` y est montré sans ses attributs (voir la section 1).

```mermaid
classDiagram
    class World {
        +patrol_cost() float
        +patrol_active(season) bool
        +patrol_exists() bool
        +set_patrol(s, season, yes, voters)
        +patrol_cover(season, zone, days, aid) tuple
        +patrolled(season, zone, days, aid) float
        +plan_patrol(season)
        +leg_text(leg) str
        +patrol_schedule(plan) list
        +discordant(c) bool
        +heard_text(c) str
        +patrol_dossier(season, captain) list
        +patrol_suspicion(season) dict
        +patrol_suspects(season) dict
        +patrol_rule(season, legs_n, days, taken) tuple
        +patrol_report(season)
        +propose_patrol(agent, asm, raw, u)
        +patrol_line(season) str
        +patrol_noun(definite, bare) str
    }
```


## 7. `World` : veillée, propositions et votes

Le conseil du soir : qui siège, qui parle, propositions de sanctions, votes, élection du délégué et clôture de l'assemblée. Vue réduite à ce domaine : `World` y est montré sans ses attributs (voir la section 1).

```mermaid
classDiagram
    class World {
        +elect(season)
        +council_members(season) list
        +open_assemblies(season, close_t, mode) list
        +post_utterance(agent, asm, outcome, rnd, horizon)
        +has_reason_to_speak(agent, asm, rnd) bool
        +propose_sanction(agent, asm, raw, action, u)
        -_motion(agent, asm, action, target, u) Sanction
        +vote_sanction(agent, s, yes)
        +policy_voter(agent) bool
        +close_sanctions(asm)
        +motion_text(s) str
        +delegate_line(agent) str
        +motion_item(observer, s, season) str
        +ballot_candidates(asm) list
        +candidate_line(voter, cand, season) str
        +ballots(asms) None?
        +closing_vote(asm)
        +close_assembly(asm)
    }
```


## 8. `World` : calendrier, saison, fin de saison et récit

Le temps vu par les agents (date, phase du jour, ciel), les événements programmés, le début et la fin d'une saison, la narration, le démarrage et la fin de la partie, le stockage. Vue réduite à ce domaine : `World` y est montré sans ses attributs (voir la section 1).

```mermaid
classDiagram
    class World {
        +when(t, short) str
        +phase_text(t) str
        +calendar_text() str
        +sky_phrase(days) str
        +sky_line(season) str
        +scheduled_injections(season)
        +end_season(season)
        +season_facts(season) list
        +narrator_facts(season, limit) list
        +narrate(season) None?
        +start()
        +finish()
        +open_storage() None?
        +close_storage(archive) None?
        +begin_season(season)
        +prepare_season(season)
        +run()
    }
```


## 9. `World` : statut et commandes

La liaison avec l'extérieur : commandes reçues de l'interface (pause, vitesse, arrêt…), publication de l'état de la partie. Vue réduite à ce domaine : `World` y est montré sans ses attributs (voir la section 1).

```mermaid
classDiagram
    class World {
        +handle_command(cmd, source)
        -_control_command(ctype, cmd, params, source)
        +poll_commands()
        -_command_pump()
        +status_payload(state, kwargs) dict
        +publish_status(state, kwargs)
    }
```


## 10. Données du conseil, du voyage et du pêcheur

`Proposal`, `Sanction`, `Assembly`, `Trip` et `Norm` sont des `dataclass` de `world.py` (`Trip` est la pêche d'un pêcheur pour toute la saison : son plan, la liste de ses sorties `outs` décidées l'une après l'autre, ce que chacune a rapporté, et le bilan à son dernier retour) ; `Agent` et `Outcome` viennent de `agents.py`,
`Profile` de `profiles.py`. Un `Norm` est une `Proposal` devenue règle après le vote (il garde son `proposal_id`). Une `Assembly`
regroupe les paroles, les propositions et les sanctions soumises au vote d'une veillée.

```mermaid
classDiagram
    class Proposal {
        +str id
        +str author
        +float quota
        +float t
        +str event_id
        +str scope
        +str kind
        +str? target
        +tuple key
    }
    class Sanction {
        +str id
        +str author
        +str target
        +str action
        +float t
        +str event_id
        +dict votes
    }
    class Assembly {
        +str scope
        +list participants
        +int season
        +float close_t
        +list utterances
        +dict proposals
        +dict support
        +dictstrtuple stated
        +list accused
        +dict sanctions
        +str mode
        +bool delegates
        +bool closed
        +str label
    }
    class Trip {
        +Agent agent
        +float requested
        +dict decision
        +float horizon
        +float? declared
        +Lake home
        +bool secret
        +dict obs
        +dict view
        +float ration
        +float? stock_at_action
        +list outs
        +list got
        +dict taken
        +float? before
        +float? after
        +set breach
        +bool done
    }
    class Norm {
        +str scope
        +float quota
        +int effective_season
        +str proposal_id
        +float adopted_t
        +str event_id
        +list supporters
        +str kind
        +str? target
        +int? until
        +float value
    }
    class Agent {
        +Profile profile
        +MemoryStore memory
        +random.Random rng
        +float wealth
        +float offset_days
        +dict catches
        +dict? last_decision
        +list stock_seen
        +dict declared
        +dict outings
        +float form
        +int form_season
        +dict plans
        +dict? prev
        +float temper
        +dict lake_choice
        +int? spot
        +dict spots
        +str id
        +bool is_fisher
        +str archetype
    }
    class Outcome {
        +float? value
        +dict data
        +dict decision
        +bool ok
    }
    class Profile {
        +str id
        +str name
        +str hamlet
        +str archetype
        +str archetype_label
        +int experience
        +float debt_payment
        +float wealth
        +str traits
        +str voice
        +str kind
        +str? tier
        +str role
        +str first_name
        +str boat
        +public() dict
    }
    class World
    class Lake
    class MemoryStore
    World "1" *-- "0..*" Assembly : assemblies
    World "1" *-- "0..*" Norm : norms
    World "1" *-- "1..*" Agent : agents
    World ..> Trip : open_trip (un par pecheur et saison)
    Assembly "1" *-- "0..*" Proposal : proposals
    Assembly "1" *-- "0..*" Sanction : sanctions
    Norm ..> Proposal : adoptee depuis proposal_id
    Agent "1" *-- "1" Profile : profile
    Agent o-- MemoryStore : memory
    Trip o-- Agent : agent
    Trip o-- Lake : lake
    Trip o-- Lake : home
    Agent ..> Outcome : decisions rendent
```

**Pour aller plus loin**
- `filets/world.py:111` (`Proposal`)
- `filets/world.py:128` (`Sanction`)
- `filets/world.py:141` (`Assembly`)
- `filets/world.py:164` (`Trip`)
- `filets/world.py:188` (`Norm`)
- `filets/agents.py:26` (`Agent`)
- `filets/agents.py:62` (`Outcome`)
- `filets/profiles.py:92` (`Profile`)

## 11. Population : fonctions de `profiles.py`

`profiles.py` construit la population de pêcheurs (profils, archétypes, bateaux) à partir de la configuration ou d'une liste
personnalisée. Ses fonctions sont regroupées en un bloc `<<module>>`.

```mermaid
classDiagram
    class Profile {
        +str id
        +str name
        +str hamlet
        +str archetype
        +str archetype_label
        +int experience
        +float debt_payment
        +float wealth
        +str traits
        +str voice
        +str kind
        +str? tier
        +str role
        +str first_name
        +str boat
        +public() dict
    }
    class profiles {
        <<module>>
        +list VILLAGE_NAMES
        +any HAMLETS
        +tuple BOAT_NAMES
        +str DEFAULT_BOAT
        +dict DEFAULT_BOAT_MIX
        +dict BOAT_TILT
        +list FIRST_NAMES
        +dict ARCHETYPES
        +list ORDER
        +tuple TIERS
        +tuple KINDS
        +full_name(first_name, hamlet) str
        +archetype_defaults(arch) dict
        +tier_for(kind, experience, requested, large_min) str?
        +villages_of(fishers) list
        +custom_to_profiles(custom, large_min) list
        +validate_custom(custom) list
        +draw_boat(arch, mix, rng) str
        +build_population(cfg) list
        +profile_to_spec(p) dict
    }
    class Agent
    class World
    profiles ..> Profile : fabrique
    Agent "1" *-- "1" Profile
    World ..> profiles : build_population
```

**Pour aller plus loin**
`filets/profiles.py:92` (`Profile`)
`filets/profiles.py:195` (`build_population`)

## 12. Lac, climat, règles et géographie

`Lake` porte la physique du poisson (stock par parcelle, prise, repousse, choc) ; `Climate` tire les événements climatiques et leur
effet sur la pêche. `rules.py` (types de règle) et `lakes.py` (géographie : mailles, parcelles, villages, distances) sont des
modules de fonctions, ainsi que les deux fonctions utilitaires de `world.py`.

```mermaid
classDiagram
    class Lake {
        +float stock
        +any name
        +any label
        +float capacity
        +list? parcels
        +list cap_cells
        +list cells
        -any _stock
        +list open_cells
        +float r
        +float collapse_ratio
        +float noise
        +bool collapsed
        +__init__(capacity, initial_ratio, growth_rate, collapse_ratio, observation_noise, name, label, parcels)
        -_kernel(at) list
        +take(amount, at) float
        +open_season()
        +fill_near(at) float
        +regrow(rate_factor) float
        +observe_far(rng) float
        +shock(factor) float
        +observe(rng) float
        +is_collapsed() bool
        +is_extinct() bool
    }
    class Climate {
        +int seed
        +bool enabled
        +float rate
        +set off
        +Random rng
        +list active
        +any cycle
        +float growth
        +float yield_
        +str? new
        +dict by_season
        +__init__(cfg, seed)
        +begin(season) dict
        +yield_for(boat) float
        +calendar(season, n_days) list
        +day_factor(label, season, boat) float
        +conditions() dict
        +shock() float
        +line(season) str
    }
    class rules {
        <<module>>
        +tuple KINDS
        +tuple TIMED
        +tuple TARGETED
        +int MAX_DURATION
        +dict ALIASES
        +dict VALUE_TOLERANCE
        +dict DUREES
        +dict QUAND
        +kind_of(raw) str?
        +plural(n, word) str
        +words(kind, value, place, boat, cap) str
        +quand_hours(label, now) float?
    }
    class lakes {
        <<module>>
        +list LAKE_NAMES
        +int MAX_LAKES
        +dict LAKE_CENTERS
        +dict LAKE_RADII
        +dict ISO_LAKE_K
        +dict SLOTS
        +dict LAYOUTS
        +dict _PLAN_BOXES
        +int GRID
        +grid_of(size) int
        +world_size(villages, lakes) float
        +village_positions(hamlets, lake_index, n_lakes, size) dict
        +lake_parcels(n_lakes, seed, size) list
        +lake_distance(n_lakes, i, j, days_per_map) float
        +lake_label(name) str
        +split_villages(hamlets, n) list
        +resolve_lakes(L, hamlets, fishers) list
        +random_valley(seed) dict
    }
    class world_module {
        <<module>>
        +float TRUST_START
        +float TRUST_STEP
        +float LOYAL
        +dict DETECTION
        +dict PATROL
        +list PATROL_CAPTAINS
        +dict EVIDENCE
        +dict HOW
        +float MIN_LIE_T
        +tuple PATROL_ACTIONS
        +dict BREACH_WORD
        +float LOW_LAKE
        +float SKILL_STEP
        +dict WEATHER_WORD
        +day_word(factor) str
        +outings_text(outs) str
    }
    class World
    World "1" *-- "1..*" Lake : lakes
    World "1" *-- "1" Climate : climate
    World ..> rules : rules_for, rule_words
    World ..> lakes : construit ses lacs
    lakes ..> Lake : parcelles
    World ..> world_module : day_word, outings_text
```

**Pour aller plus loin**
`filets/lake.py:19` (`Lake`)
`filets/climate.py:54` (`Climate`)
- `filets/lakes.py:118` (`lake_parcels`)
- `filets/lakes.py:211` (`resolve_lakes`)
- `filets/lakes.py:254` (`random_valley`)
`filets/rules.py:36` (`words`)

## 13. Horloge et pilotage

`SimClock` compte le temps simulé (en jours) et sa vitesse ; `GameControl` y ajoute pause, reprise et arrêt (`StopRun` est levée à
l'arrêt). `clock.py` offre aussi trois fonctions de mise en forme du temps.

```mermaid
classDiagram
    class SimClock {
        +float rate
        +bool paused
        +float season_days
        +any base_rate
        +float speed
        +float idle_speedup
        +bool fast
        -float _now
        -any _wall0
        -float? _paused_at
        -float _paused_total
        +int in_flight
        +__init__(season_days, sim_hours_per_second, idle_speedup, fast)
        +set_speed(speed) float
        +pause() None?
        +resume() None?
        +now() float
        +local(t)
        +wall_elapsed() float
        +set(t) None?
        +advance_wall(dt_wall, next_due, busy) None?
        +label(t) str
        +text(t, year) str
        +season_of(t) int
        +season_start(season) float
    }
    class GameControl {
        +bool paused
        +bool stopping
        +SimClock clock
        -Event _run
        -Event _stop
        +CallableNone? on_change
        +__init__(clock)
        -_changed() None?
        +pause() bool
        +resume() bool
        +set_speed(speed) float
        +set_fast(fast) None?
        +request_stop() None?
        +checkpoint() bool
        +sleep(seconds) None?
        +guard(work) T
    }
    class StopRun {
    }
    class clock {
        <<module>>
        +tuple PERIODS
        +fmt_sim(t, season_days) str
        +day_words(day_f) str
        +fmt_text(t, season_days, year) str
    }
    class World
    World "1" *-- "1" SimClock : clock
    World "1" *-- "1" GameControl : ctl
    GameControl o-- SimClock : clock
    GameControl ..> StopRun : arret
    StopRun --|> Exception
    SimClock ..> clock : utilise fmt_*
```

**Pour aller plus loin**
`filets/clock.py:60` (`SimClock`)
- `filets/control.py:28` (`GameControl`)
- `filets/control.py:24` (`StopRun`)

## 14. Saison, file d'événements et veillées

À chaque saison, `World` crée un `SeasonScheduler` : une file d'événements datés (départs en mer, décisions d'agents, repousse du
lac). Le soir, une `Village` joue la veillée d'un village (ou du conseil de la vallée) jusqu'à la clôture de l'`Assembly`. Le
scheduler et les veillées ne décident rien : ils ordonnent les appels de `agents.py` (voir `classes-decisions.md`) et appliquent
leurs résultats via `World`.

```mermaid
classDiagram
    class SeasonScheduler {
        +float TICK
        +any w
        +any c
        +int season
        +any t0
        +list q
        +counter seq
        +asyncio.Future? recit
        +any last
        +__init__(w, season)
        +key(ident) float
        +at(t, ident, item) None?
        +show(t)
        +play() asyncio.Future
        +run_batch()
        +parallel(jobs) list
        +think(names, on)
        +open_season()
        +planned(a, o, h)
        +go(a, trip, nxt, now)
        +evening()
        +prepare(jobs)
        +regrowth()
    }
    class Decision {
        +str agent
        +float lag
        +Callable make
        +Callable then
    }
    class Village {
        +any s
        +any w
        +any asm
        +any t
        +int rounds
        +any duration
        +any close_t
        +dict spoken
        +dict prepared
        +bool done
        +__init__(sched, asm, ta)
        +prep_jobs() list
        +pick() str?
        +stale(aid) bool
        +redo(aid)
        +speak(aid) bool
    }
    class World
    class Assembly
    class SimClock
    class EventFactory
    World ..> SeasonScheduler : un par saison (play)
    SeasonScheduler o-- World : w
    SeasonScheduler o-- SimClock : c
    SeasonScheduler ..> Decision : file de decisions
    SeasonScheduler ..> Village : cree une par assemblee
    Village o-- SeasonScheduler : s
    Village o-- World : w
    Village o-- Assembly : asm
```

**Pour aller plus loin**
- `filets/scheduler.py:49` (`SeasonScheduler`)
- `filets/scheduler.py:41` (`Decision`)
- `filets/scheduler.py:252` (`Village`)
- `filets/world.py:3158` : une saison = un `SeasonScheduler(...).play()`
