"""Corpus build entrypoint: raw dataset files in, indexed corpus + manifest out.

Intended CLI surface (not wired in slice 003 -- see the slice writeup):

    felix logger ingest-corpus loghub --dataset hdfs --sample 200000 \\
        --out corpora/hdfs.db

:func:`ingest_loghub` is that command's body; wiring it should be a Typer
signature and nothing else.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Protocol

from logger.corpora.base import CorpusRecord, DatasetAdapter
from logger.corpora.manifest import CorpusManifest, manifest_path_for, utc_now_iso
from logger.corpora.registry import get_adapter
from logger.corpora.sampling import ContentDigest, deterministic_sample
from logger.parser import LogParser, ParsedLine

DEFAULT_SEED = 20260815
"""Fixed default so an omitted ``--seed`` is still reproducible."""

_FLUSH_EVERY = 5_000


class SupportsCorpusIngest(Protocol):
    """The slice of ``LogIndex`` a corpus build needs.

    Narrowed to a protocol so this module keeps working if the index grows new
    methods or changes internals; it never touches the index's connection.
    """

    def ingest(
        self,
        parsed: ParsedLine,
        *,
        location: object | None = ...,
        severity: str | None = ...,
        timestamp: str | None = ...,
    ) -> int: ...

    def template_counts(self) -> dict[int, int]: ...


_SIDECAR_SCHEMA = """
CREATE TABLE IF NOT EXISTS corpus_records (
    entry_id INTEGER PRIMARY KEY,
    dataset TEXT NOT NULL,
    source_index INTEGER NOT NULL,
    label TEXT,
    extra TEXT
);
CREATE INDEX IF NOT EXISTS idx_corpus_dataset ON corpus_records(dataset);
CREATE INDEX IF NOT EXISTS idx_corpus_label ON corpus_records(label);

CREATE TABLE IF NOT EXISTS corpus_manifest (
    dataset TEXT PRIMARY KEY,
    manifest_json TEXT NOT NULL
);
"""


def ingest_records(
    adapter: DatasetAdapter,
    records: Iterable[CorpusRecord],
    *,
    db_path: str | Path,
    sample_size: int | None = None,
    seed: int = DEFAULT_SEED,
    index: SupportsCorpusIngest | None = None,
    source_files: list[str] | None = None,
    skipped_lines: int | Callable[[], int] = 0,
    notes: str | None = None,
) -> CorpusManifest:
    """Index a stream of already-parsed records and write the manifest.

    Sampling happens on records (post-parse) rather than on raw lines so that
    ``--sample N`` means N usable rows, not N lines of which some fraction was
    an unparseable continuation line.

    ``skipped_lines`` may be a callable. ``records`` is typically a generator
    that has not run yet, so any counter it feeds is still zero at call time and
    must be read after the stream is exhausted.
    """
    db = Path(db_path)
    owns_index = index is None
    if index is None:
        from logger.index import LogIndex

        index = LogIndex(db)

    parser = LogParser()
    digest = ContentDigest()
    sidecar_rows: list[tuple[int, str, int, str | None, str | None]] = []
    conn = sqlite3.connect(db)
    conn.executescript(_SIDECAR_SCHEMA)
    conn.commit()

    try:
        for source_index, record in deterministic_sample(
            records, sample_size=sample_size, seed=seed
        ):
            parsed = parser.parse(record.raw)
            entry_id = index.ingest(
                parsed,
                location=record.location,
                severity=record.severity,
                timestamp=record.timestamp,
            )
            digest.update(
                record.raw,
                record.timestamp,
                record.severity,
                record.location.key(),
                record.label,
            )
            sidecar_rows.append(
                (
                    entry_id,
                    adapter.name,
                    source_index,
                    record.label,
                    json.dumps(record.extra, sort_keys=True) if record.extra else None,
                )
            )
            if len(sidecar_rows) >= _FLUSH_EVERY:
                _flush(conn, sidecar_rows)

        _flush(conn, sidecar_rows)

        manifest = CorpusManifest(
            dataset=adapter.name,
            source_url=adapter.source_url,
            version=adapter.version,
            sample_size=sample_size,
            seed=seed,
            row_count=digest.count,
            template_count=len(index.template_counts()),
            license=adapter.license,
            ingested_at=utc_now_iso(),
            content_digest=digest.hexdigest(),
            skipped_lines=skipped_lines() if callable(skipped_lines) else skipped_lines,
            source_files=source_files or [],
            notes=notes,
        )
        conn.execute(
            "INSERT OR REPLACE INTO corpus_manifest (dataset, manifest_json) VALUES (?, ?)",
            (adapter.name, manifest.to_json()),
        )
        conn.commit()
        manifest.write(manifest_path_for(db))
        return manifest
    finally:
        conn.close()
        if owns_index:
            closer = getattr(index, "close", None)
            if callable(closer):
                closer()


def ingest_loghub(
    dataset: str,
    *,
    source: str | Path | Iterable[str | Path],
    out: str | Path,
    sample_size: int | None = None,
    seed: int = DEFAULT_SEED,
    index: SupportsCorpusIngest | None = None,
    require_publishable: bool = False,
) -> CorpusManifest:
    """Build a corpus database from staged loghub files.

    ``require_publishable=True`` refuses datasets whose licence does not clearly
    permit redistributing derived data -- the gate decision 0004 asks for. It is
    off by default because building a corpus locally is not publishing it.
    """
    adapter = get_adapter(dataset)
    if require_publishable and not adapter.license.publishable():
        raise PermissionError(
            f"{adapter.name}: licence is '{adapter.license.name}' "
            f"({adapter.license.derived_data.value}); derived data may not be published"
        )

    paths = _as_paths(source)
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"{adapter.name}: staged files not found: {', '.join(missing)}. "
            "Stage them first (see logger.corpora.staging)."
        )

    counter = _SkipCounter()
    records = _records_from_files(adapter, paths, counter)
    return ingest_records(
        adapter,
        records,
        db_path=out,
        sample_size=sample_size,
        seed=seed,
        index=index,
        source_files=[str(p) for p in paths],
        skipped_lines=counter,
    )


class _SkipCounter:
    """Mutable line-skip tally shared with a generator that runs later."""

    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> int:
        return self.value


def _records_from_files(
    adapter: DatasetAdapter, paths: list[Path], counter: _SkipCounter
) -> Iterator[CorpusRecord]:
    """Parse each file with an adapter bound to that file's name.

    Files are visited in the sorted order fixed by ``_as_paths``; the sampler
    then depends only on position in that concatenated stream, so a multi-file
    dataset is as reproducible as a single-file one.
    """
    for path in paths:
        bound = adapter.for_file(path.name)
        # Decoding errors are replaced, not raised: BGL and Thunderbird carry
        # occasional non-UTF-8 bytes from kernel messages, and a multi-hour
        # corpus build must not abort over one bad byte.
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.rstrip("\n")
                if not stripped.strip():
                    continue
                record = bound.parse_line(stripped)
                if record is None:
                    counter.value += 1
                    continue
                yield record


def _as_paths(source: str | Path | Iterable[str | Path]) -> list[Path]:
    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.is_dir():
            # Recursive: Hadoop stages as application_*/container_*/ trees.
            # Sorted so the concatenation order -- and therefore the sample -- is
            # fixed rather than filesystem-dependent.
            return sorted(p for p in path.rglob("*") if p.is_file())
        return [path]
    return [Path(p) for p in source]


def _flush(
    conn: sqlite3.Connection,
    rows: list[tuple[int, str, int, str | None, str | None]],
) -> None:
    if not rows:
        return
    conn.executemany(
        "INSERT OR REPLACE INTO corpus_records "
        "(entry_id, dataset, source_index, label, extra) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    rows.clear()


def read_stored_manifest(db_path: str | Path, dataset: str) -> CorpusManifest | None:
    """Read the manifest embedded in a corpus database."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT manifest_json FROM corpus_manifest WHERE dataset = ?", (dataset,)
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    return CorpusManifest.from_json(row[0]) if row else None
