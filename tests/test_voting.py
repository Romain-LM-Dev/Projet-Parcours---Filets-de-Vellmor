"""Le vote des règles. Constat sur des parties réelles : 41 propositions de quota (7,0 ; 7,3 ; 7,4 ; 7,5 ; 4,2 ; 4,3…) en trois
veillées, les voix dispersées, et aucune règle jamais adoptée (indice de norme 0). Les propositions voisines n'en font plus qu'une,
et la clôture compte les voix de ceux qui ont dit un quota sans soutenir de proposition."""
from __future__ import annotations

import asyncio

import pytest

from filets.world import Assembly
from helpers import make_world, read_events


def world_with_assembly(tmp_path, run_id="vote", **over):
    world, bus, _ = make_world(tmp_path, run_id, seasons=1, time__mode="sync", population__rule_fraction=0.0, **over)
    asm = Assembly("valley", [a.id for a in world.agents.values()], 1, 29.0)
    return world, asm


class Said:
    """Ce qu'un agent dit à la veillée (la sortie de son tour de parole)."""

    def __init__(self, world, agent, **data):
        base = {"message": "Voici mon avis.", "destinataire": "tous", "proposition_quota": None, "soutien": None,
                "promesse": None, "accuse": None}
        self.data = {**base, **data}
        self.decision = world.events.emit("decision", {"agent": agent.id, "agent_kind": "llm", "decision_type": "speak",
                                                       "info_horizon": 0.0, "retrieved": [], "used_event_ids": [], "value": None,
                                                       "observed": {"stock_estimate": 50.0, "stock_true": 50.0, "quota": None},
                                                       "justification": "x", "rule": None, "fallback": False, "model": None,
                                                       "tier": None, "llm_call_id": None}, actor=agent.id)


def speak(world, asm, agent, **data):
    world.post_utterance(agent, asm, Said(world, agent, **data), 1, world.clock.now())


def test_nearby_quotas_are_one_proposal(tmp_path):
    world, asm = world_with_assembly(tmp_path)
    for a, q in zip(world.fishers, (7.0, 7.3, 7.4, 7.5, 4.2, 4.3)):
        speak(world, asm, a, proposition_quota=q)
    assert sorted(p.quota for p in asm.proposals.values()) == [4.2, 7.0]          # 7,3 / 7,4 / 7,5 rejoignent 7,0 ; 4,3 rejoint 4,2
    by = {}
    for aid, (pid, _, _) in asm.support.items():
        by.setdefault(asm.proposals[pid].quota, []).append(aid)
    assert len(by[7.0]) == 4 and len(by[4.2]) == 2


def test_distant_quotas_stay_apart(tmp_path):
    world, asm = world_with_assembly(tmp_path)
    for a, q in zip(world.fishers, (1.0, 2.0, 3.5)):
        speak(world, asm, a, proposition_quota=q)
    assert len(asm.proposals) == 3


def test_a_majority_on_close_quotas_adopts_a_rule(tmp_path):
    world, asm = world_with_assembly(tmp_path)
    quotas = [7.0, 7.3, 7.4, 7.5, 7.2, 4.0, 3.0, 2.0]
    for a, q in zip(world.fishers, quotas):
        speak(world, asm, a, proposition_quota=q)
    world.close_assembly(asm)
    assert len(world.norms) == 1 and world.norms[0].quota == 7.0 and len(world.norms[0].supporters) == 5


def test_the_closing_vote_counts_what_people_said_without_supporting(tmp_path):
    world, asm = world_with_assembly(tmp_path)
    f = world.fishers
    speak(world, asm, f[0], proposition_quota=3.0)                  # une proposition, soutenue par son auteur
    for a in f[1:6]:
        speak(world, asm, a, promesse=3.5)                          # cinq autres promettent 3,5 t sans soutenir quoi que ce soit
    speak(world, asm, f[6], promesse=9.0)                           # trop loin de toute proposition : il s'abstient
    assert len(asm.support) == 1
    world.close_assembly(asm)
    assert len(world.norms) == 1 and world.norms[0].quota == 3.0
    assert sorted(world.norms[0].supporters) == sorted(a.id for a in f[:6])
    assert f[6].id not in asm.support and f[7].id not in asm.support           # abstention (écart ou silence)


def test_an_explicit_support_is_never_overridden_by_the_closing_vote(tmp_path):
    world, asm = world_with_assembly(tmp_path)
    f = world.fishers
    speak(world, asm, f[0], proposition_quota=2.0)
    speak(world, asm, f[1], proposition_quota=6.0)
    pid_low = next(p.id for p in asm.proposals.values() if p.quota == 2.0)
    world.clock.set(world.clock.now() + 0.01)
    speak(world, asm, f[2], promesse=6.0, soutien=pid_low)           # il dit 6 mais soutient expressément la proposition à 2
    world.close_assembly(asm)
    assert asm.support[f[2].id][0] == pid_low


def test_votes_are_support_events_tied_to_the_voters_last_speech(tmp_path):
    world, asm = world_with_assembly(tmp_path, "vote-ev")
    f = world.fishers
    speak(world, asm, f[0], proposition_quota=3.0)
    speak(world, asm, f[1], promesse=3.2)
    world.close_assembly(asm)
    world.recorder.flush()
    events = read_events(tmp_path, "vote-ev")
    sup = [e for e in events if e["type"] == "support" and e["payload"]["agent"] == f[1].id]
    utt = [e for e in events if e["type"] == "utterance" and e["payload"]["speaker"] == f[1].id]
    assert len(sup) == 1 and sup[0]["payload"]["utterance_id"] == utt[-1]["event_id"]


def test_the_tolerances_are_settings(tmp_path):
    world, asm = world_with_assembly(tmp_path, "vote-cfg", scenario__proposal_merge_tolerance=0.0)
    for a, q in zip(world.fishers, (7.0, 7.3)):
        speak(world, asm, a, proposition_quota=q)
    assert len(asm.proposals) == 2


def test_a_full_scripted_game_still_verifies(tmp_path):
    from filets.cli import verify
    world, bus, _ = make_world(tmp_path, "vote-game", seasons=3, time__mode="sync")
    asyncio.run(world.run())
    assert verify("vote-game", world.cfg)


# ---------------------------------------------------------------- le bulletin des pêcheurs à IA
from test_rumors import FOUR, Recorder, play_with_announcement

BALLOT_PROVIDERS = {"fake": {"api_key_env": None, "rpm": 0, "json_schema": True}, "scripted": {"latency_scale": 0.0}}


def run_ballot_game(tmp_path, run_id, mode="sync"):
    rec = Recorder(prise=3.0, propose_first=3.0)
    prov = {k: dict(v) for k, v in BALLOT_PROVIDERS.items()}
    prov["fake"]["base_url"] = rec.url
    over = {"time__mode": mode}
    if mode == "async":
        over.update(time__fast=False, time__sim_hours_per_second=60)
    world, events = play_with_announcement(tmp_path, run_id, None, provider=rec, seasons=1, population=FOUR,
                                           llm_overrides={"providers": prov}, **over)
    rec.close()
    return world, events, rec


def test_ai_fishers_who_supported_nothing_get_a_ballot_and_a_rule_is_voted(tmp_path):
    world, events, rec = run_ballot_game(tmp_path, "ballot-sync")
    votes = [e["payload"] for e in events if e["type"] == "llm_call" and e["payload"]["purpose"] == "vote"]
    assert len(votes) == 3 and all(v["system"] == "S1" and v["status"] == "ok" for v in votes)     # les trois qui n'avaient rien soutenu
    assert len([e for e in events if e["type"] == "proposal"]) == 1                                # une seule proposition sur la table
    norm = [e["payload"] for e in events if e["type"] == "norm_adopted"]
    assert len(norm) == 1 and norm[0]["quota"] == 3.0 and len(norm[0]["supporters"]) == 4          # adoptée à l'unanimité
    ballots = [r for r in rec.requests if '"vote"' in r["user"]]
    assert ballots and all(r["max_tokens"] == 10 and len(r["user"]) < 600 for r in ballots)        # un bulletin tient en quelques lignes
    assert all(r["response_format"]["json_schema"]["schema"]["properties"]["vote"]["enum"] == ["P1", "aucune"] for r in ballots)


def test_ballots_are_not_asked_of_the_fake_llm_or_of_those_who_already_voted(tmp_path):
    world, bus, _ = make_world(tmp_path, "ballot-fake", seasons=1, time__mode="sync", population__rule_fraction=0.0)
    asm = Assembly("valley", [a.id for a in world.agents.values()], 1, 29.0)
    speak(world, asm, world.fishers[0], proposition_quota=3.0)
    assert world.ballot_candidates(asm) == []                       # faux LLM : on compte ce que chacun a dit


def test_a_slow_ai_loses_its_vote_but_the_game_goes_on(tmp_path):
    world, events, rec = run_ballot_game(tmp_path, "ballot-async", mode="async")
    assert [e for e in events if e["type"] == "run_end"][0]["payload"]["reason"] == "completed"
    votes = [e["payload"] for e in events if e["type"] == "llm_call" and e["payload"]["purpose"] == "vote"]
    assert votes and all(v["status"] in ("ok", "cancelled") for v in votes)
