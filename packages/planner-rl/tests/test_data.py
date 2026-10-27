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
)
from planner_rl.data.corpus import SPLITS, CorpusView, build_splits, literal_words
from planner_rl.data.gold import compute_gold
from planner_rl.data.pipeline import generate_dataset
from planner_rl.data.sampler import DEFAULT_MIX, PlanSampler


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
