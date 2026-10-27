"""Staging behaviour. Never touches the network -- downloading is opt-in."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from logger.corpora import staging
from logger.corpora.registry import dataset_names


def test_every_dataset_has_an_archive_entry() -> None:
    assert set(staging.ARCHIVES) == set(dataset_names())


def test_missing_archive_refuses_to_download_by_default(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError) as excinfo:
        staging.stage_dataset("hdfs", staging_dir=tmp_path)
    message = str(excinfo.value)
    # The error has to be actionable on a node with no egress.
    assert "downloading is disabled" in message
    assert staging.ARCHIVES["hdfs"].url in message


def test_unknown_dataset_is_rejected_before_touching_the_filesystem(
    tmp_path: Path,
) -> None:
    with pytest.raises(KeyError):
        staging.stage_dataset("mysql", staging_dir=tmp_path)
    assert not list(tmp_path.iterdir())


def test_already_extracted_dataset_short_circuits(tmp_path: Path) -> None:
    """A rerun must work offline even though no archive is present."""
    extracted = tmp_path / "hdfs" / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "HDFS.log").write_text("081109 203615 148 INFO a.B: x\n")

    files = staging.stage_dataset("hdfs", staging_dir=tmp_path)
    assert [f.name for f in files] == ["HDFS.log"]


def test_checksum_mismatch_refuses_to_extract(tmp_path: Path) -> None:
    archive = tmp_path / "hdfs" / staging.ARCHIVES["hdfs"].filename
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("HDFS.log", "081109 203615 148 INFO a.B: x\n")

    with pytest.raises(ValueError, match="checksum mismatch"):
        staging.stage_dataset("hdfs", staging_dir=tmp_path, expected_sha256="0" * 64)
    assert not (tmp_path / "hdfs" / "extracted").exists()


def test_matching_checksum_extracts(tmp_path: Path) -> None:
    archive = tmp_path / "hdfs" / staging.ARCHIVES["hdfs"].filename
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("HDFS.log", "081109 203615 148 INFO a.B: x\n")

    files = staging.stage_dataset(
        "hdfs", staging_dir=tmp_path, expected_sha256=staging.sha256_file(archive)
    )
    assert [f.name for f in files] == ["HDFS.log"]


def test_zip_slip_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "hdfs" / staging.ARCHIVES["hdfs"].filename
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../../escaped.log", "x")

    with pytest.raises(ValueError, match="escapes staging dir"):
        staging.stage_dataset("hdfs", staging_dir=tmp_path)
    assert not (tmp_path / "escaped.log").exists()


def test_thunderbird_size_estimate_flags_it_as_the_large_one() -> None:
    sizes = {name: a.approx_bytes for name, a in staging.ARCHIVES.items()}
    assert sizes["thunderbird"] == max(sizes.values())
    assert sizes["thunderbird"] > 30 * 10**9
