"""Le temps en toutes lettres. Le temps simulé reste un nombre de jours (l'ordre des événements, ce que chacun savait à tel instant),
mais ce que lisent les agents, et ce que porte chaque événement (`sim_text`), est du texte : « saison 2 (été), jour 25, le soir (18 h) »,
avec ce que fait la saison à cet instant et son calendrier."""
from __future__ import annotations

import asyncio

import pytest

from filets.clock import day_words, fmt_text
from helpers import make_world, read_events
from test_council import fake_game
from test_rumors import Recorder, fisher


@pytest.mark.parametrize("t, words", [
    (0.25, "jour 0, le matin (6 h)"), (3.5, "jour 3, à midi (12 h)"), (5.6, "jour 5, l'après-midi (14 h 24)"),
    (25.75, "jour 25, le soir (18 h)"), (29.9, "jour 29, le soir (21 h 36)"), (7.0, "jour 7, la nuit (0 h)"),
    (7.95, "jour 7, la nuit (22 h 48)"), (9.9999, "jour 10, la nuit (0 h)")])      # l'arrondi à la minute passe au jour suivant
def test_a_moment_of_the_day_is_said_in_words(t, words):
    assert day_words(t) == words


def test_the_season_comes_first_with_its_place_in_the_year():
    assert fmt_text(25.75, 30) == "saison 1, jour 25, le soir (18 h)"
    assert fmt_text(55.75, 30, "été") == "saison 2 (été), jour 25, le soir (18 h)"
    assert fmt_text(30.0, 30) == "saison 2, jour 0, la nuit (0 h)"


def test_the_world_reads_the_time_as_text_and_says_what_the_season_is_doing(tmp_path):
    world, bus, _ = make_world(tmp_path, "texte", climate__enabled=True)
    assert world.when(0.25) == "saison 1 (printemps), jour 0, le matin (6 h)"
    assert world.when(3 * 30 + 25.75) == "saison 4 (hiver), jour 25, le soir (18 h)"
    assert world.when(5 * 30 + 1.0).startswith("saison 6 (été)")                       # le cycle de l'année reprend
    assert world.when(25.75, short=True) == "saison 1, jour 25"
    assert world.phase_text(0.0) == "la saison commence, la pêche n'est pas encore ouverte"
    assert world.phase_text(0.25) == "la pêche est ouverte, encore 20 jours"
    assert world.phase_text(19.2) == "la pêche est ouverte, encore 1 jour"
    assert world.phase_text(22.0) == "la pêche est finie, la veillée chez l'ancien approche"
    assert world.phase_text(26.0) == "veillée chez l'ancien"
    assert world.phase_text(29.5) == "la veillée est finie, le lac va se repeupler"
    assert world.phase_text(29.95) == "le lac se repeuple, la saison s'achève"
    assert "30 jours, numérotés depuis 0" in world.calendar_text() and "du jour 0 au jour 20" in world.calendar_text()
    assert "au jour 25, le soir (18 h)" in world.calendar_text()
    calm, _, _ = make_world(tmp_path, "sans-climat", climate__enabled=False)
    assert calm.when(0.25) == "saison 1, jour 0, le matin (6 h)"                     # pas de saison de l'année sans climat


def test_every_event_carries_its_time_in_words(tmp_path):
    world, bus, _ = make_world(tmp_path, "evenements", seasons=2, climate__enabled=True)
    asyncio.run(world.run())
    events = read_events(tmp_path, "evenements")
    assert events and all(e["sim_text"] == world.when(e["sim_time"]) for e in events)
    assert any(e["sim_text"].startswith("saison 2") for e in events)


def test_the_agents_read_the_time_the_phase_and_the_calendar(tmp_path):
    """Dans chaque invite : où l'on en est (en toutes lettres), ce que fait la saison, quand a lieu chaque chose ; les souvenirs
    et le suivi du lac portent la même lecture du temps."""
    rec = Recorder()
    fake_game(tmp_path, "agents", rec, population=[fisher("Mathis", "Ostrel", "ancienne_famille"),
                                                   fisher("Inès", "Tilque", "nouveau_venu")],
              seasons=2, mode="sync", scenario__council="all", climate__enabled=True)
    catch = [r["user"] for r in rec.requests if '"prise"' in r["user"]]
    speech = [r["user"] for r in rec.requests if "Veillée chez l'ancien" in r["user"]]
    assert catch and speech
    assert catch[0].startswith("Nous sommes en saison 1 (printemps), jour 0, le matin (6 h) : la pêche est ouverte, encore 20 jours.")
    assert speech[0].startswith("Nous sommes en saison 1 (printemps), jour 25, le soir (18 h) : veillée chez l'ancien.")
    for prompt in catch + speech:
        assert "Une saison compte 30 jours, numérotés depuis 0" in prompt
        assert "S1 ·" not in prompt and " · J" not in prompt                    # plus d'étiquette codée dans ce que lit un agent
    second = [u for u in catch if u.startswith("Nous sommes en saison 2")][0]
    assert "saison 1, jour 0 (ouverture de la pêche)" in second and "[saison 1" in second
