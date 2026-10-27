"""Manifest round-tripping and the publication gate."""

from __future__ import annotations

from pathlib import Path

from logger.corpora import licenses
from logger.corpora.base import DatasetLicense, DerivedDataPolicy
from logger.corpora.manifest import CorpusManifest, manifest_path_for


def _manifest(**overrides: object) -> CorpusManifest:
    base = dict(
        dataset="hdfs",
        source_url="https://zenodo.org/records/8196385",
        version="HDFS_v1 (loghub 2023 release)",
        sample_size=200_000,
        seed=20260815,
        row_count=200_000,
        template_count=48,
        license=licenses.HDFS,
        ingested_at="2026-08-15T12:00:00+00:00",
        content_digest="abc123",
        source_files=["HDFS.log"],
    )
    base.update(overrides)
    return CorpusManifest(**base)  # type: ignore[arg-type]


def test_json_round_trip_preserves_everything() -> None:
    original = _manifest()
    assert CorpusManifest.from_json(original.to_json()) == original


def test_json_round_trip_preserves_the_licence_enum() -> None:
    restored = CorpusManifest.from_json(_manifest().to_json())
    assert isinstance(restored.license, DatasetLicense)
    assert restored.license.derived_data is DerivedDataPolicy.PUBLISHABLE_WITH_ATTRIBUTION


def test_manifest_records_every_field_the_slice_requires() -> None:
    data = _manifest().to_dict()
    for field in (
        "dataset",
        "source_url",
        "version",
        "sample_size",
        "seed",
        "row_count",
        "template_count",
        "license",
        "ingested_at",
    ):
        assert field in data, field


def test_write_and_read(tmp_path: Path) -> None:
    path = tmp_path / "hdfs.manifest.json"
    _manifest().write(path)
    assert CorpusManifest.read(path) == _manifest()


def test_manifest_path_is_a_sidecar_of_the_db() -> None:
    assert manifest_path_for("corpora/hdfs.db").name == "hdfs.manifest.json"


def test_reproduces_ignores_wall_clock_time() -> None:
    """Two identical builds differ only in ingested_at, and must still match."""
    a = _manifest(ingested_at="2026-08-15T12:00:00+00:00")
    b = _manifest(ingested_at="2027-01-01T09:30:00+00:00")
    assert a != b
    assert a.reproduces(b)


def test_reproduces_is_false_when_content_differs() -> None:
    assert not _manifest().reproduces(_manifest(content_digest="different"))


def test_reproduces_is_false_when_the_seed_differs() -> None:
    assert not _manifest().reproduces(_manifest(seed=1))


def test_reproduces_is_false_when_row_count_differs() -> None:
    assert not _manifest().reproduces(_manifest(row_count=1))


def test_unverified_licence_is_not_publishable() -> None:
    unverified = DatasetLicense(
        name="?", url=None, derived_data=DerivedDataPolicy.UNVERIFIED
    )
    assert not _manifest(license=unverified).publishable()


def test_restricted_licence_is_not_publishable() -> None:
    restricted = DatasetLicense(
        name="research only", url=None, derived_data=DerivedDataPolicy.RESTRICTED
    )
    assert not _manifest(license=restricted).publishable()


def test_verified_loghub_licences_are_publishable_with_attribution() -> None:
    assert _manifest().publishable()


def test_full_sample_is_representable_as_none() -> None:
    manifest = _manifest(sample_size=None)
    assert CorpusManifest.from_json(manifest.to_json()).sample_size is None


def test_bgl_and_thunderbird_licence_notes_flag_the_unstated_terms() -> None:
    """The weak link must stay findable, not get smoothed into a one-word status."""
    for lic in (licenses.BGL, licenses.THUNDERBIRD):
        assert "CFDR" in lic.name or "CFDR" in (lic.notes or "")
        assert "not a grant" in (lic.notes or "").lower() or "NOT sanitised" in (
            lic.notes or ""
        )
