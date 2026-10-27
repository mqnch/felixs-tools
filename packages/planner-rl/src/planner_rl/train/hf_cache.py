"""Hugging Face cache staging.

Two steps, on two machines:

1. **Prefetch** on a node with internet (login node) into a persistent shared
   cache: `planner-rl slurm prefetch Qwen/Qwen3.5-2B --cache /shared/hf`.
2. **Stage** at job start, from the shared cache onto node-local scratch
   (WATcloud mounts the `tmpdisk` GRES at `/tmp`), then run fully offline.

Reading model weights from a network filesystem on every step of a rollout
server is the slow path; offline mode makes a missing file fail loudly at
startup instead of silently downloading on a compute node.
"""

from __future__ import annotations

import shutil
from pathlib import Path


def prefetch(repo_id: str, *, cache_dir: str | Path, revision: str | None = None) -> Path:
    """Download a model snapshot into the shared cache. Needs the `train` extra."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:  # pragma: no cover - exercised only on the cluster
        raise RuntimeError("prefetch needs huggingface_hub: uv sync --extra train") from exc
    return Path(
        snapshot_download(repo_id=repo_id, revision=revision, cache_dir=str(Path(cache_dir) / "hub"))
    )


def stage(src: str | Path, dst: str | Path) -> int:
    """Copy a cache tree to local scratch, skipping files already present at the same size.

    Symlinks (the hub cache's snapshot → blob layout) are copied as symlinks,
    so the staged tree is a valid hub cache. Returns bytes copied.
    """
    src, dst = Path(src), Path(dst)
    if not src.is_dir():
        raise FileNotFoundError(f"shared HF cache not found: {src}")
    copied = 0
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        target = dst / rel
        if path.is_symlink():
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink() or target.exists():
                target.unlink()
            target.symlink_to(path.readlink())
        elif path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            if target.exists() and target.stat().st_size == path.stat().st_size:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied += path.stat().st_size
    return copied


def offline_env(hf_home: str | Path) -> dict[str, str]:
    """Environment for a job reading only from the staged cache."""
    home = str(hf_home)
    return {
        "HF_HOME": home,
        "HF_HUB_CACHE": str(Path(home) / "hub"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }
