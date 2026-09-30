"""Does the ranking let a better late entry overtake an established one?

Agents keep doing the same kind of task. An incumbent entry is in the commons
from the start. At step 50 a better entry is contributed, along with a weak
one. Each step, one agent searches, applies the top result, and reports the
outcome. All entries match the query equally well, so ranking comes down to
quality alone. Every report is human-grounded and from a distinct situation,
so each carries full weight and the comparison isolates the ranking rule.

Ranking rules compared:

  counts    confidence starts at 0.5, +0.1 per success, -0.15 per failure,
            clamped to [0, 1] (the confirm/flag scheme common in agent
            knowledge stores); ties go to the older entry
  mean      posterior mean of Beta(1 + successes, 1 + failures)
  thompson  a draw from that posterior (Commonplace's rule)

Run: python sim/simulate_ranking.py
"""

from __future__ import annotations

import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commonplace.scoring import ReportView, compute_quality  # noqa: E402

STEPS, ARRIVAL, RUNS = 400, 50, 1000
SCENARIOS = {
    "mediocre incumbent (65%) vs better newcomer (85%)": {"incumbent": 0.65, "better": 0.85, "weak": 0.35},
    "good incumbent (80%) vs better newcomer (95%)": {"incumbent": 0.80, "better": 0.95, "weak": 0.35},
}


def run(true_p: dict, rule: str, seed: int, audit: bool = False) -> dict:
    rng = random.Random(seed)
    wins = {k: 0 for k in true_p}
    losses = {k: 0 for k in true_p}
    counts = {k: 0.5 for k in true_p}
    log: dict[str, list[ReportView]] = {k: [] for k in true_p}
    picks, successes = [], 0
    for step in range(STEPS):
        live = ["incumbent"] + (["better", "weak"] if step >= ARRIVAL else [])
        if rule == "counts":
            choice = max(live, key=lambda k: (counts[k], -live.index(k)))
        elif rule == "mean":
            choice = max(live, key=lambda k: (1 + wins[k]) / (2 + wins[k] + losses[k]))
        else:
            choice = max(live, key=lambda k: rng.betavariate(1 + wins[k], 1 + losses[k]))
        ok = rng.random() < true_p[choice]
        successes += ok
        wins[choice] += ok
        losses[choice] += not ok
        counts[choice] = min(1.0, max(0.0, counts[choice] + (0.1 if ok else -0.15)))
        picks.append(choice)
        if audit:
            log[choice].append(ReportView(reporter=f"r{step}", outcome="success" if ok else "failure",
                                          human_signal="accepted", task="task",
                                          domain=f"situation{step}", created_at=f"{step:06d}"))
    if audit:
        # The simulation's incremental posterior must match the server's scoring code exactly.
        for k in true_p:
            q = compute_quality(log[k])
            assert abs(q.alpha - (1 + wins[k])) < 1e-9 and abs(q.beta - (1 + losses[k])) < 1e-9
    tail = picks[-100:]
    best_possible = ARRIVAL * true_p["incumbent"] + (STEPS - ARRIVAL) * true_p["better"]
    return {
        "better_share_last100": tail.count("better") / len(tail),
        "regret": best_possible - successes,
        "better_ever_tried": "better" in picks,
    }


def main() -> None:
    for name, true_p in SCENARIOS.items():
        run(true_p, "thompson", 0, audit=True)
        print(f"\n{name}; {RUNS} runs x {STEPS} steps, newcomer arrives at step {ARRIVAL}")
        print(f"  {'rule':<10}{'newcomer share, last 100':>26}{'regret':>9}{'newcomer ever tried':>22}")
        for rule in ("counts", "mean", "thompson"):
            rs = [run(true_p, rule, s) for s in range(RUNS)]
            share = statistics.mean(r["better_share_last100"] for r in rs)
            regret = statistics.mean(r["regret"] for r in rs)
            tried = sum(r["better_ever_tried"] for r in rs) / RUNS
            print(f"  {rule:<10}{share:>25.0%}{regret:>9.1f}{tried:>21.0%}")


if __name__ == "__main__":
    main()
