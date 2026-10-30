"""Stock-model baselines on the cluster: one job, one GPU, the models in turn (decision 0021).

For each model the driver starts `vllm serve`, waits for `/v1/models`, runs
`planner-rl eval` against it, then stops the server. It is safe to requeue:
a model whose final results file exists is skipped, and an interrupted eval
resumes from its `.partial.jsonl`. On the pre-timeout SIGUSR1 the driver
stops vLLM and requeues the job itself, as `preempt.requeue` does for trainers.

vLLM runs from its own virtualenv (`--vllm-bin`) so its pinned torch never
touches the workspace environment `planner-rl eval` runs in.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

STOCK_MODELS = ("Qwen/Qwen3.5-0.8B", "Qwen/Qwen3.5-2B", "Qwen/Qwen3.5-4B")
DATA_DIRS = ("data/full/hadoop-50k", "data/full/bgl-20k", "data/full/openstack-20k")


@dataclass(frozen=True)
class BaselineSpec:
    models: tuple[str, ...] = STOCK_MODELS
    data_dirs: tuple[str, ...] = DATA_DIRS
    results_dir: str = "results"
    split: str = "test"
    port: int = 8000
    vllm_bin: str = "vllm"
    # Hadoop's prompt is ~5k tokens and replies are capped at 1024; 16k leaves
    # room and keeps the KV cache small on a 24 GB card.
    max_model_len: int = 16384
    ready_timeout_s: int = 1200
    concurrency: int = 16
    vllm_args: tuple[str, ...] = field(default_factory=tuple)


def results_path(spec: BaselineSpec, model: str) -> str:
    return f"{spec.results_dir}/stock-{model.rsplit('/', 1)[-1].lower()}.json"


def driver_script(spec: BaselineSpec) -> str:
    """Bash run as the job step. Pure: rendering it has no side effects."""
    q = shlex.quote
    data = " ".join(f"--data {q(d)}" for d in spec.data_dirs)
    extra = " ".join(q(a) for a in spec.vllm_args)
    out = [
        "#!/bin/bash",
        "# Rendered by `planner-rl slurm eval-baselines`; edit the options, not this file.",
        "set -euo pipefail",
        f"PORT={spec.port}",
        "VLLM_PID=",
        "EVAL_PID=",
        "",
        "stop_vllm() {",
        '  if [ -n "$VLLM_PID" ] && kill -0 "$VLLM_PID" 2>/dev/null; then',
        '    kill "$VLLM_PID"; wait "$VLLM_PID" 2>/dev/null || true',
        "  fi",
        "  VLLM_PID=",
        "}",
        "",
        "# Pre-timeout signal: stop the server and requeue; finished results stay,",
        "# an interrupted eval resumes from its .partial.jsonl.",
        "on_usr1() {",
        '  echo "SIGUSR1: stopping vLLM and requeueing job ${SLURM_JOB_ID:-?}"',
        '  [ -n "$EVAL_PID" ] && kill "$EVAL_PID" 2>/dev/null || true',
        "  stop_vllm",
        '  [ -n "${SLURM_JOB_ID:-}" ] && scontrol requeue "$SLURM_JOB_ID"',
        "  exit 0",
        "}",
        "trap on_usr1 USR1",
        "trap stop_vllm EXIT",
        "",
        "wait_ready() {",
        f"  local deadline=$((SECONDS + {spec.ready_timeout_s}))",
        '  until curl -sf "http://127.0.0.1:${PORT}/v1/models" >/dev/null; do',
        '    if ! kill -0 "$VLLM_PID" 2>/dev/null; then echo "vLLM exited before it was ready"; return 1; fi',
        '    if [ "$SECONDS" -ge "$deadline" ]; then echo "vLLM not ready after ' + str(spec.ready_timeout_s) + 's"; return 1; fi',
        "    sleep 10",
        "  done",
        "}",
        "",
        f"mkdir -p {q(spec.results_dir)} logs/slurm",
        f'{q(spec.vllm_bin)} --version || echo "vllm --version failed"',
    ]
    for model in spec.models:
        result = results_path(spec, model)
        log = f"logs/slurm/vllm-{model.rsplit('/', 1)[-1].lower()}-${{SLURM_JOB_ID:-local}}.log"
        out += [
            "",
            f"# --- {model}",
            f"if [ -f {q(result)} ]; then",
            f'  echo "skip {model}: {result} exists"',
            "else",
            f"  {q(spec.vllm_bin)} serve {q(model)} --served-model-name {q(model)} --port \"$PORT\" "
            f"--host 127.0.0.1 --max-model-len {spec.max_model_len} --dtype bfloat16"
            + (f" {extra}" if extra else "")
            + f' > "{log}" 2>&1 &',
            "  VLLM_PID=$!",
            f'  wait_ready || {{ tail -n 50 "{log}"; exit 1; }}',
            f"  uv run planner-rl eval {data} --split {q(spec.split)} --model {q(model)} "
            f'--base-url "http://127.0.0.1:${{PORT}}/v1" --concurrency {spec.concurrency} --out {q(result)} &',
            # Waiting on a background child lets the USR1 trap run mid-eval.
            "  EVAL_PID=$!",
            '  wait "$EVAL_PID"',
            "  EVAL_PID=",
            "  stop_vllm",
            "fi",
        ]
    out.append("")
    return "\n".join(out)
