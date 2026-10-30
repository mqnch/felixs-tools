from __future__ import annotations

import csv
import json
import random
import sqlite3
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from common import AndNode, NotNode, Query, QueryPlan, SeverityNode, TermNode
from logger.index import LogIndex
from logger.validator import validate_plan

from planner_rl.data import filters
from planner_rl.data.audit import score_audit_sheet, write_audit_sheet
from planner_rl.data.author import (
    AnthropicAuthor,
    AuthoredQuestion,
    AuthorRequest,
    AuthorResult,
    OpenRouterAuthor,
    author_view_of_plan,
    render_user_prompt,
)
from planner_rl.data.corpus import SPLITS, CorpusView, build_splits, literal_words
from planner_rl.data.gold import compute_gold
from planner_rl.data.pipeline import generate_dataset
from planner_rl.data.sampler import DEFAULT_MIX, PlanSampler, term_words


@pytest.fixture()
def splits(corpus_db: Path, tmp_path: Path):
    return tmp_path, build_splits(corpus_db, tmp_path)


def _ids(db: Path) -> list[int]:
    conn = sqlite3.connect(db)
    try:
        return [r[0] for r in conn.execute("SELECT id FROM log_entries ORDER BY id")]
    finally:
        conn.close()


# --- splits -------------------------------------------------------------------


def test_splits_partition_the_corpus_into_ordered_time_windows(corpus_db, splits):
    out, windows = splits
    assert [w.split for w in windows] == list(SPLITS)
    all_ids = [i for s in SPLITS for i in _ids(out / f"{s}.db")]
    assert sorted(all_ids) == _ids(corpus_db)  # disjoint, complete, IDs preserved
    for earlier, later in zip(windows, windows[1:]):
        assert earlier.until <= later.since


def test_split_db_supports_full_text_search(splits):
    out, _ = splits
    index = LogIndex(out / "test.db")
    try:
        hits = index.query(Query(where=TermNode(value="blk"), limit=1000)).row_ids
    finally:
        index.close()
    assert hits and set(hits) <= set(_ids(out / "test.db"))


# --- sampler + gold -------------------------------------------------------------


@pytest.mark.parametrize("stratum", sorted(DEFAULT_MIX))
def test_every_stratum_samples_valid_plans(splits, stratum):
    out, _ = splits
    view = CorpusView(out / "train.db")
    sampler = PlanSampler(view, random.Random(3))
    try:
        plans = [p for p in (sampler.sample(stratum) for _ in range(30)) if p is not None]
    finally:
        view.close()
    assert plans, f"{stratum} never produced a plan"
    for sampled in plans:
        assert validate_plan(sampled.plan).ok, sampled.plan.model_dump_json()


def test_gold_rejects_a_negation_that_excludes_nothing(splits):
    out, _ = splits
    index = LogIndex(out / "train.db")
    try:
        # Every PacketResponder line is INFO, so `not ERROR` does no work.
        plan = QueryPlan(
            queries=[
                Query(
                    where=AndNode(
                        of=[TermNode(value="PacketResponder"), NotNode(of=[SeverityNode(value="ERROR")])]
                    ),
                    limit=1000,
                )
            ]
        )
        gold, reason = compute_gold(
            index, plan, now=index.reference_now(), row_count=index.row_count(), max_fraction=1.0
        )
    finally:
        index.close()
    assert gold is None and reason == "noop_negation"


def test_gold_rejects_an_and_child_that_narrows_nothing(splits):
    out, _ = splits
    index = LogIndex(out / "train.db")
    try:
        # Every PacketResponder line is INFO, so `and INFO` does no work.
        plan = QueryPlan(
            queries=[
                Query(where=AndNode(of=[TermNode(value="PacketResponder"), SeverityNode(value="INFO")]), limit=1000)
            ]
        )
        gold, reason = compute_gold(
            index, plan, now=index.reference_now(), row_count=index.row_count(), max_fraction=1.0
        )
    finally:
        index.close()
    assert gold is None and reason == "noop_conjunct"


def test_template_text_is_the_most_general_not_the_earliest(tmp_path):
    """Drain generalizes clusters over time; early rows keep their literal text."""
    import sqlite3

    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE log_entries (id INTEGER PRIMARY KEY, raw TEXT, template TEXT, template_id INTEGER,"
        " severity TEXT, timestamp TEXT, location_key TEXT)"
    )
    conn.executemany(
        "INSERT INTO log_entries VALUES (?, ?, ?, 3, 'INFO', '2005-06-01T00:00:00', 'K:x.log')",
        [
            (1, "1534 double-hummer alignment exceptions", "1534 double-hummer alignment exceptions"),
            (2, "12 double-hummer alignment exceptions", "<*> double-hummer alignment exceptions"),
        ],
    )
    conn.commit()
    conn.close()
    view = CorpusView(db)
    try:
        assert view.template_text(3) == "<*> double-hummer alignment exceptions"
    finally:
        view.close()


def test_term_words_drop_function_words_and_short_tokens():
    assert term_words("Received block <*> of size <*> such as it is from <*>") == ["Received", "block", "size"]


def test_gold_rejects_empty_and_overbroad_results(splits):
    out, _ = splits
    index = LogIndex(out / "train.db")
    now, n = index.reference_now(), index.row_count()
    try:
        empty = QueryPlan(queries=[Query(where=TermNode(value="nonexistentword"), limit=1000)])
        broad = QueryPlan(queries=[Query(where=SeverityNode(value="INFO"), limit=1000)])
        assert compute_gold(index, empty, now=now, row_count=n) == (None, "empty_rows")
        assert compute_gold(index, broad, now=now, row_count=n)[1] in {"too_broad", "truncated_rows"}
    finally:
        index.close()


# --- pipeline ------------------------------------------------------------------


def test_dry_run_gold_reexecutes_and_stays_inside_its_split(corpus_db, tmp_path):
    manifest = generate_dataset(corpus_db=corpus_db, out_dir=tmp_path, n=60, author=None, seed=11)
    assert manifest.dry_run and manifest.generator_model is None
    for split in SPLITS:
        split_ids = set(_ids(tmp_path / f"{split}.db"))
        index = LogIndex(tmp_path / f"{split}.db")
        try:
            for line in (tmp_path / f"{split}.jsonl").open():
                ex = json.loads(line)
                assert set(ex["gold"]["row_ids"]) <= split_ids
                result = index.execute(QueryPlan.model_validate(ex["plan"]))
                assert sorted(result.row_ids) == ex["gold"]["row_ids"]
        finally:
            index.close()
    train = manifest.splits["train"]
    assert train["accepted"] == train["target"]
    assert len(train["strata"]) >= 5, train


def test_generation_is_reproducible_for_a_fixed_seed(corpus_db, tmp_path):
    a = generate_dataset(corpus_db=corpus_db, out_dir=tmp_path / "a", n=30, author=None, seed=5)
    b = generate_dataset(corpus_db=corpus_db, out_dir=tmp_path / "b", n=30, author=None, seed=5)
    assert a.splits == b.splits
    for split in SPLITS:
        assert (tmp_path / "a" / f"{split}.jsonl").read_text() == (tmp_path / "b" / f"{split}.jsonl").read_text()


class _ScriptedAuthor:
    """Returns one scripted question per call, cycling."""

    model = "scripted"

    def __init__(self, questions: list[str | None]) -> None:
        self.questions = questions
        self.calls = 0

    def author(self, request: AuthorRequest) -> AuthorResult:
        q = self.questions[self.calls % len(self.questions)]
        self.calls += 1
        if q is None:
            return AuthorResult(question=None, model=self.model, reason="author_declined")
        return AuthorResult(question=f"{q} #{self.calls}", model=self.model)


def test_pipeline_applies_question_filters(corpus_db, tmp_path):
    # The scripted author appends "#<call>", so accepted questions stay distinct.
    author = _ScriptedAuthor(
        [
            "slow mirror writes datanode",
            "show logs where template_id is 3",  # leak
            None,  # declined
        ]
    )
    manifest = generate_dataset(corpus_db=corpus_db, out_dir=tmp_path, n=9, author=author, seed=2)
    rejections: Counter = Counter()
    for stats in manifest.splits.values():
        rejections.update(stats["rejections"])
    assert rejections["dsl_leak"] > 0
    assert rejections["author_declined"] > 0
    for split in SPLITS:
        for line in (tmp_path / f"{split}.jsonl").open():
            ex = json.loads(line)
            assert ex["question"] and not filters.leaks_dsl(ex["question"])
            assert ex["author_model"] == "scripted"


# --- filters --------------------------------------------------------------------


@pytest.mark.parametrize(
    "question,leaks",
    [
        ("errors from the namenode in the last hour", False),
        ("rows where template_id = 4", True),
        ("severity=ERROR lines", True),
        ("lines after 2008-11-09T20:10:00", True),
        ("group_by location", True),
        ("which message templates spiked", True),
    ],
)
def test_leak_filter(question, leaks):
    assert filters.leaks_dsl(question) is leaks


def test_near_duplicates_are_caught_across_word_order():
    idx = filters.NearDuplicateIndex()
    idx.add("show connection reset errors on the datanode")
    assert idx.is_duplicate("datanode connection reset errors")
    assert not idx.is_duplicate("slow mirror writes in the last hour")


def test_keyword_trivial_flags_a_single_word_answer(splits):
    out, _ = splits
    index = LogIndex(out / "train.db")
    now = index.reference_now()
    try:
        gold = index.query(Query(where=TermNode(value="PacketResponder"), limit=1000), now=now).row_ids
        assert filters.keyword_trivial(index, "packetresponder terminating lines", gold, now=now)
        assert not filters.keyword_trivial(index, "nothing relevant here", gold, now=now)
    finally:
        index.close()


def test_literal_words_skip_parameters():
    assert literal_words("PacketResponder <*> for block <*> terminating") == [
        "PacketResponder",
        "block",
        "terminating",
    ]


# --- author ---------------------------------------------------------------------


class _FakeMessages:
    def __init__(self, response) -> None:
        self.response = response
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def _request() -> AuthorRequest:
    return AuthorRequest(
        dataset="hdfs", plan_json="{}", reference_now=None, sample_rows=[], template_texts={}, groups=[]
    )


def test_prompt_spells_out_locations_and_window_kinds():
    plan = {
        "version": "1.0.0",
        "queries": [
            {
                "where": {
                    "op": "and",
                    "of": [
                        {"op": "location_key", "value": "nova.compute.manager:nova-compute.log"},
                        {"op": "time_range", "since": "2017-05-16T17:38:28+00:00", "until": "2017-05-16T17:48:28+00:00"},
                    ],
                }
            },
            {"where": {"op": "time_range", "since": "-6h"}},
        ],
    }
    request = AuthorRequest(
        dataset="openstack", plan_json=json.dumps(plan), reference_now=None,
        sample_rows=[], template_texts={}, groups=[],
    )
    prompt = render_user_prompt(request)
    assert "- component nova.compute.manager in file nova-compute.log" in prompt
    assert "- absolute: since 2017-05-16T17:38:28+00:00 until 2017-05-16T17:48:28+00:00" in prompt
    assert "- relative to now: since -6h until now" in prompt


def test_prompt_hides_aggregate_group_keys():
    request = AuthorRequest(
        dataset="bgl", plan_json='{"queries": []}', reference_now=None, sample_rows=[], template_texts={},
        groups=[{"key": {"location_key": "KERNEL:BGL.log"}, "count": 56}],
    )
    prompt = render_user_prompt(request)
    assert "KERNEL" not in prompt
    assert "returned 1 group(s)" in prompt


def test_anthropic_author_returns_parsed_question():
    messages = _FakeMessages(
        SimpleNamespace(
            stop_reason="end_turn",
            parsed_output=AuthoredQuestion(expressible=True, question=" slow mirror writes? "),
        )
    )
    author = AnthropicAuthor(client=SimpleNamespace(messages=messages))
    result = author.author(_request())
    assert result.question == "slow mirror writes?"
    assert messages.kwargs["model"] == "claude-opus-5-5"
    assert messages.kwargs["output_format"] is AuthoredQuestion


@pytest.mark.parametrize(
    "response,reason",
    [
        (SimpleNamespace(stop_reason="refusal", parsed_output=None), "author_refused"),
        (SimpleNamespace(stop_reason="end_turn", parsed_output=None), "author_unparseable"),
        (
            SimpleNamespace(stop_reason="end_turn", parsed_output=AuthoredQuestion(expressible=False, question="")),
            "author_declined",
        ),
    ],
)
def test_anthropic_author_maps_failures_to_reasons(response, reason):
    author = AnthropicAuthor(client=SimpleNamespace(messages=_FakeMessages(response)))
    assert author.author(_request()).reason == reason


def test_author_view_hides_sampler_defaults_but_keeps_real_constraints():
    plan = {
        "version": "1.0.0",
        "queries": [
            {"limit": 1000, "order": "newest", "where": {"op": "severity", "value": "ERROR"}},
            {"limit": 20, "order": "oldest"},
        ],
    }
    view = json.loads(author_view_of_plan(json.dumps(plan)))
    assert view["queries"][0] == {"where": {"op": "severity", "value": "ERROR"}}
    assert view["queries"][1] == {"limit": 20, "order": "oldest"}


class _ScriptedPost:
    def __init__(self, *replies: tuple[int, dict]) -> None:
        self.replies = list(replies)
        self.bodies: list[dict] = []

    def __call__(self, url, headers, body):
        self.bodies.append(body)
        return self.replies.pop(0)


def _openrouter(post: _ScriptedPost) -> OpenRouterAuthor:
    return OpenRouterAuthor(api_key="test", post=post, sleep=lambda _s: None)


def _content(text: str) -> tuple[int, dict]:
    return 200, {"choices": [{"message": {"content": text}}]}


def test_openrouter_author_returns_parsed_question():
    post = _ScriptedPost(_content('{"expressible": true, "question": " slow mirror writes? "}'))
    result = _openrouter(post).author(_request())
    assert result.question == "slow mirror writes?"
    assert result.model == "anthropic/claude-haiku-5.5"
    fmt = post.bodies[0]["response_format"]
    assert fmt["json_schema"]["strict"] is True
    assert set(fmt["json_schema"]["schema"]["required"]) == {"expressible", "question"}


@pytest.mark.parametrize(
    "reply,reason",
    [
        (_content('{"expressible": false, "question": ""}'), "author_declined"),
        (_content("not json"), "author_unparseable"),
        ((200, {"choices": [{"message": {"refusal": "no", "content": None}}]}), "author_refused"),
        ((400, {"error": {"message": "bad request"}}), "author_error"),
    ],
)
def test_openrouter_author_maps_failures_to_reasons(reply, reason):
    assert _openrouter(_ScriptedPost(reply)).author(_request()).reason == reason


@pytest.mark.parametrize("status", [401, 402, 403])
def test_openrouter_auth_and_billing_errors_abort_the_run(status):
    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        _openrouter(_ScriptedPost((status, {}))).author(_request())


def test_openrouter_retries_rate_limits_then_succeeds():
    post = _ScriptedPost((429, {}), (503, {}), _content('{"expressible": true, "question": "q"}'))
    assert _openrouter(post).author(_request()).question == "q"
    assert len(post.bodies) == 3


def test_openrouter_retries_network_errors_then_succeeds():
    post = _ScriptedPost((0, {"error": "TimeoutError"}), _content('{"expressible": true, "question": "q"}'))
    assert _openrouter(post).author(_request()).question == "q"
    assert len(post.bodies) == 2


def test_post_json_turns_a_read_timeout_into_a_retryable_status(monkeypatch):
    import urllib.request

    from planner_rl.data import author as author_mod

    def _timeout(*_args, **_kwargs):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(urllib.request, "urlopen", _timeout)
    status, payload = author_mod._post_json("https://x", {}, {})
    assert status == author_mod.NETWORK_ERROR and "timed out" in payload["error"]


def test_read_gives_up_on_endless_keepalive_whitespace():
    import time

    from planner_rl.data import author as author_mod

    class _KeepAlive:
        def read1(self, _n):
            time.sleep(0.01)
            return b"\n"

    with pytest.raises(TimeoutError):
        author_mod._read_with_deadline(_KeepAlive(), time.monotonic() + 0.05)


def test_openrouter_refuses_floating_aliases():
    with pytest.raises(ValueError, match="alias"):
        OpenRouterAuthor("~anthropic/claude-haiku-latest", api_key="test")


def test_anthropic_auth_errors_abort_the_run():
    import anthropic
    import httpx2 as httpx

    class _Failing:
        def parse(self, **_kwargs):
            response = httpx.Response(401, request=httpx.Request("POST", "https://x"))
            raise anthropic.AuthenticationError("bad key", response=response, body=None)

    author = AnthropicAuthor(client=SimpleNamespace(messages=_Failing()))
    with pytest.raises(anthropic.AuthenticationError):
        author.author(_request())


# --- audit ----------------------------------------------------------------------


def test_audit_sheet_round_trip(corpus_db, tmp_path):
    author = _ScriptedAuthor(["slow mirror writes datanode"])
    generate_dataset(corpus_db=corpus_db, out_dir=tmp_path, n=6, author=author, seed=4)
    sheet = write_audit_sheet(tmp_path, sample=4, seed=0, out=tmp_path / "audit.csv")
    rows = list(csv.DictReader(sheet.open()))
    assert rows and all(r["question"] for r in rows)
    for i, r in enumerate(rows):
        r.update(natural="y", answerable="n" if i == 0 else "y", best_plan="y")
    with sheet.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    score = score_audit_sheet(sheet)
    assert score.judged == len(rows) and score.unjudged == 0
    assert score.rates["natural"] == 1.0
    assert score.reversal_trigger is (score.rates["answerable"] < 0.85)
