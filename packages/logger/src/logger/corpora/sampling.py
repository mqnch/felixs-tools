"""Deterministic, streaming, order-preserving sampling.

Reproducibility rules that this module exists to enforce:

- Never use the builtin ``hash()``. It is salted per process (``PYTHONHASHSEED``),
  so a hash-based sampler would silently produce a different corpus per run.
- Never use the module-level ``random`` functions. A shared global generator is
  perturbed by any other caller; each sample owns a private ``random.Random``.
- The sample is returned in **original stream order**, not selection order, so
  that downstream time-window splits (decision 0004) still see a monotonically
  ordered log, and so drain3's order-dependent template ids are reproducible.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable, Iterator
from typing import TypeVar

T = TypeVar("T")


def deterministic_sample(
    stream: Iterable[T],
    *,
    sample_size: int | None,
    seed: int,
) -> Iterator[tuple[int, T]]:
    """Yield ``(source_index, item)`` for a reproducible subset of ``stream``.

    Uses reservoir sampling (Algorithm R) seeded by ``seed``: one pass, O(k)
    memory, and independent of how long the stream turns out to be -- which is
    what makes it usable on Thunderbird without knowing the line count up front.

    ``sample_size=None`` (or a size at least as large as the stream) keeps
    everything, still yielded in source order.
    """
    if sample_size is not None and sample_size < 0:
        raise ValueError("sample_size must be non-negative")

    if sample_size is None:
        yield from enumerate(stream)
        return

    if sample_size == 0:
        return

    rng = random.Random(seed)
    reservoir: list[tuple[int, T]] = []

    for index, item in enumerate(stream):
        if index < sample_size:
            reservoir.append((index, item))
            continue
        # Draw for every subsequent item so the decision sequence depends only
        # on (seed, position) -- not on which items happened to be kept.
        slot = rng.randrange(index + 1)
        if slot < sample_size:
            reservoir[slot] = (index, item)

    reservoir.sort(key=lambda pair: pair[0])
    yield from reservoir


class ContentDigest:
    """Running SHA-256 over corpus content, for reproducibility checks.

    A corpus database is not byte-identical across runs -- both the manifest and
    ``log_entries.ingested_at`` record wall-clock time. This digest covers the
    parts that *must* be stable, so "same command, same seed" is checkable
    rather than merely asserted.
    """

    def __init__(self) -> None:
        self._hasher = hashlib.sha256()
        self._count = 0

    def update(self, *fields: str | None) -> None:
        self._count += 1
        # "\x00" marks a genuinely absent field so a missing severity cannot
        # collide with an empty-string one.
        payload = "\x1f".join("\x00" if f is None else f for f in fields)
        self._hasher.update(payload.encode("utf-8"))
        self._hasher.update(b"\x1e")

    @property
    def count(self) -> int:
        return self._count

    def hexdigest(self) -> str:
        return self._hasher.hexdigest()
