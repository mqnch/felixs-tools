import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from common import QueryPlan
from logger.index import LogIndex

from planner_rl.eval import report
from planner_rl.eval.backend import ChatBackend, Completion
from planner_rl.eval.harness import run_eval, sample_examples
from planner_rl.eval.score import extract_json, score_output

NOW = datetime(2008, 11, 10, 12, tzinfo=timezone.utc)


def _plan(*queries: dict) -> str:
    return json.dumps({"version": "1.0.0", "queries": list(queries)})


ERRORS = {"where": {"op": "severity", "value": "ERROR"}, "limit": 1000}
WARNS = {"where": {"op": "severity", "value": "WARN"}, "limit": 1000}
BY_SEVERITY = {"where": None, "limit": 50, "aggregate": {"op": "count", "group_by": ["severity"]}}


@pytest.fixture
def index(corpus_db):
    idx = LogIndex(corpus_db)
    yield idx
    idx.close()


def _gold(index: LogIndex, text: str) -> dict:
    result = index.execute(QueryPlan.model_validate_json(text), now=NOW)
    return {
        "row_ids": sorted(result.row_ids),
        "groups": [{"key": g.key, "count": g.count} for g in result.groups],
    }


def test_the_gold_plan_scores_one(index):
    gold = _gold(index, _plan(ERRORS))
    s = score_output(_plan(ERRORS), gold, index, now=NOW)
    assert (s.format_valid, s.executed, s.answer, s.row_f1, s.group_f1) == (True, True, 1.0, 1.0, None)


def test_extra_rows_cost_precision_not_recall(index):
    gold = _gold(index, _plan(ERRORS))
    s = score_output(_plan(ERRORS, WARNS), gold, index, now=NOW)
    assert s.row_recall == 1.0 and s.row_precision < 1.0 and 0 < s.answer < 1
    assert s.query_count == 2


def test_rows_returned_for_an_aggregate_question_score_zero_on_the_rows_component(index):
    gold = _gold(index, _plan(BY_SEVERITY))
    s = score_output(_plan(BY_SEVERITY, ERRORS), gold, index, now=NOW)
    assert s.group_f1 == 1.0 and s.row_f1 == 0.0 and s.answer == 0.5


def test_a_group_with_the_wrong_count_does_not_match(index):
    gold = _gold(index, _plan(BY_SEVERITY))
    gold["groups"][0]["count"] += 1
    s = score_output(_plan(BY_SEVERITY), gold, index, now=NOW)
    assert s.group_f1 < 1.0


def test_format_is_binary_and_invalid_output_scores_zero(index):
    gold = _gold(index, _plan(ERRORS))
    s = score_output('{"queries": [{"where": {"op": "nope"}}]}', gold, index, now=NOW)
    assert not s.format_valid and s.answer == 0.0 and s.error_codes
    assert not score_output("I cannot help with that.", gold, index, now=NOW).format_valid


def test_think_blocks_fences_and_prose_are_stripped():
    text = '<think>maybe {"x": 1}</think>Sure:\n```json\n{"a": {"b": 1}}\n```\nDone.'
    assert json.loads(extract_json(text)) == {"a": {"b": 1}}


class _ScriptedPost:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.bodies: list[dict] = []
        self.urls: list[str] = []

    def __call__(self, url, headers, body, *, deadline_s):
        self.urls.append(url)
        self.bodies.append(body)
        return self.responses.pop(0)


def _ok(content: str, **usage) -> tuple[int, dict]:
    return 200, {"choices": [{"message": {"content": content}}], "usage": usage}


def test_local_backend_disables_qwen_thinking_and_needs_no_key():
    post = _ScriptedPost(_ok("{}", prompt_tokens=10, completion_tokens=2))
    c = ChatBackend("qwen", base_url="http://127.0.0.1:8080/v1", post=post).complete("s", "u")
    assert post.urls == ["http://127.0.0.1:8080/v1/chat/completions"]
    assert post.bodies[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "reasoning" not in post.bodies[0]
    assert (c.text, c.prompt_tokens, c.completion_tokens) == ("{}", 10, 2)


def test_openrouter_anthropic_caches_the_corpus_card_and_reports_cost():
    post = _ScriptedPost(_ok("{}", cost=0.002))
    c = ChatBackend("anthropic/claude-x", api_key="k", post=post).complete("s", "q", shared_prefix="card ")
    user = post.bodies[0]["messages"][1]["content"]
    assert user == [
        {"type": "text", "text": "card ", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "q"},
    ]
    assert post.bodies[0]["reasoning"] == {"enabled": False}
    assert c.cost_usd == 0.002


def test_other_models_get_the_same_text_as_one_string():
    post = _ScriptedPost(_ok("{}"))
    ChatBackend("qwen/q", api_key="k", post=post).complete("s", "q", shared_prefix="card ")
    assert post.bodies[0]["messages"][1]["content"] == "card q"


def test_backend_retries_transient_failures_and_aborts_on_auth():
    post = _ScriptedPost((0, {}), (503, {}), _ok("{}"))
    assert ChatBackend("m", api_key="k", post=post, sleep=lambda _s: None).complete("s", "u").text == "{}"
    with pytest.raises(RuntimeError, match="402"):
        ChatBackend("m", api_key="k", post=_ScriptedPost((402, {}))).complete("s", "u")


def test_backend_refuses_floating_aliases():
    with pytest.raises(ValueError, match="alias"):
        ChatBackend("~anthropic/claude-latest", api_key="k")


def test_sample_is_seeded_and_independent_of_file_order():
    examples = [{"id": f"x-{i:03d}"} for i in range(50)]
    assert sample_examples(examples, 10, 1) == sample_examples(list(reversed(examples)), 10, 1)
    assert sample_examples(examples, 10, 1) != sample_examples(examples, 10, 2)


def _dataset(tmp_path: Path, corpus_db: Path, index: LogIndex) -> Path:
    import shutil

    d = tmp_path / "ds"
    d.mkdir()
    shutil.copy(corpus_db, d / "test.db")
    plans = [_plan(ERRORS), _plan(WARNS), _plan(BY_SEVERITY)]
    with open(d / "test.jsonl", "w") as fh:
        for i, plan in enumerate(plans):
            fh.write(json.dumps({
                "id": f"t-{i}", "question": f"question {i}", "stratum": "s", "plan": json.loads(plan),
                "gold": _gold(index, plan), "reference_now": NOW.isoformat(),
            }) + "\n")
    (d / "manifest.json").write_text(json.dumps({"dataset": "toy", "corpus_digest": "d", "prompt_version": "p"}))
    return d


class _Oracle:
    model, base_url, thinking = "oracle", "none", False

    def __init__(self, data_dir: Path, fail_on: str | None = None):
        self.plans = {}
        for line in open(data_dir / "test.jsonl"):
            e = json.loads(line)
            self.plans[e["question"]] = e["plan"]
        self.fail_on = fail_on
        self.calls = 0

    def complete(self, system, user, *, shared_prefix=""):
        question = user.rsplit("Question: ", 1)[1]
        if question == self.fail_on:
            raise RuntimeError("server died")
        self.calls += 1
        return Completion(json.dumps(self.plans[question]), 1, 1, 0.1)


def test_harness_scores_an_oracle_at_one_and_resumes_after_a_crash(tmp_path, corpus_db, index):
    data = _dataset(tmp_path, corpus_db, index)
    out = tmp_path / "r.json"
    with pytest.raises(RuntimeError):
        run_eval([data], split="test", backend=_Oracle(data, fail_on="question 2"), out=out)
    assert out.with_suffix(".partial.jsonl").exists() and not out.exists()

    resumed = _Oracle(data)
    results = run_eval([data], split="test", backend=resumed, out=out)
    assert resumed.calls == 1
    assert results["summary"]["all"]["answer"] == 1.0 and results["summary"]["all"]["n"] == 3
    assert not out.with_suffix(".partial.jsonl").exists()

    loaded = report.load([out, out])
    assert "oracle" in report.table(loaded) and report.over_gate(loaded) == ["oracle", "oracle"]


def test_compare_restricts_every_file_to_the_shared_examples(tmp_path, corpus_db, index):
    data = _dataset(tmp_path, corpus_db, index)
    full, part = tmp_path / "full.json", tmp_path / "part.json"
    run_eval([data], split="test", backend=_Oracle(data), out=full)
    run_eval([data], split="test", backend=_Oracle(data), out=part, per_corpus=2)
    loaded = report.load([full, part])
    assert [r["summary"]["all"]["n"] for r in loaded] == [2, 2]


def test_reasoning_effort_implies_thinking_and_is_sent():
    post = _ScriptedPost(_ok("{}"))
    backend = ChatBackend("anthropic/claude-x", api_key="k", effort="low", post=post)
    backend.complete("s", "u")
    assert backend.thinking and post.bodies[0]["reasoning"] == {"effort": "low"}


class _Rejecting(_Oracle):
    def complete(self, system, user, *, shared_prefix=""):
        self.calls += 1
        return Completion("", None, None, 0.1, error="http_400: Reasoning is mandatory")


def test_harness_stops_when_every_call_is_rejected(tmp_path, corpus_db, index, monkeypatch):
    from planner_rl.eval import harness

    monkeypatch.setattr(harness, "ABORT_AFTER_CALL_ERRORS", 2)
    data = _dataset(tmp_path, corpus_db, index)
    with pytest.raises(RuntimeError, match="mandatory"):
        run_eval([data], split="test", backend=_Rejecting(data), out=tmp_path / "r.json")


def test_grouping_by_a_pinned_field_matches_the_plain_total(index):
    pinned = {"where": {"op": "severity", "value": "ERROR"}, "limit": 50,
              "aggregate": {"op": "count", "group_by": ["severity"]}}
    total = {"where": {"op": "severity", "value": "ERROR"}, "limit": 50,
             "aggregate": {"op": "count", "group_by": []}}
    gold = _gold(index, _plan(pinned))
    assert score_output(_plan(total), gold, index, now=NOW).group_f1 == 1.0


def test_a_varying_group_field_still_has_to_match(index):
    gold = _gold(index, _plan(BY_SEVERITY))
    total = {"where": None, "limit": 50, "aggregate": {"op": "count", "group_by": []}}
    assert score_output(_plan(total), gold, index, now=NOW).group_f1 == 0.0


def test_the_last_valid_plan_in_a_self_corrected_reply_is_scored(index):
    gold = _gold(index, _plan(ERRORS))
    bad = '{"version": "1.0.0", "queries": [{"where": {"op": "and", "of": [{"op": "term", "value": "x"}]}}]}'
    text = f"{bad}\n\nWait, that is invalid. Correction:\n\n{_plan(ERRORS)}"
    assert score_output(text, gold, index, now=NOW).answer == 1.0
    assert score_output(f"{_plan(ERRORS)}\nAlternatively: {bad}", gold, index, now=NOW).answer == 1.0


def test_rescore_recomputes_from_saved_outputs(tmp_path, corpus_db, index):
    from planner_rl.eval.harness import rescore

    data = _dataset(tmp_path, corpus_db, index)
    out = tmp_path / "r.json"
    run_eval([data], split="test", backend=_Oracle(data), out=out)
    saved = json.loads(out.read_text())
    saved["scorer_version"] = "old"
    for rec in saved["records"]:
        rec["answer"] = 0.0
    out.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="scorer"):
        report.load([out, _copy_fresh(tmp_path, data)])
    assert rescore(out)["summary"]["all"]["answer"] == 1.0


def _copy_fresh(tmp_path, data):
    fresh = tmp_path / "fresh.json"
    run_eval([data], split="test", backend=_Oracle(data), out=fresh)
    return fresh
