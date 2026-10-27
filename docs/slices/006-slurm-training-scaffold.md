# 006 — SLURM training scaffold

**Date:** 2026-10-27
**Status:** In progress. Built and tested locally; the cluster smoke run and the vLLM version pin need a session on WATcloud.
**Touches:** `packages/planner-rl` (`planner_rl.train`, `slurm` CLI group)
**Source of truth:** §6 (post-training stack, "every training run must checkpoint and resume")
**Decisions:** [0005](../decisions/0005-grpo-primary-prime-ablation.md), [0006](../decisions/0006-qwen3-base-models.md)
**Depends on:** nothing (parallel with 002–005)

## What a person can now do

Render an sbatch script with WATcloud-correct defaults, stage a shared HF cache onto node-local scratch, and run a trainer-shaped smoke job. The smoke job checkpoints, catches the pre-timeout signal, requeues itself and resumes to an identical result.

```bash
uv run planner-rl slurm prefetch Qwen/Qwen3.5-0.8B --cache /path/to/shared/hf      # login node
uv run planner-rl slurm render --name smoke --run-id smoke-1 --out jobs/smoke.sbatch \
    --gpus 0 --time 00:10:00 -- uv run planner-rl slurm smoke --run-id smoke-1
uv run planner-rl slurm render ... --submit                                         # only with --submit
uv run planner-rl slurm env-check                                                   # on a GPU node: torch/CUDA/vLLM/GPUs
```

## How it works

- **`runs.RunDir`**: `runs/<run_id>/` holds a frozen `config.json` (a resume with a different config is refused), an fsync'd `events.jsonl` (start, resume, metrics, checkpoint, stop; each line carries git SHA, dirty flag and SLURM job/restart IDs), and `checkpoints/`. A checkpoint is written to `step-N.partial`, renamed, then `LATEST` is flipped, so a job killed mid-save never leaves a half checkpoint as latest. Partials are swept on the next start.
- **`preempt`**: the sbatch has `--signal=USR1@300 --requeue`. The Python step sees `StopFlag.requested`, checkpoints, and calls `scontrol requeue`.
- **`slurm`**: pure `render(JobSpec)`. Defaults follow WATcloud's docs: partition `compute` (1 day max; `compute_dense` for 7 days), `gpu:rtx_3090:N`, and `tmpdisk` GRES for node-local `/tmp`. `submit()` runs only on `--submit`.
- **`hf_cache`**: prefetch on the login node, then at job start copy to `/tmp/hf`, preserving the hub's symlink layout, and set `HF_HUB_OFFLINE=1`. A missing file then fails at startup instead of downloading on a compute node.
- **`smoke`**: the outer loop every real trainer in 007–010 will share, with a toy deterministic state so that "resumed correctly" is checkable.

## Deliberately not in this slice

- **The vLLM pin is not done.** Decision 0006 makes it the highest-priority unknown (Qwen3.5 was reported unsupported on vLLM 0.16.0). It has to be found on a real 3090 node: install candidates, run `slurm env-check`, and load Qwen3.5-0.8B in vLLM. That cannot be done from a laptop. **Slice 008 must not start until it is.**
- **No training dependencies installed.** torch, vllm, unsloth and trl are left out of the package on purpose. The `train` extra only adds `huggingface_hub`. The right versions are the output of the pin above, not a guess written now.
- **No shared-storage path baked in.** WATcloud's docs don't name one for datasets or caches, so `--hf-cache` is required whenever staging is used.
- **No job arrays, no multi-node, no sweep launcher.** Slice 007's sweep will show which of these is needed.
- **Whole GPUs (`gpu:`), not `shard:`.** WATcloud prefers shards for small jobs, but training and rollouts need whole cards.

## Decisions made here

None. These are WATcloud's documented conventions plus the checkpointing requirement already in §6.

## Friction observed

None yet, since this has not been run on the cluster.

## What this unlocks

Slice 007 (SFT) once the cluster checklist below is done:

1. Submit the smoke job with `--time 00:10:00` and `--steps 900 --step-seconds 1`: the signal fires 5 min in (300 s lead), so it must requeue at least once. Confirm it is signalled, requeues, and finishes with `acc == 405450` (sum of 1..900) in `events.jsonl`.
2. On a `trpro-slurm1` GPU job, find a vLLM version that serves Qwen3.5-0.8B; record it with `env-check` output in a decision record. Otherwise fall back to Unsloth rollouts per 0006.
