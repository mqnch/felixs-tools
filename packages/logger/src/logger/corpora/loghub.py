"""Adapters for the six loghub datasets named in decision 0004.

Each adapter is one regex plus a field mapping. The regexes follow loghub's own
``log_format`` templates so a row here lines up with the published
``*_structured.csv`` for the same dataset.

Sizes below are the full uncompressed datasets; all six are far larger than a
default sample, which is why sampling is not optional in practice.
"""

from __future__ import annotations

import re

from common import LocationId

from logger.corpora import licenses, timestamps
from logger.corpora.base import CorpusRecord, DatasetAdapter, normalise_severity

ZENODO = "https://zenodo.org/records/8196385"


class HdfsAdapter(DatasetAdapter):
    """HDFS_v1 -- 1.47 GiB, 11,175,629 lines, from a 203-node EC2 cluster."""

    name = "hdfs"
    source_url = ZENODO
    version = "HDFS_v1 (loghub 2023 release)"
    license = licenses.HDFS
    log_format = "<Date> <Time> <Pid> <Level> <Component>: <Content>"
    default_path = "HDFS.log"
    severities = ("INFO", "WARN")
    label_source = "file:preprocessed/anomaly_label.csv keyed by BlockId"
    """NOT on the line. 575,061 block traces labelled Normal/Anomaly (16,838
    anomalous, 2.93%). The label is per *block trace*, not per line: group lines
    by the ``blk_-?\d+`` token in the content and join. ``block_id`` is extracted
    into ``extra`` so that join stays possible without a re-ingest."""

    _RE = re.compile(
        r"^(?P<date>\d{6})\s+(?P<time>\d{6})\s+(?P<pid>\d+)\s+"
        r"(?P<level>[A-Z]+)\s+(?P<component>[^:]+):\s*(?P<content>.*)$"
    )
    _BLOCK_RE = re.compile(r"\bblk_-?\d+")

    def parse_line(self, line: str) -> CorpusRecord | None:
        m = self._RE.match(line)
        if not m:
            return None
        extra = {"pid": m["pid"]}
        block = self._BLOCK_RE.search(m["content"])
        if block:
            extra["block_id"] = block.group(0)
        return CorpusRecord(
            raw=m["content"],
            timestamp=timestamps.from_yymmdd_hhmmss(m["date"], m["time"]),
            severity=normalise_severity(m["level"]),
            location=LocationId(path=self.default_path, service=m["component"]),
            label=None,
            extra=extra,
        )


class BglAdapter(DatasetAdapter):
    """BGL -- 708.76 MiB, 4,747,963 lines, Blue Gene/L at LLNL."""

    name = "bgl"
    source_url = ZENODO
    version = "BGL (loghub 2023 release)"
    license = licenses.BGL
    log_format = (
        "<Label> <Timestamp> <Date> <Node> <Time> <NodeRepeat> "
        "<Type> <Component> <Level> <Content>"
    )
    default_path = "BGL.log"
    severities = ("INFO", "WARN", "ERROR", "SEVERE", "FATAL", "FAILURE")
    label_source = "inline: field 1"
    """``-`` means normal; anything else is one of 41 alert categories
    (``KERNDTLB``, ``KERNSTOR``, ``APPSEV``, ...). 348,460 of 4,747,963 lines are
    alerts. Preserved, never read."""

    # <NodeRepeat> is OPTIONAL. 316 lines of the real 4.7M-line BGL.log omit it
    # (they also carry Node="-"), e.g.
    #   - 1119415930 2005.06.21 - 2005-06-21-21.52.10.214285 RAS KERNEL FATAL ...
    # Positional splitting on those shifts every later field right, silently
    # yielding component="FATAL" and level="Kill". Anchoring <Type> to its closed
    # vocabulary makes the regex backtrack into the 9-field form instead. None of
    # this is visible in BGL_2k.log -- the sample contains no such line.
    _RE = re.compile(
        r"^(?P<label>\S+)\s+(?P<epoch>\d+)\s+(?P<date>\S+)\s+(?P<node>\S+)\s+"
        r"(?P<stamp>\S+)\s+(?:(?P<node2>\S+)\s+)?(?P<type>RAS|NULL)\s+"
        r"(?P<component>\S+)\s+(?P<level>\S+)\s+(?P<content>.*)$"
    )

    def parse_line(self, line: str) -> CorpusRecord | None:
        m = self._RE.match(line)
        if not m:
            return None
        extra = {"epoch": m["epoch"], "node": m["node"], "type": m["type"]}
        if m["node2"] is None:
            extra["node_repeat_missing"] = "1"
        return CorpusRecord(
            raw=m["content"],
            timestamp=timestamps.from_bgl_stamp(m["stamp"]),
            severity=normalise_severity(m["level"]),
            location=LocationId(path=self.default_path, service=m["component"]),
            label=None if m["label"] == "-" else m["label"],
            extra=extra,
        )


class ThunderbirdAdapter(DatasetAdapter):
    """Thunderbird -- 29.60 GiB, 211,212,192 lines, Sandia supercomputer syslog.

    Much the largest of the six and the reason streaming reservoir sampling is
    the only sane default: a full ingest is a multi-hour job producing a database
    nothing downstream currently needs.
    """

    name = "thunderbird"
    source_url = ZENODO
    version = "Thunderbird (loghub 2023 release)"
    license = licenses.THUNDERBIRD
    log_format = (
        "<Label> <Id> <Date> <Admin> <Month> <Day> <Time> <AdminAddr> <Content>"
    )
    default_path = "Thunderbird.log"
    severities = ()
    """No level field at all -- see the module note in the slice writeup.

    Severity-filtered plans cannot be generated against this corpus. Guessing a
    level from the message text was rejected: it would invent structure the
    source does not have, and slice 004's gold answers come from executing the
    plan, so an invented severity becomes invented ground truth.
    """
    label_source = "inline: field 1"
    """``-`` means normal, otherwise an alert tag (``VAPI``, ``ECC``, ``SCSI``,
    ``MPT``, ``EXT_FS``, ``CPU``, ``CHK_DSK``, ``NMI``, ...). The full tag
    vocabulary is unverified -- only ~16% of the 29.6 GiB file has been scanned,
    and Thunderbird_2k.log is 100% ``-``, so the sample shows none of them."""

    _RE = re.compile(
        r"^(?P<label>\S+)\s+(?P<epoch>\d+)\s+(?P<date>\S+)\s+(?P<admin>\S+)\s+"
        r"(?P<month>[A-Za-z]{3})\s+(?P<day>\d{1,2})\s+"
        r"(?P<time>\d{2}:\d{2}:\d{2})\s+(?P<addr>\S+)\s+(?P<content>.*)$"
    )
    # Leading syslog program tag: "crond(pam_unix)[2915]:", "ACPI:", an absolute
    # path like "/apps/.../sbin/gmetad[1682]:", or a tag CONTAINING SPACES such
    # as "Server Administrator:". Spaces are allowed (loghub's own format takes
    # <Component> up to the first ": "), but colons are not, which keeps the
    # match from running away into a message body. The PID is optional -- 255 of
    # the 2000 sample lines have none.
    _PROC_RE = re.compile(
        r"^(?P<proc>[^:\[(\n]{1,60}?)(?:\((?P<mod>[^)]*)\))?"
        r"(?:\[(?P<pid>\d+)\])?:\s"
    )

    def parse_line(self, line: str) -> CorpusRecord | None:
        m = self._RE.match(line)
        if not m:
            return None
        content = m["content"]
        extra = {"epoch": m["epoch"], "node": m["admin"], "admin_addr": m["addr"]}

        service: str | None = None
        proc = self._PROC_RE.match(content)
        if proc:
            service = proc["proc"].rsplit("/", 1)[-1]
            if proc["mod"]:
                extra["module"] = proc["mod"]
            if proc["pid"]:
                extra["pid"] = proc["pid"]

        return CorpusRecord(
            raw=content,
            timestamp=timestamps.from_dotted_date_and_syslog_time(
                m["date"], m["month"], m["day"], m["time"]
            ),
            severity=None,
            location=LocationId(path=self.default_path, service=service),
            label=None if m["label"] == "-" else m["label"],
            extra=extra,
        )


class OpenStackAdapter(DatasetAdapter):
    """OpenStack -- 58.61 MiB, 207,820 lines, CloudLab (DeepLog authors)."""

    name = "openstack"
    source_url = ZENODO
    version = "OpenStack (loghub 2023 release)"
    license = licenses.OPENSTACK
    log_format = "<Logrecord> <Date> <Time> <Pid> <Level> <Component> [<ADDR>] <Content>"
    default_path = "openstack.log"
    severities = ("INFO", "WARN", "ERROR", "CRITICAL")
    label_source = "file:anomaly_labels.txt listing 4 VM instance UUIDs"
    """NOT on the line, and two-level: the archive splits into
    ``openstack_normal1/2.log`` vs ``openstack_abnormal.log``, and
    ``anomaly_labels.txt`` names 4 VM instance UUIDs. Those match the
    ``[instance: <uuid>]`` group that opens the content, so ``instance_id`` is
    extracted into ``extra`` to keep the join available."""

    _RE = re.compile(
        r"^(?P<logrecord>\S+)\s+(?P<date>\d{4}-\d{2}-\d{2})\s+"
        r"(?P<time>\d{2}:\d{2}:\d{2}\.\d+)\s+(?P<pid>\d+)\s+(?P<level>[A-Z]+)\s+"
        r"(?P<component>\S+)\s+(?P<rest>.*)$"
    )
    _ADDR_RE = re.compile(r"^\[(?P<addr>[^\]]*)\]\s*(?P<content>.*)$")
    _INSTANCE_RE = re.compile(r"\[instance:\s*(?P<uuid>[0-9a-f-]{36})\]")

    def parse_line(self, line: str) -> CorpusRecord | None:
        m = self._RE.match(line)
        if not m:
            return None
        content = m["rest"]
        extra = {"pid": m["pid"], "logrecord": m["logrecord"]}
        # The [<ADDR>] group is optional: 184 lines of the real dataset are
        # Python traceback continuations that repeat the full prefix but omit it.
        addr = self._ADDR_RE.match(content)
        if addr:
            extra["request"] = addr["addr"]
            content = addr["content"]
        instance = self._INSTANCE_RE.search(content)
        if instance:
            extra["instance_id"] = instance["uuid"]

        # "nova-api.log.1.2017-05-16_13:53:08" -> "nova-api.log"
        source_file = m["logrecord"].split(".log", 1)[0] + ".log"
        return CorpusRecord(
            raw=content,
            timestamp=timestamps.from_iso_like(m["date"], m["time"]),
            severity=normalise_severity(m["level"]),
            location=LocationId(path=source_file, service=m["component"]),
            label=None,
            extra=extra,
        )


class SparkAdapter(DatasetAdapter):
    """Spark -- 2.75 GiB, 33,236,604 lines, LogPAI's own CUHK lab cluster."""

    name = "spark"
    source_url = ZENODO
    version = "Spark (loghub 2023 release)"
    license = licenses.SPARK
    log_format = "<Date> <Time> <Level> <Component>: <Content>"
    default_path = "Spark.log"
    severities = ("INFO", "WARN", "ERROR")
    label_source = None
    """Genuinely unlabelled -- loghub ships Spark as-is, mixing normal and
    abnormal runs with no label file, column, or inline tag."""

    _RE = re.compile(
        r"^(?P<date>\d{2}/\d{2}/\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s+"
        r"(?P<level>[A-Z]+)\s+(?P<component>[^:]+):\s*(?P<content>.*)$"
    )

    def parse_line(self, line: str) -> CorpusRecord | None:
        m = self._RE.match(line)
        if not m:
            return None
        return CorpusRecord(
            raw=m["content"],
            timestamp=timestamps.from_slashed_yy(m["date"], m["time"]),
            severity=normalise_severity(m["level"]),
            location=LocationId(path=self.default_path, service=m["component"]),
            label=None,
            extra={},
        )


class HadoopAdapter(DatasetAdapter):
    """Hadoop -- 48.61 MiB, 394,308 lines, lab cluster with injected failures.

    Ships as a tree of ``application_*/container_*`` files rather than one blob,
    so ``for_file`` matters here: without it every row would claim the same
    ``LocationId.path`` and the application a line came from would be lost.
    """

    name = "hadoop"
    source_url = ZENODO
    version = "Hadoop (loghub 2023 release)"
    license = licenses.HADOOP
    log_format = "<Date> <Time> <Level> [<Process>] <Component>: <Content>"
    default_path = "Hadoop.log"
    severities = ("INFO", "WARN", "ERROR", "FATAL")
    label_source = "file:abnormal_label.txt keyed by application id"
    """NOT on the line and NOT per container: ``abnormal_label.txt`` labels each
    ``application_*`` directory as Normal / Machine down / Network disconnection
    / Disk full. The join key is the directory name, which is why ``for_file``
    matters for this dataset."""

    _RE = re.compile(
        r"^(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2},\d+)\s+"
        r"(?P<level>[A-Z]+)\s+\[(?P<process>[^\]]*)\]\s+"
        r"(?P<component>[^:\s]+):\s*(?P<content>.*)$"
    )

    def parse_line(self, line: str) -> CorpusRecord | None:
        m = self._RE.match(line)
        if not m:
            return None
        return CorpusRecord(
            raw=m["content"],
            timestamp=timestamps.from_iso_like(m["date"], m["time"]),
            severity=normalise_severity(m["level"]),
            location=LocationId(path=self.default_path, service=m["component"]),
            label=None,
            extra={"process": m["process"]},
        )
