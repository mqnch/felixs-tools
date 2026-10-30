# planner-rl

Post-training Logger's query planner with execution-verified rewards. Gold answers come from executing plans, not from a teacher model's judgment ([decision 0004](../../docs/decisions/0004-reverse-generated-gold-over-loghub.md)).

Canonical design context: [docs/sourceoftruth.md](../../docs/sourceoftruth.md) (§3.1, §6, §7 step 2a). Placement: [decision 0007](../../docs/decisions/0007-planner-rl-package-placement.md).

Mirror (read-only output, not yet created): `mqnch/planner-rl`. Because the mirror force-pushes, consumers must **re-clone rather than `git pull`** (§5).

## Status

**Data generation and the SLURM scaffold are built and tested; no model is trained yet.**

- [Slice 004](../../docs/slices/004-reverse-generated-dataset.md), *in progress*: dataset pipeline, filters, splits, manifest and audit tooling. The first real-corpus run and the manual audit are still pending.
- [Slice 006](../../docs/slices/006-slurm-training-scaffold.md), *in progress*: run dirs, atomic checkpoints, pre-timeout requeue, sbatch rendering, HF cache staging. The cluster smoke run and the **vLLM version pin** are still pending, and slice 008 is blocked on the pin.
- Not started: eval harness and baselines (005), SFT (007), GRPO (008), PRIME (009), cost curve (010).

## Modules

| Module | Purpose |
|---|---|
| `data.corpus` | Time-window split DBs; read-only value pools |
| `data.sampler` | Stratified plan sampling over the frozen DSL |
| `data.gold` | Execute plan → gold; structural rejection |
| `data.author` | Question authoring with Claude (`AnthropicAuthor`), `PROMPT_VERSION` |
| `data.filters` | DSL-leak, keyword-trivial and near-duplicate filters |
| `data.pipeline` | `generate_dataset()`: the `gen-data` body; `DatasetManifest` |
| `data.audit` | Manual-audit sheet and scoring |
| `train.runs` | `RunDir`: config freeze, event log, atomic checkpoints, resume |
| `train.preempt` | `StopFlag` (SIGUSR1/SIGTERM), `requeue()` |
| `train.slurm` | `JobSpec` → sbatch; explicit `submit()` |
| `train.hf_cache` | Prefetch, stage to node-local `/tmp`, offline env |
| `train.smoke` | Toy trainer proving the checkpoint/resume loop |

## CLI

| Command | What it does |
|---|---|
| `planner-rl gen-data --corpus DB --n N --out DIR [--dry-run] [--seed S] [--provider anthropic\|openrouter] [--model M]` | Build a dataset. `--dry-run` makes no API calls. `--provider openrouter` defaults to `anthropic/claude-haiku-5.5` ([0016](../../docs/decisions/0016-openrouter-as-a-second-authoring-provider.md)) |
| `planner-rl audit-data DIR [--sample 100]` / `--score SHEET` | Write or score the manual-audit sheet |
| `planner-rl slurm render --name --run-id --out [--gpus --partition --time --hf-cache --nodelist] [--submit] -- CMD...` | Render (and, only with `--submit`, submit) an sbatch script |
| `planner-rl slurm smoke --run-id ID` | Toy checkpoint/resume job |
| `planner-rl slurm stage --src --dst` / `prefetch REPO --cache DIR` | HF cache staging |
| `planner-rl slurm env-check` | Versions of torch/CUDA/vLLM/etc. and GPUs on this node |

## Environment

| Variable | Used by |
|---|---|
| `ANTHROPIC_API_KEY` (or an `ant auth login` profile) | `gen-data --provider anthropic` (the default) without `--dry-run` |
| `OPENROUTER_API_KEY` | `gen-data --provider openrouter` |
| `HF_HOME`, `HF_HUB_CACHE`, `HF_HUB_OFFLINE` | Set by rendered sbatch scripts when `--hf-cache` is given |
| `PLANNER_RL_RUN_ID` | Exported by rendered sbatch scripts |

Install the cluster-side extra with `uv sync --all-packages --extra train`.
