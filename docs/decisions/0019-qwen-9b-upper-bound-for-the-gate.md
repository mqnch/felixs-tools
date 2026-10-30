# 0019 — The difficulty gate runs on stock Qwen3.5-9B as an upper bound; the stock 2B number moves to the cluster

**Date:** 2026-10-30
**Status:** Accepted
**Affects:** slice 005 gate procedure
**Slice:** [005](../slices/005-eval-harness-and-baselines.md)

## Context

The gate asks whether stock Qwen3.5-2B (the model to be trained, decision [0006](0006-qwen3-base-models.md)) already scores at least ~0.85. OpenRouter hosts no Qwen3.5 model below 9B. Running 0.8B, 2B and 4B in bf16 on the development laptop (M5, 16 GB) is too slow to be practical. The cluster's vLLM pin is still open (slice 006).

## Decision

Run the gate on stock **Qwen3.5-9B** via OpenRouter, as a one-sided test:
- **9B scores below 0.85:** the smaller same-family models score lower, so the gate passes.
- **9B scores 0.85 or higher:** the gate is inconclusive, and the 2B must be measured directly before any training.

The stock 0.8B, 2B and 4B baselines are still owed. They run on the cluster with vLLM through the same harness (`--base-url`) before slice 007 reports any number. The frontier baseline is Claude Sonnet 5.5 at low reasoning effort (reasoning can't be turned off on it), on a seeded 100-per-corpus sample.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Run 0.8B/2B/4B locally with mlx-lm | ~15 GB of weights and hours per model on a 16 GB laptop |
| Use a different small model (e.g. a hosted 3B from another family) as the stand-in | Not an upper or lower bound on Qwen3.5-2B, so the gate says nothing either way |
| Wait for the cluster | Blocks the go/no-go on infrastructure when a cheaper bound may already answer it |
| Claude Haiku 5.5 as the frontier model | It wrote the questions, so it would have an unfair edge reading them |

## Consequences

- If the gate passes on the 9B, slice 007 may start. The trained-vs-stock comparison still needs the stock 2B, measured on the cluster.
- The upper-bound argument assumes larger means better within one family on this task. The cluster run checks that.

## Reversal trigger

The 9B scores ≥ 0.85, or the cluster 2B run comes out higher than the 9B.
