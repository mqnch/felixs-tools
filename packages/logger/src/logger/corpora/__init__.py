"""Public log corpora: adapters, deterministic sampling, and manifests.

Turns a LogHub dataset into a reproducible indexed corpus. Reproducibility is
the point -- the same command with the same seed must yield the same rows, in
the same order, with the same template assignment (decision 0004).
"""

from logger.corpora.base import (
    CorpusRecord,
    DatasetAdapter,
    DatasetLicense,
    DerivedDataPolicy,
)
from logger.corpora.ingest import (
    DEFAULT_SEED,
    ingest_loghub,
    ingest_records,
    read_stored_manifest,
)
from logger.corpora.manifest import CorpusManifest, manifest_path_for
from logger.corpora.registry import dataset_names, get_adapter
from logger.corpora.sampling import ContentDigest, deterministic_sample
from logger.corpora.staging import stage_dataset

__all__ = [
    "DEFAULT_SEED",
    "ContentDigest",
    "CorpusManifest",
    "CorpusRecord",
    "DatasetAdapter",
    "DatasetLicense",
    "DerivedDataPolicy",
    "dataset_names",
    "deterministic_sample",
    "get_adapter",
    "ingest_loghub",
    "ingest_records",
    "manifest_path_for",
    "read_stored_manifest",
    "stage_dataset",
]
