# 0006 — Qwen3.5 0.8B / 2B / 4B as base models, overriding MiniCPM-1B

**Date:** 2026-08-15 (checkpoints corrected same day — see Correction below)
**Status:** Accepted
**Affects:** source of truth §6; `packages/planner-rl`
**Slice:** [005](../slices/005-eval-harness-and-baselines.md), [007](../slices/README.md)

## Context

§6 named "MiniCPM-1B class" as the small base model, written when the model was an implementation detail of a side project. It is now the object of the work, and the task — emitting valid structured JSON against a fixed schema — rewards base models with strong instruction-following and structured-output ability.

The chosen headline claim also includes a cost curve, which needs more than one point to be a curve.

## Decision

Three sizes from the **Qwen3.5** small series: **0.8B** as the fast debug loop, **2B** as the headline model, **4B** as the upper scale point. All fit a 24 GB RTX 3090 with LoRA.

## Correction (2026-08-15)

This record originally specified Qwen3 **0.6B / 1.7B / 4B**, and deferred checkpoint verification to slice 005. Verification happened immediately instead, and those were the wrong generation: **Qwen3.5 shipped its small series (0.8B, 2B, 4B, 9B) on 2026-03-02**, after the flagship in February. The role mapping is unchanged — debug / headline / scale point — only the checkpoints move.

Two consequences follow, and the second is more important than the first:

1. **vLLM support is a live risk.** Qwen3.5 is reported unsupported on vLLM 0.16.0, requiring a newer or nightly build. Decision [0005](0005-grpo-primary-prime-ablation.md) assumes a vLLM rollout server alongside the trainer. Slice 006 must pin and verify a working vLLM version *before* slice 008 depends on it; the documented fallback is Unsloth's own inference path for GRPO rollouts, at some throughput cost. **This is now the highest-priority unknown in the training stack.**

2. **The slice 005 difficulty gate just got harder to pass.** Qwen3.5 small models are a substantial jump over Qwen3 — roughly +9 points on the 4B and +2.5 on the smallest. A stronger stock baseline means *less headroom for RL to demonstrate a gain*, which is precisely what decision [0003](0003-extend-the-query-dsl.md)'s gate tests for. The DSL extension in slice 002 must be more ambitious than it would have needed to be against Qwen3, and the ≥0.85 F1 trip-wire is now more likely to fire. Better to absorb that in slice 002's design than to discover it after training.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| MiniCPM-1B, per §6 | Keeps the source of truth unedited, but structured-JSON reliability is the whole task and Qwen3.5 small models are materially stronger at it |
| Qwen3 (previous generation) | Would sidestep the vLLM support risk above and make the difficulty gate easier to pass — but deliberately training a weaker base model to make your own result look better is exactly the kind of thing that does not survive an interview question |
| A single size | Reduces the cost curve to a single point, weakening half the headline claim for very little saved effort |
| Qwen3.5-9B | Exceeds comfortable single-3090 RL with rollouts, and contradicts §3.1's requirement that the planner be small enough for interactive latency |

## Consequences

- §6 is edited; this is a documented override, not a silent drift.
- The 0.6B debug model is a process win: pipeline bugs surface in minutes rather than hours of GPU time.
- Three sizes triples training runs, but they are independent and can be queued in parallel across cluster nodes.

## Reversal trigger

A stronger small model in the same size class ships. §3.1's "swap the base model rather than retrain" principle applies to the base — though note that this project now retrains by design, so a swap means rerunning the pipeline, which is exactly what the pipeline is for.
