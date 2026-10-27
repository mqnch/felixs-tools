"""Pre-timeout checkpoint-and-requeue.

The sbatch template asks SLURM to send SIGUSR1 a few minutes before the time
limit (`--signal=USR1@<s>`). The trainer polls `StopFlag.requested` between
steps; on True it checkpoints, then calls `requeue()`, which puts the same job
back in the queue. The requeued job starts the same run_id and resumes.
"""

from __future__ import annotations

import os
import signal
import subprocess


class StopFlag:
    def __init__(self, signals: tuple[int, ...] = (signal.SIGUSR1, signal.SIGTERM)) -> None:
        self.requested = False
        self.signal: int | None = None
        for sig in signals:
            signal.signal(sig, self._handle)

    def _handle(self, signum, _frame) -> None:
        self.requested = True
        self.signal = signum


def requeue() -> bool:
    """Requeue this SLURM job. Returns False outside SLURM or if scontrol fails."""
    job_id = os.environ.get("SLURM_JOB_ID")
    if not job_id:
        return False
    try:
        subprocess.run(["scontrol", "requeue", job_id], check=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True
