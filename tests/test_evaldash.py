import json
import math

import pytest

from evaldash import metrics
from evaldash.cli import main
from evaldash.loader import load_dataset
from evaldash.report import render
from evaldash.stats import bootstrap_ci, paired, sign_test_p, wilson


# ------------------------------------------------------------------ statistics
def test_wilson_matches_known_values_and_edges():
    lo, hi = wilson(11, 12)
    assert math.isclose(lo, 0.6458, abs_tol=2e-3) and math.isclose(hi, 0.9853, abs_tol=2e-3)
    assert wilson(0, 10)[0] == pytest.approx(0.0, abs=1e-9) and wilson(10, 10)[1] == pytest.approx(1.0, abs=1e-9) and wilson(0, 0) == (0.0, 1.0)
    narrow, wide = wilson(500, 1000), wilson(5, 10)
    assert narrow[1] - narrow[0] < wide[1] - wide[0]  # more data, tighter interval


def test_sign_test_is_exact():
    assert sign_test_p(0, 0) == 1.0
    assert math.isclose(sign_test_p(5, 0), 2 / 32)
    assert sign_test_p(3, 3) == 1.0
    assert sign_test_p(10, 0) < 0.01


def test_bootstrap_is_deterministic_and_brackets_the_mean():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    a, b = bootstrap_ci(values), bootstrap_ci(values)
    assert a == b and a[0] < 3.5 < a[1] and bootstrap_ci([1.0]) is None


def ids(passed, n=20):
    return {f"q{i}": i in passed for i in range(n)}


def test_a_small_improvement_is_within_noise_the_lesson_from_project_1():
    """Six answers flip one way and none the other, over 38 items: a visible gap, yet p = 0.031 is only just significant.
    Three flips one way and none the other is not."""
    base = ids(set(range(32)), 38)
    assert paired(base, ids(set(range(35)), 38)).verdict == "within noise"
    assert paired(base, ids(set(range(38)), 38)).verdict == "better"


def test_a_large_consistent_change_is_called_better_or_worse():
    base = ids(set(), 20)
    better = paired(base, ids(set(range(12)), 20))
    assert better.verdict == "better" and better.b_only == 12 and better.delta == pytest.approx(0.6) and better.ci[0] > 0
    worse = paired(ids(set(range(12)), 20), base)
    assert worse.verdict == "worse"


def test_only_shared_items_are_compared_and_no_overlap_is_handled():
    r = paired({"a": True, "b": False}, {"b": True, "c": True})
    assert r.n == 1 and r.b_only == 1
    assert paired({"a": True}, {"z": True}).verdict == "too few items"


# ------------------------------------------------------------------ loading and metrics
def write_run(root, project, version, run_id, **kw):
    folder = root / project / "data" / "runs" / version
    folder.mkdir(parents=True, exist_ok=True)
    rec = {"version": version, "question": "q", "status": "answered", "answer": "a", "reasons": [], "searches": 1, "llm_calls": 2, "input_tokens": 100,
           "output_tokens": 20, "cost_usd": 0.001, "latency_ms": 1000.0, "run_id": run_id, "created_at": 1.0, "schema_version": 1, "verified": True} | kw
    (folder / f"{run_id}.json").write_text(json.dumps(rec), encoding="utf-8")


def write_results(root, project, name, body):
    folder = root / project / "evals" / "results"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps(body), encoding="utf-8")


@pytest.fixture
def world(tmp_path):
    for i in range(4):
        write_run(tmp_path, "p1", "v1", f"a{i}", latency_ms=1000 + i * 1000, status="answered" if i < 3 else "abstained", reasons=["max_steps"] if i == 3 else [])
    write_run(tmp_path, "p1", "v2", "b0", status="error", reasons=["error:RuntimeError"], latency_ms=0)
    (tmp_path / "p1" / "data" / "runs" / "v1" / "broken.json").write_text("{not json", encoding="utf-8")
    write_run(tmp_path, "p1", "v1", "old", schema_version=99)
    write_results(tmp_path, "p1", "agents", {v: {"summary": {}, "scores": [{"id": f"q{i}", "type": "simple" if i < 5 else "multi", "success": ok(v, i)} for i in range(10)]}
                                            for v, ok in (("v1", lambda v, i: i < 4), ("v2", lambda v, i: i < 10))})
    write_results(tmp_path, "p2", "tasks", {"summary": {}, "scores": [{"id": "t1", "success": True, "checks": {}}, {"id": "t2", "success": False, "checks": {}}]})
    write_results(tmp_path, "p2", "attacks", {"summary": {}, "scores": [{"id": "a1", "attack": "body", "hijacked": False}, {"id": "a2", "attack": "link", "hijacked": True}]})
    write_results(tmp_path, "p2", "retrieval", {"hit_rate": 0.9})
    return tmp_path


def test_loader_reads_valid_records_and_reports_everything_it_skipped(world):
    data = load_dataset(world)
    assert len(data.runs) == 5 and {s.name for s in data.suites} == {"agents", "tasks", "attacks"}
    text = " ".join(data.warnings)
    assert "broken.json" in text and "schema_version 99" in text and "retrieval.json is not a recognised" in text


def test_run_summary_numbers(world):
    data = load_dataset(world)
    s = {(r.project, r.version): r for r in metrics.summarize_runs(data.runs)}
    v1 = s[("p1", "v1")]
    assert v1.n == 4 and v1.status["answered"].k == 3 and v1.latency_p50 == 2000 and v1.reasons == [("max_steps", 1)]
    assert s[("p1", "v2")].status["error"].value == 1.0 and s[("p1", "v2")].latency_p50 is None  # zero latency (failed call) is not a measurement


def test_suite_summary_groups_and_comparison(world):
    data = load_dataset(world)
    agents = next(s for s in data.suites if s.name == "agents")
    summary = metrics.summarize_suite(agents)
    v1 = next(r for r in summary.versions if r[0] == "v1")
    assert v1[1].k == 4 and v1[2]["simple"].k == 4 and v1[2]["multi"].k == 0
    (cmp,) = metrics.compare_suite(agents)
    assert cmp["baseline"] == "v1" and cmp["candidate"] == "v2" and cmp["b_only"] == 6 and cmp["verdict"] == "better"
    attacks = next(s for s in data.suites if s.name == "attacks")
    assert [i.success for i in attacks.versions["agent"]] == [True, False]  # success = resisted


# ------------------------------------------------------------------ report and CLI
def test_report_is_one_self_contained_page_with_the_key_content(world):
    page = render(load_dataset(world))
    assert page.startswith("<!doctype html>") and "<script" not in page and "http://" not in page.replace("http://www.w3.org", "")
    assert "<svg" in page and "within noise" in page.lower() and "better" in page and "broken.json" in page
    assert "Is the change real?" in page


def test_cli_report_and_gate(world, tmp_path, capsys):
    out = tmp_path / "out" / "index.html"
    assert main(["report", "--root", str(world), "--out", str(out)]) == 0 and out.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert main(["gate", "--root", str(world), "--project", "p1", "--suite", "agents", "--baseline", "v1", "--candidate", "v2"]) == 0
    assert main(["gate", "--root", str(world), "--project", "p1", "--suite", "agents", "--baseline", "v2", "--candidate", "v1"]) == 1  # a regression fails the gate
    assert "GATE FAILED" in capsys.readouterr().out
    assert main(["gate", "--root", str(world), "--project", "p1", "--suite", "agents", "--baseline", "v1", "--candidate", "nope"]) == 2
    assert main(["summary", "--root", str(world)]) == 0
