# 0001 — Post-training Logger's query planner becomes the primary near-term deliverable

**Date:** 2026-08-15
**Status:** Accepted
**Affects:** source of truth §3.1, §7; `packages/logger`, `packages/planner-rl`
**Slice:** [002](../slices/002-extended-query-dsl.md) onward

## Context

§3.1 framed post-training a small model as "explicitly a side project decoupled from Logger's core success," motivated by wanting hands-on experience with RL post-training. Under that framing the work was optional and unscheduled, and §7 put Brain next.

The reason changed: this work is now the artifact for upcoming recruiting. That inverts its priority — it is no longer a byproduct of building Logger, it is the thing being built, and Logger is its substrate.

## Decision

Post-training Logger's query planner is the primary active workstream. Brain (§7 step 3) is deferred behind it.

One invariant from §3.1 is **kept unchanged**: Logger's core function must still work against a stock small model with good prompting, with no fine-tuned checkpoint required. The Router stub's fallback path stays. This is not deference to the old plan — it means a stalled or disappointing training run degrades the artifact without breaking the tool.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Keep fine-tuning as an unscheduled side project | Produces no artifact on any particular timeline, which is the entire point now |
| Follow §7 and build Brain next | Brain is deterministic static analysis with no model in it — good software, but it evidences none of the post-training skill being signalled |
| Ship a prompt-engineered Logger and call it the artifact | Demonstrates tool-building, not post-training. §3.1 already says stock-model-plus-prompting is enough for the tool, so this produces no new evidence |
| Make the fine-tuned model mandatory for Logger to work | Couples a working tool to a research outcome. If training disappoints, the tool breaks too |

## Consequences

- §7's build order changes; Brain slips behind an entire workstream.
- The project acquires a GPU-cluster dependency (WATcloud SLURM) it did not previously have.
- Retraining becomes a real activity, where §3.1 previously said "swap the base model, don't retrain." That principle still holds for *base model upgrades*; it no longer describes the project as a whole.
- A new package and a new public mirror repo (decision [0007](0007-planner-rl-package-placement.md)).

## Reversal trigger

Recruiting concludes, or the artifact ships. At that point the §7 order resumes and Brain becomes next. This decision is explicitly time-boxed to a purpose, not a permanent re-architecture of the project's priorities.
