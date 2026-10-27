# 0002 — Post-train the query planner, rewarded by execution against gold row IDs

**Date:** 2026-08-15
**Status:** Accepted
**Affects:** `packages/logger` (planner, index), `packages/planner-rl`; source of truth §3.1
**Slice:** [002](../slices/002-extended-query-dsl.md), [005](../slices/005-eval-harness-and-baselines.md)

## Context

§3.1 names exactly two model-using components in Logger: the **query planner** (NL question → structured queries) and the **anomaly scorer** (novelty/spike detection over incoming lines). Only one can be the focus, and the choice determines whether RL is even the right tool.

The planner already emits a machine-checkable artifact: `{"queries":[{"filters":{...},"terms":[...],"limit":N}]}`, which `LogIndex.query()` executes into a set of row IDs. That means correctness can be *computed*, not judged.

## Decision

Post-train the query planner. Reward is produced by executing the model's emitted plan against the index and comparing the returned row-ID set to a gold row-ID set — a verifiable reward requiring no human labeling and no LLM judge.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Anomaly scorer | No free ground truth. Some LogHub datasets ship anomaly labels, but it reduces to a classification task where supervised training is the obvious baseline and RL is hard to justify — an interviewer would reasonably ask why RL was used at all |
| Both components | Two datasets, two reward designs, two eval harnesses. Doubles scope and reliably yields two half-finished stories instead of one complete one |
| LLM-as-judge reward on plan quality | Reintroduces exactly the expensive, noisy, unverifiable signal that execution-based reward eliminates, and makes the result far easier to dismiss |

## Consequences

- The planner's DSL becomes a **training contract**. Changing it after data generation invalidates the dataset and every trained checkpoint. This forces a DSL freeze (decision [0003](0003-extend-the-query-dsl.md)) before slice 004 runs.
- `LogIndex.query()` moves onto the critical path for correctness: a bug there silently corrupts every reward computation. It needs tests before training, not after.
- Reward is deterministic and replayable, so training runs are reproducible given a fixed corpus and seed.

## Reversal trigger

If the planner task proves saturable by stock models even after the DSL extension in [0003](0003-extend-the-query-dsl.md) — the explicit gate in slice 005 — the choice reopens. The likelier response is to harden the DSL further rather than to switch components.
