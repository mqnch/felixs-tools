"""Structured SQLite + FTS5 index for parsed log templates, and the plan executor.

`LogIndex.execute()` is on the correctness path for every RL reward computation
(decision 0002): a bug here silently corrupts training, so the SQL generation is
deliberately boring and the semantics are pinned by tests.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from common import (
    MAX_LIMIT,
    AndNode,
    GroupByField,
    LocationId,
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

from logger import timeutil
from logger.parser import ParsedLine

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

_GROUP_COLUMNS = {
    GroupByField.TEMPLATE_ID: "e.template_id",
    GroupByField.SEVERITY: "e.severity",
    GroupByField.LOCATION_KEY: "e.location_key",
}

# SQL fragment plus its bound parameters. Kept as a pair so a fragment can be
# discarded (see `_scan_sql`) without leaking its parameters into the query.
_Frag = tuple[str, list[object]]


@dataclass(frozen=True)
class IndexedEntry:
    id: int
    raw: str
    template: str
    template_id: int
    severity: str | None
    timestamp: str | None
    location_key: str | None
    path: str | None
    service: str | None


@dataclass(frozen=True)
class AggregateGroup:
    """One row of a `count` aggregate. `key` is empty for an ungrouped count."""

    key: dict[str, object]
    count: int


@dataclass(frozen=True)
class QueryResult:
    label: str | None = None
    rows: list[IndexedEntry] = field(default_factory=list)
    groups: list[AggregateGroup] = field(default_factory=list)
    rows_scanned: int = 0

    @property
    def row_ids(self) -> list[int]:
        return [r.id for r in self.rows]


@dataclass(frozen=True)
class PlanResult:
    """Union of a plan's query results, plus the efficiency counters."""

    results: list[QueryResult] = field(default_factory=list)
    rows: list[IndexedEntry] = field(default_factory=list)
    groups: list[AggregateGroup] = field(default_factory=list)
    rows_scanned: int = 0

    @property
    def row_ids(self) -> list[int]:
        return [r.id for r in self.rows]

    @property
    def query_count(self) -> int:
        return len(self.results)


class LogIndex:
    """Stores parsed lines with structured fields and FTS over raw/template text."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS log_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw TEXT NOT NULL,
                template TEXT NOT NULL,
                template_id INTEGER NOT NULL,
                severity TEXT,
                timestamp TEXT,
                path TEXT,
                service TEXT,
                location_key TEXT,
                parameters TEXT,
                ingested_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_log_template_id ON log_entries(template_id);
            CREATE INDEX IF NOT EXISTS idx_log_severity ON log_entries(severity);
            CREATE INDEX IF NOT EXISTS idx_log_location ON log_entries(location_key);
            CREATE INDEX IF NOT EXISTS idx_log_timestamp ON log_entries(timestamp);

            CREATE VIRTUAL TABLE IF NOT EXISTS log_entries_fts USING fts5(
                raw,
                template,
                content='log_entries',
                content_rowid='id'
            );

            CREATE TRIGGER IF NOT EXISTS log_entries_ai AFTER INSERT ON log_entries BEGIN
              INSERT INTO log_entries_fts(rowid, raw, template)
              VALUES (new.id, new.raw, new.template);
            END;
            """
        )
        self._conn.commit()

    def ingest(
        self,
        parsed: ParsedLine,
        *,
        location: LocationId | None = None,
        severity: str | None = None,
        timestamp: str | None = None,
    ) -> int:
        ingested_at = timeutil.canonical(timeutil.utcnow())
        location_key = location.key() if location else None
        cur = self._conn.execute(
            """
            INSERT INTO log_entries (
                raw, template, template_id, severity, timestamp,
                path, service, location_key, parameters, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parsed.raw,
                parsed.template,
                parsed.template_id,
                severity,
                timeutil.normalize_timestamp(timestamp),
                location.path if location else None,
                location.service if location else None,
                location_key,
                "|".join(parsed.parameters),
                ingested_at,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    # --- execution -----------------------------------------------------------

    def row_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM log_entries").fetchone()
        return int(row["n"])

    def reference_now(self) -> datetime:
        """Reference instant for relative bounds: the corpus's newest timestamp.

        Wall-clock would make rewards unreplayable and would return nothing on
        archival corpora (decision 0010).
        """
        row = self._conn.execute(
            "SELECT MAX(timestamp) AS t FROM log_entries WHERE timestamp IS NOT NULL"
        ).fetchone()
        latest = timeutil.parse_instant(row["t"]) if row and row["t"] else None
        return latest or timeutil.utcnow()

    def execute(self, plan: QueryPlan, *, now: datetime | None = None) -> PlanResult:
        """Run every query in the plan; union rows, concatenate groups, sum counters."""
        reference = now or self.reference_now()
        results = [self.query(q, now=reference) for q in plan.queries]

        seen: set[int] = set()
        rows: list[IndexedEntry] = []
        groups: list[AggregateGroup] = []
        for result in results:
            for entry in result.rows:
                if entry.id in seen:
                    continue
                seen.add(entry.id)
                rows.append(entry)
            groups.extend(result.groups)
        return PlanResult(
            results=results,
            rows=rows,
            groups=groups,
            rows_scanned=sum(r.rows_scanned for r in results),
        )

    def query(self, query: Query, *, now: datetime | None = None) -> QueryResult:
        """Execute a single DSL query. Plans run as written — there is no optimizer."""
        reference = now or self.reference_now()
        where_sql, where_params = _node_sql(query.where, reference) if query.where else ("1", [])
        limit = max(1, min(int(query.limit), MAX_LIMIT))
        scanned = self._rows_scanned(query, reference)

        if query.aggregate is not None:
            groups = self._run_aggregate(query, where_sql, where_params, limit)
            return QueryResult(label=query.label, groups=groups, rows_scanned=scanned)

        direction = "ASC" if query.order == "oldest" else "DESC"
        sql = (
            "SELECT e.id, e.raw, e.template, e.template_id, e.severity, "
            "e.timestamp, e.location_key, e.path, e.service "
            f"FROM log_entries e WHERE {where_sql} ORDER BY e.id {direction} LIMIT ?"
        )
        rows = self._conn.execute(sql, [*where_params, limit]).fetchall()
        return QueryResult(
            label=query.label,
            rows=[_entry(row) for row in rows],
            rows_scanned=scanned,
        )

    def _run_aggregate(
        self,
        query: Query,
        where_sql: str,
        where_params: list[object],
        limit: int,
    ) -> list[AggregateGroup]:
        aggregate = query.aggregate
        assert aggregate is not None
        fields = list(dict.fromkeys(aggregate.group_by))
        columns = [_GROUP_COLUMNS[f] for f in fields]

        selected = ", ".join(f"{col} AS g{i}" for i, col in enumerate(columns))
        select = f"{selected}, COUNT(*) AS n" if columns else "COUNT(*) AS n"
        group_by = f" GROUP BY {', '.join(columns)}" if columns else ""

        params: list[object] = list(where_params)
        having_parts: list[str] = []
        if aggregate.having is not None:
            if aggregate.having.min_count is not None:
                having_parts.append("COUNT(*) >= ?")
                params.append(int(aggregate.having.min_count))
            if aggregate.having.max_count is not None:
                having_parts.append("COUNT(*) <= ?")
                params.append(int(aggregate.having.max_count))
        having = f" HAVING {' AND '.join(having_parts)}" if having_parts else ""

        order_keys = ", ".join(f"g{i} ASC" for i in range(len(columns)))
        order = f" ORDER BY n DESC{', ' + order_keys if order_keys else ''}"
        params.append(limit)

        sql = (
            f"SELECT {select} FROM log_entries e WHERE {where_sql}"
            f"{group_by}{having}{order} LIMIT ?"
        )
        rows = self._conn.execute(sql, params).fetchall()
        return [
            AggregateGroup(
                key={f.value: row[f"g{i}"] for i, f in enumerate(fields)},
                count=int(row["n"]),
            )
            for row in rows
        ]

    def _rows_scanned(self, query: Query, now: datetime) -> int:
        """Rows the filter had to be evaluated over.

        Measured, not estimated: the query's *positive skeleton* (the filter tree
        with every `not` replaced by TRUE) bounds the candidate set, because only
        index-backed positive predicates can narrow the driving scan. Negation and
        disjunction therefore never reduce it, which is the honest cost model.
        """
        skeleton = _scan_sql(query.where, now) if query.where else None
        if skeleton is None:
            return self.row_count()
        sql_text, params = skeleton
        row = self._conn.execute(
            f"SELECT COUNT(*) AS n FROM log_entries e WHERE {sql_text}", params
        ).fetchone()
        return int(row["n"])

    def template_counts(self) -> dict[int, int]:
        rows = self._conn.execute(
            "SELECT template_id, COUNT(*) AS n FROM log_entries GROUP BY template_id"
        ).fetchall()
        return {int(r["template_id"]): int(r["n"]) for r in rows}


def _entry(row: sqlite3.Row) -> IndexedEntry:
    return IndexedEntry(
        id=row["id"],
        raw=row["raw"],
        template=row["template"],
        template_id=row["template_id"],
        severity=row["severity"],
        timestamp=row["timestamp"],
        location_key=row["location_key"],
        path=row["path"],
        service=row["service"],
    )


def fts_phrase(term: str) -> str | None:
    """Quote a model-generated term as a single FTS5 phrase.

    Terms are untrusted. They are bound as SQL parameters (so no SQL injection is
    possible), but an unescaped `"` would still let a term inject FTS5 *query*
    syntax — `NEAR`, `OR`, column filters. Doubling the quote is FTS5's own
    escape, and control characters are stripped.
    """
    cleaned = _CONTROL_RE.sub(" ", term).strip()
    if not cleaned:
        return None
    return '"' + cleaned.replace('"', '""') + '"'


_FTS_SUBQUERY = "e.id IN (SELECT rowid FROM log_entries_fts WHERE log_entries_fts MATCH ?)"


def _leaf_sql(node: object, now: datetime) -> _Frag | None:
    """SQL for a leaf predicate, or None when it cannot constrain anything."""
    if isinstance(node, TermNode):
        phrase = fts_phrase(node.value)
        if phrase is None:
            return ("0", [])
        return (_FTS_SUBQUERY, [phrase])
    if isinstance(node, SeverityNode):
        return ("e.severity = ?", [node.value.value])
    if isinstance(node, TemplateIdNode):
        return ("e.template_id = ?", [int(node.value)])
    if isinstance(node, LocationKeyNode):
        return ("e.location_key = ?", [node.value])
    if isinstance(node, TimeRangeNode):
        parts: list[str] = []
        params: list[object] = []
        for value, op in ((node.since, ">="), (node.until, "<=")):
            if value is None:
                continue
            bound = timeutil.resolve_bound(value, now)
            if bound is None:
                # Unresolvable bound matches nothing; the validator rejects it first.
                return ("0", [])
            parts.append(f"e.timestamp {op} ?")
            params.append(bound)
        if not parts:
            return None
        return ("(e.timestamp IS NOT NULL AND " + " AND ".join(parts) + ")", params)
    return None


def _node_sql(node: object, now: datetime) -> _Frag:
    """Full SQL for a filter tree. Always returns a usable boolean expression."""
    if isinstance(node, AndNode):
        if not node.of:
            return ("1", [])
        return _join(" AND ", [_node_sql(child, now) for child in node.of])
    if isinstance(node, OrNode):
        if not node.of:
            return ("0", [])
        return _join(" OR ", [_node_sql(child, now) for child in node.of])
    if isinstance(node, NotNode):
        if not node.of:
            return ("1", [])
        inner = (
            _node_sql(node.of[0], now)
            if len(node.of) == 1
            else _join(" AND ", [_node_sql(child, now) for child in node.of])
        )
        # COALESCE collapses SQL three-valued logic: a NULL column does not match
        # the inner predicate, so its negation must be true, not unknown.
        return (f"(NOT COALESCE({inner[0]}, 0))", inner[1])
    leaf = _leaf_sql(node, now)
    return leaf if leaf is not None else ("1", [])


def _scan_sql(node: object, now: datetime) -> _Frag | None:
    """The positive skeleton of a filter tree. None means "cannot bound the scan"."""
    if isinstance(node, AndNode):
        parts = [p for p in (_scan_sql(child, now) for child in node.of) if p is not None]
        return _join(" AND ", parts) if parts else None
    if isinstance(node, OrNode):
        if not node.of:
            return ("0", [])
        parts = [_scan_sql(child, now) for child in node.of]
        if any(p is None for p in parts):
            return None
        return _join(" OR ", [p for p in parts if p is not None])
    if isinstance(node, NotNode):
        return None
    return _leaf_sql(node, now)


def _join(operator: str, frags: list[_Frag]) -> _Frag:
    params: list[object] = []
    for _, frag_params in frags:
        params.extend(frag_params)
    return ("(" + operator.join(sql for sql, _ in frags) + ")", params)
