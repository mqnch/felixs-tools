"""Dataset-name lookup, so ``--dataset hdfs`` resolves to an adapter."""

from __future__ import annotations

from logger.corpora import loghub
from logger.corpora.base import DatasetAdapter

_ADAPTERS: tuple[type[DatasetAdapter], ...] = (
    loghub.HdfsAdapter,
    loghub.BglAdapter,
    loghub.ThunderbirdAdapter,
    loghub.OpenStackAdapter,
    loghub.SparkAdapter,
    loghub.HadoopAdapter,
)

_BY_NAME: dict[str, type[DatasetAdapter]] = {cls.name: cls for cls in _ADAPTERS}


def dataset_names() -> tuple[str, ...]:
    return tuple(sorted(_BY_NAME))


def get_adapter(name: str) -> DatasetAdapter:
    """Fresh adapter instance for ``name`` (case-insensitive)."""
    key = name.strip().lower()
    cls = _BY_NAME.get(key)
    if cls is None:
        raise KeyError(f"unknown dataset {name!r}; known: {', '.join(dataset_names())}")
    return cls()
