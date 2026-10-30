"""Adapter interface shared by every corpus dataset."""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum

from common import LocationId


class DerivedDataPolicy(str, Enum):
    """Whether a corpus derived from this dataset may be published.

    ``UNVERIFIED`` is a first-class value on purpose: decision 0004 requires
    licensing to be *verified* before publication, and an honest "we do not
    know" must be representable so it can block a release instead of being
    rounded down to "probably fine".
    """

    PUBLISHABLE = "publishable"
    PUBLISHABLE_WITH_ATTRIBUTION = "publishable_with_attribution"
    RESTRICTED = "restricted"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class DatasetLicense:
    """Licensing facts for one dataset, recorded in every corpus manifest."""

    name: str
    url: str | None
    derived_data: DerivedDataPolicy
    attribution: str | None = None
    notes: str | None = None

    def publishable(self) -> bool:
        return self.derived_data in (
            DerivedDataPolicy.PUBLISHABLE,
            DerivedDataPolicy.PUBLISHABLE_WITH_ATTRIBUTION,
        )


@dataclass(frozen=True)
class CorpusRecord:
    """One raw log line, normalised to what the index and a future scorer need."""

    raw: str
    """The **message body** (loghub's ``Content`` field), not the whole line.

    Everything stripped off the front -- timestamp, level, component -- is
    already captured as a structured field, so this is not data loss; it is the
    same split every log-parsing benchmark uses. Templating the full line would
    make drain3 cluster on timestamps and pids, and FTS terms would match
    against pid digits.
    """
    timestamp: str | None
    severity: str | None
    location: LocationId
    label: str | None = None
    """Anomaly label carried through from the source, never interpreted here.

    Slice 003 does not build a scorer (decision 0002). Dropping the column would
    force a re-ingest of every corpus when one is built, so it is preserved and
    unused.
    """
    extra: dict[str, str] = field(default_factory=dict)
    """Dataset-specific fields with no home in ``LocationId`` (node, pid, ...)."""


class DatasetAdapter(ABC):
    """Maps one dataset's raw lines onto :class:`CorpusRecord`.

    Adapters are pure and stateless: no I/O, no clock, no randomness. Everything
    order- or environment-dependent lives in ``ingest``/``sampling`` so that an
    adapter can be exercised with a handful of inline fixture lines.
    """

    name: str
    """Short dataset key, e.g. ``hdfs``. Matches the CLI ``--dataset`` value."""

    source_url: str
    """Where the raw dataset is fetched from."""

    version: str
    """Upstream dataset version/release, recorded in the manifest."""

    license: DatasetLicense

    log_format: str
    """Loghub-style field template, kept for documentation and cross-checking."""

    default_path: str
    """Source file, used as ``LocationId.path`` when the line carries no better."""

    severities: tuple[str, ...] = ()
    """Level vocabulary. Empty tuple means the dataset has no level field."""

    label_source: str | None = None
    """Where anomaly labels live, or ``None`` if the dataset has none.

    All four labelled datasets differ, and only two put the label on the line, so
    a bare boolean would be actively misleading to whoever builds the scorer.
    ``CorpusRecord.label`` is populated only for the inline cases; the others
    need a join whose key is preserved in ``extra``.
    """

    @property
    def has_inline_labels(self) -> bool:
        """True when the label is on the log line itself (BGL, Thunderbird)."""
        return bool(self.label_source and self.label_source.startswith("inline"))

    def for_file(self, path: str) -> DatasetAdapter:
        """Copy of this adapter whose ``default_path`` is ``path``.

        Hadoop ships as a tree of ``application_*/container_*`` files whose only
        record of origin is the filename, so a multi-file ingest needs to say
        which file a line came from. Datasets that name their own source file on
        every line (OpenStack) ignore this.
        """
        clone = copy.copy(self)
        clone.default_path = path
        return clone

    @abstractmethod
    def parse_line(self, line: str) -> CorpusRecord | None:
        """Parse one raw line, or return ``None`` if it does not match.

        Returning ``None`` rather than raising is deliberate: real loghub files
        contain continuation lines from multi-line stack traces, and a corpus
        build must not die on line 4.7 million.
        """

    def parse_lines(self, lines: Iterable[str]) -> Iterator[CorpusRecord]:
        """Parse a stream, silently skipping non-matching lines."""
        for line in lines:
            stripped = line.rstrip("\n")
            if not stripped.strip():
                continue
            record = self.parse_line(stripped)
            if record is not None:
                yield record


def normalise_severity(value: str | None) -> str | None:
    """Upper-case a level and fold ``WARNING`` onto ``WARN``.

    That single fold is a spelling difference and matches what
    ``service._guess_severity`` already does. Folds that change meaning, such as
    BGL's ``SEVERE`` and ``FAILURE``, belong in the adapter that owns that
    vocabulary, which keeps the raw level in ``extra`` (decision 0015).
    """
    if value is None:
        return None
    upper = value.strip().upper()
    if not upper:
        return None
    return "WARN" if upper == "WARNING" else upper
