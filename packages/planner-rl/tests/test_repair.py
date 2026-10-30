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


def test_unsupported_detail_flags_words_from_the_lines_not_the_plan():
    from planner_rl.data.filters import unsupported_detail

    rows = ["GET /v2/servers/detail HTTP/1.1 status: 200", "POST /v2/servers HTTP/1.1 status: 202"]
    plan_text = "<*> <*> <*> HTTP/1.1\" status: <*> len: <*> time: <*>"
    assert unsupported_detail("Find the GET requests to servers/detail", plan_text, rows) == ["servers", "detail"]
    assert unsupported_detail("Find the HTTP request lines with a status", plan_text, rows) == []


class _Author:
    model = "fake/author"

    def __init__(self, question: str | None):
        self.question = question
        self.requests = []

    def author(self, request):
        from planner_rl.data.author import AuthorResult

        self.requests.append(request)
        return AuthorResult(question=self.question, model=self.model, reason=None if self.question else "author_declined")


@pytest.fixture
def overspecified(tmp_path, corpus_db):
    d = tmp_path / "ds"
    d.mkdir()
    shutil.copy(corpus_db, d / "train.db")
    plan = {"version": "1.0.0", "queries": [{"limit": 1000, "where": {"op": "severity", "value": "WARN"}}]}
    rows = [
        ("narrowed", "Find the WARN lines about slow BlockReceiver writes to a mirror"),
        ("fine", "Find all WARN lines"),
    ]
    with open(d / "train.jsonl", "w") as fh:
        for name, question in rows:
            fh.write(json.dumps({"id": name, "stratum": "single_leaf", "question": question, "plan": plan,
                                 "gold": _gold(d / "train.db", plan), "reference_now": NOW.isoformat()}) + "\n")
    (d / "manifest.json").write_text(json.dumps({"dataset": "toy"}))
    return d


def test_reauthors_only_flagged_questions_and_keeps_plan_and_gold(overspecified):
    from planner_rl.data.repair import reauthor_unsupported_detail

    before = {e["id"]: e for e in map(json.loads, (overspecified / "train.jsonl").read_text().splitlines())}
    author = _Author("Which lines were logged at warning level?")
    report = reauthor_unsupported_detail(overspecified, author, concurrency=1)
    after = {e["id"]: e for e in map(json.loads, (overspecified / "train.jsonl").read_text().splitlines())}

    assert len(author.requests) == 1 and report["train"]["flagged"] == 1
    fixed = after["narrowed"]
    assert fixed["question"] == "Which lines were logged at warning level?"
    assert fixed["replaced_question"] == before["narrowed"]["question"]
    assert fixed["repairs"] == ["reauthor_unsupported_detail"] and fixed["author_model"] == "fake/author"
    assert (fixed["plan"], fixed["gold"]) == (before["narrowed"]["plan"], before["narrowed"]["gold"])
    assert after["fine"] == before["fine"]
    manifest = json.loads((overspecified / "manifest.json").read_text())
    assert manifest["repairs"][-1]["name"] == "reauthor_unsupported_detail"
    with pytest.raises(ValueError, match="already"):
        reauthor_unsupported_detail(overspecified, author)


def test_a_reauthored_question_that_fails_the_filters_drops_the_example(overspecified):
    from planner_rl.data.repair import reauthor_unsupported_detail

    report = reauthor_unsupported_detail(overspecified, _Author("WARN lines where template_id is 4"), concurrency=1)
    assert report["train"]["dropped:dsl_leak"] == 1 and report["train"]["after"] == 1


def test_author_prompt_shows_no_sample_lines():
    from planner_rl.data.author import AuthorRequest, render_user_prompt

    text = render_user_prompt(AuthorRequest(dataset="x", plan_json='{"queries": []}', reference_now=None,
                                            template_texts={}, groups=[]))
    assert "Sample" not in text and "sample" not in text


def test_near_duplicate_index_tells_time_windows_apart():
    from planner_rl.data.filters import NearDuplicateIndex

    idx = NearDuplicateIndex()
    idx.add("Find all lines the Fetcher logger wrote between 17:49 and 17:59 on October 19.")
    assert not idx.is_duplicate("Find all lines the Fetcher logger wrote between 18:10 and 18:20 on October 19.")
    assert idx.is_duplicate("Find all the lines the Fetcher logger wrote between 17:49 and 17:59 on October 19.")


def test_a_count_question_over_a_row_plan_is_rejected(overspecified):
    from planner_rl.data.filters import asks_count_for_rows
    from planner_rl.data.repair import reauthor_unsupported_detail

    assert asks_count_for_rows("How many WARN lines are there?", has_aggregate=False)
    assert not asks_count_for_rows("How many WARN lines are there?", has_aggregate=True)
    assert not asks_count_for_rows("Find the WARN lines", has_aggregate=False)
    report = reauthor_unsupported_detail(overspecified, _Author("How many warning lines are there?"), concurrency=1)
    assert report["train"]["dropped:shape_mismatch"] == 1


def test_a_reauthored_question_that_rounds_the_window_gets_a_floored_window(tmp_path, corpus_db):
    from planner_rl.data.repair import reauthor_unsupported_detail

    d = tmp_path / "ds"
    d.mkdir()
    shutil.copy(corpus_db, d / "train.db")
    plan = _window_plan(START + timedelta(hours=2, seconds=37), minutes=30)
    plan["queries"][0]["where"]["of"][1] = {"op": "severity", "value": "WARN"}
    ex = {"id": "x", "stratum": "time_range", "plan": plan, "gold": _gold(d / "train.db", plan),
          "reference_now": NOW.isoformat(),
          "question": "Find the WARN lines about slow BlockReceiver writes between 22:00:37 and 22:30:37"}
    (d / "train.jsonl").write_text(json.dumps(ex) + "\n")
    (d / "manifest.json").write_text(json.dumps({"dataset": "toy"}))

    report = reauthor_unsupported_detail(d, _Author("Find the warning lines between 22:00 and 22:30"), concurrency=1)
    out = json.loads((d / "train.jsonl").read_text())
    window = out["plan"]["queries"][0]["where"]["of"][0]
    assert window["since"].endswith(":00+00:00") and report["train"]["reauthored_floored"] == 1
    assert out["repairs"] == ["reauthor_unsupported_detail", "floor_time_windows"]
    assert out["gold"]["row_ids"] == _gold(d / "train.db", out["plan"])["row_ids"]
