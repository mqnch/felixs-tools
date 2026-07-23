"""Drain-style log templating. Classical, model-free."""

from __future__ import annotations

from dataclasses import dataclass

from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig


@dataclass(frozen=True)
class ParsedLine:
    raw: str
    template: str
    template_id: int
    parameters: list[str]


class LogParser:
    """Cluster raw log lines into templates via drain3."""

    def __init__(self) -> None:
        config = TemplateMinerConfig()
        config.profiling_enabled = False
        self._miner = TemplateMiner(config=config)

    def parse(self, line: str) -> ParsedLine:
        result = self._miner.add_log_message(line.rstrip("\n"))
        return ParsedLine(
            raw=line.rstrip("\n"),
            template=str(result["template_mined"]),
            template_id=int(result["cluster_id"]),
            parameters=[str(p) for p in result.get("parameter_list", [])],
        )
