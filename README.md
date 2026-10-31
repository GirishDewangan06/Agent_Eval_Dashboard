# Agent evaluation dashboard

Compares versions of an AI agent from the run records and result files they already write, and says whether a difference is **real or noise**.
It reads Project 1 (knowledge agent) and Project 2 (MCP project agent) without changing them. Standard library only; the output is one HTML file with inline SVG charts (no JavaScript, no server).

## Why it exists

In Project 1 the agent version scored 0.84 against a simpler pipeline's 0.92 and it looked like a clear loss. A score without an interval is not a result. This tool puts a 95% interval on every rate
and compares versions on the *same questions*, so it can say "better", "worse" or "within noise".

## What it shows, on the real records (155 runs, 3 result files)

| Comparison (Project 1, 38 questions) | Change | Fixed / broke | p | Verdict |
|---|---|---|---|---|
| v1 pipeline -> v2 agent | -7.9 pts | 2 / 5 | 0.45 | within noise |
| v2 -> v2.1 | +2.6 pts | 1 / 0 | 1.00 | within noise |
| v1 -> v2.1 | -5.3 pts | 2 / 4 | 0.69 | within noise |

None of the Project 1 differences is statistically supported. "Within noise" means *not shown*, not *equal*: 38 questions can only detect large changes.
What the run records do show clearly is cost: the v2 agent's median latency is about 43 s against 6.9 s for the pipeline.
Project 2: 11/12 tasks (95% interval 65% to 99%) and 8/8 attacks resisted (68% to 100%); the wide intervals are the honest reading of 12 and 8 items.

## Use

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
evaldash report --root ..                       # writes dashboard/index.html from the sibling project folders
evaldash summary --root ..                      # same numbers as text
evaldash gate --root .. --project 01-knowledge-agent --suite agents --baseline v1 --candidate v2.1 --max-drop 0.05
pytest                                          # 11 tests
```

`gate` exits 1 when the candidate is more than `--max-drop` lower than the baseline or significantly worse, so a CI job can block a regression.

## Method

- **Rates:** Wilson score interval (sound at 0%, 100% and small n).
- **Comparing versions:** paired on shared question ids. Exact two-sided sign test on the questions where the versions disagree; bootstrap interval for the difference. Ties carry no information.
- **Latency/cost:** percentiles from run records; zero latency (a failed call) is not counted as a measurement; cost shows "not recorded" when providers did not report it (free tier).
- **Inputs it cannot read** (for example `retrieval.json`) are listed on the page rather than ignored.

## Limits

- Success is whatever each project's scorer defined, so numbers are not comparable across suites.
- Version run counts differ in the run records (re-runs, partial runs).
- The sign test is conservative with few disagreements. Repeating each evaluation several times would tighten everything; that is not done yet.
- Static page: no live updates; regenerate after each evaluation. Not deployed.
