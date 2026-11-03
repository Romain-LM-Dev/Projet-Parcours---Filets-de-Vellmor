"""Les bords de la pêche en plusieurs sorties (`World.outings`, `World.apply_catch`, `Climate.day_factor`, `World.investigate`) : une
seule sortie ou beaucoup, une prise visée nulle, un lac vide ou rationné, un interdit qui sort en cachette, le temps seul sans la
chance, une tempête sur une barque, la patrouille qui n'a croisé qu'une partie des sorties, et la même pêche en synchrone comme en
asynchrone. Les tests de `test_valley.py` couvrent le cas courant ; ceux-ci posent les sorties à la main (le cache `Agent.outings`)
quand il faut des tonnes qu'on calcule de tête, et ne dépendent d'aucune valeur tirée au hasard.
"""
from __future__ import annotations

import asyncio

import pytest

from filets.climate import DAYS, Climate
from filets.world import outings_text
from helpers import make_world, read_events

BOATS = ("barque", "chaloupe", "cotre")


def kinds(events, kind):
    return [e for e in events if e["type"] == kind]


def decision(stock=50.0):
    """La décision qui précède une prise (`apply_catch` n'en lit que ce qu'il a observé du lac)."""
    return {"event_id": "d0", "payload": {"observed": {"stock_estimate": stock, "stock_true": stock}}}


def set_outings(agent, season, yields, weather="ordinaire"):
    """Impose les sorties d'un pêcheur pour une saison : un rendement chacune, pour des tonnes que l'on calcule à la main."""
    agent.outings[season] = [{"day": 1.0 + i, "weather": weather, "luck": 1.0, "yield": y} for i, y in enumerate(yields)]


def played(tmp_path, run_id, seasons=2, **over):
    """Une partie synchrone sur un grand lac (personne n'est rationné), avec chance et temps : le monde et son journal."""
    over = {"economy__luck": 0.4, "climate__enabled": True, "lake__capacity": 1000.0, "time__mode": "sync", **over}
    world, bus, _ = make_world(tmp_path, run_id, seasons=seasons, **over)
    asyncio.run(world.run())
    return world, read_events(tmp_path, run_id)


# ============================================================ le nombre de sorties
@pytest.mark.parametrize("asked", [1, 0, -3])
def test_a_fisher_always_goes_out_at_least_once_and_that_outing_brings_the_whole_catch(tmp_path, asked):
    """`economy.outings` à 1, et même à 0 ou moins : une sortie, jamais aucune (il n'y aurait rien à partager ni à diviser)."""
    world, bus, _ = make_world(tmp_path, f"une-{asked}", economy__outings=asked, economy__luck=0.4, climate__enabled=True)
    a = world.fishers[0]
    [out] = world.outings(a, 1)
    assert world.T["fishing_open_day"] <= out["day"] < world.T["fishing_close_day"]
    p = world.apply_catch(a, 3.0, decision(), 0.0)["payload"]
    assert p["landed"] > 0 and [o["tonnes"] for o in p["outings"]] == [p["landed"]]
    # (le rendement compte aussi le coin de pêche : sa parcelle du lac)
    assert p["yield"] == pytest.approx(out["yield"] * p["spot"], abs=0.002) and p["luck"] == pytest.approx(out["luck"], abs=0.001)
    notes = [m.text for m in a.memory.items if m.kind == "peche"]
    assert any("Sur 1 sortie : " in t for t in notes) and not any("sorties" in t for t in notes)       # (au singulier)


def test_the_fishers_tell_the_weather_of_their_outings():
    text = outings_text([{"weather": w} for w in ("calme", "calme", "tempête")])
    assert text.startswith("Sur 3 sorties : ") and "2 par temps calme" in text and "1 dans la tempête" in text
    assert "agité" not in text and "ordinaire" not in text                       # ce qui n'a pas eu lieu ne se dit pas
    assert outings_text([{"weather": "agité"}]).startswith("Sur 1 sortie : ")


def test_many_outings_still_add_up_to_the_catch_and_follow_the_calendar(tmp_path):
    world, events = played(tmp_path, "beaucoup", economy__outings=20, population__boat_mix={"chaloupe": 1.0, "cotre": 1.0})
    sky = {e["season"]: e["payload"]["conditions"]["days"] for e in kinds(events, "season_start")}
    catches = kinds(events, "catch")
    assert catches and sky
    for e in catches:
        c = e["payload"]
        days = [o["day"] for o in c["outings"]]
        assert len(days) == 20 and days == sorted(days)                               # une sortie après l'autre, sur la fenêtre de pêche
        assert world.T["fishing_open_day"] <= days[0] and days[-1] < world.T["fishing_close_day"]
        assert sum(o["tonnes"] for o in c["outings"]) == pytest.approx(c["landed"], abs=1e-6)
        assert all(o["weather"] == sky[e["season"]][int(o["day"])] for o in c["outings"])


# ============================================================ le ciel montré au joueur
@pytest.mark.parametrize("climate", [True, False])
def test_the_sky_shown_to_the_player_is_the_one_the_fishers_lived(tmp_path, climate):
    world, events = played(tmp_path, f"ciel-vu-{climate}", seasons=3, climate__enabled=climate)
    sky = {e["season"]: e["payload"]["conditions"]["days"] for e in kinds(events, "season_start")}
    assert sorted(sky) == [1, 2, 3] and all(len(d) == int(world.T["fishing_close_day"]) for d in sky.values())
    catches = kinds(events, "catch")
    assert catches and all(o["weather"] == sky[e["season"]][int(o["day"])] for e in catches for o in e["payload"]["outings"])
    seen = {w for days in sky.values() for w in days}
    assert len(seen) >= 3 if climate else seen == {"ordinaire"}                     # sans climat, le même temps tous les jours


# ============================================================ une prise de rien, rationnée, plafonnée
@pytest.mark.parametrize("case", ["visée nulle", "lac vide", "tempête toute la saison"])
def test_a_catch_of_nothing_is_not_a_failure(tmp_path, case):
    """Il n'y a rien à partager entre les sorties : chacune rapporte 0 t (et non une division par zéro)."""
    world, bus, _ = make_world(tmp_path, "rien", population__elder=False)
    got = []
    bus.subscribe("events", got.append)
    a = world.fishers[0]
    if case == "lac vide":
        world.lake.stock = 0.0
    if case == "tempête toute la saison":
        set_outings(a, 1, [0.0] * 6, "tempête")                                       # (une barque dont chaque sortie tombe un jour de tempête)
    p = world.apply_catch(a, 0.0 if case == "visée nulle" else 3.0, decision(), 0.0)["payload"]
    assert p["landed"] == 0.0 and p["stock_after"] == p["stock_before"]
    assert [o["tonnes"] for o in p["outings"]] == [0.0] * world.econ["outings"]
    assert a.catches[1] == 0.0 and [e["payload"]["landed"] for e in kinds(got, "report")] == [0.0]      # il rentre et le déclare


def test_each_outing_is_capped_at_its_share_of_the_hold_not_the_whole_catch(tmp_path):
    world, bus, _ = make_world(tmp_path, "cale-sortie", population__elder=False, lake__capacity=100.0)
    a = world.fishers[0]
    hold = world.hold[a.id]
    set_outings(a, 1, [2.0, 0.5, 1.0, 1.0, 1.0, 1.0])        # une très bonne sortie (elle déborderait la cale), une mauvaise, quatre ordinaires
    p = world.apply_catch(a, hold, decision(), 0.0)["payload"]
    # la bonne sortie ne rapporte que sa part de cale (comme une ordinaire) : (1 + 0,5 + 4) / 6 de la cale. Une cale qui plafonnerait
    # la prise entière rendrait toute la cale, pas de plafond du tout 1,083 fois la cale.
    assert p["landed"] == pytest.approx(hold * 5.5 / 6, abs=0.001)
    t = [o["tonnes"] for o in p["outings"]]
    assert t[0] == pytest.approx(t[2], abs=0.003) and t[1] == pytest.approx(t[2] / 2, abs=0.003)
    assert sum(t) == pytest.approx(p["landed"], abs=1e-6)


def test_a_rationed_catch_is_shared_between_the_outings_by_what_each_brings(tmp_path):
    world, bus, _ = make_world(tmp_path, "ration-direct", population__elder=False, lake__capacity=100.0)
    a, b = world.fishers[:2]
    set_outings(a, 1, [1.5, 1.5, 1.5, 0.5, 0.5, 0.5])
    p = world.apply_catch(a, 3.0, decision(), 0.0, ration=0.5)["payload"]
    assert p["rationed"] and p["landed"] == pytest.approx(0.5 * 3.0 * 1.0, abs=0.001)         # la moitié de ce qu'il visait, rendement moyen 1
    assert [o["tonnes"] for o in p["outings"]] == pytest.approx([0.375] * 3 + [0.125] * 3, abs=0.002)
    world.hold_fraction = 100.0                              # (sans limite de part : seul le lac compte)
    world.lake.stock = 1.0                                   # un lac qui n'a plus que 1 t : il ne rend pas davantage, même sans rationnement
    set_outings(b, 1, [1.0] * 6)
    q = world.apply_catch(b, 3.0, decision(), 0.0)["payload"]
    assert q["landed"] == 1.0 and q["stock_after"] == 0.0 and not q["rationed"]
    assert sum(o["tonnes"] for o in q["outings"]) == pytest.approx(1.0, abs=1e-6)


def test_a_rationed_season_never_lands_more_than_the_lake_held(tmp_path):
    world, events = played(tmp_path, "ration", lake__capacity=15.0, lake__initial_ratio=0.4,         # huit pêcheurs sur 6 t, qui se
                           economy__hold_fraction=1.0, lake__observation_noise=0.3)                  # trompent de 30 % sur le lac
    catches = kinds(events, "catch")
    assert catches
    for season in {e["season"] for e in catches}:
        fleet = [e["payload"] for e in catches if e["season"] == season]
        assert sum(c["landed"] for c in fleet) <= fleet[0]["stock_before"] + 1e-6                     # la flotte ne prend pas plus que le lac
    for c in (e["payload"] for e in catches):
        assert c["stock_after"] >= 0 and c["landed"] <= c["requested"] * c["yield"] + 0.005          # le rationnement ne fait que retrancher
        assert sum(o["tonnes"] for o in c["outings"]) == pytest.approx(c["landed"], abs=1e-6)


# ============================================================ l'interdit qui sort en cachette
def test_a_banned_fisher_who_goes_out_anyway_fishes_far_from_home_and_declares_nothing(tmp_path):
    world, bus, _ = make_world(tmp_path, "cachette", population__elder=False)
    got = []
    bus.subscribe("events", got.append)
    a = world.fishers[0]
    world.banned[a.id] = 1
    # la patrouille couvre toute la saison, partout sauf devant son village : elle ne peut le croiser que là où il se cache
    world.patrol_legs[1] = [{"zone": z, "from_day": 0.25, "to_day": 20.0} for z in world.zones if z != a.profile.hamlet]
    p = world.apply_catch(a, 3.0, decision(), 0.0)["payload"]
    assert p["secret"] is True and p["zone"] in world.zones and p["zone"] != a.profile.hamlet
    assert len(p["outings"]) == world.econ["outings"] and p["landed"] > 0
    assert sum(o["tonnes"] for o in p["outings"]) == pytest.approx(p["landed"], abs=1e-6)
    assert not kinds(got, "report") and (a.id, 1) not in world.reports and 1 not in a.declared      # il ne déclare rien
    [trip] = world.trips[1]
    assert trip["secret"] and trip["zone"] == p["zone"] and trip["patrol"] == 1.0
    assert any("en cachette" in m.text for m in a.memory.items)


def test_a_banned_fisher_who_stays_home_catches_nothing_and_leaves_no_trace(tmp_path):
    world, bus, _ = make_world(tmp_path, "a-quai", population__elder=False)
    got = []
    bus.subscribe("events", got.append)
    a = world.fishers[0]
    world.banned[a.id] = 1
    assert world.apply_catch(a, 0.0, decision(), 0.0) is None
    assert not [e for e in got if e["type"] in ("catch", "report", "sale")] and not world.trips.get(1)
    assert 1 not in a.outings and any("resté à quai" in m.text for m in a.memory.items)


# ============================================================ le temps seul, sans la chance
@pytest.mark.parametrize("boat", BOATS)
def test_with_no_luck_the_weather_alone_decides_what_an_outing_brings(tmp_path, boat):
    """`economy.luck: 0` avec le climat : ni chance ni malchance, ni expérience ni lac bas, seulement le temps de la journée."""
    world = make_world(tmp_path, f"temps-{boat}", economy__luck=0.0, climate__enabled=True, climate__event_rate=0.0,
                       population__boat_mix={boat: 1.0}, population__elder=False)[0]
    veteran, novice = world.fishers[:2]
    veteran.profile.experience, novice.profile.experience = 40, 2
    seen = {}                                                   # (saison, temps) -> les rendements vus ce jour-là, tous pêcheurs confondus
    for season in range(1, 9):
        world.climate.begin(season)
        for f in world.fishers:
            for o in world.outings(f, season, 0.05 * world.capacity if f is novice else None):      # (un lac presque vide pour lui)
                assert o["luck"] == 1.0
                seen.setdefault((season, o["weather"]), set()).add(o["yield"])
    assert all(len(v) == 1 for v in seen.values())             # un seul rendement par temps et par saison : le pêcheur n'y est pour rien
    assert len({weather for _, weather in seen}) >= 3          # et le ciel a changé
    ranking = ["calme", "ordinaire", "agité", "tempête"]
    for season in range(1, 9):
        brought = [next(iter(seen[(season, w)])) for w in ranking if (season, w) in seen]
        assert brought == sorted(brought, reverse=True)       # plus le temps est dur, moins la sortie rapporte


def test_a_storm_never_makes_a_boat_lose_fish():
    climate = Climate({"climate": {"enabled": True}}, 1)
    worst = min(climate.day_factor(label, season, boat) for label in DAYS for season in range(1, 9) for boat in BOATS)
    assert worst >= 0.0                                        # (une barque, un jour de tempête : elle ne rapporte rien, pas moins que rien)


def test_no_outing_ever_brings_back_less_than_nothing(tmp_path):
    world = make_world(tmp_path, "pire", economy__luck=0.6, climate__enabled=True, climate__event_rate=1.0,
                       population__boat_mix={"barque": 1.0}, population__elder=False)[0]
    storms, yields = 0, []
    for season in range(1, 41):
        world.climate.begin(season)
        for f in world.fishers:
            outs = world.outings(f, season)
            storms += sum(o["weather"] == "tempête" for o in outs)
            yields += [o["yield"] for o in outs]
    assert storms > 10 and min(yields) >= 0.0                  # (le cas dur est bien arrivé : des barques sorties par gros temps)


# ============================================================ la patrouille et la part des sorties qu'elle a croisées
def test_the_patrol_measures_a_boat_only_as_often_as_it_met_its_outings(tmp_path):
    world = make_world(tmp_path, "mesure", population__elder=False)[0]
    world.detection.update({"patrol": 1.0, "patrol_error": 0.0, "witness": 0.0, "seen_leaving": 0.0, "lifestyle": 0.0})
    a = world.fishers[0]

    def measures(share, seasons=100):
        """Combien de saisons sur 100 la patrouille mesure une barque qu'elle a croisée sur cette part de ses sorties."""
        first = max(world.trips, default=0) + 1
        for s in range(first, first + seasons):
            world.trips[s] = [{"agent": a.id, "zone": a.profile.hamlet, "landed": 3.0, "secret": False, "patrol": share,
                               "event_id": "t"}]
            world.investigate(s)
        return sum(c["kind"] == "patrouille" and first <= c["season"] < first + seasons for c in world.clues)

    never, half, always = measures(0.0), measures(0.5), measures(1.0)
    assert never == 0 and always == 100          # croisée à chaque sortie, la patrouille (fiable à 100 %) la mesure toujours
    assert 25 < half < 75                        # croisée à une sortie sur deux : une fois sur deux environ, ni toujours ni jamais


def test_a_day_when_the_patrol_changes_zone_belongs_to_one_zone_only(tmp_path):
    world = make_world(tmp_path, "relais", population__elder=False)[0]
    world.patrol_legs[1] = [{"zone": "Ostrel", "from_day": 0.25, "to_day": 10.0}, {"zone": "Bramois", "from_day": 10.0, "to_day": 20.0}]
    for day in (0.25, 9.99, 10.0, 19.99):
        assert world.patrolled(1, "Ostrel", [day]) + world.patrolled(1, "Bramois", [day]) == 1.0      # ni deux fois, ni jamais
    assert world.patrolled(1, "Ostrel", [10.0]) == 0.0 and world.patrolled(1, "Bramois", [10.0]) == 1.0


# ============================================================ une saison de pêche se tire une fois
def test_a_fisher_fishes_a_season_once_whatever_he_is_asked_again(tmp_path):
    world = make_world(tmp_path, "cache", economy__luck=0.4, climate__enabled=True)[0]
    a = world.fishers[0]
    first = world.outings(a, 1)
    form = a.form
    assert world.outings(a, 1, stock=0.05 * world.capacity) == first and world.outings(a, 1) is first
    assert a.form == form and a.outings == {1: first}          # redemandée, la saison ne se tire pas deux fois : ni sorties, ni forme
    second = world.outings(a, 2)
    assert second != first and a.form != form and set(a.outings) == {1, 2}


def test_scripted_fishers_fish_the_same_in_sync_and_async(tmp_path):
    """Sans IA, le mode ne change pas la pêche : mêmes sorties (jours, temps, chance, rendement) et, pour une même prise visée, la même
    prise. (Sur un grand lac : un lac bas rend le poisson plus dur à prendre selon le stock du moment, qui dépend du mode.)"""
    runs = {}
    for mode in ("sync", "async"):
        world, events = played(tmp_path, f"mode-{mode}", seasons=3, time__mode=mode)
        runs[mode] = world, {(e["payload"]["agent"], e["season"]): e["payload"] for e in kinds(events, "catch")}
    (sync, caught_sync), (asyn, caught_asyn) = runs["sync"], runs["async"]
    assert sync.fishers and [a.outings for a in sync.fishers] == [a.outings for a in asyn.fishers]
    assert len({o["weather"] for a in sync.fishers for outs in a.outings.values() for o in outs}) >= 3       # (sous un ciel qui change)
    assert caught_sync.keys() == caught_asyn.keys() and len(caught_sync) == 3 * len(sync.fishers)
    same_aim = [k for k in caught_sync if caught_sync[k]["requested"] == caught_asyn[k]["requested"]]
    assert len(same_aim) >= len(sync.fishers)                                       # au moins la première saison, où personne n'a rien appris
    def days(c):            # les sorties sans leurs tonnes : le jour, le temps, la chance, le rendement
        return [{x: v for x, v in o.items() if x != "tonnes"} for o in c["outings"]]
    # (une règle du conseil sur les sorties peut en retrancher, toujours les dernières : on compare le début de la liste)
    assert all(days(caught_sync[k])[:min(len(caught_sync[k]["outings"]), len(caught_asyn[k]["outings"]))] ==
               days(caught_asyn[k])[:min(len(caught_sync[k]["outings"]), len(caught_asyn[k]["outings"]))] for k in same_aim)
    # la même prise : à la première saison, où les coins de pêche (les parcelles du lac) sont encore intacts ; ensuite, chaque coin
    # garde la trace de ce que les autres y ont pris, et ils n'ont pas tous visé pareil dans les deux modes
    first = [k for k in same_aim if k[1] == 1]
    assert first and all(caught_sync[k]["landed"] == caught_asyn[k]["landed"]
                                                and caught_sync[k]["outings"] == caught_asyn[k]["outings"] for k in first)
