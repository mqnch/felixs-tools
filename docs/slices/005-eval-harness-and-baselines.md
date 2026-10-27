# 005 — Eval harness, stock baselines, and the difficulty gate

**Date:** planned
**Status:** Planned
**Touches:** `packages/planner-rl`
**Decisions:** [0003](../decisions/0003-extend-the-query-dsl.md), [0005](../decisions/0005-grpo-primary-prime-ablation.md), [0006](../decisions/0006-qwen3-base-models.md)
**Depends on:** 004

## What a person can now do

Score any planner — stock, fine-tuned, or frontier — on one benchmark with one command.

```bash
uv run planner-rl eval --model qwen3-1.7b --split test --out results/stock-1.7b.json
uv run planner-rl eval --model claude-frontier --split test --out results/frontier.json
uv run planner-rl compare results/*.json
```

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

## What this unlocks

The gate for 007/008, and the benchmark every later number is reported on. Slices 006 (SLURM scaffold) and 007 (SFT) can be built in parallel with this, but neither should be *run* in anger until the gate passes.
