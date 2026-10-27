# 0012 — Aggregate results are a separate group list, not pseudo-rows

**Date:** 2026-08-15
**Status:** Accepted
**Affects:** `packages/logger` (index); `packages/planner-rl` (reward, slice 005 eval)
**Slice:** [002](../slices/002-extended-query-dsl.md)

## Context

Decision [0003](0003-extend-the-query-dsl.md) added template-level aggregation, so a query can answer "which templates spiked" rather than "show me matching lines". Reward, however, is defined as F1 over returned **row IDs** ([0002](0002-post-train-the-query-planner.md)), and an aggregate has no row IDs. How the result is represented decides how the reward handles it.

## Decision

A query carries an optional `aggregate` modifier over the same filter tree; it is not a separate plan mode. When set, the query returns `AggregateGroup(key, count)` values and **no rows**. `PlanResult` carries `rows`, `groups`, and `rows_scanned` side by side, so a plan may mix row queries and aggregate queries and each query's contribution stays addressable by its `label`.

Aggregation composes with everything else rather than replacing it: the same `where` tree applies, `having` filters on the resulting counts (how "templates that spiked" is expressed), and `group_by` takes up to two of `template_id` / `severity` / `location_key`. Groups are ordered by count descending, then by key ascending, so results are deterministic.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Aggregates as pseudo-rows with a synthetic ID | Keeps a single reward path, but the IDs would be positional artefacts: two plans that agree perfectly on counts could disagree on synthetic IDs, and F1 would report a difference that does not exist |
| Return matching row IDs *and* the groups | Also keeps one reward path, and is cheap to compute — but it makes `limit` ambiguous (does it cap rows or groups?) and lets a model score well on an aggregate question by retrieving rows and ignoring the aggregate entirely |
| Aggregation as a plan-level mode (a plan is aggregate *or* rows) | Simpler result type, but forbids the genuinely useful shape "count by template, and show me two examples" in one plan — and that shape is exactly the compositional depth slice 002 was asked to add |
| `count` only, no `group_by` or `having` | Matches the minimum in [0003](0003-extend-the-query-dsl.md), but the DSL freezes here. `having` is what makes spike detection expressible, and it cannot be added later without a retrain |

## Consequences

- **Slice 005 needs two reward paths**: row-ID F1 for row queries, and group-set comparison (key → count) for aggregate queries. This is the main cost of this decision and it is deliberate — it is cheaper than a reward that silently mis-scores every aggregate question.
- Slice 004's reverse-generated dataset must record which queries in a gold plan are aggregate, since gold is a group set rather than a row-ID set for those.
- `rows_scanned` is reported for aggregate queries exactly as for row queries, so the efficiency term needs no special case.

## Reversal trigger

If slice 005 shows the group-comparison reward path is a meaningful source of eval noise or implementation bugs, drop aggregate questions from the *training* distribution before changing the representation — the representation is frozen with the DSL, the sampling mix is not.
