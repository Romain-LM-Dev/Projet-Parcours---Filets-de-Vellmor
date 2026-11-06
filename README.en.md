<div align="center">

🇬🇧 English | 🇫🇷 [Français](README.md)

</div>

# FILETS — the tragedy of the commons around Lake Vellmor

*Mondes Vivants* project (5th year IABD, EIGSI Casablanca). Fishers played by free LLMs
share a lake that replenishes itself. They fish, sell, meet in the evening at the elder's house,
propose rules, make promises, accuse each other… and keep their word or not. World events
flow through **Apache Kafka**, indicators are computed as a stream, and the **Godot** scene
shows everything live.

> **First build.** The full chain works end to end. By default, the agents
> use a *fake LLM* (`scripted`) that imitates answers from noisy rules: it is meant
> for developing and testing without a key or a GPU. **No scientific result should be drawn from it**:
> switch to Ollama or a free API (`config/ollama.yaml`, `config/groq.yaml`) for real
> experiments.

```
 Python engine ──► Kafka (filets.events) ──► indicators service ─────► Kafka (filets.indicators)
  (lobby, agents,       │                                                        │
   lake, clock)         ├──► history service ───────► PostgreSQL (or SQLite)    │
    │   ▲  │            └──────────────► API FastAPI (REST + WebSocket) ◄────────┘
    │   │  └─ Kafka (filets.status : engine state) ────►│  ▲
    │   └──── Kafka (filets.commands : start, pause, speed, mode, injections) ◄───────┘
    ├─ catalog (menu)                                   Godot (menu, scene, controls, inspector)
    ├─ Ollama: Qwen (reflection), tev1 (simple decisions), embeddinggemma (embeddings)
    └─ RAG: PostgreSQL + pgvector (corpus, memories) · S3 object storage (documents, game archives)
```

To understand how the pieces talk to each other (architecture, clock, communication and memory, tokens, asynchronous
libraries, storage): [docs/architecture.md](docs/architecture.md).

## Quick start

On Windows, two scripts do everything (see `install.ps1` and `start.ps1`, or their `.cmd` launchers):

```powershell
.\install.cmd                 # once: Python 3.13, .venv, dependencies, tests, Kafka, Ollama models (3B and 1.5B; -Quality adds
                              # the 7B, -Open the tev1 decision model, -Data PostgreSQL + pgvector, S3 and embeddinggemma)
.\start.cmd                   # everything: Kafka and its services, Ollama (Qwen + tev1), PostgreSQL + pgvector and S3, Godot,
                              # the engine in lobby mode (Docker Desktop is started if needed); the game is set up in the menu
.\start.cmd -Light            # lightweight, without Docker or Ollama: the engine alone with the fake LLM
.\start.cmd -OllamaProfile quality   # "quality" Ollama (7B + 1.5B): better, but much slower
.\stop.cmd                    # shuts down the engine, the services and the containers (data is kept)
```

By hand, without Kafka:

```bash
pip install -r requirements.txt
python -m pytest -q                                  # consistency tests (Kafka and Godot tests are skipped if absent)
python -m filets serve                               # lobby + API on :8765 (WebSocket for Godot, REST: http://localhost:8765/docs)
python -m filets run --mode async --ws               # or: immediate game, without the menu
```

Open `godot/project.godot` in **Godot 4.3+** and run the scene (F5): a start menu appears
if the engine is in lobby mode. Click on a fisher to inspect them; the buttons at the bottom inject
events into the current game. Without Godot, the console is enough: every catch, speech, adopted rule
or broken promise is printed there.

## The start menu

On launch, Godot shows the **Nouvelle partie** (New game) menu as long as the engine is in lobby mode (`serve`):

| Setting | Detail |
|---|---|
| World time | a single mode: thinking takes no time (the clock waits for the AIs), acting does; the evening gathering unfolds as it goes ([docs/temps.md](docs/temps.md)) |
| Duration and randomness | number of seasons, seed (the same settings and the same seed replay the same game with the fake LLM) |
| The valley | evening gatherings (**valley council**, per village, forbidden), council (**one delegate per village** or all the fishers), **speaking rounds** per gathering (1 to 3, 2 by default; only one in asynchronous mode), catches known to all or not, the elder (present or not, AI or rules) |
| The lake | **max stock**: the stock limit, from 10 to 1000 t, or *Auto* (12.5 t per fisher, which then follows the number of fishers). It is 100 % of the gauge: the lake starts full and never exceeds it. **Replenishment**: the lake's rate `r`, from 0.1 to 2 per season (1 = normal). The menu shows what the lake renews (`r·K/4` per season) against what the boats can bring back. **Stop if the lake is empty** (checked by default) |
| Valley, lakes, patrols | **Paramétrée** (Configured: you set villages, fishers, fleet and number of lakes) or **Aléatoire** (Random: everything is drawn from the seed: villages, fishers, fleet, lakes and their fish, patrols; the die changes the valley). **Lakes**: from 1 to 4; with several, one row per lake (max stock, full share at the start, replenishment), the villages splitting into blocks. **Patrols**: from 1 to 4 (unchecked: none). **Catchable share**: the share of a lake's fish that a boat can take (50 %) |
| Seasons and randomness | **seasons of the year and events** (drought, storm, school of fish…), their frequency, and the amplitude of **luck at fishing** (0: neither luck nor bad luck, only the weather counts) |
| Patrol | **Patrouille du lac** (Lake patrol) box: checked (by default), the council can vote for a patrol whose captain, an AI, chooses its route based on shared suspicions; unchecked, there is none in the game |
| AI engine | fake test LLM, **Ollama · rapide** (fast: 3B + 1.5B, recommended), Ollama · qualité (quality: 7B + 1.5B) or Groq; the engine checks before launching (Ollama reachable, models present, API key) |
| Reflection | **Adaptative (système 1 / 2)** (Adaptive, system 1 / 2): a one-number reflex for routine catches, reflection for the rest ([details](docs/architecture.md)). **Rapide** (Fast: one short sentence, lighter context, bounded answer: about twice as fast) or **Complète** (Complete: free answers, full context: the reference profile for experiments) |
| Fishers | from 1 to 24: first name, village, archetype, **boat** (rowboat, launch, cutter), experience, savings, debt per season, "brain" (AI auto/large/small, or rules). **Générer la vallée** (Generate the valley): you choose the number of **villages** (1 to 8), of fishers and the **fleet** (small boats, mixed, large boats), the engine generates the valley from the seed, which you then touch up; it is regenerated as soon as one of these settings or the seed changes |
| Layout | a preview of the valley, villages placed around the lake: you drag a fisher from one village to another; **Composition de base** (Base composition) restores the valley proposed by the engine, all set to "IA auto" (AI auto) |
| Speed | starting speed (× 1/16 to × 16, or maximum) |

**Lake stock limit.** The setting fixes the capacity `K` of the logistic model: the stock starts at `K` (`lake.initial_ratio = 1`) and
never exceeds it, and the gauge, `stock_ratio` and all percentages refer to it. A small lake is depleted quickly with many
fishers; a large one barely feels the fishing. The collapse threshold (`lake.collapse_ratio`, 5 % of `K`) stays in the
YAML configuration.

**Replenishment rate.** `r` is the rate of logistic growth, applied once per season: `stock + r × stock × (1 − stock/K)`.
The lake recovers fastest when half full, where it regains `r·K/4` (the maximum sustainable yield, shown in the menu). With `r = 0.3`
overfishing is paid for over many seasons; with `r = 2` the lake refills almost in one season (beyond that, the logistic
sequence oscillates, hence the limit). `lake.growth_rate` in the YAML, `lake.growth_rate` in the menu request.

**Game over when the lake is empty.** A lake that has dropped to 0 never replenishes (growth starts from the stock). As soon as it falls below
50 kg (`lake.EXTINCT_BELOW`, it shows "0.0 t"), the game stops **immediately**, even mid-season, with the reason
`extinction` (`run_end`, end screen "Le lac est à sec" (The lake has run dry), banner and "LAC À SEC" line in the feed). The menu box, or
`run.stop_on_extinction: false` in the YAML (`--set run.stop_on_extinction=false`), lets you continue anyway. Different from
`run.stop_on_collapse` (lake below 5 %, stop at the end of the season, disabled by default): a collapsed lake can still recover.

**A fisher's brain** ("Cerveau" column, and the elder's setting) says who decides their catch and their speech:

| Brain | What decides |
|---|---|
| **IA · auto** (AI · auto) | a language model; the engine chooses its size from **experience**: large model from 15 years of fishing (`population.large_model_min_experience`), small below, never from a social category (A5) |
| **IA · grand** / **IA · petit** (AI · large / small) | a language model, of the imposed size |
| **Règles** (Rules) | no AI: a fixed rule specific to the archetype (`filets/policies.py`), the same for a given situation |

With "rapide" Ollama, "large" is `qwen2.5:3b` and "small" `qwen2.5:1.5b` (with "qualité": `qwen2.5:7b` and `qwen2.5:1.5b`);
with the fake test LLM, the large one is simply more reliable (less noise) and slower than the small one. An "AI" fisher whose model does not answer, or answers in an unusable way,
plays their rule instead (`règle de repli` incident, fallback rule). Rule-based agents serve as a control (A6): they separate the "AI" effect from the "profile" effect.

Changing a fisher's archetype resets the typical values of that archetype (experience, savings, debt), which can always be modified afterwards.
As long as the max stock has not been set by hand, the lake's capacity follows the number of fishers (12.5 t each). The engine validates the
request; if it is refused (Ollama off, missing key…), the menu stays open with the message.

## Controlling the game

A bar above the map controls the current game (**Space** key to pause):

* **Pause / Resume**: the world freezes completely (simulated time, AI calls, events). A call already sent whose answer
  arrives during the pause waits for the resume. Pause time is not counted in `processed_at`.
* **Speed** × 1/16 … × 16, or **Max** (no display wait). In asynchronous mode, speed also changes the weight of the AIs' reflection
  in world time: it is a parameter of the time model (C5), recorded in the log by an `injection` event.
  **The faster you go, the slower the AI seems**: the world moves on while it thinks, and the gathering can close without it.
  When this happens (asynchronous, real AI, speed above what the AI engine can keep up with), an orange button
  **Ralentir (× ¼)** (Slow down) appears; a counter shows the speeches and outings lost since the start of the season. If, even at the
  recommended speed, at least two are lost in the season, the button offers the next speed down.
* **Reflection**: a "…" bubble hovers over each agent with a decision in progress, and the top bar shows "N en réflexion" (N thinking); the clock waits.
  Each `season_start` carries the mode in which the season is played.
* **Arrêter la partie** (Stop the game, two clicks): immediate, even while an AI is thinking; the run is closed with the reason `stop`.
  An end screen then offers **Nouvelle partie** (New game).

## With Kafka (reference configuration)

```powershell
.\start.cmd -Ui                                      # broker, 3 services (separate windows), Godot, engine in lobby mode
```

or by hand:

```bash
docker compose up -d                                 # KRaft broker on 127.0.0.1:19092
python -m filets.services.indicators                 # terminal 1: streaming indicators
python -m filets.services.store                      # terminal 2: history (SQLite; PostgreSQL with --config config/data.yaml)
python -m filets.services.bridge                     # terminal 3: FastAPI API (ws://localhost:8765/ws for Godot, REST on /api)
python -m filets serve --bus kafka                   # terminal 4: the engine in lobby mode (or: run --bus kafka)
```

`docker compose --profile ui up -d` adds Kafka UI on http://localhost:8080 to look at the topics.
The topics are `filets.events`, `filets.indicators`, `filets.commands`, `filets.deadletter` and `filets.status`
(the engine state, kept for one hour).

**Start in any order.** The indicator services and the bridge position themselves on the last
`run_start` of the topic: started before, during or after the simulation, they rebuild the current run and arrive
at the same figures. The engine only announces its lobby (`idle`) once its command consumer is ready, so
a "Start" clicked too early is not lost.

## Commands

| Command | Role |
|---|---|
| `python -m filets serve [--bus local\|kafka] [--mode …] [--agents N] [--seasons S] [--llm ollama] [--no-ws]` | **lobby**: waits for `start_game` from the Godot menu, plays the game, then another; `--mode/--agents/--seasons/--llm` set the values offered by the menu |
| `python -m filets run [--agents N] [--mode sync\|async] [--seasons S] [--config …] [--set clé=valeur]` | starts a run right away, saves it in `runs/<id>/` |
| `python -m filets replay <id> [--speed 4] [--ws]` | replays a run **without any LLM call**, recomputes and compares the indicators |
| `python -m filets verify <id>` | schemas, ordering, monotonicity of simulated time, temporal violations |
| `python -m filets batch --config A.yaml --config B.yaml --runs 5` | repeated runs (successive seeds), mean ± standard deviation table, SQLite archiving |
| `python -m filets query [analysis/queries.sql]` | reproducible queries on the history; `query analysis/queries_pg.sql --pg` on PostgreSQL |
| `python -m filets retrieval <id> --sample 20` | sample of decisions and of what was retrieved, to annotate (F2) |
| `python -m filets ingest [--pg]` | imports the saved runs into SQLite, or into PostgreSQL (`--pg`) |
| `python -m filets schemas` | exports the event schemas into `schemas/` |

**Two base valleys.** `config/default.yaml`: four villages of two fishers (8). `config/large.yaml`: the same four
villages with four or five fishers each (18, a 225 t lake, the same stock per head): one delegate speaks there for three or four neighbors.
`python -m filets serve --config config/large.yaml`, or `.\start.cmd -Config config/large.yaml` (with `-Ollama` for a local AI).

Examples: `--set scenario.communication=hamlet`, `--set scenario.catches_visible=false`,
`--set population.rule_fraction=0.5`, `--set time.sim_hours_per_second=1`.

## Choosing your models (all free)

Two levels, `grand` and `petit` (large and small), assigned according to the profile's **fishing experience**
(`large_model_min_experience`, 15 years by default), never according to a social category (A5).

```bash
ollama pull qwen2.5:3b && ollama pull qwen2.5:1.5b          # fast setting (recommended on 6 GB of graphics memory)
python -m filets run --config config/ollama_fast.yaml --agents 6
ollama pull qwen2.5:7b                                      # quality setting: better, much slower
python -m filets run --config config/ollama.yaml --agents 6
```

From the start menu, choosing "Ollama · rapide" (or "qualité") is enough. Before launching, the engine checks that the server
answers and that the models **actually used by the game** are installed (a fisher with a "small" AI does not require the large
model; an elder with an AI does), then loads them into memory so that the first season does not start with calls waiting for
loading. The timeout of an Ollama call is 240 s (`llm.providers.ollama`). The recorded `latency_s` counts the whole wait;
it is the time the agent spent thinking.

**Why the AIs' reflections slowed the game down, and what changed.** On a 6 GB card, Ollama serves **one request at a
time** and does not keep two large models in memory:

* *Model swaps.* Alternating 7B and 1.5B costs about thirty seconds at each switch from one to the other. The
  "rapide" setting uses a large model of 3B that **fits alongside the 1.5B** on the card: no more swaps. In addition, a
  queue (`ModelGate`, in `filets/llm.py`) serves all the requests of one model before moving on to the other, instead of following
  the order of arrival (at most 24 in a row, so that nobody waits indefinitely).
* *Answer length.* A 7B produces about 17 tokens per second, a 3B about sixty, a 1.5B about a hundred: generation
  costs more than reading the prompt. **Fast reflection** (`llm.reflection: rapide`) asks for one short sentence per field, lightens
  the context (last 8 catches, 4 memories, 2 documents, last 8 speeches) and bounds the answer (110 tokens for a catch,
  150 for a speech, against 350). `complete` remains the reference profile for experiments: use it for measurements.
* *Slow AIs make nothing get lost.* A decision is instantaneous in the world: the world waits for it (the engine state says who
  is thinking, `thinking`), no outing, speech or ballot is lost because of slowness any more. The `missed_window` incident
  only remains in old logs. The faster you go, the slower the AI seems, on screen only.

**On a laptop, the graphics card heats up.** A long game with Ollama keeps it at 100 %: around 88 °C the frequency drops
(measured: from 2100 MHz to 210–580 MHz) and each answer takes 5 to 10 times longer than when cold. The AIs then seem "slow"
without anything being broken: plugging in the power, raising the back of the laptop, or slowing down the world (asynchronous) makes more difference than
any game setting. `nvidia-smi --query-gpu=temperature.gpu,clocks.sm --format=csv` shows the state of the card.

Ollama server settings (environment variables, not applied by the game): `OLLAMA_FLASH_ATTENTION=1` and
`OLLAMA_KV_CACHE_TYPE=q8_0` reduce context memory; `OLLAMA_NUM_PARALLEL=1` is already the safest value on 6 GB.

**An open decision model alongside Qwen ("Ollama · rapide + réflexes open", `config/ollama_open.yaml`).** Simple choices
(a routine catch, a ballot) do not need a text: `tev1:0.8b` (Together AI, fine-tuned from Qwen 3.5,
0.8 GB) answers them through a typed question on Ollama's `POST /v1/systemone`, in one or two tokens with the probabilities of each
answer. Qwen keeps reflection and speech. It requires **Ollama 0.40.4 or later** (`winget upgrade Ollama.Ollama`, with Ollama
closed) then `ollama pull tev1:0.8b`; without it, the game still launches and these decisions go through Qwen 1.5B. Details:
[docs/architecture.md § 4](docs/architecture.md#4-économie-de-tokens--système-1-et-système-2).
tev1 also catches an outing to which the large model did not answer in time (or answered illegibly) and judges trust at the debrief
of an absent fisher; it never writes (speech, non-routine catch and narration stay with Qwen 3B).
*Comparison bench* (to run once the game is over; it refuses if port 8765 answers): `python -m filets bench-reflexe <run_id> [--limit N]`
replays the prompts recorded in `runs/<id>/s1_calls.jsonl` (games launched with `ollama_open`) on tev1 and on the 3B, and
shows the agreement of the decisions (same vote, same choice, catch within ±0.5 t), the illegible answers and the time of each.

For an API (Groq, OpenRouter `:free`, Gemini, Mistral, GitHub Models): copy `.env.example` to
`.env`, export the key, and adapt `config/groq.yaml`. All these offers speak the OpenAI format;
a single client handles rate limiting, retries on 429 and token counting. Check quotas and model
names when the project starts: they change often, and some free offers reuse
the data sent.

## The world

A **season** lasts 30 simulated days, and it is a season of the year (spring, summer, autumn, winter, in that order: the game
starts in spring):

| Moment | What happens |
|---|---|
| before D0 | each village chooses its **delegate**; the captain of the **lake patrol** (an AI) chooses its route, if the council has voted for one |
| D0 06:00 | fishing opens: each fisher estimates the stock (±10 %) and decides on their **target catch**; what they really bring back depends on each day's weather, their luck, the season and events |
| D20 | closing: a decision still in progress is abandoned and the outing is lost (`missed_window`, "sortie perdue", lost outing) |
| D25 18:00 | evening gathering at the elder's: the **valley council** (the elder and the delegate of each village), gatherings per village, or none; 1 to 3 speaking rounds in turn (synchronous) or one speech from each, on their own (asynchronous); a speech not ready at closing is a "lost speech" |
| D29 | end of the gathering: a proposal supported by **at least half of those present at the council** becomes a rule for the next season |
| D29 21:36 | logistic replenishment (according to the season of the year and events), review, promises kept or broken |

**Time, spelled out.** Simulated time remains a number of days (it orders events and bounds what each knew at
a given moment), but what the agents read is text, and each event carries it (`sim_text`, next to `sim_label` and `sim_time`):
"saison 2 (été), jour 25, le soir (18 h)" (season 2 (summer), day 25, in the evening (6 pm)) (`World.when`; the season of the year only with the climate). Each prompt begins with
where things stand, what the season is doing at that moment ("fishing is open, 16 more days", "evening gathering at the elder's") and the
calendar of a season (when fishing closes, when the gathering takes place); memories ("[season 1, day 29, at night (0 h)]") and
lake tracking ("season 1, day 0 (fishing opens) ≈ 103 t") state their date the same way.

Lake: capacity `12.5 t × number of fishers` (same stock per head when changing scale) or limit chosen in the menu,
logistic growth at rate `r` (1 by default, adjustable in the menu), maximum sustainable yield `r·K/4` per season, reached when
the lake is brought back to half its capacity.

**Economy and boats.** 100 écus per tonne, 100 écus of living costs per season, plus boat maintenance, and 120 écus of debt
for newcomers. Three boat sizes (`economy.boats`):

| boat | maximum catch per season | maintenance per season | total with living costs |
|---|---|---|---|
| rowboat | 4 t | 20 écus | 120 écus |
| launch | 7 t | 50 écus | 150 écus |
| cutter | 11 t | 110 écus | 210 écus |

**What the lake lets you take.** A fisher's catch exceeds neither their boat's hold nor their share of the **fish there is** in their
lake at the opening of the season: at most `economy.hold_fraction` (half) of the stock, shared among the boats of the lake **in proportion
to their hold** (`World.hold_of`). A full lake gives each their share of the half (6.25 t for a launch when eight launches share
100 t); a half-empty lake, half of that; a cutter takes more than a rowboat, and the more boats there are on a lake,
the less each one gets. The prompt tells the fisher ("you can aim from 1 to X t", based on what they think they see of the lake); the lake itself decides when
the boat returns (a fisher who underestimates or overestimates the lake finds out). This share therefore drops with the fish: a lake being
emptied lets you take less and less (with `hold_fraction: 1`, all the fish is within reach). A rule applies per fisher, whatever
the size of their boat: the large boat costs more and is more tempting. Character influences the
boat (the indebted newcomer borrowed for a rowboat, the old family has the biggest one).

**Fishing is not always good.** The fisher decides on a **target catch** for the season; it is spread over
`economy.outings` outings (6), distributed over the fishing window (the first one leaves on a day specific to each), and **each outing yields
according to its day**: the **day's weather**, the **fisher's luck**, the season of the year and events, their experience (±0.5 % per
year of difference from 15 years) and the difficulty of a low lake (below 30 % of capacity, fish are harder to catch). An outing does not exceed
its share of the hold, so that a season of good days does not quite make up for a season of storms.

* **The weather** (`Climate.calendar`, `World.weather`) is drawn for each season, day by day, and is **the same for the whole lake**: calm,
  ordinary, rough or stormy, with a probability that depends on the season of the year (winter is the season of heavy weather) and some
  inertia (yesterday's weather carries on nearly one time in two). A bad day weighs more on a rowboat than on a cutter
  (`BAD_DAY_BOATS`); a good day benefits everyone. The interface shows it (bottom bar, feed at the start of each season).
* **Luck** is specific to each fisher: their form of the season (`economy.luck_streak`: it **carries on from one season to the next**,
  a good spell heralds another) and their form of the day (which carries on from one outing to the next) make each outing vary around 1, with a
  standard deviation of `economy.luck` (0.4). Two fishers under the same sky therefore do not get the same catch. Everything is drawn for this fisher and this
  season: the result does not depend on the order in which the boats come back.
* In the `catch` event: `requested`, `landed`, `yield` and `luck` (season averages) and `outings` (for each outing: `day`,
  `weather`, `luck`, `yield`, `tonnes`). `economy.luck: 0` removes luck, experience and the difficulty of a low lake: only the weather remains.

A fisher tells their season in their memory ("Over 6 outings: 2 in calm weather, 3 in ordinary weather, 1 in the storm. I was aiming
for 4 t: a bad catch"). The declaration to the elder keeps the same proportion of the real catch: whoever declares everything stays honest, whatever
their season. The lake patrol measures a fisher with a probability proportional to the share of their outings during which it was
in their zone.

**Seasons of the year and events** (`climate.py`, `climate` setting). Each season carries two factors: what fishing yields and
the lake's replenishment speed.

| season | fishing | replenishment |
|---|---|---|
| spring | × 1.00 | × 1.3 |
| summer | × 1.15 | × 1.1 |
| autumn | × 1.00 | × 0.9 |
| winter | × 0.75 | × 0.7 |

From the 2nd season, an event occurs with probability `climate.event_rate` (0.3): **drought** (2 seasons: replenishment × 0.6 and the
stock loses 10 % at once), **storm** (heavy weather becomes much more frequent: fishing yields about × 0.65, much less for small rowboats,
see above), **school of fish** (× 1.35), **algae** (2 seasons: replenishment × 0.5), **flood** (replenishment × 1.25, fishing × 0.85) and **fish
disease** (the stock loses 20 %). They are drawn from a separate random source (`world_event`, `season_start.conditions`); the agents know the season
of the year and the ongoing events. Averaged over the year, the seasons do not change replenishment (× 1.0).

**A generated valley** (procedural generation, `profiles.build_population`). The engine draws the valley from its parameters and the
seed: `population.villages` (1 to 8), `population.fishers`, `population.boat_mix` (the share of
rowboats, launches and cutters; the menu offers three, `catalog.FLEETS`); same parameters, same valley. Villages are taken in
the order of `profiles.VILLAGE_NAMES` (Ostrel, Bramois, Tilque, Hennad, then Varenne, Corbel, Mirande, Sauvet, Lormes, Quéran, Brevelle, Dunac),
fishers are distributed to within one (never more villages than fishers), characters in a cycle, experience, savings and boats drawn,
first names taken from 48. **Each fisher has their own sequence of draws** (`<graine>|fisher|<i>`): adding a fisher does not change any other
profile, and changing the number of villages only moves people. **The seed decides the setup**: in what order the villages
receive their fishers and in what order the characters follow one another, so who lives where changes from one seed to another. The lake has one zone per
village (its shore) and the open water. On the command line: `python -m filets run --agents 14 --villages 6`. In the menu, **changing the number of
villages or fishers, the fleet or the seed** (or clicking **Générer la vallée**) sends `generate_world` to the engine, which answers with a catalog in which only the
valley changes; the player then touches up each profile. The two numbers follow the list (adding or removing a fisher updates them), there is
always at least one fisher per village, and a refusal from the engine is shown in the menu.
The engine places the villages around their lake (the four corners for the base valley, then the sides; with several lakes, on the
outer shore of each, never in the water nor against the elder's house) and the Godot map takes them over (`run_start.map`).

**The world in grids.** The valley (the square of ground) is divided into three grids, each suited to what it carries:

* **lakes: 30 × 30 plots** (`lakes.GRID`). Each lake is a patch of plots drawn from the seed around its center, with a
  wavy edge: it looks like a lake, and two lakes requested make two. Each plot has **its own fish** (more in the deep than at the edge) and
  **its own luck** (better or worse spots, 1 on average over the lake). A boat fishes **around its plot**: it empties the
  fish there first, then that of the neighboring plots. Replenishment of the whole lake does not change (the same logistic); it goes to the plots according to
  what they lack, and part of the fish returns to its spots. The yield of an outing counts the plot's luck and what past
  seasons have left there (at the opening of the season: the order of returns changes nothing). **Each fisher chooses their spot**
  on the shore of their village, based on their own experience: a spot near home the first time, they keep it if it yielded
  like the lake, otherwise they go to the best spot they know or try a new one; they remember it ("My fishing spot gave
  little"). In secret or in another lake, they fish in open water, on a deep plot. Events: `catch.cell`, `catch.spot`,
  `run_start.lakes[].cells`, `lake_cells` (the fish of each plot after replenishment);
* **houses: 24 × 24 lots**, one house per lot around the square of its village, and it is **an obstacle**;
* **characters: 120 × 120 steps**, much finer: they slip between houses and go around the water (pathfinding
  on the grid); boats only go on water, to the plot the engine gave them. Dirt paths follow the
  same steps.

On the map, **G** shows the three grids (houses in red, the luck of the plots from green to red).

Population (cycle of the sheet's four archetypes, distributed among the villages):
cautious old family, indebted newcomer, silent one who hauls in their nets in secret, smooth
talker who fishes little; plus **the elder**, an arbiter without power. A share `rule_fraction` of the
fishers (drawn at random) follows fixed rules (A6).

The start menu offers the valley generated by the engine for its default parameters (same first names, villages, archetypes,
experience, savings and boats), but all set to "IA auto": it is up to the player to switch some to "Règles". Launched from the command
line (`run`), the engine keeps its 25 % of rule-based agents. The menu lets you modify the composition:
the chosen list is passed to the engine (`population.custom`, one profile per
fisher: first name, village, archetype, boat, experience, savings, debt, brain). It then replaces generation;
the number of fishers, the lake's capacity and the share of rule-based agents are deduced from it, and everything is saved in
`runs/<id>/config.json` (the game remains reproducible).

## The AIs see the lake

Observation from real games: the lake went from 100 % to 0 % and the AI fishers still asked for 5 to 7 t each (the average
catch did not depend on the stock), saying "the lake seems well stocked" with a stock of 0 t. The stock was only one line among
ten in the context, with no reference point or trend, and old speeches from the gathering contradicted it. What each decision
now receives (`prompts.py`, `world.observe`):

* **The state of the lake, at the top of the context**: tonnes, percentage of capacity and level in words (full, well stocked, about
  half full, low, very low, almost empty, **empty: there is no fish left**), measured against half the capacity where the
  lake replenishes best (the elders' knowledge also appears in the world text).
* **What the agent has observed so far**: the sequence of ITS own estimates (opening of each fishing season, each gathering) and the
  trend ("it has dropped a lot", "it stays empty"). Nothing invented nor from the future (C6); each figure is linked to the decision
  that carried it (`used_event_ids`).
* **A reminder just before the question** (small models mostly read the end): the lake level, then, when it is no longer enough
  to fill all the boats, the resulting split ("there are 8 of you fishers, 40 t remain: if each took 5, there would be
  none left at all"), then the elders' reference point in tonnes ("there are 0 tonnes above half the lake (50 t)"). Without this
  last line, small models read "half, 50 tonnes" as a catch quota.
* **Dated memories**: a speech from the gathering two seasons ago no longer passes for today's state of the lake.
* **A constrained answer**: with Ollama, the answer is imposed by a JSON schema (`llm.providers.ollama.json_schema`), the
  justification (what the agent observes of the lake and concludes from it) BEFORE the catch, so that the number is written following this
  reasoning. Without this, small models often forgot the "catch" field and the decision fell back on the fallback rule, which
  takes the stock into account: fallback decisions (`decision.fallback`) must always be counted when measuring the effect of a prompt.
* **Rule-based agents never ask for more than the lake they see**, but **an outing always yields at least `economy.min_catch` (1 t)**: you never come back empty-handed. An AI that asks for less is brought back to this minimum (`invalid_value` incident), and a quota or a promise below this minimum is worth this minimum.

## Voting on rules

Before, no rule was ever adopted: three gatherings had produced 41 proposals (7.0; 7.3; 7.4; 7.5; 4.2; 4.3…), the votes
scattered. Now, two quotas less than `scenario.proposal_merge_tolerance` (0.75 t) apart are the same proposal, and at closing a
**vote** counts what each one said: whoever supported no proposal votes for the one closest to their proposed or promised quota, within
`scenario.vote_tolerance` (1.5 t); whoever said nothing with a figure abstains. Each vote is a `support` event. A proposal
supported by at least half of the fishers present (4 out of 8) becomes a rule.

**The ballot.** Many AI fishers state no figure and support nothing: they abstained, and proposals
missed the threshold by one vote. Before closing, each AI fisher who has supported nothing therefore fills in a **ballot**: a
question of a few lines (the proposals, their supporters, the state of the lake), asked to the small model, whose answer is constrained
to the identifier of a proposal or "none" (10 tokens at most, `llm_call` of kind `vote`, system 1). In asynchronous mode the
ballots are filled in 6 h before the end of the gathering (`time.ballot_lead_days`): an AI that is too slow loses its vote, like its speech.
With the fake LLM, which cannot answer a ballot, what each one said is counted.

Measured with Ollama (3B + 1.5B, 8 fishers, 6 seasons): three rules of 1.5 t adopted (7, 7 then 8 fishers out of 8, 88 % agreement), where
there were none. But compliance remains low (12 to 25 % of fishers respect the rule they voted for): people vote 1.5 t and
fish 4 to 10 t, the gap between what is said and what is done that the game studies; the lake was depleted in season 6 and the game
stopped ("the lake has run dry").

To tighten behaviors (one fished 0 t, the other 10 t at the same moment), each fisher also receives a summary of what the
others declared last season ("between 2 and 6 t, 4.0 t for the middle fisher"), and the adopted rules serve as a common reference point.

**Types of rules.** In addition to the quota (tonnes per fisher and per season), the council can adopt a **reserve** (the shore of a village
or the open water of a lake are forbidden, for a few seasons; whoever respects it fishes elsewhere), the **rest** of a lake (closed for one or more
seasons; people stay at the dock or go fishing in another lake), a **limit on outings** (at most N outings per season) or a **maximum boat
size** (the biggest ones only take the permitted hold). Each agent chooses the type according to the situation (low lake, overfished spot,
large boats, catches that exceed); whether to respect it or not remains their choice: their AI, or the character of a rule-based agent (the silent one cheats,
the cautious family respects it). Two proposals only merge if they are of the same type and the same target. A violation is seen by the
patrol and the witnesses, and the player reads it in the feed ("règle enfreinte", rule broken). On the map, buoys and hatching mark a
reserve, "au repos" (resting) a closed lake. Events: `proposal` and `norm_adopted` carry `kind`, `value`, `target`, `text` (+ `duration`,
`until_season`); `catch.breach` signals the violation.

## Secret catches, declarations and trust

**Only the fisher and the player know the real catch.** On returning, each fisher **declares** their catch to the elder
(`report` event: `declared`, and `landed`, the real one). The others only know the declaration: that is what appears in
their decisions, and in the valley's judgment (the external narrator of the end-of-season story, however, knows the real catch). An AI decides on its declaration in the same call as its
catch (`declaration` field, no extra token); a reflex declares the truth; among rule-based agents, the silent one declares the
rule when fishing beyond it (unless one of their lies has just come out). `scenario.catches_visible` says whether the declarations are
read to the whole valley or only to the hamlet (menu: "Les déclarations à l'ancien sont lues à toute la vallée", declarations to the elder are read to the whole valley).

**A lie is discovered from clues, not by chance.** The lake has one zone per village (its shore, where its fishers usually
go) and the open water. On the evening of the gathering, the season's clues are gathered (`clue` events, settings
`scenario.detection`):

* **the lake patrol**, if the council has voted for one (see below): its captain, an AI, decides where to go based on shared suspicions; it crosses the boats of the zone where it is and measures their load (within ±12 %);
* **the neighbors** fishing in the same zone see a boat come back (40 %) and estimate its load (within ±30 %);
* **a banned fisher's boat** is seen leaving at dawn by their hamlet (30 %);
* **lifestyle**: declaring less than needed to live, and yet living as before, gets noticed (50 %);
* **the lake's accounts**: the elder measures what fishing has made it lose (within ±3 % of capacity) and compares it to the total
  declared (`lake_audit`).

Whoever has nothing to reproach themselves for says in front of everyone what they saw, except against a friend (trust of 0.8 and above); **whoever cheated keeps quiet**
(their clue stays with them, in their notebook). From the opening of the gathering, the elder **reports what the clues establish**: they
weigh those that were said in front of everyone (patrol 3, witness 1, departure seen 1, lifestyle 0.5, accounts 0.5 if they do not add up).
The lie is **established** (`lie_discovered`) when this weight reaches 2 and the estimated load exceeds the declaration by more than
25 % (and by at least 0.3 t); for a banned fisher, any proven outing is an offense. The valley retains the estimate from the clues, not
the truth; and since only the clues count, the elder can be wrong: the feed writes it `ACCUSÉ À TORT` (wrongly accused, seen by you alone). The elder
reports, they do not punish: the AIs read these facts ("Indices et soupçons dans la vallée", clues and suspicions in the valley), judge, accuse, and propose
exclusion if they want.

**Trust: each one judges it.** Each agent (fishers and elder) has a trust toward each fisher, from 0 to 1, at 0.5 at the
start. The engine does not set it: at the gathering, **each agent says themselves what what they have learned about each one changes for them**,
according to their morals and interests (from −3 to +3, in steps of 0.1). An AI says it in its speech (`confiance` field: `{"F02": -2}`),
after reading the facts reported by the elder (declarations, clues, established lies, the fate of promises) and what is said that
evening, each speech preceded by the trust it places in the one who says it. A rule-based agent judges according to their character
(`policies.trust_rule`):

| what they learn about a fisher | old family | newcomer | silent one | smooth talker |
|---|---|---|---|---|
| exceeds the rule a little / a lot (admitted) | −0.1 / −0.2 | 0 / −0.1 | 0 | −0.1 |
| keeps the rule | +0.1 | 0 | 0 | +0.1 |
| established lie / caught fishing in secret | −0.3 / −0.3 | −0.2 / −0.1 | −0.1 / 0 | −0.3 / −0.2 |
| broken / kept promise | −0.2 / +0.1 | −0.1 / +0.1 | 0 | −0.3 / +0.2 |
| accuses me | −0.1 | −0.3 | −0.3 | −0.2 |
| testified against a cheater | +0.1 | 0 | −0.1 | +0.1 |
| banned, stayed away (nobody saw them out) | +0.1 | +0.2 | +0.1 | +0.1 |

The old family cares about the rule; the indebted newcomer forgives those who fish to live but not those who accuse them; the
silent one hardly judges others, but resents those who denounce; the smooth talker cares about one's given word. For all, an admitted
overrun is forgiven more easily than an established lie. Each judgment is a `trust` event (who judges, `by`, by how much, `delta`, the
resulting trust and the **reputation**, the average of the others' trust).

**A judgment that depends on everything that matters, and not always the same.** This table is only the starting point of a rule-based agent
(`policies.trust_rule` with its context, `World.trust_facts` and `World.trust_context`). The judgment also weighs: the **seriousness** of a
lie (the gap between what the clues estimate and what was declared); **neighborliness** (a neighbor is forgiven more, depending on the
character); **luck** (a catch that exceeds the rule by what luck explains, `economy.luck`, or a school of fish, is not
a challenge to the rule: without this, luck would punish the honest, and the liars, who declare exactly the rule, would seem the
wisest); their **debts** (whoever owes money understands those who fish to live) and their **own cheating** (whoever cheated forgives); what they
**already** thought of the fisher (the more one had, the more one loses; one gains less and less, and never beyond 90 % through
obedience alone, otherwise everyone ends up at 100 %); what **is said about them in the valley** (reputation, with a weight specific to each
character); and their **temperament**, drawn once per agent (`Agent.temper`, from 0.85 to 1.15: more severe or more lenient). The result
is a real number, **rounded by the agent's own randomness**: the same news does not always change trust by the same number of tenths.
"Testified" only counts for a testimony that contradicts someone's declaration, not for a reading that confirms it. The AIs
receive the same elements in their context (the fishing weather and the dispersion due to luck, their neighbors, what the valley
thinks of the others, their finances) and judge on their own.

**Trust guides reactions.** The AIs read it in their **notebook** ("Your trust in the others: Loïc low,
Théo high; the others, medium", and their own reputation) and before each speech at the gathering. A witness does not denounce in front of
everyone someone they trust completely (0.8 and above); a rule-based agent does not support the proposal of someone they no longer
believe; the patrol captain goes where shared suspicions lead.

**Excluding from fishing, or re-authorizing: the valley votes.** At the gathering, a fisher can propose to **ban another from fishing**
(`exclure` field) or to **let a banned fisher fish again** (`reautoriser`), according to their trust, their interests and their morals
(`sanction_proposal`). The other fishers present (except the one targeted) vote: the AIs through a ballot ("yes" or "no",
with their trust in them and what they know about them), rule-based agents according to their character (`sanction_vote`). With at
least half of the votes, the decision takes effect from the next season (`sanction_result`, `ban`). The elder reports the facts and
the accounts; they neither propose nor vote on a sanction.

**Banned from fishing.** A banned fisher no longer declares anything: they stay at the dock, or **fish in secret**, far from their shore, preferably in open water
(their catch is marked `secret` in the log). Caught, they lose further trust from those who judge them; having stayed away, they can
regain it, until someone proposes to re-authorize them. Their AI always decides in reflection (system 2): stay at the dock or
risk fishing in secret. Each one's catch question reminds them what each choice costs: exceeding the rule means exposing oneself to the
judgment of others and to an exclusion proposal; an admitted overrun is forgiven more easily than a discovered lie.
On a well-stocked lake, the elders' reference point reminds them that above half the lake hardly replenishes any more and that one can
fish this surplus without harming it (the valley voted 2 t each for 6 t of surplus per fisher).

In Godot, the **Confiance** (Trust) tab shows one gauge per fisher (their reputation), whether they are banned, their last catch and their
declaration (in red "ment" (lies) if they declared less than they fished, which only you know) and their lies **established** by the elder from clues (the elder can be wrong); on the map, the patrol sails from zone to zone, a golden star marks the village delegates, a crossed red ring marks the
banned and the boats are the size of their hold; the feed writes `MENSONGE` and `EN CACHETTE` (seen by you alone), `INDICE` (or `INDICE GARDÉ`), `COMPTES`,
`MENSONGE ÉTABLI`, `PRIS EN CACHETTE`, `ACCUSÉ À TORT`, `CONFIANCE` (a marked judgment, of at least 0.2), `EXCLUSION` and
`RÉAUTORISATION` (a proposal), `VOTE`, `INTERDIT DE PÊCHE`, `RÉAUTORISÉ`, `ÉLU`, `CONSEIL`, `PATROUILLE` and `ÉVÉNEMENT`; fishing
says when the day was not ordinary ("visait 4 t : mauvaise journée", was aiming for 4 t: bad day); the *Agent* tab lists their catches
("S2 5.5 t (déclaré 4.0)", declared 4.0) and who distrusts them.

## The valley council

At the valley council, **each village is represented by a delegate** (`scenario.council: delegates`, by default; `all` opens the
session to all fishers). Ordinary villagers no longer attend: only the delegates and the elder speak and vote. A rule, an
exclusion or the patrol passes with at least half of the delegates present (the one an exclusion targets does not vote).

**Each one chooses their delegate through their own reflection**, never through an engine threshold. Before each season, each fisher of a village votes
for the one among their own (themselves included) whom they judge most fit to speak and vote for all: an AI answers a **ballot** of a few
lines (system 1; it sees its trust in each candidate, their experience, what it knows about them, its situation); a rule-based agent votes
according to its rule (the one among the others it trusts most, on a tie the most experienced). The engine counts (`election`: `ballots`,
`votes`); on a tie, the average trust, the outgoing delegate, experience. A fisher banned from fishing cannot be elected: an unmasked liar does not
keep their village's seat.

**Those who are not there still judge.** At the next resumption, each absent villager receives from the elder the decisions of the council
and what the valley knows about each fisher, and says themselves what this changes for their trust (from −3 to +3, as at the gathering): an AI through
a small call, a rule-based agent according to its character. A delegate is the **spokesperson** of their village: their context reminds them of each of
their own (character, boat, what they need to live). They remain themselves: their way of being colors what they report, and that is intended. Result on tokens: the gathering now only makes 4 to 9 people speak, instead of everyone.

## Lakes, random valley

**Several lakes.** `lake.count` (1 to 4) or `lake.lakes` (a list: name, `capacity` in tonnes or `"auto"` with `richness`, starting `stock_ratio`,
`growth_rate`, `villages`). Each village fishes in the lake on its shore: its boats only take from there, each lake replenishes
at its own pace (`lake_update.lakes`, `catch.lake`), and each one's prompt talks about **their** lake (its name, its fish, the elders'
reference point for its fishers) and names the others. The game only stops (extinction, collapse) when **all** the lakes are
empty (or collapsed). The "open water" of each lake is a fishing zone (`large-Orsane`), where a banned fisher goes out in secret; the
map places up to four lakes with their villages around them, one gauge each. `config/lakes.yaml` gives three.

**A favorite lake, and others if there are good reasons.** A fisher usually fishes in their village's lake, but nothing
forces them to: each season, before their catch, they can choose another lake (`lac` field of an AI's answer, stated **before** the number;
`policies.lake_choice_rule` for a rule-based agent, the fake LLM doing the same). Their prompt shows them the other lakes: what they believe of them
from here (with twice as much error as for their own), the route, what it would leave them in catch and what it would cost them, and what
the lake would let them aim for over there. **The route is a constraint, which the engine applies**: a lake is at a distance from the other
(`lakes.LAKE_CENTERS`, `economy.travel_days` days to cross the map, 1.5 by default, one way); each outing then lasts
1 + 2 × route days instead of one, so they only bring back `1 / (1 + 2 × route)` of what the same outing would yield at home (47 % for
a route of 0.6 day); and the route costs `economy.travel_cost` écus per day at sea on each outing (68 écus for the season for 0.6 day,
6 outings). They then fish in the "open water" of the target lake (`catch.away`, `home_lake`, `travel_days`, `travel_cost`), with the locals:
the more visitors there are, the more the pressure rises. The engine sets no threshold: it is the fisher's reflection (or the character of a rule-based
agent: the old family, attached to its lake, wants a much better lake; the indebted newcomer goes where people fish; all leave
an empty lake) that decides, route included. On the map, they bring their boat in, walk to the other lake and come back the same way; the feed says so
("pêche dans le lac de Vellmor, à 0.6 j de route : 68 écus", fishes in Lake Vellmor, 0.6 d away: 68 écus). The menu sets the route (days, écus) when there are several lakes.

**A valley drawn at random.** `population.random: true` (`config/random.yaml`): the number of villages (3 to 6), of fishers (2 to 5 per
village, 24 at most), of lakes (1 to 3) and their richness in fish (per fisher), their full share at the start and their replenishment, the fleet
(small boats, mixed, large; the size of each boat is then drawn fisher by fisher, according to their character) and the number of
patrols (0 to 2) come from the seed alone (`lakes.random_valley`). In the menu, **Vallée : Aléatoire** (Valley: Random) does the same and grays out the
numbers; each fisher and each lake can then be touched up.

## The lake patrol

**The patrol is an agent.** Its captain ("Capitaine Aubry", the agent `PAT`) is an AI, or a rule-based agent like the elder (it follows
the elder's choice); it does not fish, does not sit, does not vote, has no power to punish. It decides alone where to go, based on the suspicions and
clues that villagers and fishers have **shared**, and remembers what it has recorded.

**Several patrols.** `scenario.patrol.count` (1 to 4, one by default; 0: none): each has its captain (`PAT`, `PAT2`…) and its
route for the season, decided in turn: the following ones read those of the first ones ("the other patrols will head toward…") and
go elsewhere. Each patrol costs `cost` to each fisher per season (`World.patrol_cost`), and the council installs or removes them
all with one vote. Each one measures the boats it crosses (`patrol_by`: the one that crossed it the most), and the patrols
tell each other about their rounds. The map shows one boat per patrol.

**It is a starting setting.** The menu offers "Patrouille du lac" (`scenario.patrol.enabled`, enabled by default). Unchecked, there is
no captain, no proposal at the council, no cost, no route: the agents do not hear about it.

**It is voted on.** A delegate proposes installing it (`patrouille: "installer"` field) if they judge that frauds need to be unmasked; the delegates vote
(`sanction_proposal`, `sanction_vote`, `sanction_result` with the action `patrouille`); it goes out from the next season (`patrol`). It costs
**each fisher** `scenario.patrol.cost` écus per season (15), which weighs on the vote: the indebted newcomer is reluctant, the silent one never
wants it, the old family and the smooth talker want it as soon as a lie has been established (`policies.PATROL_WANTS`, for rule-based agents;
an AI thinks it over). A delegate can also propose to **remove** it (`"retirer"`); it still goes out in the season of the vote. `scenario.patrol.from_season`
installs a patrol from the outset, without a vote (to compare games).

**Before each season, its captain decides its route** (`World.plan_patrol`, `patrol_route` event, with `why`, its reason). It has
`scenario.patrol.days` days at sea (14) to spread over `scenario.patrol.legs` legs (3): each leg is **a zone of the lake** (a village or
"open water"), where it measures the boats of those fishing there, or **a fisher it follows closely**, whom it crosses wherever they go (even in open water,
when they are banned from fishing). The legs follow one another, spread over the fishing window. It reads its **dossier** (`World.patrol_dossier`), zone by
zone: what was said in front of everyone (accusations, clues reported by the elder, established lies, lake accounts), what the valley thinks of
each one (the average trust, in words), and what it itself recorded over the last two seasons. A clue that someone keeps to themselves (one
does not denounce a friend), the truth of the outings and the declarations it did not hear do not reach it. A rule-based captain
(`World.patrol_rule`) follows the most suspected fisher based on what has been said, then goes where distrust is greatest; a zone where it passed
without finding anything inspires less distrust; a glance elsewhere one time in five so that it cannot be guessed. The fishers know
that it exists, not where it will pass.

**What it finds.** A boat is crossed in proportion to the outing days during which the patrol was in its zone (or on its heels):
chance of measuring it `scenario.detection.patrol` (90 %) times this share; the load is measured within ±12 %. The reading is a clue (`clue`,
`kind: patrouille`, observer `PAT`) that the elder reports at the gathering; it weighs 3, enough to establish a lie on its own. Its captain
notes after each season where it went, whom it measured and whether it matched what was declared; it rereads this before choosing its
next route. A captain cannot be everywhere: covering one zone means leaving others unwatched.

## Time: a single mode, and the dialogues

There is no longer a choice between Synchronous / Asynchronous: an **event scheduler** runs each season (specification: [docs/temps.md](docs/temps.md)).
Thinking takes no simulated time, acting does: a slow AI makes no outing get lost and does not change the world, and
decisions that no event separates are requested **in parallel**.

* **Gathering as it goes.** Speeches are prepared in parallel on the current minutes; only one person speaks at a
  time (`time.speech_minutes`, 20 simulated minutes); whoever has just been addressed answers first (`destinataire`, recalled separately
  in the prompt: "Someone addressed you"), then according to the seed key; a speech is only redone if its author
  was addressed in the meantime. Gatherings of different villages move forward side by side. Details: [docs/temps.md](docs/temps.md).
* `time.mode` and the `set_mode` command are accepted and ignored (warning); `run_start.mode` is `unique`.

**Proposing a rule.** When a rule is in force, recalling it does not renew it: `proposition_quota: null` keeps it (it remains
valid without a new vote), a figure proposes a **new** one. The prompt also gives the rule's record (how many fishers
exceeded it according to their declarations): without this, a small model copied the quota in force from one gathering to the next.

## Fewer tokens, more consistent agents

Speech cost 80 % of a game's tokens (speeches of about 2,000 tokens, each fisher speaking again at each round). In
`rapide` or `adaptive` reflection:

* **a gathering context** (`prompts.veillee_block`): the lake in one line, the rules, the declarations, the notebook, two memories;
  without the corpus archives or the season-by-season details of finances and the lake;
* **from the 2nd round, only those with a reason speak again** (`scenario.quiet_listeners`): they are addressed, named
  or accused, or another proposal competes with theirs. The others listen, and their position is collected at the ballot
  (a few tokens);
* **a notebook** in each decision, short and always there: real catches and declarations, commitments, trust in the others.
  This is what keeps a character consistent from one decision to the next, where memories retrieved at random do not guarantee it.

Measured with the real AI (Ollama, Qwen 2.5 3B + 1.5B and tev1, 8 fishers, 2 seasons, same seed, before and after): 74,000 → 51,000
tokens (−31 %); a speech 1,966 → 1,489 tokens, 28 → 20 speech calls; no fallback, no incident, same game duration. With
the fake LLM (5 seasons, estimated tokens): 165,000 → 86,000 tokens (−48 %). A reflected fishing decision costs a little more
(notebook, declaration, clues).

## The player's announcements have an effect

The bottom bar spreads a **rumor** ("Diffuser", Spread) in the valley. It is an injection: `injection` event, memory of type
`rumeur` for each inhabitant, "Une rumeur court" (A rumor is going around) banner and `RUMEUR` line in the feed. What makes it effective:

* **It appears in each AI decision** (catch and speech, section "Rumeurs qui courent dans la vallée", rumors going around the valley), during the season of the
  announcement and the next one, then it is forgotten. Before, it was only one memory among others, retrieved by memory in
  less than one decision in three: it got lost among the catches, the promises and the speeches of the gathering.
* **It is traced.** The *Agent* tab lists what was retrieved to decide, and the rumor appears there with the label
  `[rumeur]` (source `rumor` in `decision.retrieved`, identifier = that of the injection event: F6 traceability).
* **The fake LLM reacts to it**, otherwise an announcement would have no effect in test mode: a word of shortage ("sécheresse" (drought), "plus de poisson" (no more fish)…)
  reduces catches by 15 %; an accusing rumor that names a fisher ("Inès ment sur ce qu'elle ramène", Inès lies about what she brings back) makes the combative characters accuse this person
  at the gathering, makes her defend herself, and makes her sober (−20 %); any other rumor is relayed in the speeches.
* **Rule-based agents stay deaf**: they serve as a control (A6); this is what makes it possible to measure the effect of the rumor on the AIs.

## What we observe: the interactions

Each speech is an `utterance` event (who speaks, to whom, what they heard before),
and its effects are separate events: `proposal`, `support`, `promise`, `accusation`,
`norm_adopted`, then `promise_outcome` at the review. In Godot:

* **bubble** above the one speaking, **blue arrow** toward their addressee, a ripple if they speak to all;
* **golden badge** `P3 · 2 t` on the author of a proposal, **green link** from each supporter to the author;
* **red arrow** for an accusation; "promesse trahie" (broken promise) / "parole tenue" (word kept) labels at the review;
* **Interactions** tab: the complete feed, filterable on the selected agent;
* **Agent** tab: profile, model, savings, catches, promises (announced vs real), last decision
  with its information horizon, its justification or the rule applied, and **everything that was
  retrieved** to decide (pinned commitments, memories, archives, rumors), then the complete memory;
* **Règles** (Rules) tab: proposals on the table and history of adopted rules;
* **Confiance** (Trust) tab: each fisher's trust gauge, their real catch and their declaration, their discovered lies.

## The Godot scene

Top-down view of the valley, drawn entirely in code (no external image):

* **the map fills the whole frame**: the diamond-shaped valley touches its four edges, the forest extends beyond. The valley is larger than the screen (its size follows the number of villages and lakes, `run_start.map.size`);
  its edges blend into the forest and the hills, and a **minimap** at the bottom right shows the whole valley and the view (a click there moves the view; at minimum zoom, the whole valley fits on the screen). You move around as
  in Age of Empires: **the mouse wheel zooms** toward the pointer (up to ×4), **right click** (or middle click) drags the
  map, **the arrow keys** and the edge of the map scroll it, **Home** reframes on the whole valley, **G** shows the grids;
* **the lake** is a shader, drawn from its plots: its water clouds over and becomes covered with weed beds where fish are lacking
  (overfished spots can be seen), and **the number of fish seen swimming follows the stock**; the meadow turns yellow after a drought;
* **the fishers** leave their hamlet, take the pontoon, go out by boat to their fishing
  spot, cast the net ("+3.2 t"), then come back;
* **day and night** follow the simulated hour. The gathering is held in the evening: the map darkens,
  windows and fires light up, and **the elder's hall** opens over the map, the
  participants seated in a circle around the hearth. Bubbles are placed there without overlapping;
* **banners** announce the key moments: season, fishing opening, gathering, rule adopted,
  no agreement, drought, collapse;
* the clock (sun or moon, current phase) is at the top left, the lake gauge (with the half
  mark) at the bottom; hovering over a token shows its full name and archetype;
* **each fisher has the color of their hamlet** (token, boat, name); the elder has their own;
* on the right, the **Récit du narrateur** (Narrator's story) tab, next to the interactions feed: at the end of each season, an external and omniscient narrator tells in
  a few sentences what the valley went through, truth included (real catches, lies even undiscovered, stock of each lake, rules and who exceeds them, vote, accusations).
  The large model writes it from the facts recorded in the log alone (outside any agent, without the elder's voice); without AI, the story restates these facts (`narration`
  event, replayed like the others).

Tokens and links keep the same code everywhere: color = archetype, circle = LLM agent (thick
golden ring = large model), square = rule-based agent; blue = speech, green = support, red =
accusation, gold = proposal. The legend at the bottom of the screen is drawn with the same functions as
the map. The interactions feed uses these colors (fishers' names, labels by type).

Fonts: Nunito (interface) and Alegreya (titles), SIL OFL license, files in `godot/fonts/`.

Offline test of the view (replays a saved run and checks the state of the scene):

```bash
godot --headless --path godot -s res://tests/feed_test.gd -- --events=$PWD/runs/<id>/events.jsonl
```

Automatic screenshots of a live run: `godot --path godot -- --shots=4,12,20 --shotdir=/tmp`.

Windowless tests of the main interface (interactions feed, lost speeches, announcements, "Ralentir" button) and of the menu:

```bash
godot --headless --path godot -s res://tests/main_feed_test.gd -- --events=$PWD/runs/<id>/events.jsonl
godot --headless --path godot -s res://tests/menu_test.gd -- --catalog=/chemin/catalog.json   # (pytest runs it and validates the request)
```

## Indicators (common context, B1–B3)

For FILETS, the *common context* is a **shared harvesting norm**:

* `norm_agreement`: share of **all** fishers who supported the rule that concerns them (village first, valley otherwise); at the delegates' council, a fisher supports it if their village's delegate supported it (`norm_adopted.delegates`);
* `norm_compliance`: share of fishers subject to a rule whose real catch respects it (within 0.05 t, `scenario.quota_tolerance`);
* `norm_index = agreement × compliance` ∈ [0, 1].

Without a declared agreement, the index is 0 even if everyone happens to fish the same thing: this
coordination without a norm is read separately in `catch_cv` (dispersion of catches). The control
`config/no_comm.yaml` (no gathering) gives a zero index by construction, which makes it possible to
check that the indicator distinguishes the two situations well (B3).

Also computed as a stream: stock / capacity, promises kept and promised/fished gap, inequality
of savings (Gini), incidents by type, LLM calls and tokens, temporal consistency violations,
average staleness (gap between the lake observed and the lake at the moment the catch applies), and
lag between an event and the indicator it produces (`lag_s`, C7). Each indicator carries the
list of raw events that produced it (F6).

**Verifiable figures.** Each percentage is published with its counts (`norm_supporters`, `norm_compliers`,
`norm_concerned`, `fishers`, `promises_kept`, `promises`): Godot shows "6 sur 9 la respectent" (6 out of 9 respect it) under "67 %".
The stock in % is always `stock / capacity` of the current run (`capacity` is published with the indicator): it stays
between 0 and 100 %.

**Safeguards.** Indicators are only computed from the `run_start` of the current run (lake capacity, list of
fishers): an event that arrives without it, or from another run, is ignored rather than producing false figures.
The Kafka services therefore resume at the last `run_start` of the topic, and the bridge only sends Godot the indicators
of the displayed run. `tests/test_indicators_audit.py` recomputes each indicator separately, from the raw events, for
synchronous, asynchronous, per-hamlet, no-communication and rule-based games, and requires the same result.

## Time (C3–C6)

Each event carries `sim_time` (moment in the world) and `processed_at` (real moment).

* **A single mode** (scheduler, see [docs/temps.md](docs/temps.md)): simulated time does not move while an agent
  is thinking; its actions take time (a one-day outing, the route to another lake) and apply at their end, in the order of the
  queue (time, class, seed key), never in the order in which the models answer. Between two deadlines, the display clock
  advances at `sim_hours_per_second` (3 h/s by default), accelerated by `idle_speedup`.

`sim_hours_per_second` now only sets the display pace: a model's latency has no effect on the world. No agent can use
information later than its horizon: memory, archives, speeches and proposals are filtered,
and any violation is detected and counted.

**No more mode changes.** The `set_mode` command is received and ignored (warning in the engine log). Pause,
speed and stop are still traced by `injection pause|resume|set_speed|stop`.

## Data (F1–F6)

| Data | Where | Why |
|---|---|---|
| Event stream | Kafka `filets.events` (1 partition, key = actor, 7 days) | total order for replay and indicators; independent consumers |
| Indicators | Kafka `filets.indicators` | the scene and the history consume them without recomputation |
| Engine state | Kafka `filets.status` (1 hour) | lobby, current game, pause, speed, mode: what the control bar shows; only the last message counts |
| Current world state | engine memory | read and written at each decision, zero latency |
| Replayable run | `runs/<id>/events.jsonl` + `config.json` | single source for replay without LLM (E3) |
| Run history | SQLite `data/history.db`, or **PostgreSQL** (`config/data.yaml`), typed views | reproducible analytical queries across runs (F5); indexed JSONB and concurrent writing with PostgreSQL |
| Knowledge base | `corpus/*.md`, in-memory BM25 index, or **PostgreSQL + pgvector** (`config/data.yaml`) | BM25: zero cost, explainable scores (F2); pgvector: search by meaning, vectors kept from one game to the next; access by hamlet and by date in both cases |
| Agents' memories | engine memory, or **pgvector** (`config/data.yaml`) | collective memory of a game queryable by meaning (`GET /api/runs/{id}/memories?q=…`) |
| Raw files | `runs/<id>/`, and an **S3 object storage** with `config/data.yaml` | corpus documents and archive of each game, off the gaming machine |
| Invalid events | Kafka `filets.deadletter` | isolated without stopping the simulation (F4) |

The versioned schemas of each event type are in `schemas/` (source: `filets/schemas.py`).

**PostgreSQL + pgvector and object storage (`config/data.yaml`).** `docker compose --profile data up -d` starts PostgreSQL 17 with
pgvector (on 127.0.0.1:19432) and the MinIO object storage (S3 on 127.0.0.1:19000, console on http://127.0.0.1:19001; any
S3 service will do). FILETS uses 19xxx ports (Kafka on 19092) rather than the standard ports, which another project or an
installed PostgreSQL may hold: both run at the same time, each with its containers, its volumes and its credentials.
`ollama pull embeddinggemma` installs the embedding model (multilingual, 768 dimensions, computed on the CPU to leave
the graphics card to the LLMs). Then `python -m filets serve --config config/data.yaml` (this is what `.\start.cmd` does). If the database goes down
during a game, search falls back on in-memory BM25 and the game continues. Everything is done asynchronously (asyncpg,
miniopy-async, aiokafka, httpx). See [docs/architecture.md § 6](docs/architecture.md#6-stockage--postgresql--pgvector-et-stockage-objet).

## Directory tree

```
filets/            engine: world.py (the world), scheduler.py (the scheduler, see docs/temps.md), control.py (pause, speed, stop),
                   engine.py (the lobby: request validation, AI checks, successive games),
                   catalog.py (what the menu offers), agents.py, prompts.py, policies.py, profiles.py,
                   memory.py, rag.py, llm.py, routing.py, scripted.py, indicators.py, console.py, cli.py,
                   api.py (FastAPI), aio.py (aiokafka), vectors.py (embeddings, pgvector), pgstore.py (PostgreSQL
                   history), store.py (SQLite history), objects.py (S3 object storage)
filets/services/   asynchronous Kafka services: indicators, bridge (FastAPI API), store (PostgreSQL or SQLite)
godot/             Godot 4 project: main.gd (interface, control bar, inspector), start_menu.gd (start menu),
                   menu_map.gd (menu valley preview), world_view.gd (scene), art.gd (palette, tokens), chart.gd,
                   legend.gd, shaders/valley.gdshader, fonts/, tests/ (feed_test.gd, menu_test.gd, main_feed_test.gd)
install.ps1, start.ps1, stop.ps1 (and .cmd)   installation, start and stop on Windows
corpus/            fictional knowledge base of the valley
config/            default (base valley: 4 villages, 8 fishers), large (large valley: 4 villages, 18 fishers), lakes (three lakes,
                   six villages, two patrols), random (valley drawn from the seed), baseline (without LLM),
                   no_comm, hamlet, drought, ollama (7B), ollama_fast (3B),
                   ollama_open (3B + tev1), groq, data (PostgreSQL + pgvector, object storage)
docs/              architecture.md: architecture, time, communication, tokens, asynchronous, storage
schemas/           versioned JSON schemas of the events
analysis/          SQL queries for the report (queries.sql for SQLite, queries_pg.sql for PostgreSQL)
runs/              saved runs (one example provided)
tests/             consistency tests
```

## What remains to be done

* Plug in real models and calibrate the prompts (breaking character, "cautious
  assistant" posture, overly accommodating agents: see the sheet's leads).
* Evaluate retrieval (`filets retrieval`): compare BM25 and pgvector on the same annotated decisions.
* Validate the tev1 decision model on a real game (Ollama 0.40.4): share of reflexes, confidence, gap from Qwen's catches.
* Energy measurement (CodeCarbon for Ollama, EcoLogits for APIs) to add to the cost report.
* The experimental protocol: hypotheses, at least 5 runs × 2 configurations, baseline (E1, E2).
* Exploit the measurements already instrumented for excellence: event → indicator lag under
  load (C7) and comparison of two population sizes (`--agents`, C8).

## License

Non-commercial source-available license: see [LICENSE.md](LICENSE.md). Commercial use requires written permission from the rights holder.
