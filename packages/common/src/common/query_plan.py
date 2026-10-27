"""Frozen query-plan DSL for Logger's planner.

This is a **training contract**, not just a schema: the post-trained planner
emits instances of `QueryPlan`, and reward is computed by executing them
(decision 0002). Changing the shape invalidates datasets and checkpoints
together, so `SCHEMA_VERSION` is bumped, never silently edited.

Types only — parsing, validation, and execution live in `logger`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0.0"
"""Frozen at the end of slice 002. Major-version mismatch is a hard reject."""

MAX_QUERIES = 8
MAX_NODE_CHILDREN = 8
MAX_NODE_DEPTH = 6
MAX_TERM_LENGTH = 128
MAX_LIMIT = 1000
DEFAULT_LIMIT = 50
MAX_GROUP_BY = 2


class Severity(StrEnum):
    """Severities the index stores. `WARNING` is normalized to `WARN` on input."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    FATAL = "FATAL"


class GroupByField(StrEnum):
    TEMPLATE_ID = "template_id"
    SEVERITY = "severity"
    LOCATION_KEY = "location_key"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- filter tree -------------------------------------------------------------
#
# One recursive boolean expression per query. `and`/`or`/`not` nest freely over
# five leaf predicates, so negation and disjunction compose instead of being
# flat side-lists. `of` is always a list, including for `not` (arity 1).


class AndNode(_Strict):
    """All children must match."""

    op: Literal["and"] = "and"
    of: list[Node] = Field(default_factory=list)


class OrNode(_Strict):
    """At least one child must match."""

    op: Literal["or"] = "or"
    of: list[Node] = Field(default_factory=list)


class NotNode(_Strict):
    """The single child must not match. A row with a NULL field does not match."""

    op: Literal["not"] = "not"
    of: list[Node] = Field(default_factory=list)


class TermNode(_Strict):
    """FTS5 phrase match over the raw line and its mined template."""

    op: Literal["term"] = "term"
    value: str


class SeverityNode(_Strict):
    op: Literal["severity"] = "severity"
    value: Severity

    @field_validator("value", mode="before")
    @classmethod
    def _normalize(cls, value: object) -> object:
        if isinstance(value, str):
            upper = value.strip().upper()
            return "WARN" if upper == "WARNING" else upper
        return value


class TemplateIdNode(_Strict):
    op: Literal["template_id"] = "template_id"
    value: int


class LocationKeyNode(_Strict):
    op: Literal["location_key"] = "location_key"
    value: str


class TimeRangeNode(_Strict):
    """Half-open-friendly window over `timestamp`; both bounds inclusive.

    Bounds are either an ISO-8601 instant or a relative offset (`-24h`, `-30m`,
    `-7d`, `-2w`, `-90s`) resolved against the executor's reference time.
    """

    op: Literal["time_range"] = "time_range"
    since: str | None = None
    until: str | None = None


Node = Annotated[
    Union[
        AndNode,
        OrNode,
        NotNode,
        TermNode,
        SeverityNode,
        TemplateIdNode,
        LocationKeyNode,
        TimeRangeNode,
    ],
    Field(discriminator="op"),
]

AndNode.model_rebuild()
OrNode.model_rebuild()
NotNode.model_rebuild()


# --- aggregation -------------------------------------------------------------


class Having(_Strict):
    """Post-aggregation count filter — how "templates that spiked" is expressed."""

    min_count: int | None = None
    max_count: int | None = None


class Aggregate(_Strict):
    """Counts over the same filtered set a row query would return."""

    op: Literal["count"] = "count"
    group_by: list[GroupByField] = Field(default_factory=list)
    having: Having | None = None


# --- plan --------------------------------------------------------------------


class Query(_Strict):
    """One targeted query. Returns rows, or aggregate groups when `aggregate` is set."""

    label: str | None = Field(
        default=None,
        description="Optional name; unique within a plan. Makes decomposed queries addressable.",
    )
    where: Node | None = Field(
        default=None,
        description="Boolean filter tree. None matches every row.",
    )
    limit: int = DEFAULT_LIMIT
    order: Literal["newest", "oldest"] = "newest"
    aggregate: Aggregate | None = None


class QueryPlan(_Strict):
    """A small set of targeted queries whose row results union (§3.1)."""

    version: str = SCHEMA_VERSION
    queries: list[Query] = Field(default_factory=list)


# --- validator output --------------------------------------------------------


class PlanErrorCode(StrEnum):
    """Distinguishable failure modes. This is the format-reward signal (0005)."""

    # payload / structure
    INVALID_JSON = "invalid_json"
    NOT_AN_OBJECT = "not_an_object"
    UNKNOWN_FIELD = "unknown_field"
    MISSING_FIELD = "missing_field"
    WRONG_TYPE = "wrong_type"
    UNKNOWN_OP = "unknown_op"
    UNSUPPORTED_VERSION = "unsupported_version"

    # plan shape
    EMPTY_QUERIES = "empty_queries"
    TOO_MANY_QUERIES = "too_many_queries"
    DUPLICATE_QUERY = "duplicate_query"
    DUPLICATE_LABEL = "duplicate_label"

    # filter-tree shape
    EMPTY_GROUP = "empty_group"
    DEGENERATE_GROUP = "degenerate_group"
    NOT_ARITY = "not_arity"
    MAX_DEPTH_EXCEEDED = "max_depth_exceeded"
    TOO_MANY_CHILDREN = "too_many_children"

    # leaf values
    INVALID_SEVERITY = "invalid_severity"
    INVALID_TERM = "invalid_term"
    INVALID_TIME_FORMAT = "invalid_time_format"
    INVALID_TIME_RANGE = "invalid_time_range"
    INVALID_LIMIT = "invalid_limit"
    INVALID_AGGREGATE = "invalid_aggregate"
    INVALID_VALUE = "invalid_value"

    # semantics
    CONTRADICTION = "contradiction"


class PlanError(_Strict):
    """One machine-readable validation failure."""

    code: PlanErrorCode
    path: str = Field(description="Dotted/indexed path into the plan, e.g. queries[0].where.of[1]")
    message: str
    value: str | None = Field(default=None, description="Offending value, stringified")


class PlanValidation(_Strict):
    """Result of validating a candidate plan."""

    ok: bool
    errors: list[PlanError] = Field(default_factory=list)
    plan: QueryPlan | None = Field(
        default=None,
        description="Parsed plan when the payload was structurally parseable, even if semantics failed",
    )

    def codes(self) -> list[PlanErrorCode]:
        return [e.code for e in self.errors]
