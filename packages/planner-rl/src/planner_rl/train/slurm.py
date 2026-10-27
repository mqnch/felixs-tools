"""sbatch rendering and (explicitly requested) submission.

Defaults follow WATcloud's documented conventions: partitions `compute`
(1 day max) and `compute_dense` (7 days), whole GPUs as `gpu:rtx_3090:<n>`,
node-local scratch as the `tmpdisk` GRES mounted at `/tmp`.

Rendering is pure and always safe. Submission is a separate call that a person
asks for with `--submit`; nothing here submits on its own.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

LOCAL_SCRATCH = "/tmp"


@dataclass(frozen=True)
class JobSpec:
    name: str
    command: list[str]
    run_id: str
    workdir: str
    shared_hf_cache: str | None = None
    partition: str = "compute"
    gpus: int = 1
    gpu_type: str = "rtx_3090"
    cpus: int = 8
    mem: str = "48G"
    time: str = "1-00:00:00"
    tmpdisk_mib: int = 40_960
    signal_lead_s: int = 300
    log_dir: str = "logs/slurm"
    nodelist: str | None = None
    env: dict[str, str] = field(default_factory=dict)

    def directives(self) -> list[str]:
        gres = [f"tmpdisk:{self.tmpdisk_mib}"]
        if self.gpus > 0:
            gres.insert(0, f"gpu:{self.gpu_type}:{self.gpus}")
        lines = [
            f"--job-name={self.name}",
            f"--partition={self.partition}",
            f"--gres={','.join(gres)}",
            f"--cpus-per-task={self.cpus}",
            f"--mem={self.mem}",
            f"--time={self.time}",
            f"--output={self.log_dir}/%j-%x.out",
            # No "B:" prefix: the signal goes to the job step (the Python
            # process), which checkpoints and requeues itself (preempt.py).
            f"--signal=USR1@{self.signal_lead_s}",
            "--requeue",
            "--open-mode=append",
        ]
        if self.nodelist:
            lines.append(f"--nodelist={self.nodelist}")
        return lines


def render(spec: JobSpec) -> str:
    out = ["#!/bin/bash"]
    out += [f"#SBATCH {d}" for d in spec.directives()]
    out += [
        "",
        "set -euo pipefail",
        f"cd {shlex.quote(spec.workdir)}",
        f"export PLANNER_RL_RUN_ID={shlex.quote(spec.run_id)}",
    ]
    for key, value in sorted(spec.env.items()):
        out.append(f"export {key}={shlex.quote(value)}")
    if spec.shared_hf_cache:
        local = f"{LOCAL_SCRATCH}/hf"
        out += [
            "",
            "# Stage the shared HF cache onto node-local scratch, then run offline.",
            f"uv run planner-rl slurm stage --src {shlex.quote(spec.shared_hf_cache)} --dst {local}",
            f"export HF_HOME={local}",
            f"export HF_HUB_CACHE={local}/hub",
            "export HF_HUB_OFFLINE=1",
            "export TRANSFORMERS_OFFLINE=1",
        ]
    out += [
        "",
        'echo "job=${SLURM_JOB_ID} restart=${SLURM_RESTART_COUNT:-0} host=$(hostname)"',
        # srun so the job step receives --signal; exec-free so set -e still applies.
        "srun " + " ".join(shlex.quote(c) for c in spec.command),
        "",
    ]
    return "\n".join(out)


def write(spec: JobSpec, path: str | Path) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # sbatch does not create the --output directory; a missing one fails the
    # job before it can log anything.
    (Path(spec.workdir) / spec.log_dir).mkdir(parents=True, exist_ok=True)
    dest.write_text(render(spec))
    return dest


def submit(script: str | Path) -> str:
    """Run sbatch on a rendered script. Only call this on an explicit user request."""
    result = subprocess.run(
        ["sbatch", "--parsable", str(script)], capture_output=True, text=True, check=True
    )
    return result.stdout.strip().split(";")[0]
