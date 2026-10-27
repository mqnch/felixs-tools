# 0009 — The plan schema lives in `common`; validation and execution stay in `logger`

**Date:** 2026-08-15
**Status:** Accepted
**Affects:** `packages/common`, `packages/logger`, `packages/planner-rl`; source of truth §7 step 1
**Slice:** [002](../slices/002-extended-query-dsl.md)

## Context

Slice 002 left the schema's home open: `common` "if Swarm will ever reference it, otherwise `logger`". Swarm is deferred and speculative, so on §2.2 grounds ("generalize only on demonstrated pain") that clause alone points at `logger`.

But `common`'s stated rule is stronger than a Swarm hypothetical: *"add shared contracts here before duplicating shapes in other packages"*, and §7 step 1 defines `common` as "the shared contract everything else is built against." The live second consumer is not Swarm — it is `packages/planner-rl` (decision [0007](0007-planner-rl-package-placement.md)), which samples plans in slice 004, scores their format validity in slice 007+, and mirrors to a standalone public repo. That is a real, dated, already-planned dependency, not a speculative one.

## Decision

Split by the `common` rule that already exists — types there, logic elsewhere:

| Lives in `common/query_plan.py` | Lives in `logger` |
|---|---|
| `SCHEMA_VERSION`, DSL limits | `validator.validate_plan()` |
| `QueryPlan` / `Query` / filter nodes / `Aggregate` | `LogIndex.execute()` and SQL generation |
| `PlanErrorCode` / `PlanError` / `PlanValidation` | `timeutil` bound resolution |
| — | `QueryResult` / `PlanResult` / `AggregateGroup` |

The error *taxonomy* is a contract (planner-rl keys reward on the codes), so it sits in `common`. The rules that decide when each code fires are logic, so they sit in `logger`. Execution **results** stay in `logger` because they are shaped by how Logger's index works, not by the emit-side contract.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Everything in `logger` | Makes `planner-rl` — a package that mirrors out publicly — depend on all of Logger (drain3, sqlite, scorer) just to construct and check a plan. It also puts the frozen training contract inside the package most likely to keep changing |
| Schema *and* validator in `common` | Would violate `common`'s "no business logic" rule for the sake of one import. Validation is a few hundred lines of rules with real judgment in them, and `common` staying inert is what makes it safe to depend on |
| A fourth package (`query-dsl`) | A package for one module, against §2.1's litmus test and the four-package rule. Nothing is gained that the `common` split does not already give |
| Results (`PlanResult`) in `common` too | They encode Logger's row/group model. Putting them in `common` would freeze Logger's storage shape into the shared contract for no current consumer |

## Consequences

- `common` gains a pydantic v2 module with real field constraints. This is the first time `common` carries anything beyond inert shapes; the boundary held is "declarative constraints yes, rules no."
- Bumping `SCHEMA_VERSION` is now a `common` change, which makes it visible to every package at once — the intended effect, given a post-freeze DSL change is a retrain, not an edit ([0002](0002-post-train-the-query-planner.md)).
- `planner-rl` will depend on `common` for the contract and on `logger` for execution-based reward. That is the correct split: the reward needs the executor, the sampler does not.

## Reversal trigger

If a second package ever needs the *validator* (not just the schema) without needing the executor — a plausible shape for a Swarm preset that checks a plan before dispatching it — move `validator.py` behind a narrow interface rather than duplicating it. Nothing about this decision makes that harder.
