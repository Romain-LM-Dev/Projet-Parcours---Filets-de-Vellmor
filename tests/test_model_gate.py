"""File d'attente des requêtes d'un fournisseur local : plafond de simultanéité et regroupement par modèle.

Sur une petite carte graphique, passer d'un modèle à l'autre coûte une dizaine de secondes (1,5B) à une trentaine (7B).
La file doit donc servir toutes les requêtes d'un modèle avant de changer, au lieu d'alterner au gré des arrivées.
"""
from __future__ import annotations

import asyncio

from filets.llm import ModelGate


async def run_requests(gate: ModelGate, models: list[str], hold: float = 0.01):
    """Lance une requête par entrée de `models` (dans cet ordre) ; renvoie l'ordre de service et la simultanéité maximale."""
    served: list[str] = []
    running: list[str] = []
    seen = {"max": 0, "mixed": False}

    async def one(model: str):
        await gate.acquire(model)
        try:
            served.append(model)
            running.append(model)
            seen["max"] = max(seen["max"], len(running))
            if len(set(running)) > 1:
                seen["mixed"] = True                 # deux modèles servis en même temps : jamais souhaité
            await asyncio.sleep(hold)
        finally:
            running.remove(model)
            gate.release()

    tasks = [asyncio.create_task(one(m)) for m in models]
    await asyncio.gather(*tasks)
    return served, seen


def test_requests_are_grouped_by_model_whatever_the_arrival_order():
    gate = ModelGate(slots=1)
    order = list("gpggppgg")                          # grand, petit, grand, grand, petit, petit, grand, grand
    served, _ = asyncio.run(run_requests(gate, order))
    assert served == list("ggggg") + list("ppp"), served
    assert gate.swaps == 1                            # un seul changement de modèle au lieu de quatre


def test_without_grouping_the_same_arrivals_would_swap_four_times():
    swaps = sum(1 for a, b in zip("gpggppgg", "gpggppgg"[1:]) if a != b)
    assert swaps == 4                                 # ce que ferait un serveur qui sert dans l'ordre d'arrivée


def test_concurrency_is_capped_and_never_mixes_two_models():
    gate = ModelGate(slots=3)
    served, seen = asyncio.run(run_requests(gate, list("gpgpgpgpgp"), hold=0.02))
    assert seen["max"] <= 3
    assert seen["max"] >= 2                           # le parallélisme est bien utilisé quand il est permis
    assert not seen["mixed"]
    assert sorted(served) == sorted("gpgpgpgpgp")


def test_a_streak_limit_lets_an_older_waiter_of_another_model_through():
    order = ["g1", "g2", "g3", "p", "g4", "g5", "g6"]
    models = [m[0] for m in order]

    async def scenario(max_streak):
        gate = ModelGate(slots=1, max_streak=max_streak)
        names: list[str] = []

        async def one(label: str):
            await gate.acquire(label[0])
            names.append(label)
            await asyncio.sleep(0.005)
            gate.release()

        await asyncio.gather(*(asyncio.create_task(one(m)) for m in order))
        return names

    unlimited = asyncio.run(scenario(1000))
    assert unlimited[-1] == "p"                       # sans limite, tous les « g » passent d'abord
    limited = asyncio.run(scenario(2))
    assert limited.index("p") < limited.index("g4")   # avec limite, « p », arrivé avant g4, passe avant lui
    assert models and len(limited) == 7


def test_cancelled_waiters_do_not_leak_slots_or_block_the_queue():
    async def scenario():
        gate = ModelGate(slots=1)
        await gate.acquire("g")                       # le créneau est pris
        waiter_b = asyncio.create_task(gate.acquire("g"))
        waiter_c = asyncio.create_task(gate.acquire("p"))
        await asyncio.sleep(0.01)
        waiter_b.cancel()                             # B abandonne en file d'attente
        await asyncio.gather(waiter_b, return_exceptions=True)
        gate.release()                                # A termine : C doit passer
        await asyncio.wait_for(waiter_c, 1)
        assert gate.running == 1
        gate.release()
        assert gate.running == 0
        return gate

    gate = asyncio.run(scenario())
    assert gate.running == 0
    assert all(f.done() for q in gate.waiting.values() for _, f in q)       # il ne reste que des demandes annulées


def test_a_waiter_cancelled_right_after_being_served_gives_its_slot_back():
    async def scenario():
        gate = ModelGate(slots=1)
        await gate.acquire("g")
        first = asyncio.create_task(gate.acquire("g"))
        second = asyncio.create_task(gate.acquire("g"))
        await asyncio.sleep(0.01)
        gate.release()                                # `first` est servi (son futur est résolu)...
        first.cancel()                                # ...mais annulé avant d'avoir repris la main
        await asyncio.gather(first, return_exceptions=True)
        await asyncio.wait_for(second, 1)             # sa place doit revenir à `second`, sans blocage
        assert gate.running == 1
        gate.release()
        return gate.running

    assert asyncio.run(scenario()) == 0


def test_an_idle_gate_serves_any_model_immediately():
    async def scenario():
        gate = ModelGate(slots=2)
        await gate.acquire("g")
        gate.release()
        await asyncio.wait_for(gate.acquire("p"), 0.5)      # personne en service : changer de modèle ne bloque pas
        gate.release()
        return gate.swaps

    assert asyncio.run(scenario()) == 1
