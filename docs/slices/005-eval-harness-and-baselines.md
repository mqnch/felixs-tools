# 005 — Eval harness, stock baselines, and the difficulty gate

**Date:** 2026-10-30 (planned 2026-08-15)
**Status:** In progress. Harness built and tested; gate passes on the letter but not clearly in spirit (see Results); stock 0.8B/2B/4B still owed on the cluster
**Touches:** `packages/planner-rl`
**Decisions:** [0017](../decisions/0017-planner-prompt-carries-a-corpus-card.md), [0018](../decisions/0018-eval-scoring-and-reward-combination.md), [0019](../decisions/0019-qwen-9b-upper-bound-for-the-gate.md), [0003](../decisions/0003-extend-the-query-dsl.md), [0005](../decisions/0005-grpo-primary-prime-ablation.md), [0006](../decisions/0006-qwen3-base-models.md)
**Depends on:** 004

## What a person can now do

Score any planner — stock, fine-tuned, or frontier — on one benchmark with one command.

```bash
D="--data data/full/hadoop-50k --data data/full/bgl-20k --data data/full/openstack-20k"
uv run planner-rl eval $D --model qwen/qwen3.5-9b --concurrency 12 --out results/stock-qwen3.5-9b.json
uv run planner-rl eval $D --model anthropic/claude-sonnet-5.5 --reasoning-effort low --per-corpus 100 --out results/frontier.json
uv run planner-rl eval $D --model Qwen/Qwen3.5-2B --base-url http://<node>:8000/v1 --out results/stock-2b.json   # vLLM on the cluster
uv run planner-rl compare results/*.json      # on the examples all files share
uv run planner-rl rescore results/*.json      # after a scorer change; no model calls
```

(In zsh, write the `--data` flags out or use `${=D}`; zsh does not word-split `$D`.)

## Scope

Metrics, all computed by execution:

| Metric | Meaning |
|---|---|
| Format validity | Parses and validates against the frozen schema |
| Execution success | Runs against the index without error |
| Retrieved-set F1 / recall | Against gold row IDs — the headline number |
| Group-set score | For aggregate queries, which return groups and **no rows** |
| Query count, rows scanned | The efficiency terms |
| Latency, tokens | Reported, not rewarded — feeds the cost curve |

Baselines measured now, before any training: stock Qwen3.5 0.8B / 2B / 4B, plus a frontier model. Fixed seeds, fixed prompt, versioned.

**Two reward paths, not one.** Slice 002 made aggregate queries return groups and no rows ([decision 0012](../decisions/0012-aggregates-as-groups-not-rows.md)), so row-ID F1 is undefined for them. The harness needs a second comparison for group results, and a documented rule for how a plan mixing both is scored. The rejected alternative — synthesizing row IDs for aggregates — would have made F1 report differences that don't exist, which is worse than carrying two paths. Decide the combination rule here, because slice 008's reward inherits it.

**Format-reward granularity.** The validator reports all errors *within* a stage but skips the semantic stage entirely if the structural stage fails (see [slice 002](002-extended-query-dsl.md)). A binary valid/invalid term is unaffected; a graded term based on error count would be misleading. Choose deliberately.

## Why this comes before all training

**This slice is a go/no-go gate.** If stock Qwen3-1.7B scores **≥ ~0.85 retrieved-set F1**, the task is too easy: RL will show a flat curve and the method half of the claim collapses. The correct response is to reopen slice 002 and harden the DSL — *before* spending GPU time, not after.

Measuring the ceiling before training is the whole reason this ordering exists.

## Deliberately not in this slice

- **No training of any kind.** Measurement only.
- **No LLM-judge metrics.** Execution-verified metrics only, per [0002](../decisions/0002-post-train-the-query-planner.md).
- **No prompt-optimization campaign** on the stock baselines beyond a reasonable, documented prompt — but it must be a genuine attempt, since an under-prompted stock baseline inflates the trained model's apparent gain exactly the way a weak SFT baseline would.

## How it was built

`planner_rl/eval/`:
- **`prompt`**: DSL spec plus a corpus card, so template IDs and location keys are knowable ([0017](../decisions/0017-planner-prompt-carries-a-corpus-card.md)).
- **`score`**: execution scoring, which slice 008 reuses as its reward ([0018](../decisions/0018-eval-scoring-and-reward-combination.md)).
- **`backend`**: one OpenAI-compatible client for OpenRouter, `mlx_lm.server` and vLLM.
- **`harness`**: seeded sampling, concurrency, resume from a partial file, and `rescore`.
- **`report`**: `compare` and the gate.

The invariant: gold plans fed back as model output score exactly 1.0 on all 1,484 test examples.

## Results (test split, prompt p-2026-10-30.1, scorer s-2026-10-30.2)

After the time-window repair ([0020](../decisions/0020-repair-time-windows-in-place.md)), rescored from saved outputs with no new model calls. Pre-repair numbers are in brackets.

| Model | n | answer | format valid | answer when format valid | cost |
|---|---|---|---|---|---|
| Qwen3.5-9B, stock, no thinking | 1480 | **0.707** [0.700] | 77.9% | **0.905** [0.899] | $1.32 |
| Claude Sonnet 5.5, low reasoning | 300 | **0.965** [0.946] | 99.0% | 0.975 [0.956] | $1.62 |

Qwen3.5-9B by corpus: Hadoop 0.72, BGL 0.64, OpenStack 0.74. By stratum, its weakest are aggregate (0.52), conjunction (0.55) and multi_query (0.64).

Its format failures:
- `unknown_field`, 140: emitting a bare query without the `{"queries": [...]}` wrapper.
- `degenerate_group`, 113: a one-child `and`/`or`.

**Gate verdict: passes on the letter, not clearly in spirit.** The 9B upper bound scores 0.70, under 0.85, so the stock 2B is under the gate too ([0019](../decisions/0019-qwen-9b-upper-bound-for-the-gate.md)). But the 9B's whole gap is format. When it emits a valid plan it scores 0.90, above the gate, and SFT fixes format cheaply. Whether the *2B* is also near the ceiling once format is fixed is the open question. Only the stock 2B run (cluster) answers it, and slice 007 must not report a number before that run.

### Label noise found by the eval

Reviewing all 45 Sonnet failures (answer < 1):

| Cause | Count |
|---|---|
| Dataset question doesn't specify gold: minute-rounded times vs gold seconds (14), question adds detail gold lacks (6), AND/OR flip (1), wrong date (1) | ~22 |
| Scorer too strict: correct totals scored 0 because of the group-key shape, and self-corrected replies scored invalid | 8, fixed in scorer v2 |
| Real model mistakes | ~19 |

The minute-rounding problem is systematic. Share of examples where the gold window has seconds the question never states:

| | train | test |
|---|---|---|
| Hadoop | 12% | 10% |
| BGL | 24% | 25% |
| OpenStack | 23% | 14% |

The slice-004 audit passed it because a reader sees "17:45" as a fine rendering of 17:45:24. **Repaired** ([0020](../decisions/0020-repair-time-windows-in-place.md)). The remaining known label noise (questions adding detail gold lacks, ~2%) needs an authoring-prompt fix and is still open.

## Deliberately not in this slice (added during the build)

- **No stock 0.8B/2B/4B numbers yet.** OpenRouter doesn't host them, and running them on the dev laptop isn't practical. They run on the cluster with the same harness ([0019](../decisions/0019-qwen-9b-upper-bound-for-the-gate.md)).
- **Frontier is a 300-example sample**, seeded and the same for any model. `compare` scores on the shared examples.
- **Over-specified questions (~2%) are not fixed.** That needs an authoring-prompt change and a regeneration. The time-window repair was free and is done.

## What this unlocks

The gate for 007/008, and the benchmark every later number is reported on. Slices 006 (SLURM scaffold) and 007 (SFT) can be built in parallel with this, but neither should be *run* in anger until the gate passes.
