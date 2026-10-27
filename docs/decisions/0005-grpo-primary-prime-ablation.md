# 0005 — GRPO with correctness-plus-efficiency reward as primary; PRIME as an ablation

**Date:** 2026-08-15
**Status:** Accepted
**Affects:** `packages/planner-rl` (training, reward)
**Slice:** [007](../slices/README.md), [008](../slices/README.md), [009](../slices/README.md)

## Context

§3.1 named PRIME-RL specifically as the technique worth learning. But PRIME's contribution is an *implicit process reward model* that densifies sparse outcome reward across long reasoning chains — and a query plan is a short structured output, which is close to the worst case for process rewards to matter.

Meanwhile the outcome reward here is unusually good: cheap, deterministic, and genuinely verifiable (decision [0002](0002-post-train-the-query-planner.md)).

## Decision

**GRPO with outcome reward is the primary method.** Reward composition:

| Term | Signal |
|---|---|
| Format validity | Parses, and validates against the frozen DSL schema |
| Execution success | Runs against the index without error |
| Retrieval quality | F1 of returned row-ID set against gold |
| Efficiency penalty | Query count and **rows scanned** |

**PRIME's implicit process reward is a second experiment**, run after a working GRPO curve exists — giving both the headline result and a real ablation. If process rewards don't help on short structured outputs, that negative result is worth reporting and is a more honest signal than an unexamined claim that they do.

An **honestly tuned SFT baseline comes first** (slice 007). An artificially weak baseline is the single most common way an RL-beats-SFT claim gets dismantled in an interview, so the baseline gets a real hyperparameter sweep, not one run.

Efficiency uses **rows scanned**, a deterministic proxy, rather than measured wall-clock — wall-clock on a shared SLURM cluster is noisy, and noisy reward destabilizes RL.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| PRIME-RL as the primary method | Its strength is dense reward over long chains; short plan outputs may not exercise it. Betting the headline result on that mismatch is the riskier order |
| GRPO only, no PRIME | Cleanest path to a number, but abandons the stated learning goal from §3.1 for no gain — PRIME as an ablation costs one extra experiment on an existing pipeline |
| Wall-clock latency in the reward | Faithful to the product goal but noisy on shared hardware; rows-scanned captures the same intent deterministically |
| Correctness-only reward | Simpler and less prone to collapse, but §3.1 specifies "a small set of targeted queries" — efficiency is in the product spec, and a shotgun-broad policy would demo badly |

## Consequences

- The efficiency term needs weight tuning: too strong and the policy collapses to emitting one trivial query that scans nothing. This is a known failure mode to watch from the first run, not to discover late.
- Requires a vLLM rollout server alongside the trainer — on a 4×3090 node, roughly 1 GPU serving and 3 training.
- Three reward terms means reward-component ablations are nearly free once the harness exists, which strengthens the writeup.

## Reversal trigger

If the efficiency penalty destabilizes training or collapses the policy after weight tuning, drop to correctness-only and report the efficiency term as a failed ablation. If PRIME shows no gain over GRPO, report that as the finding rather than burying it.
