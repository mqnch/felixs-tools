# Slices

Append-only log of work, one file per slice, `NNN-kebab-title.md`.

## What counts as a slice

A **thin vertical cut that ends in something usable end to end**. Not a task list, not a file inventory.

- ✅ "Ingest a log file and answer one natural-language query, stub Router, no cache"
- ✅ "Git co-change graph answers `who owns this file` from the CLI"
- ❌ "Add `index.py`" — that's a file, not a slice
- ❌ "Implement Logger" — that's a package, too big to learn anything from

If you can't state a slice as *something a person can now do that they couldn't before*, it isn't scoped as a slice yet.

## Rules

- **Write it while building**, not afterward. The cut lines and the reasoning are only cheap to capture in the moment.
- **Always fill in "Deliberately not in this slice."** This project defers things on purpose (§2.2, §9). A slice with no stated cut lines reads six months later as an oversight instead of a decision — that's the single most valuable field here.
- Keep it short. A slice entry that takes 20 minutes to write won't get written next time.
- Link out rather than restate: source of truth sections, decision records, friction lines.
- Never rewrite a past slice to match how things turned out. If it turned out wrong, that's a new slice or a friction line.
- Numbering is sequential and never reused. An abandoned slice stays in the log marked `Abandoned` with a sentence on why.
- A slice may be written ahead as `Planned` — its scope and cut lines are provisional until it ships, and it must be updated to match what actually happened rather than left aspirational.

## Current focus: the post-trained query planner

Per decision [0001](../decisions/0001-post-trained-planner-is-primary-deliverable.md), slices 002–012 are one workstream: post-training Logger's query planner with verifiable execution rewards, as a recruiting artifact. Brain is deferred behind it.

**Dependency order** — 002 gates everything, then three tracks run in parallel:

```
002 DSL (freeze)  ──┬──> 004 dataset ──> 005 eval + GATE ──┬──> 007 SFT ──> 008 GRPO ──┬──> 009 PRIME ablation
                    │                                      │                           └──> 010 cost curve
003 corpus ─────────┘                          006 SLURM scaffold ─┘                         ↓
                                                                                    011 wire back into Logger
                                                                                    012 ship artifact
```

003 and 006 have no dependency on 002 and can start immediately alongside it.

## Index

| # | Slice | Status | Notes |
|---|---|---|---|
| [001](001-common-logger-router-stub.md) | Common types, Logger bare bones, Router stub, `felix` CLI | Shipped | 2026-07-23, backfilled |
| [002](002-extended-query-dsl.md) | Extended query DSL, validator, executor | Shipped | 2026-08-15. DSL frozen at `SCHEMA_VERSION` 1.0.0 |
| [003](003-loghub-corpus-ingest.md) | LogHub corpus ingestion | Shipped | 2026-08-15. CLI wired as `felix logger ingest-corpus` |
| [004](004-reverse-generated-dataset.md) | Reverse-generated training dataset | In progress | 2026-10-27. Pipeline built and tested; real-corpus run + manual audit pending |
| [005](005-eval-harness-and-baselines.md) | Eval harness, stock baselines, difficulty gate | Planned | **Go/no-go before any GPU spend** |
| [006](006-slurm-training-scaffold.md) | SLURM training scaffold — sbatch, HF cache staging, checkpoint/resume, run logging | In progress | 2026-10-27. Built and tested locally; cluster smoke run + vLLM pin pending |
| 007 | SFT baseline, all three sizes, honestly tuned with a real sweep | Planned | A weak baseline is the fastest way to lose the RL claim |
| 008 | GRPO with execution reward — **the headline result** | Planned | vLLM rollouts + trainer on one 4×3090 node |
| 009 | PRIME implicit process-reward ablation | Planned | Negative result is publishable and expected to be possible |
| 010 | Cost + latency curve vs. frontier baseline | Planned | Second half of the headline claim |
| 011 | Wire the trained planner back into `felix logger search` via Router | Planned | Turns a benchmark into a working tool |
| 012 | Ship the artifact — mirror repo, model + dataset cards, technical writeup | Planned | Per decision [0007](../decisions/0007-planner-rl-package-placement.md) |

## Template

Copy [TEMPLATE.md](TEMPLATE.md).
