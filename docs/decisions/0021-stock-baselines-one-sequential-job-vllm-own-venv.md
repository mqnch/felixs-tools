# 0021 — Stock baselines run as one sequential single-GPU job, with vLLM in its own virtualenv

**Date:** 2026-10-30
**Status:** Accepted
**Affects:** `packages/planner-rl` (`train.baselines`, `slurm eval-baselines`)
**Slice:** [005](../slices/005-eval-harness-and-baselines.md), [006](../slices/006-slurm-training-scaffold.md)

## Context

Slice 005's gate needs stock Qwen3.5 0.8B, 2B and 4B scored on the cluster ([0019](0019-qwen-9b-upper-bound-for-the-gate.md)). The eval harness only needs an OpenAI-compatible server, so the job is: serve a model with vLLM, run `planner-rl eval` against it, repeat. vLLM's version isn't pinned yet (slice 006), and it pins its own torch.

## Decision

- **One job, one GPU, the three models in sequence.** A rendered bash driver starts `vllm serve` and waits for `/v1/models`, runs `eval`, then stops the server. A model whose results file exists is skipped. On the pre-timeout SIGUSR1 the driver stops everything and runs `scontrol requeue`, and an interrupted eval resumes from its partial file.
- **vLLM runs from a separate virtualenv** given by `--vllm-bin`. `planner-rl eval` runs in the workspace env, and the two talk only over HTTP.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| One job per model / a job array | Three GPUs on the one 4×3090 node for an hour of work, three jobs to watch, and three requeue paths. Each model's eval is short, so running in parallel saves little. Slice 006 also deferred arrays until a sweep needs them |
| A Python driver command instead of bash | Can't run without the cluster anyway. A bash driver is readable in one `cat` and editable in place when a vLLM flag turns out to be needed |
| vLLM in the workspace env (`--extra train`) | vLLM pins torch and CUDA wheels. Putting it in the lockfile before the version is pinned would make every `uv sync` resolve a GPU stack, including on the laptop |
| Hand-written sbatch file | Would drift from `JobSpec`'s WATcloud defaults and the HF-cache staging the other jobs share |

## Consequences

- The driver was exercised locally against a fake `vllm` (serve, readiness, full eval, stop, skip on rerun, SIGUSR1 mid-eval, then resume). Real vLLM behaviour on a 3090 is untested until the cluster session.
- Slices 007–008 will need vLLM importable next to the trainer. The pin found here decides whether the separate env stays or vLLM joins the `train` extra.

## Reversal trigger

The baselines grow past ~3 models or a few hours (then use arrays), or the pinned vLLM installs cleanly into the `train` extra (then drop `--vllm-bin`).
