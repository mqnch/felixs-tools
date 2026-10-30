"""Per-dataset adapter behaviour.

Fixtures are verbatim lines from each dataset's ``*_2k.log`` sample in the
loghub repo. Nothing here downloads anything -- a corpus adapter that needs a
30 GB file to test is an adapter nobody will change later.
"""

from __future__ import annotations

import pytest

from logger.corpora import loghub
from logger.corpora.base import DerivedDataPolicy
from logger.corpora.registry import dataset_names, get_adapter

import corpus_fixtures as cf
from corpus_fixtures import (
    ALL_FIXTURES,
    BGL_LINES,
    HADOOP_LINES,
    HDFS_LINES,
    OPENSTACK_LINES,
    SPARK_LINES,
    THUNDERBIRD_LINES,
)

# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------


def test_all_six_datasets_are_registered() -> None:
    assert set(dataset_names()) == {
        "bgl",
        "hadoop",
        "hdfs",
        "openstack",
        "spark",
        "thunderbird",
    }


def test_lookup_is_case_insensitive() -> None:
    assert get_adapter("HDFS").name == "hdfs"


def test_unknown_dataset_names_the_known_ones() -> None:
    with pytest.raises(KeyError, match="thunderbird"):
        get_adapter("nope")


@pytest.mark.parametrize("dataset", sorted(ALL_FIXTURES))
def test_every_fixture_line_parses(dataset: str) -> None:
    adapter = get_adapter(dataset)
    records = list(adapter.parse_lines(ALL_FIXTURES[dataset]))
    assert len(records) == len(ALL_FIXTURES[dataset])


@pytest.mark.parametrize("dataset", sorted(ALL_FIXTURES))
def test_timestamps_are_iso_and_sortable(dataset: str) -> None:
    from datetime import datetime

    for record in get_adapter(dataset).parse_lines(ALL_FIXTURES[dataset]):
        assert record.timestamp is not None
        parsed = datetime.fromisoformat(record.timestamp)
        # No timezone is invented -- see corpora.timestamps.
        assert parsed.tzinfo is None


@pytest.mark.parametrize("dataset", sorted(ALL_FIXTURES))
def test_severity_is_within_the_declared_vocabulary(dataset: str) -> None:
    adapter = get_adapter(dataset)
    for record in adapter.parse_lines(ALL_FIXTURES[dataset]):
        if adapter.severities:
            assert record.severity in adapter.severities
        else:
            assert record.severity is None


@pytest.mark.parametrize("dataset", sorted(ALL_FIXTURES))
def test_garbage_lines_are_skipped_not_raised(dataset: str) -> None:
    adapter = get_adapter(dataset)
    assert adapter.parse_line("not a log line at all") is None
    assert list(adapter.parse_lines(["", "   ", "\n"])) == []


@pytest.mark.parametrize("dataset", sorted(ALL_FIXTURES))
def test_licence_is_verified_and_carries_attribution(dataset: str) -> None:
    lic = get_adapter(dataset).license
    assert lic.derived_data is not DerivedDataPolicy.UNVERIFIED
    assert lic.attribution


# --------------------------------------------------------------------------
# HDFS
# --------------------------------------------------------------------------


def test_hdfs_maps_every_field() -> None:
    record = get_adapter("hdfs").parse_line(HDFS_LINES[0])
    assert record is not None
    assert record.raw == "PacketResponder 1 for block blk_38865049064139660 terminating"
    assert record.timestamp == "2008-11-09T20:36:15"
    assert record.severity == "INFO"
    assert record.location.service == "dfs.DataNode$PacketResponder"
    assert record.location.path == "HDFS.log"
    assert record.extra["pid"] == "148"


def test_hdfs_extracts_block_id_for_a_future_label_join() -> None:
    """HDFS labels live in anomaly_label.csv keyed by BlockId, not on the line."""
    record = get_adapter("hdfs").parse_line(HDFS_LINES[0])
    assert record is not None
    assert record.extra["block_id"] == "blk_38865049064139660"

    negative = get_adapter("hdfs").parse_line(HDFS_LINES[2])
    assert negative is not None
    assert negative.extra["block_id"] == "blk_-3544583377289625738"


def test_hdfs_two_digit_year_expands_to_2008() -> None:
    record = get_adapter("hdfs").parse_line(HDFS_LINES[0])
    assert record is not None
    assert record.timestamp.startswith("2008-")


# --------------------------------------------------------------------------
# BGL
# --------------------------------------------------------------------------


def test_bgl_normal_line_has_no_label() -> None:
    record = get_adapter("bgl").parse_line(BGL_LINES[0])
    assert record is not None
    assert record.label is None
    assert record.severity == "INFO"
    assert record.location.service == "KERNEL"
    assert record.raw == "instruction cache parity error corrected"
    assert record.timestamp == "2005-06-03T15:42:50.675872"


def test_bgl_alert_label_is_preserved_verbatim() -> None:
    record = get_adapter("bgl").parse_line(BGL_LINES[1])
    assert record is not None
    assert record.label == "KERNDTLB"
    assert record.severity == "FATAL"


@pytest.mark.parametrize(
    ("line", "folded", "raw_level"),
    [
        (
            "- 1118245894 2005.06.08 R33-M1-N6 2005-06-08-08.51.34.505108 R33-M1-N6 "
            "NULL DISCOVERY SEVERE Can not get assembly information for node card",
            "ERROR",
            "SEVERE",
        ),
        (
            "MASNORM 1119992001 2005.06.28 NULL 2005-06-28-13.53.21.974236 NULL "
            "RAS BGLMASTER FAILURE mmcs_server exited normally with exit code 13",
            "FATAL",
            "FAILURE",
        ),
    ],
)
def test_bgl_levels_outside_the_dsl_fold_and_keep_the_raw_level(
    line: str, folded: str, raw_level: str
) -> None:
    """Decision 0015: the frozen DSL has no SEVERE or FAILURE."""
    record = get_adapter("bgl").parse_line(line)
    assert record is not None
    assert record.severity == folded
    assert record.extra["level"] == raw_level


def test_bgl_in_vocabulary_level_carries_no_raw_level() -> None:
    record = get_adapter("bgl").parse_line(BGL_LINES[1])
    assert record is not None
    assert "level" not in record.extra


def test_bgl_keeps_node_and_epoch_out_of_locationid() -> None:
    record = get_adapter("bgl").parse_line(BGL_LINES[0])
    assert record is not None
    assert record.extra["node"] == "R02-M1-N0-C:J12-U11"
    assert record.extra["epoch"] == "1117838570"
    assert record.extra["type"] == "RAS"


def test_bgl_prefers_the_formatted_stamp_over_the_epoch_column() -> None:
    """The epoch is the same instant in UTC; the stamp is site-local.

    Using the epoch would put BGL on a different clock convention from the four
    datasets that only ship local time, so the stamp wins and the epoch is kept.
    """
    record = get_adapter("bgl").parse_line(BGL_LINES[0])
    assert record is not None
    assert record.timestamp.startswith("2005-06-03T15:42:50")
    assert record.extra["epoch"] == "1117838570"


# --------------------------------------------------------------------------
# Thunderbird
# --------------------------------------------------------------------------


def test_thunderbird_has_no_severity_at_all() -> None:
    adapter = get_adapter("thunderbird")
    assert adapter.severities == ()
    record = adapter.parse_line(THUNDERBIRD_LINES[0])
    assert record is not None
    assert record.severity is None


def test_thunderbird_derives_service_from_the_syslog_process_tag() -> None:
    record = get_adapter("thunderbird").parse_line(THUNDERBIRD_LINES[0])
    assert record is not None
    assert record.location.service == "crond"
    assert record.extra["module"] == "pam_unix"
    assert record.extra["pid"] == "2915"
    assert record.extra["node"] == "dn228"


def test_thunderbird_process_tag_without_a_module() -> None:
    record = get_adapter("thunderbird").parse_line(THUNDERBIRD_LINES[1])
    assert record is not None
    assert record.location.service == "crond"
    assert "module" not in record.extra
    assert record.extra["pid"] == "2916"


def test_thunderbird_path_style_process_tag_is_reduced_to_a_basename() -> None:
    line = (
        "- 1131566461 2005.11.09 tbird-admin1 Nov 9 12:01:01 local@tbird-admin1 "
        "/apps/x86_64/system/ganglia-3.0.1/sbin/gmetad[1682]: data_thread() got no answer"
    )
    record = get_adapter("thunderbird").parse_line(line)
    assert record is not None
    assert record.location.service == "gmetad"
    assert record.extra["pid"] == "1682"


def test_thunderbird_year_comes_from_the_date_column_not_a_guess() -> None:
    """The syslog portion has no year; the adjacent <Date> column supplies it."""
    record = get_adapter("thunderbird").parse_line(THUNDERBIRD_LINES[0])
    assert record is not None
    assert record.timestamp == "2005-11-09T12:01:01"


# --------------------------------------------------------------------------
# OpenStack
# --------------------------------------------------------------------------


def test_openstack_splits_logrecord_component_and_request_id() -> None:
    record = get_adapter("openstack").parse_line(OPENSTACK_LINES[0])
    assert record is not None
    assert record.location.path == "nova-api.log"
    assert record.location.service == "nova.osapi_compute.wsgi.server"
    assert record.raw.startswith('10.11.10.1 "GET ')
    assert record.extra["request"].startswith("req-38101a0b")
    assert record.extra["pid"] == "25746"
    assert record.timestamp == "2017-05-16T00:00:00.008000"


def test_openstack_warning_folds_to_warn() -> None:
    line = (
        "nova-compute.log.1.2017-05-16_13:55:31 2017-05-16 00:00:04.500 2931 WARNING "
        "nova.compute.manager [req-abc - - - - -] disk usage is high"
    )
    record = get_adapter("openstack").parse_line(line)
    assert record is not None
    assert record.severity == "WARN"
    assert record.location.path == "nova-compute.log"


# --------------------------------------------------------------------------
# Spark / Hadoop
# --------------------------------------------------------------------------


def test_spark_maps_every_field() -> None:
    record = get_adapter("spark").parse_line(SPARK_LINES[0])
    assert record is not None
    assert record.timestamp == "2017-06-09T20:10:40"
    assert record.severity == "INFO"
    assert record.location.service == "executor.CoarseGrainedExecutorBackend"
    assert record.raw == "Registered signal handlers for [TERM, HUP, INT]"


def test_hadoop_maps_every_field_including_thread() -> None:
    record = get_adapter("hadoop").parse_line(HADOOP_LINES[0])
    assert record is not None
    assert record.timestamp == "2015-10-18T18:01:47.978000"
    assert record.severity == "INFO"
    assert record.location.service == "org.apache.hadoop.mapreduce.v2.app.MRAppMaster"
    assert record.extra["process"] == "main"


def test_hadoop_for_file_binds_the_source_path() -> None:
    """Hadoop ships as a tree; the filename is the only record of origin."""
    adapter = get_adapter("hadoop").for_file("container_1445144423722_0020_01_000001.log")
    record = adapter.parse_line(HADOOP_LINES[0])
    assert record is not None
    assert record.location.path == "container_1445144423722_0020_01_000001.log"
    # The original adapter is untouched.
    assert get_adapter("hadoop").default_path == "Hadoop.log"


def test_adapters_are_stateless_across_calls() -> None:
    adapter = loghub.SparkAdapter()
    first = adapter.parse_line(SPARK_LINES[0])
    second = adapter.parse_line(SPARK_LINES[1])
    assert first is not None and second is not None
    assert first.location.service != second.location.service
    assert adapter.parse_line(SPARK_LINES[0]) == first


# --------------------------------------------------------------------------
# Sample-vs-full traps
#
# Every case below is absent from the *_2k.log samples but present in the real
# datasets. These are the tests that would have caught the two bugs the sample
# hid: BGL's missing <NodeRepeat> and Thunderbird's spaced program tag.
# --------------------------------------------------------------------------


def test_bgl_line_missing_noderepeat_does_not_shift_fields() -> None:
    """316 real lines omit <NodeRepeat>; naive splitting gives level='Kill'."""
    record = get_adapter("bgl").parse_line(cf.BGL_MISSING_NODEREPEAT)
    assert record is not None
    assert record.severity == "FATAL"
    assert record.location.service == "KERNEL"
    assert record.extra["type"] == "RAS"
    assert record.raw == "Kill job 20251 timed out. Block freed."
    assert record.extra["node_repeat_missing"] == "1"


def test_bgl_still_parses_the_normal_ten_field_form() -> None:
    record = get_adapter("bgl").parse_line(BGL_LINES[0])
    assert record is not None
    assert "node_repeat_missing" not in record.extra
    assert record.severity == "INFO"


def test_bgl_null_node_is_tolerated() -> None:
    record = get_adapter("bgl").parse_line(cf.BGL_NULL_NODE)
    assert record is not None
    assert record.severity == "ERROR"
    assert record.location.service == "MMCS"
    assert record.extra["node"] == "NULL"


@pytest.mark.parametrize("line", cf.THUNDERBIRD_ALERT_LINES)
def test_thunderbird_alert_lines_carry_their_label(line: str) -> None:
    """Thunderbird_2k.log is 100% '-', so the sample proves nothing here."""
    record = get_adapter("thunderbird").parse_line(line)
    assert record is not None
    assert record.label in ("VAPI", "ECC")
    assert record.severity is None


def test_thunderbird_program_tag_with_a_space_is_captured() -> None:
    record = get_adapter("thunderbird").parse_line(cf.THUNDERBIRD_ALERT_LINES[1])
    assert record is not None
    assert record.location.service == "Server Administrator"


def test_thunderbird_program_tag_without_a_pid_is_captured() -> None:
    record = get_adapter("thunderbird").parse_line(cf.THUNDERBIRD_ALERT_LINES[0])
    assert record is not None
    assert record.location.service == "kernel"
    assert "pid" not in record.extra


@pytest.mark.parametrize("line", cf.SPARK_NON_INFO_LINES)
def test_spark_warn_and_error_parse(line: str) -> None:
    """Spark_2k.log is 100% INFO; WARN/ERROR appear only in the full dataset."""
    record = get_adapter("spark").parse_line(line)
    assert record is not None
    assert record.severity in ("WARN", "ERROR")


@pytest.mark.parametrize("dataset", ["spark", "hadoop"])
@pytest.mark.parametrize("line", cf.CONTINUATION_LINES)
def test_stack_trace_continuations_are_skipped_not_fatal(
    dataset: str, line: str
) -> None:
    """54% of the real Hadoop file and 17.5% of Spark are continuation lines."""
    assert get_adapter(dataset).parse_line(line) is None


def test_openstack_traceback_line_without_an_addr_group_still_parses() -> None:
    record = get_adapter("openstack").parse_line(cf.OPENSTACK_TRACEBACK_LINE)
    assert record is not None
    assert record.severity == "ERROR"
    assert record.location.service == "oslo_service.periodic_task"
    assert record.raw.startswith("Traceback")
    assert "request" not in record.extra


def test_openstack_extracts_instance_id_for_a_future_label_join() -> None:
    """anomaly_labels.txt keys on VM instance UUIDs found in the content."""
    record = get_adapter("openstack").parse_line(cf.OPENSTACK_INSTANCE_LINE)
    assert record is not None
    assert record.extra["instance_id"] == "b9000564-fe1a-409b-b8cc-1e88b294cd1d"


def test_openstack_critical_is_in_the_vocabulary() -> None:
    line = (
        "nova-api.log.1.2017-05-16_13:53:08 2017-05-16 06:25:02.869 25746 CRITICAL "
        "keystonemiddleware.auth_token [req-1cc7d50c - - -] Unable to validate token"
    )
    record = get_adapter("openstack").parse_line(line)
    assert record is not None
    assert record.severity == "CRITICAL"
    assert record.severity in get_adapter("openstack").severities


def test_hadoop_thread_name_with_spaces_and_colons() -> None:
    record = get_adapter("hadoop").parse_line(cf.HADOOP_COMPLEX_THREAD_LINE)
    assert record is not None
    assert record.extra["process"] == "LeaseRenewer:msrabi@msra-sa-41:9000"
    assert record.location.service == "org.apache.hadoop.ipc.Client"


def test_label_source_is_documented_for_every_dataset() -> None:
    """All four labelled datasets differ; only two put the label on the line."""
    inline = {n for n in dataset_names() if get_adapter(n).has_inline_labels}
    assert inline == {"bgl", "thunderbird"}
    assert get_adapter("spark").label_source is None
    for name in ("hdfs", "openstack", "hadoop"):
        assert get_adapter(name).label_source is not None
        assert not get_adapter(name).has_inline_labels
