from __future__ import annotations

import json
from pathlib import Path

import pytest

from planner_rl.train import hf_cache, slurm
from planner_rl.train.runs import ConfigMismatch, RunDir
from planner_rl.train.smoke import run_smoke


def _write(value: str):
    def save(path: Path) -> None:
        (path / "state.txt").write_text(value)

    return save


def test_fresh_run_has_nothing_to_resume(tmp_path):
    run = RunDir(tmp_path, "r1")
    assert run.start({"lr": 1e-4}) is None
    assert [e["event"] for e in run.events()] == ["start"]


def test_resume_returns_latest_complete_checkpoint(tmp_path):
    run = RunDir(tmp_path, "r1")
    run.start({"lr": 1e-4})
    run.save_checkpoint(10, _write("a"))
    run.save_checkpoint(20, _write("b"))

    reopened = RunDir(tmp_path, "r1")
    latest = reopened.start({"lr": 1e-4})
    assert latest is not None and latest.step == 20
    assert (latest.path / "state.txt").read_text() == "b"
    assert reopened.events()[-1]["event"] == "resume"


def test_a_save_killed_midway_never_becomes_latest(tmp_path):
    run = RunDir(tmp_path, "r1")
    run.start({})
    run.save_checkpoint(10, _write("good"))

    def crash(path: Path) -> None:
        (path / "half").write_text("x")
        raise KeyboardInterrupt  # SIGKILL stand-in: the save never finishes

    with pytest.raises(KeyboardInterrupt):
        run.save_checkpoint(20, crash)

    latest = RunDir(tmp_path, "r1").start({})
    assert latest is not None and latest.step == 10
    assert not list(run.checkpoints.glob("*.partial"))  # swept on start


def test_resume_with_changed_config_is_refused(tmp_path):
    RunDir(tmp_path, "r1").start({"lr": 1e-4})
    with pytest.raises(ConfigMismatch):
        RunDir(tmp_path, "r1").start({"lr": 3e-4})


def test_old_checkpoints_are_pruned(tmp_path):
    run = RunDir(tmp_path, "r1")
    run.start({})
    for step in (1, 2, 3, 4):
        run.save_checkpoint(step, _write(str(step)), keep=2)
    assert sorted(p.name for p in run.checkpoints.glob("step-*")) == ["step-000003", "step-000004"]


def test_smoke_job_survives_preemption_with_identical_result(tmp_path):
    assert run_smoke(runs_root=tmp_path, run_id="s", total_steps=50, checkpoint_every=7, stop_after=23) == 23
    assert run_smoke(runs_root=tmp_path, run_id="s", total_steps=50, checkpoint_every=7) == 50

    events = RunDir(tmp_path, "s").events()
    kinds = [e["event"] for e in events]
    assert kinds[0] == "start" and "stop" in kinds and "resume" in kinds
    assert events[-1] == {**events[-1], "event": "done", "step": 50, "acc": sum(range(1, 51))}


def test_sbatch_render_carries_requeue_and_signal(tmp_path):
    spec = slurm.JobSpec(
        name="grpo-2b",
        command=["uv", "run", "planner-rl", "slurm", "smoke", "--run-id", "x"],
        run_id="x",
        workdir="/home/me/felixs-tools",
        shared_hf_cache="/shared/hf",
        gpus=4,
        partition="compute_dense",
        nodelist="trpro-slurm1",
    )
    text = slurm.render(spec)
    assert "#SBATCH --gres=gpu:rtx_3090:4,tmpdisk:40960" in text
    assert "#SBATCH --signal=USR1@300" in text
    assert "#SBATCH --requeue" in text
    assert "#SBATCH --partition=compute_dense" in text
    assert "#SBATCH --nodelist=trpro-slurm1" in text
    assert "export HF_HUB_OFFLINE=1" in text
    assert text.splitlines()[-1].startswith("srun uv run planner-rl slurm smoke")


def test_cpu_only_job_requests_no_gpu():
    spec = slurm.JobSpec(name="data", command=["true"], run_id="x", workdir=".", gpus=0)
    assert "--gres=tmpdisk:40960" in slurm.render(spec)


def test_hf_stage_copies_files_and_preserves_symlinks(tmp_path):
    src = tmp_path / "shared" / "hub" / "models--q"
    (src / "blobs").mkdir(parents=True)
    (src / "snapshots" / "abc").mkdir(parents=True)
    (src / "blobs" / "deadbeef").write_bytes(b"weights")
    (src / "snapshots" / "abc" / "model.safetensors").symlink_to("../../blobs/deadbeef")

    dst = tmp_path / "local"
    assert hf_cache.stage(tmp_path / "shared", dst) == len(b"weights")
    staged = dst / "hub" / "models--q" / "snapshots" / "abc" / "model.safetensors"
    assert staged.is_symlink() and staged.read_bytes() == b"weights"
    assert hf_cache.stage(tmp_path / "shared", dst) == 0  # second stage is a no-op


def test_offline_env_points_hub_cache_under_home():
    env = hf_cache.offline_env("/tmp/hf")
    assert env["HF_HUB_CACHE"] == "/tmp/hf/hub" and env["HF_HUB_OFFLINE"] == "1"
    json.dumps(env)


def test_write_creates_the_log_directory(tmp_path):
    spec = slurm.JobSpec(name="t", command=["true"], run_id="x", workdir=str(tmp_path), gpus=0)
    slurm.write(spec, tmp_path / "job.sbatch")
    assert (tmp_path / "logs" / "slurm").is_dir()
