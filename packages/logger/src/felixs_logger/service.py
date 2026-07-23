"""High-level Logger API: parse, index, plan, score."""

from __future__ import annotations

import re
from pathlib import Path

from felixs_common import LocationId

from felixs_logger.index import IndexedEntry, LogIndex
from felixs_logger.parser import LogParser, ParsedLine
from felixs_logger.planner import QueryPlanner
from felixs_logger.scorer import AnomalyScore, AnomalyScorer

_SEVERITY_RE = re.compile(
    r"\b(DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL)\b",
    re.IGNORECASE,
)


class Logger:
    def __init__(self, db_path: str | Path) -> None:
        self.parser = LogParser()
        self.index = LogIndex(db_path)
        self.planner = QueryPlanner(self.index)
        self.scorer = AnomalyScorer(self.index)

    def close(self) -> None:
        self.index.close()

    def ingest_line(
        self,
        line: str,
        *,
        location: LocationId | None = None,
        severity: str | None = None,
        timestamp: str | None = None,
        score: bool = False,
    ) -> tuple[int, ParsedLine, AnomalyScore | None]:
        parsed = self.parser.parse(line)
        sev = severity or _guess_severity(line)
        entry_id = self.index.ingest(
            parsed,
            location=location,
            severity=sev,
            timestamp=timestamp,
        )
        anomaly = self.scorer.score(parsed) if score else None
        return entry_id, parsed, anomaly

    def ingest_file(
        self,
        path: str | Path,
        *,
        location: LocationId | None = None,
        score: bool = False,
    ) -> int:
        count = 0
        file_location = location or LocationId(path=str(path))
        with Path(path).open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.strip():
                    continue
                self.ingest_line(line, location=file_location, score=score)
                count += 1
        return count

    def search(self, question: str) -> list[IndexedEntry]:
        return self.planner.search(question)


def _guess_severity(line: str) -> str | None:
    match = _SEVERITY_RE.search(line)
    if not match:
        return None
    value = match.group(1).upper()
    if value == "WARNING":
        return "WARN"
    return value
