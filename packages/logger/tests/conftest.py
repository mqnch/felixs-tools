from __future__ import annotations

from pathlib import Path

import pytest
from common import LocationId
from logger import Logger

API = LocationId(path="svc/api.log", service="api")
WORKER = LocationId(path="svc/worker.log", service="worker")

# (line, location, timestamp). Severity is inferred by Logger, so line 7 lands NULL.
CORPUS = [
    ("ERROR payment failed order=42", API, "2026-07-23T10:00:00Z"),
    ("ERROR payment failed order=43", API, "2026-07-23T10:05:00Z"),
    ("INFO healthcheck ok", API, "2026-07-23T11:00:00Z"),
    ("ERROR timeout contacting db", WORKER, "2026-07-20T09:00:00Z"),
    ("WARN timeout contacting cache", API, "2026-07-23T09:00:00Z"),
    ("CRITICAL disk full", WORKER, "2026-07-22T08:00:00Z"),
    ("plain line with no level marker", API, None),
    ("INFO payment ok order=44", API, "2026-07-23T10:10:00Z"),
]

CORPUS_SIZE = len(CORPUS)
CORPUS_NOW = "2026-07-23T11:00:00Z"  # newest timestamp; the executor's reference instant


@pytest.fixture()
def log(tmp_path: Path) -> Logger:
    instance = Logger(tmp_path / "logger.db")
    for line, location, timestamp in CORPUS:
        instance.ingest_line(line, location=location, timestamp=timestamp)
    try:
        yield instance
    finally:
        instance.close()
