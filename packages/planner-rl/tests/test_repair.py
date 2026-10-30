import json
import shutil
from datetime import datetime, timedelta, timezone

import pytest
from common import QueryPlan
from logger.index import LogIndex

from planner_rl.data.repair import floor_time_windows

from conftest import START

NOW = START + timedelta(hours=12)


def _window_plan(since: datetime, minutes: int = 10) -> dict:
    return {
        "version": "1.0.0",
        "queries": [{"limit": 1000, "order": "newest", "where": {"op": "and", "of": [
            {"op": "time_range", "since": since.isoformat(), "until": (since + timedelta(minutes=minutes)).isoformat()},
            {"op": "severity", "value": "INFO"},
        ]}}],
    }


def _gold(db, plan: dict) -> dict:
    idx = LogIndex(db)
    try:
        r = idx.execute(QueryPlan.model_validate(plan), now=NOW)
    finally:
        idx.close()
    return {"row_ids": sorted(r.row_ids), "groups": [], "aggregate_labels": [], "per_query_counts": [len(r.rows)], "rows_scanned": r.rows_scanned}


@pytest.fixture
def dataset(tmp_path, corpus_db):
    d = tmp_path / "ds"
    d.mkdir()
    shutil.copy(corpus_db, d / "train.db")
    at = START + timedelta(hours=2, seconds=37)
    rows = [
        ("no-seconds", "INFO lines between 22:00 and 22:10", _window_plan(at)),
        ("has-seconds", "INFO lines between 22:00:37 and 22:10:37", _window_plan(at + timedelta(minutes=30))),
        ("relative", "INFO lines in the last hour", {"version": "1.0.0", "queries": [{"limit": 1000, "order": "newest",
            "where": {"op": "and", "of": [{"op": "time_range", "since": "-1h"}, {"op": "severity", "value": "INFO"}]}}]}),
    ]
    with open(d / "train.jsonl", "w") as fh:
        for i, (name, question, plan) in enumerate(rows):
            fh.write(json.dumps({"id": name, "stratum": "time_range", "question": question, "plan": plan,
                                 "gold": _gold(d / "train.db", plan), "reference_now": NOW.isoformat()}) + "\n")
    (d / "manifest.json").write_text(json.dumps({"dataset": "toy"}))
    return d


def test_floors_only_questions_that_state_no_seconds_and_recomputes_gold(dataset):
    report = floor_time_windows(dataset)
    out = {e["id"]: e for e in map(json.loads, (dataset / "train.jsonl").read_text().splitlines())}

    fixed = out["no-seconds"]
    window = fixed["plan"]["queries"][0]["where"]["of"][0]
    assert window["since"].endswith(":00+00:00") and window["until"].endswith(":00+00:00")
    assert fixed["gold"]["row_ids"] == _gold(dataset / "train.db", fixed["plan"])["row_ids"]
    assert fixed["repairs"] == ["floor_time_windows"]

    assert "repairs" not in out["has-seconds"] and "repairs" not in out["relative"]
    assert report["train"]["before"] == 3 and report["train"]["after"] == 3
    assert (dataset / "train.pre-floor_time_windows.jsonl").exists()


def test_records_itself_in_the_manifest_and_refuses_to_run_twice(dataset):
    floor_time_windows(dataset)
    manifest = json.loads((dataset / "manifest.json").read_text())
    assert manifest["repairs"][0]["name"] == "floor_time_windows"
    with pytest.raises(ValueError, match="already"):
        floor_time_windows(dataset)


def test_sampler_draws_whole_minute_bounds(corpus_db):
    import random

    from planner_rl.data.corpus import CorpusView
    from planner_rl.data.sampler import PlanSampler

    view = CorpusView(corpus_db)
    try:
        sampler = PlanSampler(view, random.Random(3))
        bounds = []
        for _ in range(200):
            leaf = sampler._time_leaf(view.anchor(sampler.rng))
            if leaf is not None and leaf.since and not leaf.since.startswith("-"):
                bounds += [leaf.since, leaf.until]
    finally:
        view.close()
    assert bounds and all(b.endswith(":00+00:00") for b in bounds)
