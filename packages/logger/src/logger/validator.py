"""Strict plan validator returning structured, typed errors.

The error list is the format-reward term in decision 0005, so failure modes must
be *distinguishable*: every rejection carries a `PlanErrorCode`, a path into the
plan, and a human message. A bare boolean would collapse "malformed JSON" and
"severity contradicts its own negation" into one indistinguishable signal.
"""

from __future__ import annotations

import json
from typing import Any

from common import (
    MAX_GROUP_BY,
    MAX_LIMIT,
    MAX_NODE_CHILDREN,
    MAX_NODE_DEPTH,
    MAX_QUERIES,
    MAX_TERM_LENGTH,
    SCHEMA_VERSION,
    AndNode,
    LocationKeyNode,
    NotNode,
    OrNode,
    PlanError,
    PlanErrorCode,
    PlanValidation,
    Query,
    QueryPlan,
    SeverityNode,
    TemplateIdNode,
    TermNode,
    TimeRangeNode,
)
from pydantic import ValidationError

from logger import timeutil
from logger.index import fts_phrase

_C = PlanErrorCode


def validate_plan(payload: str | bytes | dict[str, Any] | QueryPlan) -> PlanValidation:
    """Validate a candidate plan. Never raises — malformed input is a result, not an exception."""
    if isinstance(payload, QueryPlan):
        errors = _semantic_errors(payload)
        return PlanValidation(ok=not errors, errors=errors, plan=payload)

    if isinstance(payload, (str, bytes)):
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return PlanValidation(
                ok=False,
                errors=[_err(_C.INVALID_JSON, "$", f"payload is not valid JSON: {exc}")],
            )
    else:
        data = payload

    if not isinstance(data, dict):
        return PlanValidation(
            ok=False,
            errors=[
                _err(_C.NOT_AN_OBJECT, "$", f"plan must be a JSON object, got {type(data).__name__}")
            ],
        )

    try:
        plan = QueryPlan.model_validate(data)
    except ValidationError as exc:
        return PlanValidation(ok=False, errors=[_from_pydantic(e) for e in exc.errors()])

    errors = _semantic_errors(plan)
    return PlanValidation(ok=not errors, errors=errors, plan=plan)


# --- structural (pydantic) errors -------------------------------------------


_PYDANTIC_CODES = {
    "extra_forbidden": _C.UNKNOWN_FIELD,
    "missing": _C.MISSING_FIELD,
    "union_tag_invalid": _C.UNKNOWN_OP,
    "union_tag_not_found": _C.UNKNOWN_OP,
    "literal_error": _C.INVALID_VALUE,
    "json_invalid": _C.INVALID_JSON,
}


def _from_pydantic(entry: dict[str, Any]) -> PlanError:
    loc = entry.get("loc", ())
    kind = str(entry.get("type", ""))
    path = _fmt_path(loc)

    code = _PYDANTIC_CODES.get(kind)
    if code is None:
        if kind == "enum":
            if "severity" in loc:
                code = _C.INVALID_SEVERITY
            elif "group_by" in loc:
                code = _C.INVALID_AGGREGATE
            else:
                code = _C.INVALID_VALUE
        elif kind.endswith(("_type", "_parsing")):
            code = _C.WRONG_TYPE
        else:
            code = _C.INVALID_VALUE

    value = entry.get("input")
    return _err(code, path, str(entry.get("msg", kind)), value)


_UNION_TAGS = {"and", "or", "not", "term", "severity", "template_id", "location_key", "time_range"}


def _fmt_path(loc: tuple[Any, ...]) -> str:
    """Format a pydantic location, dropping discriminator tags.

    Pydantic inserts the matched union tag into the path; the semantic checks
    below do not. Paths from the two halves of the validator must agree, or
    consumers cannot key on them.
    """
    out = "$"
    previous: Any = None
    for part in loc:
        is_tag = part in _UNION_TAGS and (previous == "where" or isinstance(previous, int))
        if not is_tag:
            out += f"[{part}]" if isinstance(part, int) else f".{part}"
        previous = part
    return out


# --- semantic errors ---------------------------------------------------------


def _semantic_errors(plan: QueryPlan) -> list[PlanError]:
    errors: list[PlanError] = []

    if _major(plan.version) != _major(SCHEMA_VERSION):
        errors.append(
            _err(
                _C.UNSUPPORTED_VERSION,
                "$.version",
                f"plan targets schema {plan.version}, executor speaks {SCHEMA_VERSION}",
                plan.version,
            )
        )

    if not plan.queries:
        errors.append(_err(_C.EMPTY_QUERIES, "$.queries", "a plan needs at least one query"))
    elif len(plan.queries) > MAX_QUERIES:
        errors.append(
            _err(
                _C.TOO_MANY_QUERIES,
                "$.queries",
                f"{len(plan.queries)} queries exceeds the limit of {MAX_QUERIES}",
                len(plan.queries),
            )
        )

    seen_labels: set[str] = set()
    seen_queries: dict[str, int] = {}
    for i, query in enumerate(plan.queries):
        base = f"$.queries[{i}]"
        errors.extend(_query_errors(query, base))

        if query.label is not None:
            if not query.label.strip():
                errors.append(_err(_C.INVALID_VALUE, f"{base}.label", "label must not be blank"))
            elif query.label in seen_labels:
                errors.append(
                    _err(_C.DUPLICATE_LABEL, f"{base}.label", "label repeats", query.label)
                )
            seen_labels.add(query.label)

        fingerprint = query.model_dump_json(exclude={"label"})
        if fingerprint in seen_queries:
            errors.append(
                _err(
                    _C.DUPLICATE_QUERY,
                    base,
                    f"identical to queries[{seen_queries[fingerprint]}]; decompose or drop it",
                )
            )
        else:
            seen_queries[fingerprint] = i

    return errors


def _query_errors(query: Query, base: str) -> list[PlanError]:
    errors: list[PlanError] = []

    if query.limit < 1 or query.limit > MAX_LIMIT:
        errors.append(
            _err(
                _C.INVALID_LIMIT,
                f"{base}.limit",
                f"limit must be between 1 and {MAX_LIMIT}",
                query.limit,
            )
        )

    if query.aggregate is not None:
        errors.extend(_aggregate_errors(query, f"{base}.aggregate"))

    if query.where is not None:
        errors.extend(_node_errors(query.where, f"{base}.where", depth=1))

    return errors


def _aggregate_errors(query: Query, base: str) -> list[PlanError]:
    aggregate = query.aggregate
    assert aggregate is not None
    errors: list[PlanError] = []

    if len(aggregate.group_by) > MAX_GROUP_BY:
        errors.append(
            _err(
                _C.INVALID_AGGREGATE,
                f"{base}.group_by",
                f"at most {MAX_GROUP_BY} group-by fields",
                len(aggregate.group_by),
            )
        )
    if len(set(aggregate.group_by)) != len(aggregate.group_by):
        errors.append(
            _err(_C.INVALID_AGGREGATE, f"{base}.group_by", "group-by fields must be distinct")
        )

    having = aggregate.having
    if having is not None:
        if having.min_count is None and having.max_count is None:
            errors.append(
                _err(_C.INVALID_AGGREGATE, f"{base}.having", "having needs a bound; drop it instead")
            )
        if having.min_count is not None and having.min_count < 0:
            errors.append(
                _err(
                    _C.INVALID_AGGREGATE,
                    f"{base}.having.min_count",
                    "min_count must not be negative",
                    having.min_count,
                )
            )
        if (
            having.min_count is not None
            and having.max_count is not None
            and having.min_count > having.max_count
        ):
            errors.append(
                _err(
                    _C.CONTRADICTION,
                    f"{base}.having",
                    "min_count exceeds max_count; no group can match",
                )
            )

    return errors


def _node_errors(node: object, base: str, *, depth: int) -> list[PlanError]:
    errors: list[PlanError] = []

    if depth > MAX_NODE_DEPTH:
        return [
            _err(
                _C.MAX_DEPTH_EXCEEDED,
                base,
                f"filter tree nests deeper than {MAX_NODE_DEPTH}",
                depth,
            )
        ]

    if isinstance(node, (AndNode, OrNode)):
        if not node.of:
            errors.append(_err(_C.EMPTY_GROUP, f"{base}.of", f"`{node.op}` needs children"))
        elif len(node.of) == 1:
            errors.append(
                _err(
                    _C.DEGENERATE_GROUP,
                    f"{base}.of",
                    f"`{node.op}` with one child is a no-op; use the child directly",
                )
            )
        elif len(node.of) > MAX_NODE_CHILDREN:
            errors.append(
                _err(
                    _C.TOO_MANY_CHILDREN,
                    f"{base}.of",
                    f"{len(node.of)} children exceeds {MAX_NODE_CHILDREN}",
                    len(node.of),
                )
            )
        for i, child in enumerate(node.of):
            errors.extend(_node_errors(child, f"{base}.of[{i}]", depth=depth + 1))
        if isinstance(node, AndNode):
            errors.extend(_contradiction_errors(node, base))
        return errors

    if isinstance(node, NotNode):
        if len(node.of) != 1:
            errors.append(
                _err(
                    _C.NOT_ARITY,
                    f"{base}.of",
                    f"`not` takes exactly one child, got {len(node.of)}",
                    len(node.of),
                )
            )
        for i, child in enumerate(node.of):
            errors.extend(_node_errors(child, f"{base}.of[{i}]", depth=depth + 1))
        return errors

    if isinstance(node, TermNode):
        errors.extend(_term_errors(node.value, f"{base}.value"))
        return errors

    if isinstance(node, LocationKeyNode):
        if not node.value.strip():
            errors.append(_err(_C.INVALID_VALUE, f"{base}.value", "location_key must not be blank"))
        return errors

    if isinstance(node, TimeRangeNode):
        return _time_range_errors(node, base)

    return errors


def _term_errors(value: str, path: str) -> list[PlanError]:
    if not value.strip():
        return [_err(_C.INVALID_TERM, path, "term must not be blank", value)]
    if len(value) > MAX_TERM_LENGTH:
        return [
            _err(_C.INVALID_TERM, path, f"term exceeds {MAX_TERM_LENGTH} characters", len(value))
        ]
    if fts_phrase(value) is None:
        return [_err(_C.INVALID_TERM, path, "term is empty after stripping control characters", value)]
    return []


def _time_range_errors(node: TimeRangeNode, base: str) -> list[PlanError]:
    errors: list[PlanError] = []
    if node.since is None and node.until is None:
        return [_err(_C.INVALID_TIME_RANGE, base, "time_range needs `since`, `until`, or both")]

    bounds: dict[str, object] = {}
    for name in ("since", "until"):
        raw = getattr(node, name)
        if raw is None:
            continue
        if timeutil.is_relative(raw):
            bounds[name] = timeutil.parse_relative(raw)
            continue
        instant = timeutil.parse_instant(raw)
        if instant is None:
            errors.append(
                _err(
                    _C.INVALID_TIME_FORMAT,
                    f"{base}.{name}",
                    "expected an ISO-8601 instant or a relative offset like -24h",
                    raw,
                )
            )
        else:
            bounds[name] = instant

    since, until = bounds.get("since"), bounds.get("until")
    if since is not None and until is not None and type(since) is type(until) and since > until:  # type: ignore[operator]
        errors.append(
            _err(_C.INVALID_TIME_RANGE, base, "since is after until; no row can match")
        )
    return errors


def _contradiction_errors(node: AndNode, base: str) -> list[PlanError]:
    """Catch conjunctions that can never match. Direct children only — cheap and precise."""
    errors: list[PlanError] = []

    severities = {c.value for c in node.of if isinstance(c, SeverityNode)}
    if len(severities) > 1:
        errors.append(
            _err(
                _C.CONTRADICTION,
                base,
                "a row has one severity; ANDing several matches nothing",
                ",".join(sorted(severities)),
            )
        )

    templates = {c.value for c in node.of if isinstance(c, TemplateIdNode)}
    if len(templates) > 1:
        errors.append(
            _err(
                _C.CONTRADICTION,
                base,
                "a row has one template_id; ANDing several matches nothing",
                ",".join(str(t) for t in sorted(templates)),
            )
        )

    positive = {_fingerprint(c) for c in node.of if _fingerprint(c) is not None}
    for child in node.of:
        if not isinstance(child, NotNode) or len(child.of) != 1:
            continue
        negated = _fingerprint(child.of[0])
        if negated is not None and negated in positive:
            errors.append(
                _err(_C.CONTRADICTION, base, f"asserts and negates the same predicate: {negated}")
            )
    return errors


def _fingerprint(node: object) -> str | None:
    if isinstance(node, (TermNode, SeverityNode, TemplateIdNode, LocationKeyNode)):
        return f"{node.op}={node.value}"
    return None


def _major(version: str) -> str | None:
    head = version.split(".", 1)[0].strip()
    return head if head.isdigit() else None


def _err(code: PlanErrorCode, path: str, message: str, value: object | None = None) -> PlanError:
    return PlanError(
        code=code,
        path=path,
        message=message,
        value=None if value is None else str(value),
    )
