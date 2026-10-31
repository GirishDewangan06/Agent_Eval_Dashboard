"""Turns loaded data into the numbers the dashboard and the CLI show. Pure functions, no I/O."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from evaldash.loader import Dataset, Run, Suite
from evaldash.stats import bootstrap_ci, mean, paired, percentile, wilson

STATUSES = ("answered", "abstained", "blocked", "error")


@dataclass
class Rate:
    k: int
    n: int
    lo: float
    hi: float

    @property
    def value(self) -> float:
        return self.k / self.n if self.n else 0.0


def rate(k: int, n: int) -> Rate:
    lo, hi = wilson(k, n)
    return Rate(k, n, lo, hi)


@dataclass
class RunSummary:
    project: str
    version: str
    n: int
    status: dict[str, Rate]
    latency_p50: float | None
    latency_p95: float | None
    latency_mean_ci: tuple[float, float] | None
    avg_llm_calls: float | None
    avg_searches: float | None
    avg_tokens: float | None
    total_cost_usd: float
    verified: Rate | None
    reasons: list[tuple[str, int]] = field(default_factory=list)


def summarize_runs(runs: list[Run]) -> list[RunSummary]:
    groups: dict[tuple[str, str], list[Run]] = {}
    for r in runs:
        groups.setdefault((r.project, r.version), []).append(r)
    out = []
    for (project, version), rs in sorted(groups.items()):
        n = len(rs)
        lat = [r.latency_ms for r in rs if r.latency_ms > 0]
        checked = [r.verified for r in rs if r.verified is not None]
        reasons = Counter(x.split(":")[0] for r in rs for x in set(r.reasons))
        out.append(RunSummary(project, version, n, {s: rate(sum(r.status == s for r in rs), n) for s in STATUSES},
                              percentile(lat, 0.5), percentile(lat, 0.95), bootstrap_ci(lat),
                              mean([r.llm_calls for r in rs]), mean([r.searches for r in rs]),
                              mean([r.input_tokens + r.output_tokens for r in rs]), round(sum(r.cost_usd for r in rs), 6),
                              rate(sum(bool(v) for v in checked), len(checked)) if checked else None, reasons.most_common(6)))
    return out


@dataclass
class SuiteSummary:
    suite: Suite
    versions: list[tuple[str, Rate, dict[str, Rate]]]  # version, overall, by group


def summarize_suite(suite: Suite) -> SuiteSummary:
    rows = []
    for version, items in suite.versions.items():
        groups: dict[str, list[bool]] = {}
        for it in items:
            if it.group:
                groups.setdefault(it.group, []).append(it.success)
        rows.append((version, rate(sum(i.success for i in items), len(items)), {g: rate(sum(v), len(v)) for g, v in sorted(groups.items())}))
    return SuiteSummary(suite, rows)


def compare_suite(suite: Suite) -> list[dict]:
    """Each version against the one before it, and against the first. Same items on both sides, so the comparison is paired."""
    names = list(suite.versions)
    results = {v: {i.id: i.success for i in items} for v, items in suite.versions.items()}
    pairs = [(names[i - 1], names[i]) for i in range(1, len(names))]
    pairs += [(names[0], n) for n in names[2:]]
    return [{"baseline": a, "candidate": b, **paired(results[a], results[b]).to_dict()} for a, b in pairs]


def failing_items(suite: Suite, version: str) -> list[str]:
    return [i.id for i in suite.versions.get(version, []) if not i.success]


def build(data: Dataset) -> dict:
    return {"runs": summarize_runs(data.runs), "suites": [(summarize_suite(s), compare_suite(s)) for s in data.suites], "warnings": data.warnings}
