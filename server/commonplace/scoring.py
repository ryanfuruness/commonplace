"""Evidence arithmetic for Commonplace.

Everything here is deterministic and dependency-free. The server owns the
arithmetic (weights, posteriors, thresholds); curators own the judgment.

An entry's quality is a Beta posterior over "probability this entry helps when
it is used". Evidence comes only from usage reports, never from ratings:

  * each report contributes an outcome o in [0, 1] with a weight w
  * alpha = PRIOR + sum(w * o), beta = PRIOR + sum(w * (1 - o))

Weights encode how much a report should be believed:

  * grounded in a human reaction (accepted / corrected / rejected) -> 1.0,
    the agent's own assessment with no human signal -> 0.5
  * the k-th report from the same reporter in the same situation is
    discounted by 0.5**k, so repeating one judgment cannot manufacture
    consensus; the same person using an entry across different situations
    is real evidence of breadth and counts in full
  * stale reports count half: when a curator makes a material revision, the
    reports that preceded it describe an entry that no longer exists in that
    form. Staleness is a property of the report, so it survives merges and
    splits. Rewording and boundary edits are not material and stale nothing.

Distinct reporters are counted excluding the entry's author, so an author
cannot promote their own entry alone. A personal commons, where every report
comes from the author, sets the reporter thresholds to 0.
"""

from __future__ import annotations

import math
import os
import random
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Sequence

OUTCOME_VALUE = {"success": 1.0, "partial": 0.5, "failure": 0.0}
HUMAN_SIGNALS = ("accepted", "corrected", "rejected", "none")
PRIOR = 1.0


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Thresholds:
    """Promotion and retirement thresholds. Defaults suit a small team.

    `*_reporters` counts distinct contributors other than the entry's author.
    A personal deployment has exactly one contributor, so it sets both to 0.
    """

    pattern_n_eff: float = 3.0
    pattern_low: float = 0.50
    pattern_situations: int = 2
    pattern_reporters: int = 1
    canonical_n_eff: float = 8.0
    canonical_low: float = 0.70
    canonical_situations: int = 4
    canonical_reporters: int = 2
    retire_n_eff: float = 4.0
    retire_mean: float = 0.35

    @classmethod
    def from_env(cls) -> "Thresholds":
        d = cls()
        return cls(
            pattern_n_eff=_env_float("CP_PATTERN_N_EFF", d.pattern_n_eff),
            pattern_low=_env_float("CP_PATTERN_LOW", d.pattern_low),
            pattern_situations=int(_env_float("CP_PATTERN_SITUATIONS", d.pattern_situations)),
            pattern_reporters=int(_env_float("CP_PATTERN_REPORTERS", d.pattern_reporters)),
            canonical_n_eff=_env_float("CP_CANONICAL_N_EFF", d.canonical_n_eff),
            canonical_low=_env_float("CP_CANONICAL_LOW", d.canonical_low),
            canonical_situations=int(_env_float("CP_CANONICAL_SITUATIONS", d.canonical_situations)),
            canonical_reporters=int(_env_float("CP_CANONICAL_REPORTERS", d.canonical_reporters)),
            retire_n_eff=_env_float("CP_RETIRE_N_EFF", d.retire_n_eff),
            retire_mean=_env_float("CP_RETIRE_MEAN", d.retire_mean),
        )


# --------------------------------------------------------------------------
# Beta distribution helpers (regularized incomplete beta + quantile)
# --------------------------------------------------------------------------

def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    return h


def beta_cdf(x: float, a: float, b: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log(1.0 - x)
    )
    front = math.exp(ln_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def beta_ppf(q: float, a: float, b: float) -> float:
    """Quantile of Beta(a, b) by bisection. Accurate to ~1e-9."""
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if beta_cdf(mid, a, b) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# --------------------------------------------------------------------------
# Situations
# --------------------------------------------------------------------------

_STOP = {
    "a", "an", "and", "the", "of", "for", "in", "on", "to", "with", "by", "at",
    "or", "from", "into", "as", "is", "are", "be", "this", "that", "it", "its",
}


def fold(text: str) -> str:
    """Casefold and strip diacritics, matching SQLite's unicode61 tokenizer."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def tokens(text: str | None, *, strip_marks: bool = True) -> list[str]:
    """Word tokens for comparing situations and entries.

    Full-text queries pass strip_marks=False and leave diacritic handling to
    SQLite's tokenizer, which applies the same folding to the index and the
    query; stripping here as well would diverge from it for non-Latin scripts.
    """
    if not text:
        return []
    base = fold(text) if strip_marks else text.casefold()
    return [t for t in re.findall(r"[^\W_]+", base) if len(t) > 1 and t not in _STOP]


def situation_key(task: str | None, domain: str | None) -> str:
    """Coarse fingerprint used to count distinct situations.

    Order-insensitive bag of task + domain tokens. Agents phrase situations
    differently, so this over-counts rather than under-counts; the curator
    reviews every promotion, and canonical promotion needs a human.
    """
    return " ".join(sorted(set(tokens(task) + tokens(domain))))


# --------------------------------------------------------------------------
# Quality
# --------------------------------------------------------------------------

@dataclass
class ReportView:
    reporter: str
    outcome: str
    human_signal: str
    task: str | None
    domain: str | None
    created_at: str
    stale: bool = False
    is_author: bool = False
    id: str = ""
    situation: str | None = None


@dataclass
class Quality:
    alpha: float
    beta: float
    n_eff: float
    reports: int            # reports that count toward quality
    not_applicable: int     # opened but did not fit; a retrieval signal, not a quality one
    reporters: int          # distinct reporters other than the author
    situations: int

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def low(self) -> float:
        return beta_ppf(0.05, self.alpha, self.beta)

    @property
    def high(self) -> float:
        return beta_ppf(0.95, self.alpha, self.beta)

    def sample(self, rng: random.Random | None = None) -> float:
        r = rng or random
        return r.betavariate(self.alpha, self.beta)

    def as_dict(self) -> dict:
        return {
            "mean": round(self.mean, 3),
            "interval_90": [round(self.low, 3), round(self.high, 3)],
            "evidence": round(self.n_eff, 2),
            "reports": self.reports,
            "independent_reporters": self.reporters,
            "distinct_situations": self.situations,
            "did_not_fit": self.not_applicable,
        }


def report_weights(reports: Sequence[ReportView]) -> list[float]:
    ordered = sorted(range(len(reports)), key=lambda i: reports[i].created_at)
    seen: dict[str, int] = {}
    weights = [0.0] * len(reports)
    for i in ordered:
        r = reports[i]
        if r.outcome not in OUTCOME_VALUE:
            continue
        key = f"{r.reporter}|{situation_key(r.task, r.domain)}"
        k = seen.get(key, 0)
        seen[key] = k + 1
        w = 1.0 if r.human_signal in ("accepted", "corrected", "rejected") else 0.5
        w *= 0.5 ** k
        if r.stale:
            w *= 0.5
        weights[i] = w
    return weights


def compute_quality(reports: Sequence[ReportView]) -> Quality:
    weights = report_weights(reports)
    a, b, n = PRIOR, PRIOR, 0.0
    counted, na = 0, 0
    reporters: set[str] = set()
    situations: set[str] = set()
    for r, w in zip(reports, weights):
        if r.outcome == "not_applicable":
            na += 1
            continue
        o = OUTCOME_VALUE[r.outcome]
        a += w * o
        b += w * (1.0 - o)
        n += w
        counted += 1
        if not r.is_author:
            reporters.add(r.reporter)
        situations.add(situation_key(r.task, r.domain))
    return Quality(a, b, n, counted, na, len(reporters), len(situations))


def next_tier_ready(tier: str, q: Quality, t: Thresholds) -> tuple[str | None, list[str]]:
    """Which tier this entry is eligible for next, and what is still missing."""
    if tier == "note":
        target, need = "pattern", [
            (q.n_eff >= t.pattern_n_eff, f"evidence {q.n_eff:.1f}/{t.pattern_n_eff:g}"),
            (q.low >= t.pattern_low, f"lower bound {q.low:.2f}/{t.pattern_low:g}"),
            (q.situations >= t.pattern_situations, f"situations {q.situations}/{t.pattern_situations}"),
            (q.reporters >= t.pattern_reporters, f"independent reporters {q.reporters}/{t.pattern_reporters}"),
        ]
    elif tier == "pattern":
        target, need = "canonical", [
            (q.n_eff >= t.canonical_n_eff, f"evidence {q.n_eff:.1f}/{t.canonical_n_eff:g}"),
            (q.low >= t.canonical_low, f"lower bound {q.low:.2f}/{t.canonical_low:g}"),
            (q.situations >= t.canonical_situations, f"situations {q.situations}/{t.canonical_situations}"),
            (q.reporters >= t.canonical_reporters, f"independent reporters {q.reporters}/{t.canonical_reporters}"),
        ]
    else:
        return None, []
    missing = [label for ok, label in need if not ok]
    return (target if not missing else None), missing


def retire_candidate(q: Quality, t: Thresholds) -> bool:
    return q.n_eff >= t.retire_n_eff and q.mean <= t.retire_mean


def situation_divergence(reports: Sequence[ReportView], min_weight: float = 1.5) -> dict | None:
    """Detect an entry that works in one kind of situation and fails in another.

    Agents describe situations in their own words, so exact situation labels
    rarely repeat. Instead, look for a term that divides the reports: for each
    term in the reports' domain and situation text, compare the weighted success
    rate of reports that mention it with those that do not. A term that splits
    them into a group that mostly fails (<= 0.3) and a group that mostly succeeds
    (>= 0.7), both with enough evidence, is the likely boundary: "consumer" when
    every consumer use failed and every enterprise use succeeded. The curator
    reads the reports to confirm the real dividing line before acting.
    """
    weights = report_weights(reports)
    rows = [(r, w, set(tokens(r.domain) + tokens(r.situation)))
            for r, w in zip(reports, weights) if r.outcome in OUTCOME_VALUE and w > 0]
    if len(rows) < 3:
        return None
    vocab = {t for _, _, ts in rows for t in ts}
    best = None
    for term in sorted(vocab):
        inside = [(r, w) for r, w, ts in rows if term in ts]
        outside = [(r, w) for r, w, ts in rows if term not in ts]
        w_in, w_out = sum(w for _, w in inside), sum(w for _, w in outside)
        if w_in < min_weight or w_out < min_weight:
            continue
        rate_in = sum(w * OUTCOME_VALUE[r.outcome] for r, w in inside) / w_in
        rate_out = sum(w * OUTCOME_VALUE[r.outcome] for r, w in outside) / w_out
        if max(rate_in, rate_out) >= 0.7 and min(rate_in, rate_out) <= 0.3:
            key = (abs(rate_in - rate_out), min(w_in, w_out))
            if best is None or key > best[0]:
                best = (key, term, rate_in, w_in, rate_out, w_out, inside, outside)
    if best is None:
        return None
    _, term, rate_in, w_in, rate_out, w_out, inside, outside = best
    return {
        "dividing_term": term,
        "with_term": {"success_rate": round(rate_in, 2), "evidence": round(w_in, 2),
                      "report_ids": [r.id for r, _ in inside]},
        "without_term": {"success_rate": round(rate_out, 2), "evidence": round(w_out, 2),
                         "report_ids": [r.id for r, _ in outside]},
    }


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)
