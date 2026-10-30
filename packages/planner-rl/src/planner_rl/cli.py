"""`planner-rl` CLI: dataset generation and audit (slice 004), eval (slice 005), SLURM scaffold (slice 006)."""

from __future__ import annotations

import importlib
import json
import platform
import shutil
import subprocess
from pathlib import Path

import typer

app = typer.Typer(help="Post-training Logger's query planner")
slurm_app = typer.Typer(help="SLURM training scaffold")
app.add_typer(slurm_app, name="slurm")


# --- slice 004: data -----------------------------------------------------------


@app.command("gen-data")
def gen_data(
    corpus: Path = typer.Option(..., "--corpus", exists=True, dir_okay=False, help="Corpus DB from `felix logger ingest-corpus`"),
    n: int = typer.Option(..., "--n", min=3, help="Target accepted examples across all splits"),
    out: Path = typer.Option(..., "--out", help="Output directory"),
    seed: int | None = typer.Option(None, "--seed"),
    model: str | None = typer.Option(None, "--model", help="Question-authoring model"),
    provider: str = typer.Option("anthropic", "--provider", help="anthropic | openrouter"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plans and gold only; no API calls, no questions"),
) -> None:
    """Reverse-generate (question, gold plan, gold rows) triples with train/val/test splits."""
    from planner_rl.data.author import (
        DEFAULT_MODEL,
        DEFAULT_OPENROUTER_MODEL,
        AnthropicAuthor,
        OpenRouterAuthor,
    )
    from planner_rl.data.pipeline import DEFAULT_SEED, generate_dataset

    if dry_run:
        author = None
    elif provider == "anthropic":
        author = AnthropicAuthor(model or DEFAULT_MODEL)
    elif provider == "openrouter":
        author = OpenRouterAuthor(model or DEFAULT_OPENROUTER_MODEL)
    else:
        raise typer.BadParameter(f"unknown provider {provider!r}", param_hint="--provider")
    last: dict[str, int] = {}

    def progress(split: str, done: int, target: int) -> None:
        step = max(1, target // 20)
        if done == target or done - last.get(split, 0) >= step:
            last[split] = done
            typer.echo(f"  {split}: {done}/{target}")

    manifest = generate_dataset(
        corpus_db=corpus,
        out_dir=out,
        n=n,
        author=author,
        seed=seed if seed is not None else DEFAULT_SEED,
        progress=progress,
    )
    for split, s in manifest.splits.items():
        typer.echo(f"{split}: {s['accepted']}/{s['target']} accepted from {s['attempts']} attempts")
        typer.echo(f"  strata: {json.dumps(s['strata'])}")
        typer.echo(f"  rejections: {json.dumps(s['rejections'])}")
    typer.echo(f"manifest: {out / 'manifest.json'}")


@app.command("audit-data")
def audit_data(
    data_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    sample: int = typer.Option(100, "--sample"),
    seed: int = typer.Option(0, "--seed"),
    score: Path | None = typer.Option(None, "--score", exists=True, dir_okay=False, help="Score a filled-in sheet instead"),
) -> None:
    """Write a manual-audit sheet, or score one you have filled in."""
    from planner_rl.data.audit import PASS_THRESHOLD, score_audit_sheet, write_audit_sheet

    if score is None:
        sheet = write_audit_sheet(data_dir, sample=sample, seed=seed, out=data_dir / "audit.csv")
        typer.echo(f"wrote {sheet}; mark natural / answerable / best_plan as y or n, then:")
        typer.echo(f"  planner-rl audit-data {data_dir} --score {sheet}")
        return

    result = score_audit_sheet(score)
    typer.echo(f"judged {result.judged}, unjudged {result.unjudged}")
    for judgment, rate in result.rates.items():
        typer.echo(f"  {judgment}: {rate:.1%}")
    for stratum, rates in result.by_stratum.items():
        typer.echo(f"  [{stratum}] " + "  ".join(f"{k}={v:.0%}" for k, v in rates.items()))
    if result.reversal_trigger:
        typer.echo(
            f"REVERSAL TRIGGER: natural or answerable below {PASS_THRESHOLD:.0%} "
            "(decision 0004) - add a filtering pass before training on this data"
        )
        raise typer.Exit(1)


@app.command("repair-data")
def repair_data(data_dirs: list[Path] = typer.Argument(..., exists=True, file_okay=False)) -> None:
    """Floor absolute time windows to the minute where the question states none (decision 0020)."""
    from planner_rl.data.repair import floor_time_windows

    for data_dir in data_dirs:
        typer.echo(f"{data_dir}:")
        for split, counts in floor_time_windows(data_dir).items():
            strata = counts.pop("strata")
            typer.echo(f"  {split}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
            typer.echo(f"    strata: {json.dumps(strata)}")


# --- slice 005: eval ------------------------------------------------------------


@app.command("eval")
def eval_cmd(
    data: list[Path] = typer.Option(..., "--data", exists=True, file_okay=False, help="gen-data output dir; repeat per corpus"),
    model: str = typer.Option(..., "--model", help="Model name as the server knows it"),
    out: Path = typer.Option(..., "--out", help="Results JSON"),
    split: str = typer.Option("test", "--split"),
    base_url: str | None = typer.Option(None, "--base-url", help="OpenAI-compatible endpoint; default OpenRouter, or --local"),
    local: bool = typer.Option(False, "--local", help="Use a local mlx_lm.server / vLLM at 127.0.0.1:8080"),
    per_corpus: int | None = typer.Option(None, "--per-corpus", help="Seeded sample of N examples per corpus"),
    seed: int | None = typer.Option(None, "--seed"),
    concurrency: int = typer.Option(1, "--concurrency", min=1),
    thinking: bool = typer.Option(False, "--thinking", help="Let the model reason before answering"),
    effort: str | None = typer.Option(None, "--reasoning-effort", help="low | medium | high; implies --thinking"),
    max_tokens: int = typer.Option(1024, "--max-tokens"),
) -> None:
    """Score a planner on a dataset split by executing its plans."""
    from planner_rl.eval.backend import LOCAL_BASE_URL, OPENROUTER_BASE_URL, ChatBackend
    from planner_rl.eval.harness import DEFAULT_SEED, run_eval
    from planner_rl.eval.report import table

    backend = ChatBackend(
        model,
        base_url=base_url or (LOCAL_BASE_URL if local else OPENROUTER_BASE_URL),
        thinking=thinking,
        effort=effort,
        max_tokens=max_tokens,
    )
    last = [0]

    def progress(done: int, total: int) -> None:
        if done == total or done - last[0] >= max(1, total // 20):
            last[0] = done
            typer.echo(f"  {done}/{total}")

    results = run_eval(
        data,
        split=split,
        backend=backend,
        out=out,
        per_corpus=per_corpus,
        seed=seed if seed is not None else DEFAULT_SEED,
        concurrency=concurrency,
        progress=progress,
    )
    typer.echo(table([results]))
    typer.echo(f"results: {out}")


@app.command("rescore")
def rescore_cmd(results: list[Path] = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """Re-score saved model outputs under the current scorer. Makes no model calls."""
    from planner_rl.eval.harness import rescore

    for path in results:
        summary = rescore(path)["summary"]["all"]
        typer.echo(f"{path}: answer {summary['answer']:.3f} (n={summary['n']})")


@app.command("compare")
def compare_cmd(results: list[Path] = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """Side-by-side table of results files, plus the slice-005 difficulty gate."""
    from planner_rl.eval.report import GATE_THRESHOLD, load, over_gate, table

    try:
        loaded = load(results)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(table(loaded))
    hot = over_gate(loaded)
    if hot:
        typer.echo(
            f"\nAt or above the {GATE_THRESHOLD:.2f} gate: {', '.join(hot)}. If any of these is a stock "
            "model, the task is too easy for RL to show a curve: harden the DSL (slice 002) before training."
        )


# --- slice 006: SLURM scaffold --------------------------------------------------


@slurm_app.command("render")
def slurm_render(
    name: str = typer.Option(..., "--name"),
    run_id: str = typer.Option(..., "--run-id"),
    workdir: Path = typer.Option(Path.cwd(), "--workdir"),
    out: Path = typer.Option(..., "--out", help="Where to write the sbatch script"),
    gpus: int = typer.Option(1, "--gpus"),
    partition: str = typer.Option("compute", "--partition", help="compute (1d) or compute_dense (7d)"),
    time: str = typer.Option("1-00:00:00", "--time"),
    hf_cache: str | None = typer.Option(None, "--hf-cache", help="Shared HF cache to stage to /tmp"),
    nodelist: str | None = typer.Option(None, "--nodelist", help="e.g. trpro-slurm1"),
    submit: bool = typer.Option(False, "--submit", help="Also sbatch it. Off by default."),
    command: list[str] = typer.Argument(..., help="Command the job runs, after --"),
) -> None:
    """Render an sbatch script with checkpoint-friendly defaults; optionally submit it."""
    from planner_rl.train import slurm

    spec = slurm.JobSpec(
        name=name,
        command=command,
        run_id=run_id,
        workdir=str(workdir),
        shared_hf_cache=hf_cache,
        partition=partition,
        gpus=gpus,
        time=time,
        nodelist=nodelist,
    )
    path = slurm.write(spec, out)
    typer.echo(f"wrote {path}")
    if submit:
        typer.echo(f"submitted job {slurm.submit(path)}")


@slurm_app.command("smoke")
def slurm_smoke(
    run_id: str = typer.Option(..., "--run-id"),
    runs_root: Path = typer.Option(Path("runs"), "--runs-root"),
    steps: int = typer.Option(600, "--steps"),
    checkpoint_every: int = typer.Option(30, "--checkpoint-every"),
    step_seconds: float = typer.Option(1.0, "--step-seconds"),
) -> None:
    """Toy trainer: proves checkpoint, pre-timeout requeue, and resume on the cluster."""
    from planner_rl.train.smoke import run_smoke

    step = run_smoke(
        runs_root=runs_root,
        run_id=run_id,
        total_steps=steps,
        checkpoint_every=checkpoint_every,
        step_seconds=step_seconds,
    )
    typer.echo(f"stopped at step {step}/{steps}")


@slurm_app.command("stage")
def slurm_stage(
    src: Path = typer.Option(..., "--src"),
    dst: Path = typer.Option(..., "--dst"),
) -> None:
    """Copy a shared HF cache onto node-local scratch."""
    from planner_rl.train.hf_cache import stage

    copied = stage(src, dst)
    typer.echo(f"staged {src} -> {dst} ({copied / 1e9:.2f} GB copied)")


@slurm_app.command("prefetch")
def slurm_prefetch(
    repo_id: str = typer.Argument(...),
    cache: Path = typer.Option(..., "--cache", help="Shared HF cache root"),
    revision: str | None = typer.Option(None, "--revision"),
) -> None:
    """Download a model into the shared cache (run where there is internet)."""
    from planner_rl.train.hf_cache import prefetch

    typer.echo(str(prefetch(repo_id, cache_dir=cache, revision=revision)))


@slurm_app.command("env-check")
def slurm_env_check() -> None:
    """Report Python / torch / CUDA / vLLM / GPUs. Run on the compute node to pin versions."""
    report: dict[str, object] = {"python": platform.python_version(), "host": platform.node()}
    for mod in ("torch", "transformers", "vllm", "unsloth", "trl", "peft"):
        try:
            report[mod] = getattr(importlib.import_module(mod), "__version__", "unknown")
        except Exception as exc:  # noqa: BLE001 - any import failure is the finding
            report[mod] = f"unavailable ({type(exc).__name__})"
    try:
        import torch

        report["cuda_available"] = torch.cuda.is_available()
        report["cuda"] = torch.version.cuda
        report["gpus"] = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    except Exception:  # noqa: BLE001
        pass
    if shutil.which("nvidia-smi"):
        smi = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
        )
        report["nvidia_smi"] = smi.stdout.strip().splitlines()
    typer.echo(json.dumps(report, indent=2))
