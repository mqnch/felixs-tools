"""Read-only views over an indexed corpus, and time-window split databases.

Contamination control (decision 0004) is done here, before any plan is sampled:
the corpus is cut into contiguous time windows and each split gets **its own
database** holding only that window's rows. Gold is then defined by executing
against the split database, so a test question's gold rows cannot come from the
training window, and relative bounds (`-6h`) resolve against that split's own
newest timestamp rather than the whole corpus's.

Only the `log_entries` table is read. That table's columns are the contract
`logger.index` publishes; nothing here touches the index's connection.
"""

from __future__ import annotations

import random
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from logger.index import LogIndex

SPLITS = ("train", "val", "test")
DEFAULT_FRACTIONS = (0.8, 0.1, 0.1)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.$-]{3,}")


@dataclass(frozen=True)
class SplitWindow:
    split: str
    first_id: int
    last_id: int
    since: str | None
    until: str | None
    rows: int


@dataclass(frozen=True)
class AnchorRow:
    """One real row a sampled plan is grounded in, so its leaves are satisfiable."""

    id: int
    raw: str
    template: str
    template_id: int
    severity: str | None
    timestamp: str | None
    location_key: str | None


def build_splits(
    corpus_db: str | Path,
    out_dir: str | Path,
    *,
    fractions: tuple[float, float, float] = DEFAULT_FRACTIONS,
) -> list[SplitWindow]:
    """Write `<out_dir>/<split>.db` for each split; return the windows used.

    Rows are ordered by timestamp (NULL timestamps sort first and land in
    train, where an un-placeable row can do the least damage), then cut by row
    count. Row IDs are preserved, so a gold row ID means the same line in the
    split database and the source corpus.
    """
    if abs(sum(fractions) - 1.0) > 1e-9:
        raise ValueError(f"split fractions must sum to 1, got {fractions}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    src = sqlite3.connect(corpus_db)
    ordered = [
        (int(r[0]), r[1])
        for r in src.execute(
            "SELECT id, timestamp FROM log_entries "
            "ORDER BY timestamp IS NOT NULL, timestamp, id"
        )
    ]
    src.close()
    if len(ordered) < len(SPLITS):
        raise ValueError(f"corpus has {len(ordered)} rows; too few to split")

    bounds: list[int] = []
    acc = 0.0
    for frac in fractions[:-1]:
        acc += frac
        bounds.append(round(acc * len(ordered)))
    cuts = [0, *bounds, len(ordered)]

    windows: list[SplitWindow] = []
    for split, lo, hi in zip(SPLITS, cuts, cuts[1:], strict=False):
        chunk = ordered[lo:hi]
        if not chunk:
            raise ValueError(f"split {split!r} would be empty; corpus too small")
        ids = [i for i, _ in chunk]
        stamps = [t for _, t in chunk if t is not None]
        _write_split_db(corpus_db, out / f"{split}.db", ids)
        windows.append(
            SplitWindow(
                split=split,
                first_id=min(ids),
                last_id=max(ids),
                since=min(stamps) if stamps else None,
                until=max(stamps) if stamps else None,
                rows=len(ids),
            )
        )
    return windows


def _write_split_db(corpus_db: str | Path, dest: Path, ids: list[int]) -> None:
    if dest.exists():
        dest.unlink()
    # LogIndex owns the schema (including the FTS trigger); create it through
    # the index, then bulk-copy rows so the trigger repopulates FTS.
    LogIndex(dest).close()
    conn = sqlite3.connect(dest)
    conn.execute("ATTACH DATABASE ? AS src", (str(corpus_db),))
    conn.execute("CREATE TEMP TABLE keep(id INTEGER PRIMARY KEY)")
    conn.executemany("INSERT INTO temp.keep(id) VALUES (?)", ((i,) for i in ids))
    conn.execute(
        "INSERT INTO log_entries "
        "SELECT e.* FROM src.log_entries e JOIN temp.keep k ON k.id = e.id ORDER BY e.id"
    )
    conn.commit()
    conn.execute("DETACH DATABASE src")
    conn.close()


class CorpusView:
    """Value pools a plan sampler draws from. Read-only."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        self._conn.row_factory = sqlite3.Row
        self.row_count = int(self._conn.execute("SELECT COUNT(*) FROM log_entries").fetchone()[0])
        self._ids = [int(r[0]) for r in self._conn.execute("SELECT id FROM log_entries ORDER BY id")]
        self.severities = self._distinct("severity")
        self.location_keys = self._distinct("location_key")
        self.template_ids = [int(v) for v in self._distinct("template_id")]
        # Each row stores its template as Drain had it at ingest time, and Drain
        # only ever generalizes a cluster. So the last-ingested row carries the
        # most general text ("<*> double-hummer ..."), while MIN(template) picked
        # the earliest, fully literal one ("1534 double-hummer ...") and made the
        # author write over-specific questions.
        self._templates = {
            int(r["template_id"]): r["template"]
            for r in self._conn.execute(
                "SELECT e.template_id, e.template FROM log_entries e "
                "JOIN (SELECT template_id, MAX(id) AS id FROM log_entries GROUP BY template_id) last "
                "ON e.id = last.id"
            )
        }

    def close(self) -> None:
        self._conn.close()

    def _distinct(self, column: str) -> list:
        return [
            r[0]
            for r in self._conn.execute(
                f"SELECT DISTINCT {column} FROM log_entries WHERE {column} IS NOT NULL ORDER BY 1"
            )
        ]

    def anchor(self, rng: random.Random) -> AnchorRow:
        row = self._conn.execute(
            "SELECT id, raw, template, template_id, severity, timestamp, location_key "
            "FROM log_entries WHERE id = ?",
            (rng.choice(self._ids),),
        ).fetchone()
        return AnchorRow(**dict(row))

    def template_text(self, template_id: int) -> str:
        return self._templates.get(template_id, "")

    def rows(self, ids: list[int]) -> list[AnchorRow]:
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        found = self._conn.execute(
            "SELECT id, raw, template, template_id, severity, timestamp, location_key "
            f"FROM log_entries WHERE id IN ({marks}) ORDER BY id",
            ids,
        ).fetchall()
        return [AnchorRow(**dict(r)) for r in found]

    def timestamp_bounds(self) -> tuple[str | None, str | None]:
        row = self._conn.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM log_entries WHERE timestamp IS NOT NULL"
        ).fetchone()
        return row[0], row[1]


def literal_words(template: str) -> list[str]:
    """Words of a mined template that are literal text, not `<*>` parameters."""
    words = []
    for token in template.split():
        if "<*>" in token:
            continue
        for word in _WORD_RE.findall(token):
            if word not in words:
                words.append(word)
    return words
