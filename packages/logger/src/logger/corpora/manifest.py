"""Corpus manifest: what a rerun must reproduce, and what licence governs it."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from logger.corpora.base import DatasetLicense, DerivedDataPolicy

MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CorpusManifest:
    """Everything needed to re-run a corpus build and check you got it back.

    Split into two halves on purpose:

    - the **reproducibility inputs** (``dataset``, ``version``, ``sample_size``,
      ``seed``, ``adapter``) -- fix these and the build is determined;
    - the **observed outputs** (``row_count``, ``template_count``,
      ``content_digest``) -- what the build produced, so a rerun can be
      verified instead of trusted.

    ``ingested_at`` is metadata, not content: it is deliberately excluded from
    ``content_digest`` so two runs of the same command still compare equal.
    """

    dataset: str
    source_url: str
    version: str
    sample_size: int | None
    seed: int
    row_count: int
    template_count: int
    license: DatasetLicense
    ingested_at: str
    content_digest: str = ""
    skipped_lines: int = 0
    source_files: list[str] = field(default_factory=list)
    schema_version: int = MANIFEST_SCHEMA_VERSION
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["license"]["derived_data"] = self.license.derived_data.value
        return data

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CorpusManifest:
        payload = dict(data)
        lic = dict(payload.pop("license"))
        lic["derived_data"] = DerivedDataPolicy(lic["derived_data"])
        payload.pop("schema_version", None)
        return cls(license=DatasetLicense(**lic), **payload)

    @classmethod
    def from_json(cls, text: str) -> CorpusManifest:
        return cls.from_dict(json.loads(text))

    def write(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json() + "\n", encoding="utf-8")
        return target

    @classmethod
    def read(cls, path: str | Path) -> CorpusManifest:
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    def reproduces(self, other: CorpusManifest) -> bool:
        """True when two builds agree on everything except wall-clock time."""
        return (
            self.dataset == other.dataset
            and self.version == other.version
            and self.sample_size == other.sample_size
            and self.seed == other.seed
            and self.row_count == other.row_count
            and self.template_count == other.template_count
            and self.content_digest == other.content_digest
        )

    def publishable(self) -> bool:
        return self.license.publishable()


def manifest_path_for(db_path: str | Path) -> Path:
    """Sidecar manifest path for a corpus database (``x.db`` -> ``x.manifest.json``)."""
    db = Path(db_path)
    return db.with_suffix(".manifest.json")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
