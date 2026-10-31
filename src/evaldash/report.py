"""Renders one self-contained HTML page: no JavaScript, no CDN, no server. Charts are inline SVG, so the file opens anywhere and can be hosted as-is."""
from __future__ import annotations

import html
import time

from evaldash.metrics import RunSummary, SuiteSummary, failing_items
from evaldash.loader import Dataset
from evaldash import metrics

e = html.escape

CSS = """
:root{--bg:#fff;--fg:#1f2937;--mut:#64748b;--line:#e2e8f0;--card:#f8fafc;--acc:#0f766e;--bad:#b91c1c;--ok:#15803d;--warn:#a16207;--bar:#0f766e;--whisk:#1f2937}
@media(prefers-color-scheme:dark){:root{--bg:#0f172a;--fg:#e2e8f0;--mut:#94a3b8;--line:#334155;--card:#1e293b;--acc:#2dd4bf;--bad:#f87171;--ok:#4ade80;--warn:#facc15;--bar:#2dd4bf;--whisk:#e2e8f0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 60px}h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:34px 0 8px;color:var(--acc)}h3{font-size:15px;margin:18px 0 6px}
p{margin:6px 0}.mut{color:var(--mut)}.note{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--warn);padding:10px 14px;border-radius:6px;margin:12px 0}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:13.5px}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}th{color:var(--mut);font-weight:600}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}.tbl{overflow-x:auto}
.v{font-weight:600}.better{color:var(--ok)}.worse{color:var(--bad)}.noise{color:var(--mut)}svg{max-width:100%;height:auto}svg text{fill:var(--fg);font:12px system-ui,sans-serif}
code{background:var(--card);padding:1px 5px;border-radius:4px}
"""


def pct(x: float | None, d: int = 0) -> str:
    return "n/a" if x is None else f"{x * 100:.{d}f}%"


def ms(x: float | None) -> str:
    return "n/a" if x is None else (f"{x / 1000:.1f} s" if x >= 1000 else f"{x:.0f} ms")


def money(x: float) -> str:
    return f"${x:.4f}" if x else "not recorded"


def rate_chart(rows: list[tuple[str, "metrics.Rate"]]) -> str:
    """Horizontal bars (0 to 100%) with a whisker for the 95% interval. The whisker is the point of the chart."""
    left, width, row_h = 150, 560, 30
    h = row_h * len(rows) + 28
    out = [f'<svg viewBox="0 0 {left + width + 90} {h}" role="img" aria-label="Success rate with 95% confidence interval per version">']
    for t in (0, .25, .5, .75, 1):
        x = left + t * width
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="0" y2="{h - 20}" stroke="var(--line)"/><text x="{x:.1f}" y="{h - 5}" text-anchor="middle">{int(t * 100)}%</text>')
    for i, (label, r) in enumerate(rows):
        y = i * row_h + 6
        out.append(f'<text x="{left - 8}" y="{y + 14}" text-anchor="end">{e(label)}</text>')
        out.append(f'<rect x="{left}" y="{y}" width="{max(r.value * width, 1):.1f}" height="18" fill="var(--bar)" opacity=".55" rx="2"/>')
        lo, hi, mid = left + r.lo * width, left + r.hi * width, y + 9
        out.append(f'<line x1="{lo:.1f}" x2="{hi:.1f}" y1="{mid}" y2="{mid}" stroke="var(--whisk)" stroke-width="2"/>'
                   f'<line x1="{lo:.1f}" x2="{lo:.1f}" y1="{mid - 5}" y2="{mid + 5}" stroke="var(--whisk)" stroke-width="2"/>'
                   f'<line x1="{hi:.1f}" x2="{hi:.1f}" y1="{mid - 5}" y2="{mid + 5}" stroke="var(--whisk)" stroke-width="2"/>')
        out.append(f'<text x="{left + width + 8}" y="{y + 14}">{pct(r.value)} ({r.k}/{r.n})</text>')
    out.append("</svg>")
    return "".join(out)


def suite_section(summary: SuiteSummary, comparisons: list[dict]) -> str:
    s = summary.suite
    parts = [f'<h2>{e(s.project)} / {e(s.name)}</h2><p class="mut">Success means: {e(s.success_means)}. Whiskers are 95% Wilson intervals.</p>',
             rate_chart([(v, r) for v, r, _ in summary.versions])]
    groups = sorted({g for _, _, gs in summary.versions for g in gs})
    head = "".join(f'<th class="n">{e(g)}</th>' for g in groups)
    rows = "".join(f'<tr><td class="v">{e(v)}</td><td class="n">{pct(r.value)}</td><td class="n">{pct(r.lo)} to {pct(r.hi)}</td>'
                   + "".join(f'<td class="n">{pct(gs[g].value)} <span class="mut">({gs[g].k}/{gs[g].n})</span></td>' if g in gs else '<td class="n">-</td>' for g in groups) + "</tr>"
                   for v, r, gs in summary.versions)
    parts.append(f'<div class="tbl"><table><tr><th>version</th><th class="n">success</th><th class="n">95% interval</th>{head}</tr>{rows}</table></div>')
    if comparisons:
        body = ""
        for c in comparisons:
            klass = {"better": "better", "worse": "worse"}.get(c["verdict"], "noise")
            ci = f'{c["ci"][0] * 100:+.0f} to {c["ci"][1] * 100:+.0f} pts' if c["ci"] else "n/a"
            body += (f'<tr><td>{e(c["baseline"])} &rarr; <span class="v">{e(c["candidate"])}</span></td><td class="n">{c["n"]}</td><td class="n">{c["delta"] * 100:+.1f} pts</td>'
                     f'<td class="n">{ci}</td><td class="n">{c["b_only"]} / {c["a_only"]}</td><td class="n">{c["p"]:.3f}</td><td class="{klass} v">{e(c["verdict"])}</td></tr>')
        parts.append('<h3>Is the change real? (paired, same items)</h3><div class="tbl"><table><tr><th>comparison</th><th class="n">items</th><th class="n">change</th><th class="n">95% interval</th>'
                     f'<th class="n">fixed / broke</th><th class="n">sign-test p</th><th>verdict</th></tr>{body}</table></div>'
                     '<p class="mut">"fixed / broke" counts the items that went from fail to pass and from pass to fail. Only those items carry information.</p>')
    for v, _, _ in summary.versions:
        bad = failing_items(s, v)
        if bad:
            parts.append(f'<p class="mut"><b>{e(v)}</b> failed: {e(", ".join(bad[:30]))}{" ..." if len(bad) > 30 else ""}</p>')
    return "".join(parts)


def runs_section(runs: list[RunSummary]) -> str:
    if not runs:
        return ""
    rows = ""
    for r in runs:
        ci = f' <span class="mut">({ms(r.latency_mean_ci[0])} to {ms(r.latency_mean_ci[1])} mean)</span>' if r.latency_mean_ci else ""
        rows += (f'<tr><td>{e(r.project)}</td><td class="v">{e(r.version)}</td><td class="n">{r.n}</td><td class="n">{pct(r.status["answered"].value)}</td>'
                 f'<td class="n">{pct(r.status["abstained"].value)}</td><td class="n">{pct(r.status["blocked"].value)}</td><td class="n">{pct(r.status["error"].value)}</td>'
                 f'<td class="n">{ms(r.latency_p50)} / {ms(r.latency_p95)}{ci}</td><td class="n">{r.avg_llm_calls:.1f}</td><td class="n">{r.avg_searches:.1f}</td>'
                 f'<td class="n">{r.avg_tokens:,.0f}</td><td class="n">{money(r.total_cost_usd)}</td></tr>')
    reasons = "".join(f'<tr><td>{e(r.project)} / <span class="v">{e(r.version)}</span></td><td>{e(", ".join(f"{k} ({c})" for k, c in r.reasons)) or "-"}</td></tr>' for r in runs)
    return ('<h2>Run records: cost, speed and behaviour</h2><p class="mut">Every question asked of every version, as recorded at run time. Different versions may have been asked different numbers of questions.</p>'
            '<div class="tbl"><table><tr><th>project</th><th>version</th><th class="n">runs</th><th class="n">answered</th><th class="n">abstained</th><th class="n">blocked</th><th class="n">error</th>'
            f'<th class="n">latency p50 / p95</th><th class="n">LLM calls</th><th class="n">tool/search calls</th><th class="n">tokens/run</th><th class="n">cost</th></tr>{rows}</table></div>'
            f'<h3>Most common reasons recorded</h3><div class="tbl"><table><tr><th>version</th><th>reasons (number of runs)</th></tr>{reasons}</table></div>')


def render(data: Dataset) -> str:
    m = metrics.build(data)
    suites = "".join(suite_section(s, c) for s, c in m["suites"]) or '<p class="mut">No result files found.</p>'
    warn = f'<div class="note"><b>Skipped input ({len(m["warnings"])}):</b><br>' + "<br>".join(e(w) for w in m["warnings"][:15]) + "</div>" if m["warnings"] else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Agent Eval Dashboard</title><style>{CSS}</style></head>
<body><main><h1>Agent evaluation dashboard</h1>
<p class="mut">{len(data.runs)} run records and {len(data.suites)} result files from {len({r.project for r in data.runs} | {s.project for s in data.suites})} projects. Generated {time.strftime("%Y-%m-%d %H:%M")}.</p>
<div class="note"><b>How to read this page.</b> A score without an interval is not a result. Each bar shows the success rate and a 95% interval; with a small number of test items the interval is wide, and
two versions whose intervals overlap may be identical. The "Is the change real?" table tests the <i>same items</i> on both versions and says <i>better</i> or <i>worse</i> only when the evidence is strong.
Otherwise it says <i>within noise</i>, which means "not shown", not "equal".</div>{warn}{suites}{runs_section(m["runs"])}
<h2>Limits of this page</h2><ul><li>Success is whatever each project's scorer defined; it is not comparable across different suites.</li>
<li>Small test sets (8 to 38 items) can only detect large changes. A "within noise" verdict is not proof of no difference.</li>
<li>Run records are counted as written; versions that were re-run or partly run have different counts.</li></ul></main></body></html>"""
