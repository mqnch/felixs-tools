"""Task-type taxonomy for Router decision policy."""

from enum import StrEnum


class TaskType(StrEnum):
    """Caller-tagged task types. Router maps these to backends/policy."""

    LOG_QUERY_PLANNING = "log_query_planning"
    ANOMALY_SCORING = "anomaly_scoring"
    SWARM_REASONING = "swarm_reasoning"
    GENERAL = "general"
