"""Validator error taxonomy.

`validate_plan` produces the format-reward signal (decision 0005), so what
matters is not just *that* a bad plan is rejected but that each failure mode
gets its own code and a path pointing at the offending node.
"""

from __future__ import annotations

import json

import pytest
from common import (
    MAX_NODE_CHILDREN,
    MAX_QUERIES,
    MAX_TERM_LENGTH,
    SCHEMA_VERSION,
    AndNode,
    NotNode,
    OrNode,
    Query,
    QueryPlan,
    SeverityNode,
    TemplateIdNode,
    TermNode,
)
from common import (
    PlanErrorCode as C,
)
from logger import validate_plan

VALID = {
    "version": SCHEMA_VERSION,
    "queries": [
        {
            "label": "recent_timeouts",
            "where": {
                "op": "and",
                "of": [
                    {"op": "term", "value": "timeout"},
                    {"op": "severity", "value": "ERROR"},
                    {"op": "not", "of": [{"op": "term", "value": "healthcheck"}]},
                    {"op": "time_range", "since": "-24h"},
                ],
            },
            "limit": 50,
        }
    ],
}


def codes(payload) -> list[C]:
    return validate_plan(payload).codes()


def only(payload) -> C:
    result = validate_plan(payload)
    assert len(result.errors) == 1, result.errors
    return result.errors[0].code


# --- happy path ---------------------------------------------------------------


def test_valid_plan_passes_and_is_parsed() -> None:
    result = validate_plan(json.dumps(VALID))
    assert result.ok
    assert result.errors == []
    assert result.plan is not None
    assert result.plan.queries[0].label == "recent_timeouts"


def test_accepts_dict_str_bytes_and_model() -> None:
    for payload in (VALID, json.dumps(VALID), json.dumps(VALID).encode(), QueryPlan(**VALID)):
        assert validate_plan(payload).ok


def test_version_defaults_to_current_schema() -> None:
    result = validate_plan({"queries": [{"where": {"op": "term", "value": "x"}}]})
    assert result.ok
    assert result.plan is not None
    assert result.plan.version == SCHEMA_VERSION


def test_minimal_plan_with_no_filter_is_valid() -> None:
    assert validate_plan({"queries": [{"limit": 10}]}).ok


# --- payload / structure ------------------------------------------------------


def test_invalid_json() -> None:
    assert only("{not json") is C.INVALID_JSON


def test_not_an_object() -> None:
    assert only("[1, 2]") is C.NOT_AN_OBJECT
    assert only('"a string"') is C.NOT_AN_OBJECT


def test_unknown_field_is_distinct_from_wrong_type() -> None:
    assert only({"queries": [{"wat": 1}]}) is C.UNKNOWN_FIELD
    assert only({"queries": [{"limit": "fifty"}]}) is C.WRONG_TYPE


def test_unknown_field_at_plan_level() -> None:
    assert only({"queries": [], "extra": 1}) is C.UNKNOWN_FIELD


def test_missing_field_in_a_leaf() -> None:
    assert only({"queries": [{"where": {"op": "term"}}]}) is C.MISSING_FIELD


def test_unknown_op() -> None:
    assert only({"queries": [{"where": {"op": "regex", "value": "x"}}]}) is C.UNKNOWN_OP


def test_missing_op_discriminator() -> None:
    assert only({"queries": [{"where": {"value": "x"}}]}) is C.UNKNOWN_OP


def test_error_path_points_at_the_offending_node() -> None:
    payload = {
        "queries": [
            {"where": {"op": "term", "value": "ok"}},
            {"where": {"op": "and", "of": [{"op": "term", "value": "a"}, {"op": "bogus"}]}},
        ]
    }
    error = validate_plan(payload).errors[0]
    assert error.path == "$.queries[1].where.of[1]"


# --- version ------------------------------------------------------------------


def test_unsupported_major_version() -> None:
    assert only({"version": "2.0.0", "queries": [{"limit": 5}]}) is C.UNSUPPORTED_VERSION


def test_minor_version_drift_is_accepted() -> None:
    assert validate_plan({"version": "1.7.3", "queries": [{"limit": 5}]}).ok


def test_garbage_version() -> None:
    assert only({"version": "latest", "queries": [{"limit": 5}]}) is C.UNSUPPORTED_VERSION


# --- plan shape ---------------------------------------------------------------


def test_empty_queries() -> None:
    assert only({"queries": []}) is C.EMPTY_QUERIES


def test_too_many_queries() -> None:
    payload = {"queries": [{"where": {"op": "template_id", "value": i}} for i in range(MAX_QUERIES + 1)]}
    assert only(payload) is C.TOO_MANY_QUERIES


def test_duplicate_query_is_flagged_even_under_different_labels() -> None:
    query = {"where": {"op": "term", "value": "timeout"}}
    payload = {"queries": [{**query, "label": "a"}, {**query, "label": "b"}]}
    assert only(payload) is C.DUPLICATE_QUERY


def test_duplicate_label() -> None:
    payload = {
        "queries": [
            {"label": "x", "where": {"op": "term", "value": "a"}},
            {"label": "x", "where": {"op": "term", "value": "b"}},
        ]
    }
    assert only(payload) is C.DUPLICATE_LABEL


def test_blank_label() -> None:
    assert only({"queries": [{"label": "  ", "limit": 5}]}) is C.INVALID_VALUE


# --- filter-tree shape --------------------------------------------------------


def test_empty_group() -> None:
    assert only({"queries": [{"where": {"op": "and", "of": []}}]}) is C.EMPTY_GROUP


def test_degenerate_group() -> None:
    payload = {"queries": [{"where": {"op": "or", "of": [{"op": "term", "value": "a"}]}}]}
    assert only(payload) is C.DEGENERATE_GROUP


def test_not_arity() -> None:
    payload = {
        "queries": [
            {
                "where": {
                    "op": "not",
                    "of": [{"op": "term", "value": "a"}, {"op": "term", "value": "b"}],
                }
            }
        ]
    }
    assert only(payload) is C.NOT_ARITY


def test_empty_not() -> None:
    assert only({"queries": [{"where": {"op": "not", "of": []}}]}) is C.NOT_ARITY


def test_too_many_children() -> None:
    children = [{"op": "template_id", "value": i} for i in range(MAX_NODE_CHILDREN + 1)]
    assert only({"queries": [{"where": {"op": "or", "of": children}}]}) is C.TOO_MANY_CHILDREN


def test_max_depth_exceeded() -> None:
    node: dict = {"op": "term", "value": "deep"}
    for _ in range(8):
        node = {"op": "not", "of": [node]}
    assert C.MAX_DEPTH_EXCEEDED in codes({"queries": [{"where": node}]})


def test_depth_at_the_limit_is_accepted() -> None:
    node: dict = {"op": "term", "value": "deep"}
    for _ in range(5):  # where is depth 1, so 5 wrappers reaches MAX_NODE_DEPTH == 6
        node = {"op": "not", "of": [node]}
    assert validate_plan({"queries": [{"where": node}]}).ok


# --- leaf values --------------------------------------------------------------


def test_invalid_severity() -> None:
    assert only({"queries": [{"where": {"op": "severity", "value": "SEVERE"}}]}) is C.INVALID_SEVERITY


def test_severity_aliases_are_accepted() -> None:
    for value in ("error", "Error", "WARNING", "warn"):
        assert validate_plan({"queries": [{"where": {"op": "severity", "value": value}}]}).ok


def test_blank_term() -> None:
    assert only({"queries": [{"where": {"op": "term", "value": "   "}}]}) is C.INVALID_TERM


def test_overlong_term() -> None:
    payload = {"queries": [{"where": {"op": "term", "value": "x" * (MAX_TERM_LENGTH + 1)}}]}
    assert only(payload) is C.INVALID_TERM


def test_control_character_only_term() -> None:
    assert only({"queries": [{"where": {"op": "term", "value": "\x00\x01"}}]}) is C.INVALID_TERM


def test_blank_location_key() -> None:
    assert only({"queries": [{"where": {"op": "location_key", "value": ""}}]}) is C.INVALID_VALUE


def test_invalid_time_format() -> None:
    payload = {"queries": [{"where": {"op": "time_range", "since": "last tuesday"}}]}
    assert only(payload) is C.INVALID_TIME_FORMAT


def test_relative_offset_must_be_negative_and_unit_suffixed() -> None:
    for bad in ("24h", "+24h", "-24y", "-h"):
        payload = {"queries": [{"where": {"op": "time_range", "since": bad}}]}
        assert only(payload) is C.INVALID_TIME_FORMAT


@pytest.mark.parametrize("good", ["-90s", "-30m", "-24h", "-7d", "-2w"])
def test_accepted_relative_units(good: str) -> None:
    assert validate_plan({"queries": [{"where": {"op": "time_range", "since": good}}]}).ok


def test_empty_time_range() -> None:
    assert only({"queries": [{"where": {"op": "time_range"}}]}) is C.INVALID_TIME_RANGE


def test_inverted_absolute_time_range() -> None:
    payload = {
        "queries": [
            {
                "where": {
                    "op": "time_range",
                    "since": "2026-07-23T00:00:00Z",
                    "until": "2026-07-01T00:00:00Z",
                }
            }
        ]
    }
    assert only(payload) is C.INVALID_TIME_RANGE


def test_inverted_relative_time_range() -> None:
    payload = {"queries": [{"where": {"op": "time_range", "since": "-1h", "until": "-24h"}}]}
    assert only(payload) is C.INVALID_TIME_RANGE


def test_invalid_limit() -> None:
    assert only({"queries": [{"limit": 0}]}) is C.INVALID_LIMIT
    assert only({"queries": [{"limit": 10_000}]}) is C.INVALID_LIMIT


# --- aggregation ---------------------------------------------------------------


def test_invalid_group_by_field() -> None:
    payload = {"queries": [{"aggregate": {"op": "count", "group_by": ["message"]}}]}
    assert only(payload) is C.INVALID_AGGREGATE


def test_invalid_aggregate_op() -> None:
    payload = {"queries": [{"aggregate": {"op": "sum", "group_by": []}}]}
    assert only(payload) is C.INVALID_VALUE


def test_duplicate_group_by_fields() -> None:
    payload = {
        "queries": [{"aggregate": {"op": "count", "group_by": ["severity", "severity"]}}]
    }
    assert only(payload) is C.INVALID_AGGREGATE


def test_too_many_group_by_fields() -> None:
    payload = {
        "queries": [
            {
                "aggregate": {
                    "op": "count",
                    "group_by": ["severity", "template_id", "location_key"],
                }
            }
        ]
    }
    assert only(payload) is C.INVALID_AGGREGATE


def test_empty_having() -> None:
    payload = {"queries": [{"aggregate": {"op": "count", "having": {}}}]}
    assert only(payload) is C.INVALID_AGGREGATE


def test_negative_min_count() -> None:
    payload = {"queries": [{"aggregate": {"op": "count", "having": {"min_count": -1}}}]}
    assert only(payload) is C.INVALID_AGGREGATE


def test_impossible_having_window_is_a_contradiction() -> None:
    payload = {
        "queries": [{"aggregate": {"op": "count", "having": {"min_count": 10, "max_count": 2}}}]
    }
    assert only(payload) is C.CONTRADICTION


# --- semantic contradictions ----------------------------------------------------


def test_two_severities_anded() -> None:
    where = AndNode(of=[SeverityNode(value="ERROR"), SeverityNode(value="INFO")])
    assert only(QueryPlan(queries=[Query(where=where)])) is C.CONTRADICTION


def test_two_template_ids_anded() -> None:
    where = AndNode(of=[TemplateIdNode(value=1), TemplateIdNode(value=2)])
    assert only(QueryPlan(queries=[Query(where=where)])) is C.CONTRADICTION


def test_term_asserted_and_negated_in_the_same_conjunction() -> None:
    where = AndNode(of=[TermNode(value="timeout"), NotNode(of=[TermNode(value="timeout")])])
    assert only(QueryPlan(queries=[Query(where=where)])) is C.CONTRADICTION


def test_two_severities_ored_is_fine() -> None:
    where = OrNode(of=[SeverityNode(value="ERROR"), SeverityNode(value="INFO")])
    assert validate_plan(QueryPlan(queries=[Query(where=where)])).ok


def test_same_term_in_different_or_branches_is_fine() -> None:
    where = OrNode(
        of=[
            AndNode(of=[TermNode(value="timeout"), SeverityNode(value="ERROR")]),
            NotNode(of=[TermNode(value="timeout")]),
        ]
    )
    assert validate_plan(QueryPlan(queries=[Query(where=where)])).ok


# --- reporting ------------------------------------------------------------------


def test_all_errors_are_reported_not_just_the_first() -> None:
    payload = {
        "queries": [
            {"limit": 0, "where": {"op": "time_range"}},
            {"limit": -5, "where": {"op": "and", "of": []}},
        ]
    }
    assert sorted(set(codes(payload))) == sorted(
        {C.INVALID_LIMIT, C.INVALID_TIME_RANGE, C.EMPTY_GROUP}
    )


def test_semantically_invalid_plans_still_expose_the_parsed_plan() -> None:
    """Reward needs to distinguish "unparseable" from "parsed but wrong"."""
    result = validate_plan({"queries": [{"limit": 0}]})
    assert not result.ok
    assert result.plan is not None


def test_unparseable_plans_expose_no_plan() -> None:
    assert validate_plan("{").plan is None


def test_errors_are_json_serializable() -> None:
    errors = validate_plan({"queries": []}).model_dump(mode="json")["errors"]
    assert json.loads(json.dumps(errors))[0]["code"] == "empty_queries"


def test_validator_never_raises_on_hostile_input() -> None:
    for payload in ("", "null", "0", "[]", "{}", '{"queries": null}', '{"queries": [null]}'):
        assert validate_plan(payload).ok is False
