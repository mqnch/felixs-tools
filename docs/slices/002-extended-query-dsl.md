# 002 — Extended query DSL, validator, and executor

**Date:** 2026-08-15
**Status:** Shipped
**Touches:** `packages/common`, `packages/logger`, `cli`
**Source of truth:** §3.1
**Decisions:** [0002](../decisions/0002-post-train-the-query-planner.md), [0003](../decisions/0003-extend-the-query-dsl.md), [0008](../decisions/0008-recursive-boolean-filter-tree.md), [0009](../decisions/0009-plan-schema-in-common.md), [0010](../decisions/0010-corpus-relative-time-resolution.md), [0011](../decisions/0011-rows-scanned-positive-skeleton.md), [0012](../decisions/0012-aggregates-as-groups-not-rows.md)

## What a person can now do

Write a compositional query plan by hand, execute it deterministically, and get validation errors that name the exact failure and the exact node.

```bash
uv run felix logger query --plan '{"queries":[{"label":"recent","where":{"op":"and","of":[
  {"op":"term","value":"timeout"},
  {"op":"severity","value":"ERROR"},
  {"op":"not","of":[{"op":"term","value":"healthcheck"}]},
  {"op":"time_range","since":"-24h"}]},"limit":50}]}'

uv run felix logger query --plan @plan.json --json
uv run felix logger validate-plan plan.json --json
```

## The DSL, as frozen

`SCHEMA_VERSION = "1.0.0"`, in `common.query_plan`. A plan is a small set of queries whose rows union:

```json
{"version": "1.0.0",
 "queries": [{"label": "…", "where": <node>, "limit": 50, "order": "newest",
              "aggregate": {"op": "count", "group_by": ["template_id"],
                            "having": {"min_count": 10}}}]}
```

`where` is **one recursive boolean expression**, not a bag of filter fields ([0008](../decisions/0008-recursive-boolean-filter-tree.md)):

| Node | Shape |
|---|---|
| `and` / `or` | `{"op":"and","of":[<node>,…]}` — 2–8 children, nesting to depth 6 |
| `not` | `{"op":"not","of":[<node>]}` — exactly one child |
| `term` | `{"op":"term","value":"timeout"}` — FTS5 phrase over raw line + mined template |
| `severity` | `{"op":"severity","value":"ERROR"}` — case-insensitive, `WARNING` → `WARN` |
| `template_id` | `{"op":"template_id","value":7}` |
| `location_key` | `{"op":"location_key","value":"api:svc/app.log"}` |
| `time_range` | `{"op":"time_range","since":"-24h","until":"2026-07-23T10:00:00Z"}` — ISO instant or `-<n>[smhdw]`, both bounds inclusive |

Negation and disjunction are structural, so `(ERROR AND NOT healthcheck) OR CRITICAL` is expressible — that was the point, and it is what a flat `not_terms` / `any_of` shape could not do.

## How it works

- **`common/query_plan.py`** — pydantic v2 models, `SCHEMA_VERSION`, DSL limits, and the `PlanErrorCode` / `PlanError` / `PlanValidation` shapes. Types only; `common`'s no-logic rule holds ([0009](../decisions/0009-plan-schema-in-common.md)). Every model is `extra="forbid"`, so an invented field is a rejection rather than a silent no-op.
- **`logger/validator.py`** — `validate_plan(str | bytes | dict | QueryPlan) → PlanValidation`. Never raises. Each error carries a code, a path (`$.queries[1].where.of[0].value`), a message, and the offending value. Pydantic's structural errors are mapped into the same taxonomy and the same path format, so a consumer cannot tell which half produced an error. 24 codes, grouped: payload/structure, plan shape, tree shape, leaf values, contradictions.

  **Error reporting is complete per stage, not per plan.** Validation runs in two stages — pydantic structural, then semantic — and the semantic stage is skipped entirely if the structural stage fails, because semantic checks require an already-validated model. So a plan with both a bad severity *and* an out-of-range `limit` reports only the severity; fixing it reveals the limit error on the next call. Within a single stage, every error is reported (two bad severities give two errors). Verified by probe, not assumed.

  Consequence for slice 008: a **graded** format reward based on error *count* would be misleading, since the count understates total faults and a model that fixes all structural errors gets a "progress" signal immediately followed by a fresh failure. A binary valid/invalid format term is unaffected. Decide this deliberately when designing the reward rather than inheriting it by accident.
- **`logger/index.py`** — `LogIndex.execute(plan, now=…) → PlanResult` and `LogIndex.query(query, now=…) → QueryResult`. SQL is generated straight from the tree with no rewriting; plans execute as written. Negation is emitted as `NOT COALESCE(expr, 0)` so a NULL column reads as "did not match" rather than "unknown" — a row with no severity is correctly kept by `not severity=INFO`.
- **`logger/timeutil.py`** — ingest normalizes timestamps to fixed-width canonical UTC ISO-8601, which makes SQLite's lexicographic comparison chronological. Relative bounds resolve against `MAX(timestamp)` in the index, not wall-clock ([0010](../decisions/0010-corpus-relative-time-resolution.md)).
- **`rows_scanned`** — measured with a `COUNT(*)` over the plan's *positive skeleton* (the tree with every `not` replaced by TRUE), summed across queries ([0011](../decisions/0011-rows-scanned-positive-skeleton.md)). Positive filters narrow it; negation and disjunction never do.
- **Untrusted terms** — terms are model-generated. They are bound as SQL parameters, and additionally escaped as FTS5 phrases (doubled quotes, control characters stripped) so a term cannot inject FTS *query* syntax such as `NEAR` or a column filter.
- **The planner still calls the Router stub.** No model is involved in this slice. Because the stub emits the slice-001 plan shape and Router is not this slice's to change, the planner adapts that shape to the frozen DSL and otherwise falls back to a deterministic keyword plan — `felix logger search` behaves as before.

## Difficulty headroom

Written before slice 005 measures it, so the prediction is falsifiable. Expectation for a **stock Qwen3.5-2B**, prompted with the schema:

| Expected to get right zero-shot | Expected to fumble |
|---|---|
| Single-leaf queries; `severity` and `term` selection | **Scoping a negation inside one branch of a disjunction** — the `(A AND NOT B) OR C` shape. Expect flattening to `(A OR C) AND NOT B` |
| Flat `and` of two or three leaves | **Nesting past depth 3** — expect a collapsed tree that is valid JSON and wrong semantics |
| `not` at the top of a query | **Choosing `or` over multiple queries** — the two are near-synonyms for row union, and gold prefers one query with `or`; expect over-decomposition, which the efficiency term penalises |
| Absolute `since` when the question states a date | **Relative offsets** — expect wall-clock reasoning and invented absolute timestamps rather than `-24h` |
| `aggregate.group_by` when the question says "count by" | **`having`** — expect "templates that occurred more than 10 times" to come back as an unfiltered group list |
| The `{"op":…}` envelope itself | **Complementary decomposition** — labelled before/after windows in one plan, rather than one broad query |

If the fumbles above turn out to be *syntax* failures (malformed trees) rather than *semantic* ones (well-formed, wrong), the encoding is the problem, not the task — see [0008](../decisions/0008-recursive-boolean-filter-tree.md)'s reversal trigger.

## Deliberately not in this slice

- **No model involvement at all.** Pure deterministic tooling; the planner still calls the Router stub, and the prompt describing the new DSL is a placeholder for slice 011, not a tuned prompt.
- **No SQL passthrough** — rejected in [0003](../decisions/0003-extend-the-query-dsl.md).
- **No query optimizer.** No predicate reordering, no rewriting, no index hinting. `rows_scanned` reports what a naively-executed plan cost, and efficiency is taught by reward ([0005](../decisions/0005-grpo-primary-prime-ablation.md)), not enforced by the engine.
- **No time-range inference from raw log lines.** `felix logger ingest` still stores no timestamp unless the caller supplies one, so `time_range` filters match nothing on a plain `ingest` of an unstructured file. Corpus-specific timestamp extraction is slice 003's, and the corpus ingest path already passes timestamps through.
- **No `not_location_key`, no `service` / `path` leaves, no regex leaf, no numeric parameter comparisons.** Negation was specified over terms, severities, and templates; the tree gives it over all five leaves for free, and nothing beyond that had a demonstrated need (§2.2).
- **No set operations between queries** (intersect, difference). Plan-level combination is union only — `and` / `not` inside a single query already express intersection and difference, and a second spelling would weaken the format reward.
- **No migration for pre-existing databases.** Ingest now normalizes timestamps; a database written before today compares wrongly against `time_range`. Accepted knowingly — no such database exists outside local dev. Re-ingest rather than migrate.
- **No `PlanResult` in `common`.** Results are shaped by Logger's storage, not by the emit-side contract ([0009](../decisions/0009-plan-schema-in-common.md)).
- **Cut from the original slice text:** the `{"terms":[…],"filters":{…}}` shape in this document's first draft was replaced outright by the filter tree. It was written before decision [0006](../decisions/0006-qwen3-base-models.md) was corrected to Qwen3.5, and it added surface breadth where the difficulty gate needs compositional depth.

## Decisions made here

- [0008](../decisions/0008-recursive-boolean-filter-tree.md) — recursive boolean tree, not flat filter fields
- [0009](../decisions/0009-plan-schema-in-common.md) — schema in `common`, validator and executor in `logger`
- [0010](../decisions/0010-corpus-relative-time-resolution.md) — relative times resolve against the corpus's newest timestamp
- [0011](../decisions/0011-rows-scanned-positive-skeleton.md) — `rows_scanned` as the positive skeleton's row count
- [0012](../decisions/0012-aggregates-as-groups-not-rows.md) — aggregate results as groups, not pseudo-rows

## Tests

129 tests across the executor, the validator, and the planner. The executor suite deliberately over-covers the places SQL generation breaks: de Morgan equivalence in both directions, double negation, negation scoped inside one `or` branch, NULL-column negation, inclusive time bounds, mixed-timezone ingest, and eleven hostile FTS terms. The validator suite asserts one test per error code, plus that all errors are reported rather than the first, and that a semantically-invalid-but-parseable plan still exposes its parsed form — reward needs "unparseable" and "parsed but wrong" to be distinguishable.

## Friction observed

None that cost real time. One thing worth noting for later: pydantic inserts the discriminator tag into its error paths (`…where.and.of[1]`) while the semantic checks do not, so the two halves of the validator produced different path formats for the same node. Caught by a test rather than in production, but it is exactly the kind of inconsistency that would have made the format reward key on the wrong thing.

## Exit condition

**The DSL is frozen at `SCHEMA_VERSION = "1.0.0"`.** Post-freeze changes invalidate the dataset and every checkpoint together ([0002](../decisions/0002-post-train-the-query-planner.md)) — a DSL change from here is a retrain, not an edit.

## What this unlocks

- **004** — the reverse-generated dataset can now sample plans and execute them for gold row IDs. Its sampler must stratify over *tree shapes*, not just over which features appear, or it will overproduce flat two-leaf plans.
- **005** — the eval harness, and the go/no-go difficulty gate that tests the prediction above. It needs two reward paths (row-ID F1, group-set comparison) per [0012](../decisions/0012-aggregates-as-groups-not-rows.md), and must pin an explicit `now` per [0010](../decisions/0010-corpus-relative-time-resolution.md).
- **011** — wiring a trained planner back in is now a matter of replacing the Router call in `QueryPlanner.plan()`; validation and execution are already in place around it.
