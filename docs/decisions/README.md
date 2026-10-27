# Decisions

Append-only record of choices made **after** the source of truth was written. One file per decision, `NNNN-kebab-title.md`.

## When to write one

Write a decision record when there was a **real alternative you rejected**:

- Adopt an existing library vs. build in-house
- Library A vs. library B, or storage/format choice
- A shortcut taken knowingly, with an accepted failure mode
- A schema or interface shape other packages must build against
- Un-deferring something from §9, or deferring something new

**Don't** write one for choices with no live alternative, or for pure implementation detail. A directory of trivial records makes the real ones unfindable.

## Rules

- **Record the rejected option and why**, not just the winner. The whole point is that a future run (or future Felix) doesn't silently re-propose it in six months.
- **Record the reversal trigger** where there is one — the concrete signal that would make you revisit. `docs/friction.md` is where that evidence accumulates.
- Records are immutable once accepted. To change a decision, write a new record and set the old one's status to `Superseded by NNNN`.
- If a decision changes project scope, build order, or a non-goal, **also edit `docs/sourceoftruth.md`** — that file is canonical and current, this directory is history.

## Pre-existing decisions

These predate this directory and are documented inline in [../sourceoftruth.md](../sourceoftruth.md). Link to the section; don't copy them into new records.

| Decision | Where |
|---|---|
| Four packages, not eight — "delete the LLM" litmus test | §2.1 |
| Agent-shaped ideas become Swarm presets, not packages | §2.1, §3.4 |
| Human gating of all side effects is permanent | §2.3 |
| MCP servers per package on demonstrated need, not day one | §2.5 |
| Swarm↔Brain/Logger over Python imports, not MCP | §2.5 |
| Build Brain in-house instead of forking an AST-graph tool | §3.2 |
| Naive name-based call linking first, stack-graphs only if it hurts | §3.2, §9 |
| SQLite (adjacency list + recursive CTEs) over a graph DB | §3.2, §6 |
| Full rebuild per run; incremental Brain updates deferred | §3.2, §9 |
| Adopt LiteLLM SDK mode; reject its proxy server and hosted gateways | §3.3 |
| Exact-match cache only; semantic caching deferred | §3.3, §9 |
| Python across every package | §6 |
| One-way monorepo → mirror sync, PR-based if ever reversed | §5 |
| Build order: common → Logger → Brain → Router → Swarm | §7 |

## Index

| # | Decision | Date | Status |
|---|---|---|---|
| [0001](0001-post-trained-planner-is-primary-deliverable.md) | Post-training the query planner becomes the primary near-term deliverable | 2026-08-15 | Accepted |
| [0002](0002-post-train-the-query-planner.md) | Post-train the query planner, rewarded by execution against gold row IDs | 2026-08-15 | Accepted |
| [0003](0003-extend-the-query-dsl.md) | Extend the query DSL before generating training data | 2026-08-15 | Accepted |
| [0004](0004-reverse-generated-gold-over-loghub.md) | Reverse-generated gold data over LogHub corpora | 2026-08-15 | Accepted |
| [0005](0005-grpo-primary-prime-ablation.md) | GRPO with correctness-plus-efficiency reward primary; PRIME as ablation | 2026-08-15 | Accepted |
| [0006](0006-qwen3-base-models.md) | Qwen3 0.6B / 1.7B / 4B base models, overriding MiniCPM-1B | 2026-08-15 | Accepted |
| [0007](0007-planner-rl-package-placement.md) | Training code in `packages/planner-rl`, mirrored to a standalone public repo | 2026-08-15 | Accepted |
| [0008](0008-recursive-boolean-filter-tree.md) | A recursive boolean filter tree, not flat filter fields | 2026-08-15 | Accepted |
| [0009](0009-plan-schema-in-common.md) | Plan schema in `common`; validation and execution stay in `logger` | 2026-08-15 | Accepted |
| [0010](0010-corpus-relative-time-resolution.md) | Relative time bounds resolve against the corpus's newest timestamp | 2026-08-15 | Accepted |
| [0011](0011-rows-scanned-positive-skeleton.md) | `rows_scanned` measured as the plan's positive skeleton | 2026-08-15 | Accepted |
| [0012](0012-aggregates-as-groups-not-rows.md) | Aggregate results as a separate group list, not pseudo-rows | 2026-08-15 | Accepted |

## Template

Copy [TEMPLATE.md](TEMPLATE.md).
