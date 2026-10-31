"""Reads what the agent projects already write, without changing them.

Two kinds of input:
  run records   <project>/data/runs/<version>/<run_id>.json        one per question (cost, latency, status, reasons)
  result files  <project>/evals/results/*.json                      per-item pass/fail from an evaluation run

Anything unreadable or unrecognised is counted and reported, never silently dropped.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_SCHEMA = 1


@dataclass
class Run:
    project: str
    version: str
    run_id: str
    status: str
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    llm_calls: int
    searches: int
    reasons: list[str]
    verified: bool | None
    created_at: float


@dataclass
class Item:
    id: str
    success: bool
    group: str = ""


@dataclass
class Suite:
    project: str
    name: str  # e.g. "agents", "tasks", "attacks"
    kind: str  # "versions" (several versions), "tasks" or "attacks"
    versions: dict[str, list[Item]] = field(default_factory=dict)
    success_means: str = "passed the scenario"


@dataclass
class Dataset:
    runs: list[Run] = field(default_factory=list)
    suites: list[Suite] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _num(value, default=0.0):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def load_runs(directory: Path, project: str, warnings: list[str]) -> list[Run]:
    runs: list[Run] = []
    for path in sorted(directory.glob("*/*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            if d.get("schema_version") != SUPPORTED_SCHEMA:
                warnings.append(f"{project}: {path.name} has schema_version {d.get('schema_version')!r}, expected {SUPPORTED_SCHEMA}; skipped")
                continue
            runs.append(Run(project=project, version=str(d["version"]), run_id=str(d.get("run_id", path.stem)), status=str(d["status"]),
                            latency_ms=_num(d.get("latency_ms")), input_tokens=int(_num(d.get("input_tokens"))), output_tokens=int(_num(d.get("output_tokens"))),
                            cost_usd=_num(d.get("cost_usd")), llm_calls=int(_num(d.get("llm_calls"))), searches=int(_num(d.get("searches"))),
                            reasons=[str(r) for r in d.get("reasons", [])], verified=d.get("verified"), created_at=_num(d.get("created_at"))))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            warnings.append(f"{project}: could not read {path.name}: {type(exc).__name__}")
    return runs


def _scores(entries: list) -> list[dict]:
    return [e for e in entries if isinstance(e, dict) and "id" in e]


def parse_results(path: Path, project: str, warnings: list[str]) -> Suite | None:
    """Recognises three shapes: {version: {summary, scores}}, {summary, scores} of tasks, and {summary, scores} of attacks."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        warnings.append(f"{project}: could not read {path.name}: {type(exc).__name__}")
        return None
    if isinstance(d, dict) and d and all(isinstance(v, dict) and "scores" in v for v in d.values()):
        suite = Suite(project, path.stem, "versions")
        for version, body in d.items():
            suite.versions[version] = [Item(str(s["id"]), bool(s.get("success")), str(s.get("type", ""))) for s in _scores(body["scores"])]
        return suite
    if isinstance(d, dict) and isinstance(d.get("scores"), list):
        scores = _scores(d["scores"])
        if scores and "hijacked" in scores[0]:
            suite = Suite(project, path.stem, "attacks", success_means="resisted: the model was not hijacked")
            suite.versions["agent"] = [Item(str(s["id"]), not s["hijacked"], str(s.get("attack", ""))) for s in scores]
            return suite
        if scores and "success" in scores[0]:
            suite = Suite(project, path.stem, "tasks")
            suite.versions["agent"] = [Item(str(s["id"]), bool(s["success"])) for s in scores]
            return suite
    warnings.append(f"{project}: {path.name} is not a recognised results file; skipped")
    return None


def load_dataset(root: Path) -> Dataset:
    """Scan every sibling project under `root` that has data/runs and/or evals/results."""
    data = Dataset()
    for project_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        runs_dir, results_dir = project_dir / "data" / "runs", project_dir / "evals" / "results"
        if runs_dir.is_dir():
            data.runs += load_runs(runs_dir, project_dir.name, data.warnings)
        if results_dir.is_dir():
            for f in sorted(results_dir.glob("*.json")):
                suite = parse_results(f, project_dir.name, data.warnings)
                if suite:
                    data.suites.append(suite)
    return data
