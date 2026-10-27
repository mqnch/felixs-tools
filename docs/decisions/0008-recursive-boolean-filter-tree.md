# 0008 — A recursive boolean filter tree, not flat filter fields

**Date:** 2026-08-15
**Status:** Accepted
**Affects:** `packages/common` (`query_plan`), `packages/logger` (index, validator, planner); source of truth §3.1
**Slice:** [002](../slices/002-extended-query-dsl.md)

## Context

Decision [0003](0003-extend-the-query-dsl.md) called for negation and OR groups. The obvious way to add them to the existing DSL is more fields on the same flat `filters` object — `not_terms`, `not_severities`, `not_template_ids`, and an `any_of` list of alternative clauses. That is what slice 002 was originally written against.

Two things argued against it. First, decision [0006](0006-qwen3-base-models.md) was corrected mid-slice to Qwen3.5 (0.8B/2B/4B) — materially stronger at structured output than the generation the DSL difficulty was implicitly sized for, which makes slice 005's ≥0.85 F1 trip-wire more likely to fire. Second, a flat field list is *surface* difficulty: each field is independently learnable, and a strong instruction-tuned model gets each one right in isolation. What such models actually fumble is **composition** — scoping a negation to one branch of a disjunction, nesting correctly, not distributing an operator wrongly.

## Decision

One recursive boolean expression per query. `and` / `or` / `not` nest freely (to depth 6, 8 children per group) over five leaf predicates: `term`, `severity`, `template_id`, `location_key`, `time_range`.

```json
{"op":"or","of":[
  {"op":"and","of":[{"op":"severity","value":"ERROR"},
                    {"op":"not","of":[{"op":"term","value":"healthcheck"}]}]},
  {"op":"severity","value":"CRITICAL"}]}
```

`of` is always a list, including for `not`, which takes exactly one child. There is exactly **one** way to express any given filter — no shorthand fields alongside the tree — because a training contract with two spellings of the same meaning weakens the format reward.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Flat `filters` with `not_*` lists and a one-level `any_of` | Cheaper to emit and to validate, but negation cannot be scoped inside a disjunct, so the hardest and most useful case — `(A AND NOT B) OR C` — is inexpressible. Also adds surface breadth rather than compositional depth, which is the wrong kind of difficulty against a Qwen3.5-class baseline |
| Both: a flat shorthand plus the tree for complex cases | Two encodings of the same filter. The model can satisfy the format reward two ways, gold plans become non-canonical, and duplicate-plan detection stops working |
| Arbitrary nesting with no depth or fan-out limit | Unbounded worst-case SQL generation and unbounded prompt length, for expressiveness no real log question needs. Depth 6 already exceeds anything in the hand-written eval set |
| Constrained SQL subset | Already rejected in [0003](0003-extend-the-query-dsl.md) — turns the project into text-to-SQL |

## Consequences

- Every filter feature composes with every other one, so slice 004's stratified sampler must stratify over *tree shapes* (depth, presence of `not` under `or`) and not just over which leaves appear.
- SQL generation must handle three-valued logic explicitly: `NOT (severity = 'INFO')` is NULL, not true, for a row with no severity. The executor wraps every negation in `NOT COALESCE(expr, 0)`. This is pinned by de Morgan equivalence tests, because it is the single most likely place for a silent correctness bug.
- Trivial questions cost more tokens than they would under the flat shape. Accepted: interactive latency is dominated by prefill on a sub-2B model, not by twenty extra output tokens.
- The DSL is frozen at `SCHEMA_VERSION = "1.0.0"`.

## Reversal trigger

Slice 005 measures stock Qwen3.5-2B. If it scores ≥ ~0.85 retrieved-set F1 the DSL is still too easy and reopens ([0003](0003-extend-the-query-dsl.md)). If instead stock models fail almost entirely on *syntax* rather than on semantics — malformed trees rather than wrong trees — the encoding is the problem, not the task, and a terser node spelling should be considered before concluding the task is hard.
