"""End-to-end corpus builds from inline fixtures. Nothing here downloads."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from logger.corpora import DEFAULT_SEED, ingest_loghub, read_stored_manifest
from logger.corpora.base import DatasetLicense, DerivedDataPolicy
from logger.corpora.manifest import manifest_path_for
from logger.corpora.registry import get_adapter

from corpus_fixtures import BGL_LINES, HADOOP_LINES, HDFS_LINES

# A synthetic HDFS file big enough that sampling has something to choose from.
# Two templates on purpose, so template_count is a real number.
HDFS_CORPUS = [
    f"081109 20{h:02d}{m:02d} {100 + i} {'WARN' if i % 7 == 0 else 'INFO'} "
    f"dfs.{'DataNode$PacketResponder' if i % 2 else 'FSNamesystem'}: "
    f"PacketResponder {i} for block blk_{1000 + i} terminating"
    for i, (h, m) in enumerate((i // 60, i % 60) for i in range(300))
]


def _write(tmp_path: Path, lines: list[str], name: str = "HDFS.log") -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_ingest_writes_rows_manifest_and_sidecar(tmp_path: Path) -> None:
    source = _write(tmp_path, HDFS_CORPUS)
    db = tmp_path / "hdfs.db"

    manifest = ingest_loghub("hdfs", source=source, out=db, sample_size=50)

    assert manifest.dataset == "hdfs"
    assert manifest.row_count == 50
    assert manifest.sample_size == 50
    assert manifest.seed == DEFAULT_SEED
    assert manifest.template_count >= 1
    assert manifest.content_digest
    assert manifest.source_files == [str(source)]
    assert manifest_path_for(db).exists()

    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM log_entries").fetchone()[0] == 50
        assert conn.execute("SELECT COUNT(*) FROM corpus_records").fetchone()[0] == 50
    finally:
        conn.close()


def test_manifest_is_readable_back_out_of_the_database(tmp_path: Path) -> None:
    source = _write(tmp_path, HDFS_CORPUS)
    db = tmp_path / "hdfs.db"
    written = ingest_loghub("hdfs", source=source, out=db, sample_size=25)
    assert read_stored_manifest(db, "hdfs") == written


def test_same_seed_reproduces_the_corpus(tmp_path: Path) -> None:
    """The headline guarantee of the slice."""
    source = _write(tmp_path, HDFS_CORPUS)
    first = ingest_loghub("hdfs", source=source, out=tmp_path / "a.db", sample_size=40)
    second = ingest_loghub("hdfs", source=source, out=tmp_path / "b.db", sample_size=40)

    assert first.reproduces(second)
    assert first.content_digest == second.content_digest
    assert first.template_count == second.template_count
    assert _rows(tmp_path / "a.db") == _rows(tmp_path / "b.db")


def test_different_seed_changes_the_corpus(tmp_path: Path) -> None:
    source = _write(tmp_path, HDFS_CORPUS)
    a = ingest_loghub("hdfs", source=source, out=tmp_path / "a.db", sample_size=40)
    b = ingest_loghub(
        "hdfs", source=source, out=tmp_path / "b.db", sample_size=40, seed=999
    )
    assert not a.reproduces(b)
    assert a.content_digest != b.content_digest


def test_sampled_rows_stay_in_source_order(tmp_path: Path) -> None:
    """Time-window splits downstream depend on the corpus staying ordered."""
    source = _write(tmp_path, HDFS_CORPUS)
    db = tmp_path / "hdfs.db"
    ingest_loghub("hdfs", source=source, out=db, sample_size=60)

    conn = sqlite3.connect(db)
    try:
        stamps = [
            r[0]
            for r in conn.execute(
                "SELECT timestamp FROM log_entries ORDER BY id"
            ).fetchall()
        ]
        indices = [
            r[0]
            for r in conn.execute(
                "SELECT source_index FROM corpus_records ORDER BY entry_id"
            ).fetchall()
        ]
    finally:
        conn.close()

    assert stamps == sorted(stamps)
    assert indices == sorted(indices)


def test_no_sample_size_ingests_everything(tmp_path: Path) -> None:
    source = _write(tmp_path, HDFS_CORPUS)
    manifest = ingest_loghub("hdfs", source=source, out=tmp_path / "all.db")
    assert manifest.row_count == len(HDFS_CORPUS)
    assert manifest.sample_size is None


def test_severity_and_service_survive_into_the_index(tmp_path: Path) -> None:
    source = _write(tmp_path, HDFS_LINES)
    db = tmp_path / "hdfs.db"
    ingest_loghub("hdfs", source=source, out=db)

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT severity, service, path FROM log_entries ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert {r[0] for r in rows} == {"INFO", "WARN"}
    assert all(r[1].startswith("dfs.") for r in rows)
    assert all(r[2] == "HDFS.log" for r in rows)


def test_bgl_anomaly_labels_are_preserved_and_unused(tmp_path: Path) -> None:
    """Slice 003 builds no scorer; the label just must not be thrown away."""
    source = _write(tmp_path, BGL_LINES * 5, name="BGL.log")
    db = tmp_path / "bgl.db"
    ingest_loghub("bgl", source=source, out=db)

    conn = sqlite3.connect(db)
    try:
        labels = [r[0] for r in conn.execute("SELECT label FROM corpus_records")]
        # The label is in the sidecar only -- nothing in log_entries reads it.
        columns = {
            r[1] for r in conn.execute("PRAGMA table_info(log_entries)").fetchall()
        }
    finally:
        conn.close()

    assert labels.count("KERNDTLB") == 5
    assert labels.count(None) == 5
    assert "label" not in columns


def test_extra_fields_are_preserved_as_json(tmp_path: Path) -> None:
    source = _write(tmp_path, BGL_LINES, name="BGL.log")
    db = tmp_path / "bgl.db"
    ingest_loghub("bgl", source=source, out=db)

    conn = sqlite3.connect(db)
    try:
        extras = [r[0] for r in conn.execute("SELECT extra FROM corpus_records")]
    finally:
        conn.close()
    assert all("R02-M1-N0-C" in e or "R04-M1-N4-C" in e for e in extras)


def test_unparseable_lines_are_counted_not_fatal(tmp_path: Path) -> None:
    source = _write(tmp_path, [HDFS_LINES[0], "garbage", "", HDFS_LINES[1], "more junk"])
    manifest = ingest_loghub("hdfs", source=source, out=tmp_path / "hdfs.db")
    assert manifest.row_count == 2
    assert manifest.skipped_lines == 2


def test_directory_source_ingests_every_file_in_sorted_order(tmp_path: Path) -> None:
    tree = tmp_path / "hadoop"
    (tree / "application_b").mkdir(parents=True)
    (tree / "application_a").mkdir(parents=True)
    (tree / "application_a" / "container_1.log").write_text(
        HADOOP_LINES[0] + "\n", encoding="utf-8"
    )
    (tree / "application_b" / "container_2.log").write_text(
        HADOOP_LINES[1] + "\n", encoding="utf-8"
    )

    db = tmp_path / "hadoop.db"
    manifest = ingest_loghub("hadoop", source=tree, out=db)
    assert manifest.row_count == 2

    conn = sqlite3.connect(db)
    try:
        paths = [r[0] for r in conn.execute("SELECT path FROM log_entries ORDER BY id")]
    finally:
        conn.close()
    # for_file gives each row the container file it actually came from.
    assert paths == ["container_1.log", "container_2.log"]


def test_missing_source_says_how_to_stage_it(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="staging"):
        ingest_loghub("hdfs", source=tmp_path / "nope.log", out=tmp_path / "x.db")


def test_unknown_dataset_is_rejected_before_any_io(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        ingest_loghub("mysql", source=tmp_path / "nope.log", out=tmp_path / "x.db")
    assert not (tmp_path / "x.db").exists()


def test_require_publishable_refuses_an_unverified_licence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate decision 0004 asks for: publication blocks on licence status."""
    source = _write(tmp_path, HDFS_LINES)
    adapter_cls = type(get_adapter("hdfs"))
    monkeypatch.setattr(
        adapter_cls,
        "license",
        DatasetLicense(name="?", url=None, derived_data=DerivedDataPolicy.UNVERIFIED),
    )
    with pytest.raises(PermissionError, match="may not be published"):
        ingest_loghub(
            "hdfs",
            source=source,
            out=tmp_path / "x.db",
            require_publishable=True,
        )


def test_require_publishable_allows_the_verified_datasets(tmp_path: Path) -> None:
    source = _write(tmp_path, HDFS_LINES)
    manifest = ingest_loghub(
        "hdfs", source=source, out=tmp_path / "x.db", require_publishable=True
    )
    assert manifest.publishable()


def _rows(db: Path) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT raw, template, template_id, severity, timestamp, location_key "
            "FROM log_entries ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
