"""Affichage console d'une partie : le fil des événements et le bilan final."""
from __future__ import annotations


def console_printer():
    def show(ev):
        t, p = ev["type"], ev["payload"]
        lab = ev["sim_label"]
        if t == "season_start":
            print(f"\n=== {lab} · saison {ev['season']} · stock {p['stock']:.1f} t")
        elif t == "catch":
            extra = " (rationné)" if p["rationed"] else ""
            print(f"  {lab}  {p['agent']} pêche {p['landed']:.1f} t (voulait {p['requested']:.1f}, "
                  f"croyait le lac à {p['stock_observed']:.0f} t, il était à {p['stock_at_action']:.0f}){extra}")
        elif t == "utterance":
            to = "" if p["to"] == "tous" else f" → {p['to']}"
            print(f"  {lab}  [{p['scope']} t{p['round']}] {p['speaker']}{to} : {p['text']}")
        elif t == "norm_adopted":
            print(f"  {lab}  ✔ règle adoptée ({p['scope']}) : {p['quota']} t/pêcheur dès la saison "
                  f"{p['effective_season']}, soutiens {p['supporters']}")
        elif t == "promise_outcome" and not p["kept"]:
            print(f"  {lab}  ✘ {p['agent']} avait promis {p['promised']} t, a pêché {p['landed']:.1f} t")
        elif t == "incident":
            print(f"  {lab}  ! incident {p['incident_type']} ({p['agent']}) → {p['handled_by']}")
        elif t == "injection":
            print(f"  {lab}  ⚡ {p['injection_type']} {p['params']}")
        elif t == "lake_collapsed":
            print(f"  {lab}  ☠ le lac s'effondre ({p['stock']:.1f} t)")
        elif t == "season_end":
            print(f"  {lab}  fin de saison · stock après repeuplement {p['stock']:.1f} t")
    return show


def print_summary(world, pub) -> None:
    u = world.router.usage
    print(f"\nRun {world.run_id} terminé ({world.stopped_reason}) · stock final {world.lake.stock:.1f} / "
          f"{world.capacity:.0f} t · {u.calls} appels LLM, {u.prompt_tokens + u.completion_tokens} tokens")
    if pub and pub.engine.history:
        print("saison  stock%  prises  norme  accord  conform.  promesses  cv")
        for h in pub.engine.history:
            pk = "-" if h["promise_kept_rate"] is None else f"{h['promise_kept_rate']:.2f}"
            print(f"{h['season']:>6}  {h['stock_ratio'] * 100:5.0f}  {h['total_catch']:6.1f}  {h['norm_index']:.2f}"
                  f"   {h['norm_agreement']:.2f}    {h['norm_compliance']:.2f}      {pk:>5}  {h['catch_cv']:.2f}")
    print(f"Enregistré dans {world.run_dir}")
