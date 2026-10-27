"""Fetch and unpack raw loghub archives into a local staging directory.

Downloading is **opt-in** (``allow_download=True``). The default is to fail with
an instruction, for two reasons: Thunderbird alone is ~30 GB compressed-to-disk
work, and slice 003's open question -- whether WATcloud compute nodes have
outbound internet -- is unresolved. If they do not, the archive has to be staged
from a login node and this module's job is only to find and unpack it.

Nothing here runs during tests.
"""

from __future__ import annotations

import hashlib
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from logger.corpora.registry import get_adapter

DEFAULT_STAGING_DIR = Path("corpora/raw")

_CHUNK = 1 << 20


@dataclass(frozen=True)
class Archive:
    """One downloadable dataset archive."""

    dataset: str
    filename: str
    url: str
    member: str
    """Path of the log file inside the archive, relative to its root."""

    approx_bytes: int


# Zenodo record 8196385 is the loghub ISSRE'23 release. Sizes are approximate
# uncompressed figures, present so a caller can refuse a job on a small disk.
ARCHIVES: dict[str, Archive] = {
    "hdfs": Archive(
        "hdfs",
        "HDFS_v1.zip",
        "https://zenodo.org/records/8196385/files/HDFS_v1.zip",
        "HDFS.log",
        1_580_000_000,
    ),
    "bgl": Archive(
        "bgl",
        "BGL.zip",
        "https://zenodo.org/records/8196385/files/BGL.zip",
        "BGL.log",
        780_000_000,
    ),
    "thunderbird": Archive(
        "thunderbird",
        "Thunderbird.zip",
        "https://zenodo.org/records/8196385/files/Thunderbird.zip",
        "Thunderbird.log",
        31_800_000_000,
    ),
    "openstack": Archive(
        "openstack",
        "OpenStack.zip",
        "https://zenodo.org/records/8196385/files/OpenStack.zip",
        "OpenStack",
        63_000_000,
    ),
    "spark": Archive(
        "spark",
        "Spark.zip",
        "https://zenodo.org/records/8196385/files/Spark.zip",
        "Spark.log",
        2_950_000_000,
    ),
    "hadoop": Archive(
        "hadoop",
        "Hadoop.zip",
        "https://zenodo.org/records/8196385/files/Hadoop.zip",
        "Hadoop",
        50_000_000,
    ),
}


def stage_dataset(
    dataset: str,
    *,
    staging_dir: str | Path = DEFAULT_STAGING_DIR,
    allow_download: bool = False,
    expected_sha256: str | None = None,
) -> list[Path]:
    """Return the staged log file(s) for ``dataset``, fetching only if allowed.

    Idempotent: an already-extracted dataset is returned as-is without touching
    the network, so a rerun on a compute node with no egress still works.
    """
    get_adapter(dataset)  # validates the name before any I/O
    archive = ARCHIVES[dataset.strip().lower()]
    root = Path(staging_dir) / archive.dataset
    extracted = root / "extracted"

    if extracted.exists():
        files = sorted(p for p in extracted.rglob("*") if p.is_file())
        if files:
            return files

    local = root / archive.filename
    if not local.exists():
        if not allow_download:
            raise FileNotFoundError(
                f"{archive.dataset}: {local} is missing and downloading is "
                f"disabled. Fetch {archive.url} (~{archive.approx_bytes / 1e9:.1f} GB "
                "uncompressed) on a host with egress, drop it there, and rerun."
            )
        _download(archive.url, local)

    if expected_sha256:
        actual = sha256_file(local)
        if actual != expected_sha256:
            raise ValueError(
                f"{archive.dataset}: checksum mismatch; expected {expected_sha256}, "
                f"got {actual}. Refusing to build a corpus from an unverified archive."
            )

    _extract(local, extracted)
    return sorted(p for p in extracted.rglob("*") if p.is_file())


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as response, partial.open("wb") as fh:
        while chunk := response.read(_CHUNK):
            fh.write(chunk)
    # Rename only on success so an interrupted download is never mistaken for a
    # complete one on the next run.
    partial.replace(dest)


def _extract(archive_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if archive_path.suffix == ".zip":
        import zipfile

        with zipfile.ZipFile(archive_path) as zf:
            for member in zf.namelist():
                _reject_traversal(member, dest)
            zf.extractall(dest)
        return
    with tarfile.open(archive_path) as tf:
        for member_name in tf.getnames():
            _reject_traversal(member_name, dest)
        tf.extractall(dest, filter="data")


def _reject_traversal(member: str, dest: Path) -> None:
    target = (dest / member).resolve()
    if not str(target).startswith(str(dest.resolve())):
        raise ValueError(f"archive member escapes staging dir: {member!r}")


def sha256_file(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            hasher.update(chunk)
    return hasher.hexdigest()
