"""Verbatim sample lines from each loghub dataset, for corpus tests.

Every line below is copied unmodified from that dataset's ``*_2k.log`` sample in
the loghub repo. Keeping them inline is deliberate: the real datasets run from
60 MB to 30 GB, and a test suite that downloads them is a test suite nobody runs.

Not a ``test_*`` module, so pytest imports it rather than collecting it.
"""

from __future__ import annotations

HDFS_LINES = [
    "081109 203615 148 INFO dfs.DataNode$PacketResponder: PacketResponder 1 for block blk_38865049064139660 terminating",
    "081109 204005 35 INFO dfs.FSNamesystem: BLOCK* NameSystem.addStoredBlock: blockMap updated: 10.251.73.220:50010 is added to blk_7128370237687728475 size 67108864",
    "081109 204324 34 WARN dfs.FSNamesystem: BLOCK* NameSystem.addStoredBlock: Redundant addStoredBlock request received for blk_-3544583377289625738 on 10.251.31.85:50010 size 67108864",
]

BGL_LINES = [
    "- 1117838570 2005.06.03 R02-M1-N0-C:J12-U11 2005-06-03-15.42.50.675872 R02-M1-N0-C:J12-U11 RAS KERNEL INFO instruction cache parity error corrected",
    "KERNDTLB 1117886453 2005.06.04 R04-M1-N4-C:J09-U01 2005-06-04-05.00.53.739069 R04-M1-N4-C:J09-U01 RAS KERNEL FATAL data TLB error interrupt",
]

THUNDERBIRD_LINES = [
    "- 1131566461 2005.11.09 dn228 Nov 9 12:01:01 dn228/dn228 crond(pam_unix)[2915]: session closed for user root",
    "- 1131566461 2005.11.09 dn228 Nov 9 12:01:01 dn228/dn228 crond[2916]: (root) CMD (run-parts /etc/cron.hourly)",
]

OPENSTACK_LINES = [
    'nova-api.log.1.2017-05-16_13:53:08 2017-05-16 00:00:00.008 25746 INFO nova.osapi_compute.wsgi.server [req-38101a0b-2096-447d-96ea-a692162415ae 113d3a99c3da401fbd62cc2caa5b96d2 54fadb412c4e40cdbaed9335e4c35a9e - - -] 10.11.10.1 "GET /v2/54fadb412c4e40cdbaed9335e4c35a9e/servers/detail HTTP/1.1" status: 200 len: 1893 time: 0.2477829',
]

SPARK_LINES = [
    "17/06/09 20:10:40 INFO executor.CoarseGrainedExecutorBackend: Registered signal handlers for [TERM, HUP, INT]",
    "17/06/09 20:10:40 INFO spark.SecurityManager: Changing view acls to: yarn,curi",
]

HADOOP_LINES = [
    "2015-10-18 18:01:47,978 INFO [main] org.apache.hadoop.mapreduce.v2.app.MRAppMaster: Created MRAppMaster for application appattempt_1445144423722_0020_000001",
    "2015-10-18 18:03:39,838 WARN [main] org.apache.hadoop.mapreduce.v2.app.MRAppMaster: Error while parsing",
]

ALL_FIXTURES = {
    "hdfs": HDFS_LINES,
    "bgl": BGL_LINES,
    "thunderbird": THUNDERBIRD_LINES,
    "openstack": OPENSTACK_LINES,
    "spark": SPARK_LINES,
    "hadoop": HADOOP_LINES,
}


# ---------------------------------------------------------------------------
# Sample-vs-full traps.
#
# The *_2k.log samples are not representative. Each line below appears in the
# real dataset but NOT in that dataset's sample, so an adapter validated only
# against the sample passes while being wrong on the full file. Verbatim.
# ---------------------------------------------------------------------------

# BGL: 316 real lines omit <NodeRepeat> entirely (and carry Node="-").
# Positional splitting silently yields component="FATAL", level="Kill".
BGL_MISSING_NODEREPEAT = (
    "- 1119415930 2005.06.21 - 2005-06-21-21.52.10.214285 RAS KERNEL FATAL "
    "Kill job 20251 timed out. Block freed."
)

# BGL: Node/NodeRepeat can be the literal string NULL.
BGL_NULL_NODE = (
    "- 1123110662 2005.08.03 NULL 2005-08-03-16.11.02.839771 NULL RAS MMCS ERROR "
    "idoproxydb hit ASSERT condition: ASSERT expression=0"
)

# Thunderbird: the 2k sample is 100% "-", so it contains no alert-tagged line
# at all. It also has program tags containing spaces and no PID.
THUNDERBIRD_ALERT_LINES = [
    "VAPI 1131685687 2005.11.10 bn257 Nov 10 21:08:07 bn257/bn257 kernel: [KERNEL_IB][tsIbTavorMadProcess]InfiniHost0: EVAPI_process_local_mad failed, return code = -254",
    "ECC 1131674844 2005.11.10 cn994 Nov 10 18:07:24 cn994/cn994 Server Administrator: Instrumentation Service EventID: 1404 Memory device status is critical",
]

# Spark: the 2k sample is 100% INFO -- neither WARN nor ERROR appears in it.
SPARK_NON_INFO_LINES = [
    "16/04/07 10:46:31 WARN executor.CoarseGrainedExecutorBackend: An unknown (mesos-slave-24:43670) driver disconnected.",
    "15/09/01 18:19:50 ERROR executor.CoarseGrainedExecutorBackend: Driver 10.10.18.32:65488 disassociated! Shutting down.",
]

# Spark/Hadoop: Java stack-trace continuations. 17.5% of the real Spark file and
# 54.1% of the real Hadoop file; ZERO of either 2k sample.
CONTINUATION_LINES = [
    "\tat sun.nio.ch.SocketDispatcher.read0(Native Method)",
    "Caused by: java.net.NoRouteToHostException: No route to host",
    "\t... 14 more",
]

# OpenStack: 184 traceback lines repeat the full prefix but omit the [<ADDR>].
OPENSTACK_TRACEBACK_LINE = (
    "nova-compute.log.1.2017-05-17_12:02:35 2017-05-16 16:30:35.360 2931 ERROR "
    "oslo_service.periodic_task Traceback (most recent call last):"
)

# OpenStack: the instance UUID that anomaly_labels.txt keys on.
OPENSTACK_INSTANCE_LINE = (
    "nova-compute.log.1.2017-05-16_13:55:31 2017-05-16 00:00:04.500 2931 INFO "
    "nova.compute.manager [req-3ea4052c-895d-4b64-9e2d-04d64c4d94ab - - - - -] "
    "[instance: b9000564-fe1a-409b-b8cc-1e88b294cd1d] VM Started (Lifecycle Event)"
)

# Hadoop: thread names contain spaces, colons, '#' and '@'.
HADOOP_COMPLEX_THREAD_LINE = (
    "2015-10-18 18:05:27,570 WARN [LeaseRenewer:msrabi@msra-sa-41:9000] "
    "org.apache.hadoop.ipc.Client: Address change detected. Old: msra-sa-41/10.190.173.170:9000"
)
