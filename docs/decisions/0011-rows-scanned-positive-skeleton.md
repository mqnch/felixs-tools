# 0011 — `rows_scanned` is measured as the plan's positive skeleton

**Date:** 2026-08-15
**Status:** Accepted
**Affects:** `packages/logger` (index); `packages/planner-rl` (reward)
**Slice:** [002](../slices/002-extended-query-dsl.md)

## Context

Decision [0005](0005-grpo-primary-prime-ablation.md) makes rows scanned the efficiency term in the reward, explicitly chosen over wall-clock because wall-clock on shared SLURM hardware is noisy. That only helps if "rows scanned" is defined precisely enough to be deterministic and to actually mean *work done* — otherwise the efficiency term is noise wearing a deterministic costume.

SQLite does not expose a per-query row-examined counter to Python. `sqlite3_status` is unavailable through the stdlib driver, and the progress handler counts VM steps, not rows.

## Decision

`rows_scanned` is the number of rows the filter had to be evaluated over, **measured** with a real `COUNT(*)` over the query's *positive skeleton*: the filter tree with every `not` node replaced by TRUE.

- `and` — intersection of its children's skeletons; children that cannot bound the scan drop out
- `or` — union of its children's skeletons; if **any** branch cannot bound the scan, the whole disjunction cannot
- `not` — cannot bound the scan
- leaves (`term`, `severity`, `template_id`, `location_key`, `time_range`) — bound the scan; all five are index-backed

A query whose skeleton is empty scans the table, and `rows_scanned` is the table row count. Plan-level `rows_scanned` is the **sum** across queries, so multi-query decomposition costs what it costs.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Rows returned | Trivially gamed: `limit: 1` would score as maximally efficient regardless of how much of the corpus the filter forced SQLite to read |
| A cost estimate from `EXPLAIN QUERY PLAN` | No row counts, only access-path names. Would also make the reward depend on SQLite's optimizer version, so a dependency bump would silently shift the reward function |
| Registering a Python UDF called per row to count exactly | Genuinely exact, but defeats every index and is per-row Python on million-line LogHub corpora — the reward computation would dominate rollout cost |
| Model the optimizer (pick the most selective index, intersect) | More faithful to what SQLite actually does, but it is a second implementation of a query planner inside a project that explicitly ships **no** optimizer ([0003](0003-extend-the-query-dsl.md)), and it would drift from real SQLite behaviour |
| Count only the rows the full `WHERE` matched | That is selectivity, not cost. It would reward adding negations, which are free to *match* and expensive to *evaluate* |

## Consequences

- The cost model is honest in the direction that matters: positive restrictions reduce the scan, negation and disjunction never do. A planner that reaches for `not` where a positive filter would do is correctly penalised.
- Two extra SQL statements per query (skeleton count, then the query). Acceptable — the executor already runs per-rollout, not per-token.
- `rows_scanned >= len(rows)` always holds, which is asserted in the executor tests.
- The definition is part of the frozen contract in spirit: changing it changes the reward function and therefore invalidates trained checkpoints just as a DSL change would.

## Reversal trigger

If slice 008 shows the policy collapsing toward trivially narrow plans, the fix is the reward *weight* in [0005](0005-grpo-primary-prime-ablation.md), not this definition. Revisit the definition only if profiling shows the skeleton count diverging badly from real query time on a full LogHub corpus — that would mean SQLite is choosing a different driving loop than the skeleton assumes.
