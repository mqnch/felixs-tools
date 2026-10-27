"""Executor correctness.

`LogIndex.execute()` computes every RL reward (decision 0002), so these tests
pin semantics — especially negation, disjunction, NULL handling, and the
`rows_scanned` cost model — rather than smoke-testing that queries run.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from common import (
    Aggregate,
    AndNode,
    GroupByField,
    Having,
    LocationKeyNode,
    NotNode,
    OrNode,
    Query,
    QueryPlan,
    SeverityNode,
    TemplateIdNode,
    TermNode,
    TimeRangeNode,
)
from conftest import CORPUS_SIZE
from logger import AggregateGroup, Logger


def run(log: Logger, where=None, **kwargs) -> list[str]:
    """Execute a one-query plan and return the matched raw lines."""
    result = log.execute_plan(QueryPlan(queries=[Query(where=where, **kwargs)]))
    return [r.raw for r in result.rows]


def ids(log: Logger, where=None, **kwargs) -> set[int]:
    result = log.execute_plan(QueryPlan(queries=[Query(where=where, **kwargs)]))
    return set(result.row_ids)


def scanned(log: Logger, where=None, **kwargs) -> int:
    return log.execute_plan(QueryPlan(queries=[Query(where=where, **kwargs)])).rows_scanned


# --- leaves ------------------------------------------------------------------


def test_no_filter_returns_everything(log: Logger) -> None:
    assert len(run(log)) == CORPUS_SIZE


def test_severity_leaf(log: Logger) -> None:
    assert len(run(log, SeverityNode(value="ERROR"))) == 3


def test_severity_accepts_case_and_warning_alias(log: Logger) -> None:
    assert run(log, SeverityNode(value="warning")) == run(log, SeverityNode(value="WARN"))
    assert len(run(log, SeverityNode(value="warning"))) == 1


def test_term_leaf_matches_raw_text(log: Logger) -> None:
    assert len(run(log, TermNode(value="payment"))) == 3


def test_location_key_leaf(log: Logger) -> None:
    assert len(run(log, LocationKeyNode(value="worker:svc/worker.log"))) == 2


def test_template_id_leaf_groups_structurally_identical_lines(log: Logger) -> None:
    counts = log.index.template_counts()
    repeated = max(counts, key=lambda k: counts[k])
    assert counts[repeated] == 2
    assert len(run(log, TemplateIdNode(value=repeated))) == 2


# --- negation ----------------------------------------------------------------


def test_negation_is_the_complement(log: Logger) -> None:
    positive = ids(log, SeverityNode(value="ERROR"))
    negative = ids(log, NotNode(of=[SeverityNode(value="ERROR")]))
    assert positive & negative == set()
    assert len(positive | negative) == CORPUS_SIZE


def test_negation_keeps_rows_whose_field_is_null(log: Logger) -> None:
    """The row with no severity is not INFO, so `not severity=INFO` must keep it."""
    matched = run(log, NotNode(of=[SeverityNode(value="INFO")]))
    assert "plain line with no level marker" in matched


def test_negated_term(log: Logger) -> None:
    matched = run(log, NotNode(of=[TermNode(value="payment")]))
    assert len(matched) == CORPUS_SIZE - 3
    assert all("payment" not in line for line in matched)


# --- disjunction --------------------------------------------------------------


def test_or_is_the_union(log: Logger) -> None:
    left = ids(log, TermNode(value="payment"))
    right = ids(log, TermNode(value="timeout"))
    both = ids(log, OrNode(of=[TermNode(value="payment"), TermNode(value="timeout")]))
    assert both == left | right


def test_and_is_the_intersection(log: Logger) -> None:
    left = ids(log, TermNode(value="payment"))
    right = ids(log, SeverityNode(value="ERROR"))
    both = ids(log, AndNode(of=[TermNode(value="payment"), SeverityNode(value="ERROR")]))
    assert both == left & right


# --- negation x disjunction (where SQL generation usually breaks) -------------


def test_de_morgan_not_of_or(log: Logger) -> None:
    a, b = TermNode(value="payment"), SeverityNode(value="INFO")
    not_or = ids(log, NotNode(of=[OrNode(of=[a, b])]))
    and_nots = ids(log, AndNode(of=[NotNode(of=[a]), NotNode(of=[b])]))
    assert not_or == and_nots


def test_de_morgan_not_of_and(log: Logger) -> None:
    a, b = TermNode(value="payment"), SeverityNode(value="ERROR")
    not_and = ids(log, NotNode(of=[AndNode(of=[a, b])]))
    or_nots = ids(log, OrNode(of=[NotNode(of=[a]), NotNode(of=[b])]))
    assert not_and == or_nots


def test_negation_inside_one_or_branch(log: Logger) -> None:
    """(ERROR AND NOT payment) OR CRITICAL — negation must stay scoped to its branch."""
    where = OrNode(
        of=[
            AndNode(of=[SeverityNode(value="ERROR"), NotNode(of=[TermNode(value="payment")])]),
            SeverityNode(value="CRITICAL"),
        ]
    )
    assert sorted(run(log, where)) == [
        "CRITICAL disk full",
        "ERROR timeout contacting db",
    ]


def test_negation_of_or_does_not_leak_across_branches(log: Logger) -> None:
    """NOT (INFO OR WARN) keeps the NULL-severity row; a naive `NOT IN` would drop it."""
    where = NotNode(of=[OrNode(of=[SeverityNode(value="INFO"), SeverityNode(value="WARN")])])
    matched = run(log, where)
    assert "plain line with no level marker" in matched
    assert len(matched) == CORPUS_SIZE - 3


def test_double_negation_is_identity(log: Logger) -> None:
    inner = TermNode(value="timeout")
    assert ids(log, NotNode(of=[NotNode(of=[inner])])) == ids(log, inner)


def test_nested_three_levels(log: Logger) -> None:
    """(payment AND NOT INFO) OR (timeout AND worker)."""
    where = OrNode(
        of=[
            AndNode(of=[TermNode(value="payment"), NotNode(of=[SeverityNode(value="INFO")])]),
            AndNode(
                of=[TermNode(value="timeout"), LocationKeyNode(value="worker:svc/worker.log")]
            ),
        ]
    )
    assert sorted(run(log, where)) == [
        "ERROR payment failed order=42",
        "ERROR payment failed order=43",
        "ERROR timeout contacting db",
    ]


# --- time --------------------------------------------------------------------


def test_absolute_since(log: Logger) -> None:
    assert len(run(log, TimeRangeNode(since="2026-07-23T00:00:00Z"))) == 5


def test_absolute_window(log: Logger) -> None:
    where = TimeRangeNode(since="2026-07-22T00:00:00Z", until="2026-07-23T10:00:00Z")
    assert sorted(run(log, where)) == [
        "CRITICAL disk full",
        "ERROR payment failed order=42",
        "WARN timeout contacting cache",
    ]


def test_bounds_are_inclusive(log: Logger) -> None:
    where = TimeRangeNode(since="2026-07-22T08:00:00Z", until="2026-07-22T08:00:00Z")
    assert run(log, where) == ["CRITICAL disk full"]


def test_relative_resolves_against_corpus_not_wall_clock(log: Logger) -> None:
    """Corpus timestamps are in the past; wall-clock `-24h` would return nothing."""
    assert log.index.reference_now().isoformat() == "2026-07-23T11:00:00+00:00"
    assert len(run(log, TimeRangeNode(since="-24h"))) == 5


def test_relative_units(log: Logger) -> None:
    assert len(run(log, TimeRangeNode(since="-120m"))) == 5  # 09:00 .. 11:00
    assert len(run(log, TimeRangeNode(since="-7d"))) == CORPUS_SIZE - 1  # NULL timestamp drops


def test_explicit_now_overrides_reference(log: Logger) -> None:
    """Mixed relative/absolute bounds, resolved against a caller-supplied instant."""
    now = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)
    where = TimeRangeNode(since="-2h", until="2026-07-20T10:00:00Z")
    plan = QueryPlan(queries=[Query(where=where)])
    assert [r.raw for r in log.index.execute(plan, now=now).rows] == ["ERROR timeout contacting db"]


def test_null_timestamp_excluded_from_range_but_kept_by_its_negation(log: Logger) -> None:
    where = TimeRangeNode(since="2026-07-01T00:00:00Z")
    assert "plain line with no level marker" not in run(log, where)
    assert "plain line with no level marker" in run(log, NotNode(of=[where]))


def test_naive_and_offset_timestamps_compare_correctly(tmp_path) -> None:
    """Ingest normalizes to canonical UTC, so mixed input formats stay ordered."""
    log = Logger(tmp_path / "tz.db")
    try:
        log.ingest_line("first", timestamp="2026-07-23 09:00:00")  # naive, assumed UTC
        log.ingest_line("second", timestamp="2026-07-23T12:00:00+02:00")  # == 10:00Z
        log.ingest_line("third", timestamp="2026-07-23T11:00:00Z")
        where = TimeRangeNode(since="2026-07-23T09:30:00Z", until="2026-07-23T10:30:00Z")
        assert run(log, where) == ["second"]
    finally:
        log.close()


# --- aggregation --------------------------------------------------------------


def test_count_without_group_by(log: Logger) -> None:
    result = log.execute_plan(QueryPlan(queries=[Query(aggregate=Aggregate())]))
    assert result.groups == [AggregateGroup(key={}, count=CORPUS_SIZE)]
    assert result.rows == []


def test_count_group_by_severity(log: Logger) -> None:
    plan = QueryPlan(
        queries=[Query(aggregate=Aggregate(group_by=[GroupByField.SEVERITY]), limit=10)]
    )
    groups = log.execute_plan(plan).groups
    assert {g.key["severity"]: g.count for g in groups} == {
        "ERROR": 3,
        "INFO": 2,
        "WARN": 1,
        "CRITICAL": 1,
        None: 1,
    }


def test_aggregate_groups_are_ordered_by_count_desc(log: Logger) -> None:
    plan = QueryPlan(
        queries=[Query(aggregate=Aggregate(group_by=[GroupByField.SEVERITY]), limit=10)]
    )
    counts = [g.count for g in log.execute_plan(plan).groups]
    assert counts == sorted(counts, reverse=True)


def test_aggregate_applies_the_same_filter_tree(log: Logger) -> None:
    """Aggregation is a modifier on a filtered query, not a separate mode."""
    plan = QueryPlan(
        queries=[
            Query(
                where=AndNode(
                    of=[SeverityNode(value="ERROR"), NotNode(of=[TermNode(value="timeout")])]
                ),
                aggregate=Aggregate(group_by=[GroupByField.TEMPLATE_ID]),
            )
        ]
    )
    groups = log.execute_plan(plan).groups
    assert [g.count for g in groups] == [2]


def test_aggregate_having_min_count(log: Logger) -> None:
    plan = QueryPlan(
        queries=[
            Query(
                aggregate=Aggregate(
                    group_by=[GroupByField.TEMPLATE_ID], having=Having(min_count=2)
                ),
                limit=50,
            )
        ]
    )
    groups = log.execute_plan(plan).groups
    assert groups and all(g.count >= 2 for g in groups)


def test_aggregate_having_max_count_excludes_spikes(log: Logger) -> None:
    plan = QueryPlan(
        queries=[
            Query(
                aggregate=Aggregate(
                    group_by=[GroupByField.TEMPLATE_ID], having=Having(max_count=1)
                ),
                limit=50,
            )
        ]
    )
    assert all(g.count == 1 for g in log.execute_plan(plan).groups)


def test_aggregate_two_dimensions(log: Logger) -> None:
    plan = QueryPlan(
        queries=[
            Query(
                where=SeverityNode(value="ERROR"),
                aggregate=Aggregate(
                    group_by=[GroupByField.SEVERITY, GroupByField.LOCATION_KEY]
                ),
                limit=50,
            )
        ]
    )
    groups = log.execute_plan(plan).groups
    assert {(g.key["severity"], g.key["location_key"]): g.count for g in groups} == {
        ("ERROR", "api:svc/api.log"): 2,
        ("ERROR", "worker:svc/worker.log"): 1,
    }


def test_aggregate_respects_limit(log: Logger) -> None:
    plan = QueryPlan(
        queries=[Query(aggregate=Aggregate(group_by=[GroupByField.TEMPLATE_ID]), limit=2)]
    )
    assert len(log.execute_plan(plan).groups) == 2


# --- limit and order ----------------------------------------------------------


def test_limit_truncates(log: Logger) -> None:
    assert len(run(log, limit=3)) == 3


def test_order_newest_and_oldest_are_opposite_ends(log: Logger) -> None:
    newest = run(log, limit=2, order="newest")
    oldest = run(log, limit=2, order="oldest")
    assert newest == ["INFO payment ok order=44", "plain line with no level marker"]
    assert oldest == ["ERROR payment failed order=42", "ERROR payment failed order=43"]


# --- multi-query decomposition ------------------------------------------------


def test_multi_query_unions_and_deduplicates(log: Logger) -> None:
    plan = QueryPlan(
        queries=[
            Query(label="errors", where=SeverityNode(value="ERROR")),
            Query(label="payments", where=TermNode(value="payment")),
        ]
    )
    result = log.execute_plan(plan)
    assert len(result.row_ids) == len(set(result.row_ids))
    assert len(result.row_ids) == 4  # 3 errors + 1 INFO payment
    assert result.query_count == 2


def test_per_query_results_stay_addressable_by_label(log: Logger) -> None:
    plan = QueryPlan(
        queries=[
            Query(label="before", where=TimeRangeNode(until="2026-07-22T23:59:59Z")),
            Query(label="after", where=TimeRangeNode(since="2026-07-23T00:00:00Z")),
        ]
    )
    by_label = {r.label: len(r.rows) for r in log.execute_plan(plan).results}
    assert by_label == {"before": 2, "after": 5}


def test_aggregate_and_row_queries_compose_in_one_plan(log: Logger) -> None:
    plan = QueryPlan(
        queries=[
            Query(label="counts", aggregate=Aggregate(group_by=[GroupByField.SEVERITY]), limit=10),
            Query(label="samples", where=SeverityNode(value="ERROR"), limit=2),
        ]
    )
    result = log.execute_plan(plan)
    assert len(result.groups) == 5
    assert len(result.rows) == 2


# --- rows_scanned (the efficiency reward signal) ------------------------------


def test_unfiltered_query_scans_the_table(log: Logger) -> None:
    assert scanned(log) == CORPUS_SIZE


def test_scanned_counts_candidates_not_returned_rows(log: Logger) -> None:
    result = log.execute_plan(
        QueryPlan(queries=[Query(where=SeverityNode(value="ERROR"), limit=1)])
    )
    assert len(result.rows) == 1
    assert result.rows_scanned == 3


def test_positive_term_narrows_the_scan(log: Logger) -> None:
    assert scanned(log, TermNode(value="payment")) == 3


def test_conjunction_scans_the_narrower_side(log: Logger) -> None:
    where = AndNode(of=[TermNode(value="payment"), SeverityNode(value="ERROR")])
    assert scanned(log, where) == 2


def test_negation_never_reduces_the_scan(log: Logger) -> None:
    assert scanned(log, NotNode(of=[TermNode(value="payment")])) == CORPUS_SIZE


def test_negation_beside_a_positive_still_scans_the_positive_set(log: Logger) -> None:
    where = AndNode(of=[TermNode(value="payment"), NotNode(of=[SeverityNode(value="INFO")])])
    assert scanned(log, where) == 3
    assert len(run(log, where)) == 2


def test_disjunction_scans_the_union(log: Logger) -> None:
    where = OrNode(of=[TermNode(value="payment"), TermNode(value="timeout")])
    assert scanned(log, where) == 5


def test_disjunction_with_an_unbounded_branch_scans_everything(log: Logger) -> None:
    where = OrNode(of=[TermNode(value="payment"), NotNode(of=[SeverityNode(value="INFO")])])
    assert scanned(log, where) == CORPUS_SIZE


def test_scanned_is_at_least_rows_returned(log: Logger) -> None:
    for where in (None, TermNode(value="payment"), NotNode(of=[TermNode(value="payment")])):
        result = log.execute_plan(QueryPlan(queries=[Query(where=where, limit=100)]))
        assert result.rows_scanned >= len(result.rows)


def test_scanned_sums_across_a_decomposed_plan(log: Logger) -> None:
    plan = QueryPlan(
        queries=[
            Query(where=TermNode(value="payment")),
            Query(where=TermNode(value="timeout")),
        ]
    )
    result = log.execute_plan(plan)
    assert result.rows_scanned == 3 + 2
    assert [r.rows_scanned for r in result.results] == [3, 2]


def test_aggregate_queries_still_report_scan_cost(log: Logger) -> None:
    plan = QueryPlan(
        queries=[Query(where=SeverityNode(value="ERROR"), aggregate=Aggregate())]
    )
    assert log.execute_plan(plan).rows_scanned == 3


# --- untrusted term handling ---------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        'payment" OR raw:x',
        'payment" NEAR("timeout',
        '" OR "',
        "payment*",
        "payment OR timeout",
        "raw:payment",
        "payment\x00drop",
        "NEAR(payment timeout)",
        "{payment timeout}",
        "^payment",
        "'; DROP TABLE log_entries; --",
    ],
)
def test_hostile_terms_are_escaped_not_executed(log: Logger, hostile: str) -> None:
    """Terms are model-generated. FTS operator syntax inside one must stay literal."""
    matched = run(log, TermNode(value=hostile))
    assert len(matched) < CORPUS_SIZE
    assert log.index.row_count() == CORPUS_SIZE  # nothing was dropped or rewritten


def test_term_with_only_punctuation_matches_nothing(log: Logger) -> None:
    assert run(log, TermNode(value='"')) == []


def test_quoted_term_still_matches_its_literal_text(tmp_path) -> None:
    log = Logger(tmp_path / "quotes.db")
    try:
        log.ingest_line('ERROR unexpected token " in payload')
        log.ingest_line("INFO nothing to see")
        assert len(run(log, TermNode(value='unexpected token'))) == 1
    finally:
        log.close()
