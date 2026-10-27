"""Timestamp normalization and relative-offset resolution for the query DSL.

Timestamps are stored as fixed-width canonical UTC ISO-8601 strings so that
lexicographic comparison in SQLite is chronological comparison. Anything the
index cannot parse is stored verbatim and simply never matches a time range.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_RELATIVE_RE = re.compile(r"^-(\d{1,6})([smhdw])$")
_UNITS = {
    "s": "seconds",
    "m": "minutes",
    "h": "hours",
    "d": "days",
    "w": "weeks",
}


def parse_instant(value: str) -> datetime | None:
    """Parse an ISO-8601 instant. Naive values are assumed UTC."""
    text = value.strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def parse_relative(value: str) -> timedelta | None:
    """Parse a `-<n><unit>` offset, e.g. `-24h`. Returns a negative timedelta."""
    match = _RELATIVE_RE.match(value.strip())
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2)
    return -timedelta(**{_UNITS[unit]: amount})


def is_relative(value: str) -> bool:
    return _RELATIVE_RE.match(value.strip()) is not None


def canonical(dt: datetime) -> str:
    """Fixed-width UTC form; lexicographic order == chronological order."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "+00:00"


def normalize_timestamp(value: str | None) -> str | None:
    """Canonicalize an ingested timestamp, or return it unchanged if unparseable."""
    if value is None:
        return None
    dt = parse_instant(value)
    return canonical(dt) if dt else value


def resolve_bound(value: str, now: datetime) -> str | None:
    """Resolve a DSL time bound to a canonical string, or None if malformed."""
    offset = parse_relative(value)
    if offset is not None:
        return canonical(now + offset)
    dt = parse_instant(value)
    return canonical(dt) if dt else None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
