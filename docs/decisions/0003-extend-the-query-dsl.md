# 0003 — Extend the query DSL before generating training data

**Date:** 2026-08-15
**Status:** Accepted
**Affects:** `packages/logger` (planner, index), `packages/common`
**Slice:** [002](../slices/002-extended-query-dsl.md)

## Context

The DSL as built supports `severity`, FTS `terms`, `location_key`, `template_id`, and `limit`. That is a small enough space that a stock instruction-tuned model can likely near-saturate it with prompting alone.

This is a research-design risk, not a product one: if the stock baseline already scores ~0.9, there is no headroom, the RL curve is flat, and the method half of the claim (decision [0005](0005-grpo-primary-prime-ablation.md)) has nothing to show. A too-easy task is the most common quiet failure mode of a post-training portfolio project.

## Decision

Extend the DSL before generating any training data:

- **Time ranges** — absolute and relative windows over `timestamp`
- **Negation** — exclude terms, severities, templates
- **OR groups** — disjunctions within a filter, not just implicit AND
- **Template-level aggregation** — count/group by `template_id`, not only row retrieval
- **Multi-query decomposition** — several targeted queries whose results union, per §3.1's "small set of targeted, parallel structured queries"

Ship a strict validator that returns **structured, machine-readable errors**. This is not developer ergonomics — it is the format-reward term in [0005](0005-grpo-primary-prime-ablation.md), and it needs to distinguish failure modes rather than return a bare boolean.

The DSL **freezes** at the end of slice 002. Post-freeze changes invalidate the dataset (see [0002](0002-post-train-the-query-planner.md)).

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Train against the current DSL | Fastest to a first run, but a flat learning curve is a real possibility and would not be discovered until GPU time had already been spent |
| Full constrained-SQL subset | Maximally expressive and easy to explain, but converts the project into text-to-SQL — a crowded benchmark space with well-funded prior work, where a solo result reads as weak by comparison rather than as novel |
| Extend the DSL later, after a first training run | Guarantees a full dataset regeneration and retrain; the "just to see" run costs more than designing the DSL correctly once |

## Consequences

- Slice 002 blocks everything downstream; nothing else can start until the DSL is frozen.
- The tool genuinely improves — these are capabilities a real log search should have, so this is not reward-hacking-by-design.
- Richer DSL means a larger space to sample from in slice 004, requiring **stratified sampling** so every feature appears in training data rather than the sampler favouring simple plans.

## Reversal trigger

Slice 005 measures a stock Qwen3-1.7B on the extended DSL. **If it scores ≥ ~0.85 retrieved-set F1, the DSL is still too easy** and slice 002 reopens before any training spend. That gate is the reason slice 005 precedes all training slices.
