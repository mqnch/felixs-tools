"""Run directories: config snapshot, append-only event log, checkpoints, resume.

Every training run checkpoints and resumes from the first slice onward — SLURM
time limits make that a correctness requirement (source of truth §6). The
layout is framework-agnostic; a trainer supplies a `save(path)` callback and
reads back whatever it wrote.

    runs/<run_id>/
        config.json          frozen at first start; a resume with a different config is refused
        events.jsonl         one JSON object per line: start, resume, metrics, checkpoint, stop
        checkpoints/step-000120/
        checkpoints/LATEST   name of the newest *complete* checkpoint
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from logger import timeutil

_STEP_WIDTH = 6


@dataclass(frozen=True)
class Checkpoint:
    step: int
    path: Path


class ConfigMismatch(RuntimeError):
    """A resume was attempted with a config that differs from the frozen one."""


class RunDir:
    def __init__(self, root: str | Path, run_id: str) -> None:
        self.path = Path(root) / run_id
        self.run_id = run_id
        self.checkpoints = self.path / "checkpoints"
        self._events = self.path / "events.jsonl"

    # --- lifecycle -------------------------------------------------------------

    def start(self, config: dict[str, Any]) -> Checkpoint | None:
        """Create or reopen the run. Returns the checkpoint to resume from, if any."""
        self.checkpoints.mkdir(parents=True, exist_ok=True)
        config_path = self.path / "config.json"
        frozen = json.dumps(config, indent=2, sort_keys=True) + "\n"
        if config_path.exists():
            if config_path.read_text() != frozen:
                raise ConfigMismatch(
                    f"{config_path} differs from the config passed to this resume; "
                    "start a new run_id instead of mutating a run mid-flight"
                )
        else:
            config_path.write_text(frozen)
        self._sweep_partial()
        latest = self.latest_checkpoint()
        self.log(
            "resume" if latest else "start",
            step=latest.step if latest else 0,
            **_provenance(),
        )
        return latest

    def log(self, event: str, **fields: Any) -> None:
        record = {"t": timeutil.canonical(timeutil.utcnow()), "event": event, **fields}
        with self._events.open("a") as fh:
            fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def events(self) -> list[dict[str, Any]]:
        if not self._events.exists():
            return []
        return [json.loads(line) for line in self._events.open() if line.strip()]

    # --- checkpoints -----------------------------------------------------------

    def save_checkpoint(self, step: int, save: Callable[[Path], None], *, keep: int = 2) -> Checkpoint:
        """Write a checkpoint atomically: into a temp dir, then rename, then flip LATEST.

        A job killed mid-save leaves a `.partial` directory that the next
        `start()` sweeps away; LATEST only ever names a complete checkpoint.
        """
        name = f"step-{step:0{_STEP_WIDTH}d}"
        final = self.checkpoints / name
        tmp = self.checkpoints / f"{name}.partial"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        save(tmp)
        if final.exists():
            shutil.rmtree(final)
        tmp.rename(final)
        pointer_tmp = self.checkpoints / "LATEST.tmp"
        pointer_tmp.write_text(name + "\n")
        pointer_tmp.replace(self.checkpoints / "LATEST")
        self.log("checkpoint", step=step, path=str(final))
        self._prune(keep)
        return Checkpoint(step=step, path=final)

    def latest_checkpoint(self) -> Checkpoint | None:
        pointer = self.checkpoints / "LATEST"
        if not pointer.exists():
            return None
        name = pointer.read_text().strip()
        path = self.checkpoints / name
        if not path.is_dir():
            return None
        return Checkpoint(step=int(name.removeprefix("step-")), path=path)

    def _complete(self) -> list[Checkpoint]:
        found = []
        for p in self.checkpoints.glob("step-*"):
            if p.is_dir() and not p.name.endswith(".partial"):
                found.append(Checkpoint(step=int(p.name.removeprefix("step-")), path=p))
        return sorted(found, key=lambda c: c.step)

    def _prune(self, keep: int) -> None:
        latest = self.latest_checkpoint()
        for ckpt in self._complete()[:-keep] if keep > 0 else []:
            if latest is None or ckpt.path != latest.path:
                shutil.rmtree(ckpt.path)

    def _sweep_partial(self) -> None:
        for p in self.checkpoints.glob("*.partial"):
            shutil.rmtree(p)


def _provenance() -> dict[str, Any]:
    """Git state and SLURM identity, so every event line is attributable."""
    info: dict[str, Any] = {
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "slurm_restart_count": os.environ.get("SLURM_RESTART_COUNT"),
        "host": os.uname().nodename,
    }
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
            ).stdout.strip()
        )
        info.update(git_sha=sha, git_dirty=dirty)
    except (OSError, subprocess.CalledProcessError):
        info.update(git_sha=None, git_dirty=None)
    return info
