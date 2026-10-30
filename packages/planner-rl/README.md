# planner-rl

Post-training Logger's query planner with execution-verified rewards. Gold answers come from executing plans, not from a teacher model's judgment ([decision 0004](../../docs/decisions/0004-reverse-generated-gold-over-loghub.md)).

Canonical design context: [docs/sourceoftruth.md](../../docs/sourceoftruth.md) (§3.1, §6, §7 step 2a). Placement: [decision 0007](../../docs/decisions/0007-planner-rl-package-placement.md).

Mirror (read-only output, not yet created): `mqnch/planner-rl`. Because the mirror force-pushes, consumers must **re-clone rather than `git pull`** (§5).

## Status

**Data generation and the SLURM scaffold are built and tested; no model is trained yet.**

- [Slice 004](../../docs/slices/004-reverse-generated-dataset.md), *in progress*: dataset pipeline, filters, splits, manifest and audit tooling. The first real-corpus run and the manual audit are still pending.
- [Slice 006](../../docs/slices/006-slurm-training-scaffold.md), *in progress*: run dirs, atomic checkpoints, pre-timeout requeue, sbatch rendering, HF cache staging. The cluster smoke run and the **vLLM version pin** are still pending, and slice 008 is blocked on the pin.
- [Slice 005](../../docs/slices/005-eval-harness-and-baselines.md), *in progress*: eval harness, execution scoring, `compare` and the difficulty gate are built and tested. The Qwen3.5-9B upper-bound and Sonnet 5.5 frontier runs are in progress; stock 0.8B/2B/4B are owed on the cluster ([0019](../../docs/decisions/0019-qwen-9b-upper-bound-for-the-gate.md)).
- Not started: SFT (007), GRPO (008), PRIME (009), cost curve (010).

## Modules

| Module | Purpose |
|---|---|
| `data.corpus` | Time-window split DBs; read-only value pools |
| `data.sampler` | Stratified plan sampling over the frozen DSL |
| `data.gold` | Execute plan → gold; structural rejection |
| `data.author` | Question authoring with Claude (`AnthropicAuthor`), `PROMPT_VERSION` |
| `data.filters` | DSL-leak, keyword-trivial and near-duplicate filters |
| `data.pipeline` | `generate_dataset()`: the `gen-data` body; `DatasetManifest` |
| `data.repair` | In-place dataset repairs recorded in the manifest (`floor_time_windows`, [0020](../../docs/decisions/0020-repair-time-windows-in-place.md)) |
| `data.audit` | Manual-audit sheet and scoring |
| `http` | Stdlib JSON POST with a whole-request deadline, shared by authoring and eval |
| `eval.prompt` | Planner prompt: DSL spec + corpus card ([0017](../../docs/decisions/0017-planner-prompt-carries-a-corpus-card.md)), `EVAL_PROMPT_VERSION` |
| `eval.score` | Execution-verified scoring, also slice 008's reward ([0018](../../docs/decisions/0018-eval-scoring-and-reward-combination.md)) |
| `eval.backend` | `ChatBackend`: one OpenAI-compatible client for OpenRouter, `mlx_lm.server` and vLLM |
| `eval.harness` | `run_eval()`: seeded sampling, concurrency, resume from `<out>.partial.jsonl` |
| `eval.report` | `compare` table (on the examples all files share) and the 0.85 gate |
| `train.runs` | `RunDir`: config freeze, event log, atomic checkpoints, resume |
| `train.preempt` | `StopFlag` (SIGUSR1/SIGTERM), `requeue()` |
| `train.slurm` | `JobSpec` → sbatch; explicit `submit()` |
| `train.hf_cache` | Prefetch, stage to node-local `/tmp`, offline env |
| `train.smoke` | Toy trainer proving the checkpoint/resume loop |

## CLI

| Command | What it does |
|---|---|
| `planner-rl gen-data --corpus DB --n N --out DIR [--dry-run] [--seed S] [--provider anthropic\|openrouter] [--model M]` | Build a dataset. `--dry-run` makes no API calls. `--provider openrouter` defaults to `anthropic/claude-haiku-5.5` ([0016](../../docs/decisions/0016-openrouter-as-a-second-authoring-provider.md)) |
| `planner-rl repair-data DIR...` | Floor absolute time windows to the minute where the question states no seconds; recompute gold; back up originals |
| `planner-rl audit-data DIR [--sample 100]` / `--score SHEET` | Write or score the manual-audit sheet |
| `planner-rl eval --data DIR... --model M --out FILE [--split test] [--per-corpus N] [--local \| --base-url URL] [--concurrency C] [--thinking \| --reasoning-effort E]` | Score a planner by execution. Default endpoint is OpenRouter; `--local` is `127.0.0.1:8080`. Re-running the same command resumes |
| `planner-rl rescore FILE...` | Re-score saved outputs under the current scorer and data; no model calls |
| `planner-rl compare FILE...` | Side-by-side results on their shared examples; flags anything at or above the 0.85 gate |
| `planner-rl slurm render --name --run-id --out [--gpus --partition --time --hf-cache --nodelist] [--submit] -- CMD...` | Render (and, only with `--submit`, submit) an sbatch script |
| `planner-rl slurm smoke --run-id ID` | Toy checkpoint/resume job |
| `planner-rl slurm stage --src --dst` / `prefetch REPO --cache DIR` | HF cache staging |
| `planner-rl slurm env-check` | Versions of torch/CUDA/vLLM/etc. and GPUs on this node |

## Environment

| Variable | Used by |
|---|---|
| `ANTHROPIC_API_KEY` (or an `ant auth login` profile) | `gen-data --provider anthropic` (the default) without `--dry-run` |
| `OPENROUTER_API_KEY` | `gen-data --provider openrouter`; `eval` against OpenRouter |
| `HF_HOME`, `HF_HUB_CACHE`, `HF_HUB_OFFLINE` | Set by rendered sbatch scripts when `--hf-cache` is given |
| `PLANNER_RL_RUN_ID` | Exported by rendered sbatch scripts |

Install the cluster-side extra with `uv sync --all-packages --extra train`.
