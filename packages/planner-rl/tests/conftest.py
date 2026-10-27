from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from common import LocationId
from logger.index import LogIndex
from logger.parser import LogParser

_SHAPES = [
    ("INFO", "dfs.DataNode$PacketResponder", "PacketResponder {n} for block blk_{b} terminating"),
    ("INFO", "dfs.DataNode$DataXceiver", "Receiving block blk_{b} src: /10.250.{n}.7:54106 dest: /10.250.{n}.7:50010"),
    ("INFO", "dfs.FSDataset", "Deleting block blk_{b} file /mnt/hadoop/dfs/data/current/subdir{n}/blk_{b}"),
    ("WARN", "dfs.DataNode", "Slow BlockReceiver write packet to mirror took {n}ms"),
    ("ERROR", "dfs.DataNode$DataXceiver", "writeBlock blk_{b} received exception java.io.IOException: Connection reset by peer"),
    ("ERROR", "dfs.FSNamesystem", "Redundant addStoredBlock request received for blk_{b} on 10.251.{n}.85:50010"),
    ("INFO", "dfs.FSNamesystem", "BLOCK* NameSystem.allocateBlock: /user/root/rand/_temporary/part-{n}. blk_{b}"),
    ("WARN", "dfs.FSNamesystem", "BLOCK* NameSystem.delete: blk_{b} is added to invalidSet of 10.251.{n}.85:50010"),
]

CORPUS_ROWS = 900
START = datetime(2008, 11, 9, 20, 0, tzinfo=timezone.utc)


def build_corpus(path: Path, rows: int = CORPUS_ROWS, seed: int = 7) -> Path:
    rng = random.Random(seed)
    parser = LogParser()
    index = LogIndex(path)
    for i in range(rows):
        severity, component, text = rng.choices(_SHAPES, weights=[6, 6, 4, 2, 1, 1, 3, 2])[0]
        line = text.format(n=rng.randint(1, 40), b=rng.randint(10**15, 10**16))
        stamp = START + timedelta(seconds=40 * i)
        index.ingest(
            parser.parse(f"{severity} {component}: {line}"),
            location=LocationId(path="hdfs/HDFS.log", service=component),
            severity=severity,
            timestamp=stamp.isoformat(),
        )
    index.close()
    return path


@pytest.fixture(scope="session")
def corpus_db(tmp_path_factory) -> Path:
    return build_corpus(tmp_path_factory.mktemp("corpus") / "hdfs.db")
