"""Execute a sampled plan; its result *is* the gold answer (decision 0004).

Also where structural rejection happens — everything that can be decided from
the plan and its execution alone, before any money is spent authoring a
question. Each rejection returns a short reason code, counted in the manifest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from common import MAX_LIMIT, AndNode, NotNode, OrNode, Query, QueryPlan
from logger.index import LogIndex
from logger.validator import validate_plan

# A row query must stay selective: past this share of the split the "answer"
# is most of the corpus and the question is not a retrieval question any more.
MAX_ROW_FRACTION = 0.25


@dataclass(frozen=True)
class Gold:
    """Execution-defined gold. Row IDs for row queries, groups for aggregates (0012)."""

    row_ids: list[int]
    groups: list[dict] = field(default_factory=list)
    aggregate_labels: list[str | None] = field(default_factory=list)
    per_query_counts: list[int] = field(default_factory=list)
    rows_scanned: int = 0

    def to_dict(self) -> dict:
        return {
            "row_ids": self.row_ids,
            "groups": self.groups,
            "aggregate_labels": self.aggregate_labels,
            "per_query_counts": self.per_query_counts,
            "rows_scanned": self.rows_scanned,
        }


def compute_gold(
    index: LogIndex,
    plan: QueryPlan,
    *,
    now: datetime,
    row_count: int,
    max_fraction: float = MAX_ROW_FRACTION,
) -> tuple[Gold | None, str | None]:
    """Return (gold, None) on success or (None, rejection_reason)."""
    validation = validate_plan(plan)
    if not validation.ok:
        return None, "invalid_plan"

    result = index.execute(plan, now=now)
    cap = max(1, int(row_count * max_fraction))
    counts: list[int] = []
    for query, qres in zip(plan.queries, result.results, strict=True):
        if query.aggregate is not None:
            if not qres.groups:
                return None, "empty_aggregate"
            if len(qres.groups) >= MAX_LIMIT:
                return None, "truncated_aggregate"
            counts.append(len(qres.groups))
            continue
        n = len(qres.rows)
        if n == 0:
            return None, "empty_rows"
        if n >= MAX_LIMIT:
            # Hit the cap: the true match set may be larger, so this is not
            # the complete set gold must be (decision 0013).
            return None, "truncated_rows"
        if n > cap:
            return None, "too_broad"
        counts.append(n)

    for query in plan.queries:
        reason = _operator_redundancy(index, query, now)
        if reason:
            return None, reason

    if len(plan.queries) > 1 and _has_redundant_query(result.results, plan):
        return None, "redundant_query"

    gold = Gold(
        row_ids=sorted(result.row_ids),
        groups=[{"key": g.key, "count": g.count} for g in result.groups],
        aggregate_labels=[q.label for q in plan.queries if q.aggregate is not None],
        per_query_counts=counts,
        rows_scanned=result.rows_scanned,
    )
    return gold, None


def _ids(index: LogIndex, query: Query, now: datetime) -> set[int]:
    return set(index.query(query.model_copy(update={"aggregate": None}), now=now).row_ids)


def _operator_redundancy(index: LogIndex, query: Query, now: datetime) -> str | None:
    """Every `not` must exclude something and every `or` branch must add something.

    Otherwise the plan carries an operator that does no work, and the question
    written for it will not mention it — teaching the planner to emit noise.
    """
    where = query.where
    if not isinstance(where, (AndNode, OrNode)):
        return None
    full = _ids(index, query, now)
    nodes = where.of if isinstance(where, AndNode) else [where]
    for child in nodes:
        if isinstance(child, NotNode):
            rest = [c for c in where.of if c is not child]
            relaxed = query.model_copy(update={"where": AndNode(of=rest) if rest else None})
            if _ids(index, relaxed, now) == full:
                return "noop_negation"
        if isinstance(child, OrNode):
            for branch in child.of:
                alone = _ids(index, _replace(query, child, branch), now)
                if alone == full:
                    return "noop_disjunction"
    return None


def _replace(query: Query, old, new) -> Query:
    where = query.where
    if where is old:
        return query.model_copy(update={"where": new})
    assert isinstance(where, AndNode)
    swapped = [new if c is old else c for c in where.of]
    return query.model_copy(update={"where": AndNode(of=swapped)})


def _has_redundant_query(results, plan: QueryPlan) -> bool:
    """A row query whose rows are a subset of another query's adds nothing."""
    sets = [
        set(r.row_ids) if q.aggregate is None else None
        for q, r in zip(plan.queries, results, strict=True)
    ]
    for i, a in enumerate(sets):
        for j, b in enumerate(sets):
            if i != j and a is not None and b is not None and a <= b:
                return True
    return False
