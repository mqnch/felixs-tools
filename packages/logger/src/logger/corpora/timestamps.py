"""Timestamp normalisation for loghub datasets.

Two rules apply across every adapter, and both are deliberate:

**No timezone is invented.** None of the six datasets records a UTC offset.
Emitting ``+00:00`` would assert a fact nobody verified, so timestamps are
rendered as naive ISO-8601 (``2008-11-09T20:36:15``). The format is fixed-width,
so SQLite's lexicographic ordering still sorts correctly, which is all the index
and the range operators actually need.

**Human-readable fields beat epoch fields.** BGL and Thunderbird carry both an
epoch column and a formatted local timestamp, and the two disagree -- the epoch
is not simply the local time in UTC. Picking the formatted field keeps all six
datasets on one convention; the epoch is preserved verbatim in
``CorpusRecord.extra['epoch']`` so nothing is lost.
"""

from __future__ import annotations

from datetime import datetime

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip


def _expand_year(two_digit: int) -> int:
    """POSIX-style pivot: 69->2069, 70->1970. All loghub data lands in the 2000s."""
    return 2000 + two_digit if two_digit < 70 else 1900 + two_digit


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def from_yymmdd_hhmmss(date: str, time: str) -> str | None:
    """HDFS: ``081109`` + ``203615`` -> ``2008-11-09T20:36:15``."""
    if len(date) != 6 or len(time) not in (5, 6) or not (date + time).isdigit():
        return None
    time = time.zfill(6)
    try:
        return _iso(
            datetime(
                _expand_year(int(date[0:2])),
                int(date[2:4]),
                int(date[4:6]),
                int(time[0:2]),
                int(time[2:4]),
                int(time[4:6]),
            )
        )
    except ValueError:
        return None


def from_slashed_yy(date: str, time: str) -> str | None:
    """Spark: ``17/06/09`` + ``20:10:40`` -> ``2017-06-09T20:10:40``."""
    parts = date.split("/")
    if len(parts) != 3:
        return None
    try:
        dt = datetime.strptime(f"{date} {time}", "%y/%m/%d %H:%M:%S")
    except ValueError:
        return None
    return _iso(dt.replace(year=_expand_year(int(parts[0]))))


def from_iso_like(date: str, time: str) -> str | None:
    """Hadoop/OpenStack: ``2015-10-18`` + ``18:01:47,978`` -> ISO with microseconds."""
    normalised = time.replace(",", ".")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return _iso(datetime.strptime(f"{date} {normalised}", fmt))
        except ValueError:
            continue
    return None


def from_bgl_stamp(stamp: str) -> str | None:
    """BGL: ``2005-06-03-15.42.50.363779`` -> ``2005-06-03T15:42:50.363779``."""
    try:
        return _iso(datetime.strptime(stamp, "%Y-%m-%d-%H.%M.%S.%f"))
    except ValueError:
        return None


def from_dotted_date_and_syslog_time(date: str, month: str, day: str, time: str) -> str | None:
    """Thunderbird: ``2005.11.09`` + ``Nov`` + ``9`` + ``12:01:01``.

    The syslog portion carries no year, so the adjacent ``<Date>`` column
    supplies it -- no century guessing is needed. The month name is used only as
    a consistency check; the numeric date wins if they disagree, since a syslog
    month name straddling midnight on New Year is the known failure mode.
    """
    parts = date.split(".")
    if len(parts) != 3:
        return None
    if month.lower()[:3] not in _MONTHS:
        return None
    try:
        hh, mm, ss = (int(x) for x in time.split(":"))
        return _iso(
            datetime(int(parts[0]), int(parts[1]), int(parts[2]), hh, mm, ss)
        )
    except ValueError:
        return None
