"""evaldash report | summary | gate

report   write the HTML dashboard
summary  print the same numbers as text
gate     exit 1 if a candidate version is worse than a baseline: for CI, so a regression cannot be merged unnoticed
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evaldash import metrics
from evaldash.loader import load_dataset
from evaldash.report import pct, render
from evaldash.stats import paired


def _root(p: str) -> Path:
    path = Path(p).resolve()
    if not path.is_dir():
        sys.exit(f"not a folder: {path}")
    return path


def cmd_report(args) -> int:
    data = load_dataset(_root(args.root))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(data), encoding="utf-8")
    print(f"wrote {out} ({len(data.runs)} runs, {len(data.suites)} result files, {len(data.warnings)} warnings)")
    return 0


def cmd_summary(args) -> int:
    m = metrics.build(load_dataset(_root(args.root)))
    for summary, comparisons in m["suites"]:
        s = summary.suite
        print(f"\n{s.project} / {s.name}")
        for v, r, _ in summary.versions:
            print(f"  {v:<22} {pct(r.value):>5}  ({r.k}/{r.n})  95% interval {pct(r.lo)} to {pct(r.hi)}")
        for c in comparisons:
            print(f"  {c['baseline']} -> {c['candidate']}: {c['delta'] * 100:+.1f} pts, fixed {c['b_only']} / broke {c['a_only']}, p={c['p']:.3f}  => {c['verdict']}")
    print()
    for r in m["runs"]:
        print(f"{r.project} / {r.version:<22} runs={r.n:<3} answered={pct(r.status['answered'].value):>4} p50={r.latency_p50 or 0:.0f} ms cost=${r.total_cost_usd:.4f}")
    for w in m["warnings"]:
        print("warning:", w)
    return 0


def cmd_gate(args) -> int:
    data = load_dataset(_root(args.root))
    suite = next((s for s in data.suites if s.project == args.project and s.name == args.suite), None)
    if suite is None:
        print(f"no result file {args.project}/{args.suite}", file=sys.stderr)
        return 2
    missing = [v for v in (args.baseline, args.candidate) if v not in suite.versions]
    if missing:
        print(f"version(s) not in that suite: {', '.join(missing)}. Available: {', '.join(suite.versions)}", file=sys.stderr)
        return 2
    to_map = lambda v: {i.id: i.success for i in suite.versions[v]}
    res = paired(to_map(args.baseline), to_map(args.candidate))
    print(f"{args.baseline} {pct(res.a_rate)} -> {args.candidate} {pct(res.b_rate)} on {res.n} shared items; fixed {res.b_only}, broke {res.a_only}, p={res.p:.3f}: {res.verdict}")
    failed = res.delta < -args.max_drop or res.verdict == "worse"
    if failed:
        print(f"GATE FAILED: candidate is {abs(res.delta) * 100:.1f} points lower (allowed drop {args.max_drop * 100:.1f}) or significantly worse")
        return 1
    print("GATE PASSED")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evaldash")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("report", cmd_report), ("summary", cmd_summary), ("gate", cmd_gate)):
        p = sub.add_parser(name)
        p.add_argument("--root", default="..", help="folder that contains the project folders (default: the parent folder)")
        p.set_defaults(fn=fn)
        if name == "report":
            p.add_argument("--out", default="dashboard/index.html")
        if name == "gate":
            p.add_argument("--project", required=True)
            p.add_argument("--suite", required=True)
            p.add_argument("--baseline", required=True)
            p.add_argument("--candidate", required=True)
            p.add_argument("--max-drop", type=float, default=0.05, help="largest allowed drop in success rate (0.05 = 5 points)")
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
