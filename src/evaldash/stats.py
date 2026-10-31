"""Small, dependency-free statistics. The point of this project is that a score without an interval is not a result.

  wilson        interval for a rate such as 'passed 11 of 12'. Behaves sensibly at 0%, 100% and small n (unlike the normal approximation).
  bootstrap_ci  interval for any statistic (mean latency, p95, ...) by resampling.
  paired        compare two versions on the SAME items: sign test on the items where they disagree, plus a bootstrap interval for the difference.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable, Sequence

Z95 = 1.959964


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def percentile(values: Sequence[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[int(p * (len(ordered) - 1))]


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def bootstrap_ci(values: Sequence[float], stat: Callable[[Sequence[float]], float | None] = mean, n_boot: int = 2000,
                 alpha: float = 0.05, seed: int = 0) -> tuple[float, float] | None:
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    k = len(values)
    draws = sorted(s for s in (stat([values[rng.randrange(k)] for _ in range(k)]) for _ in range(n_boot)) if s is not None)
    return (draws[int(alpha / 2 * (len(draws) - 1))], draws[int((1 - alpha / 2) * (len(draws) - 1))])


def sign_test_p(wins: int, losses: int) -> float:
    """Exact two-sided sign test on the items where two versions disagree. Ties carry no information and are ignored."""
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(wins, losses) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


@dataclass
class Paired:
    n: int  # items both versions were scored on
    a_rate: float
    b_rate: float
    delta: float  # b - a
    ci: tuple[float, float] | None
    b_only: int  # b passed, a failed
    a_only: int  # a passed, b failed
    p: float
    verdict: str  # better | worse | within noise | too few items

    def to_dict(self) -> dict:
        return {**self.__dict__, "ci": list(self.ci) if self.ci else None}


def paired(a: dict[str, bool], b: dict[str, bool], alpha: float = 0.05, seed: int = 0, min_disagree: int = 1) -> Paired:
    """Is version b better than version a on the items both were scored on? Verdict is 'within noise' unless the sign test is significant."""
    ids = sorted(set(a) & set(b))
    n = len(ids)
    if n == 0:
        return Paired(0, 0.0, 0.0, 0.0, None, 0, 0, 1.0, "too few items")
    b_only = sum(1 for i in ids if b[i] and not a[i])
    a_only = sum(1 for i in ids if a[i] and not b[i])
    a_rate, b_rate = sum(a[i] for i in ids) / n, sum(b[i] for i in ids) / n
    diffs = [float(b[i]) - float(a[i]) for i in ids]
    ci = bootstrap_ci(diffs, seed=seed)
    p = sign_test_p(b_only, a_only)
    if b_only + a_only < min_disagree:
        verdict = "within noise"
    elif p < alpha:
        verdict = "better" if b_only > a_only else "worse"
    else:
        verdict = "within noise"
    return Paired(n, a_rate, b_rate, b_rate - a_rate, ci, b_only, a_only, p, verdict)
