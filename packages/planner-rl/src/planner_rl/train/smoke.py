"""A trainer-shaped job with no model, to prove checkpoint/resume/requeue end to end.

Every real trainer in slices 007-010 has the same outer loop as this one:
start the run, resume from LATEST, step, checkpoint every k steps, and on a
stop signal checkpoint-then-requeue. Proving that loop on the cluster with a
toy state is minutes of queue time; finding it broken inside a GRPO run is
a lost day.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from planner_rl.train.preempt import StopFlag, requeue
from planner_rl.train.runs import RunDir


def run_smoke(
    *,
    runs_root: str | Path,
    run_id: str,
    total_steps: int,
    checkpoint_every: int,
    step_seconds: float = 0.0,
    stop_after: int | None = None,
) -> int:
    """Return the step reached. `stop_after` simulates a preemption, for tests."""
    run = RunDir(runs_root, run_id)
    config = {"kind": "smoke", "total_steps": total_steps, "checkpoint_every": checkpoint_every}
    latest = run.start(config)
    state = json.loads((latest.path / "state.json").read_text()) if latest else {"step": 0, "acc": 0}
    flag = StopFlag()
    taken = 0

    def save(path: Path) -> None:
        (path / "state.json").write_text(json.dumps(state))

    while state["step"] < total_steps:
        state["step"] += 1
        state["acc"] += state["step"]  # deterministic, so a resume is checkable
        taken += 1
        if step_seconds:
            time.sleep(step_seconds)
        if state["step"] % checkpoint_every == 0:
            run.save_checkpoint(state["step"], save)
            run.log("metrics", step=state["step"], acc=state["acc"])
        if flag.requested or (stop_after is not None and taken >= stop_after):
            run.save_checkpoint(state["step"], save)
            requeued = requeue()
            run.log("stop", step=state["step"], signal=flag.signal, requeued=requeued)
            return state["step"]

    run.log("done", step=state["step"], acc=state["acc"])
    return state["step"]
