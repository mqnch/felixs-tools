"""Structured SQLite + FTS5 index for parsed log templates."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from felixs_common import LocationId

from felixs_logger.parser import ParsedLine


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
        ingested_at = datetime.now(timezone.utc).isoformat()
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
                timestamp,
                location.path if location else None,
                location.service if location else None,
                location_key,
                "|".join(parsed.parameters),
                ingested_at,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def query(
        self,
        *,
        terms: list[str] | None = None,
        severity: str | None = None,
        location_key: str | None = None,
        template_id: int | None = None,
        limit: int = 50,
    ) -> list[IndexedEntry]:
        clauses: list[str] = []
        params: list[object] = []

        if severity:
            clauses.append("e.severity = ?")
            params.append(severity.upper())
        if location_key:
            clauses.append("e.location_key = ?")
            params.append(location_key)
        if template_id is not None:
            clauses.append("e.template_id = ?")
            params.append(template_id)
        if terms:
            fts = " ".join(f'"{t}"' for t in terms if t.strip())
            if fts:
                clauses.append(
                    "e.id IN (SELECT rowid FROM log_entries_fts WHERE log_entries_fts MATCH ?)"
                )
                params.append(fts)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT e.id, e.raw, e.template, e.template_id, e.severity,
                   e.timestamp, e.location_key, e.path, e.service
            FROM log_entries e
            {where}
            ORDER BY e.id DESC
            LIMIT ?
        """
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [
            IndexedEntry(
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
            for row in rows
        ]

    def template_counts(self) -> dict[int, int]:
        rows = self._conn.execute(
            "SELECT template_id, COUNT(*) AS n FROM log_entries GROUP BY template_id"
        ).fetchall()
        return {int(r["template_id"]): int(r["n"]) for r in rows}
