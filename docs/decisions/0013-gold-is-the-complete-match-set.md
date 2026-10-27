# 0013 — Gold for a row query is its complete match set, never a limit-truncated page

**Date:** 2026-10-27
**Status:** Accepted
**Affects:** `packages/planner-rl` (data generation; reward and eval in slices 005, 008)
**Slice:** [004](../slices/004-reverse-generated-dataset.md)

## Context

Gold is whatever the sampled plan returns when executed (decision [0004](0004-reverse-generated-gold-over-loghub.md)). But a row query's result depends on `limit` (default 50) and `order`, and those are artefacts of the plan, not of the question. If the sampler emitted `limit: 50` over a 400-row match set, gold would be "the 50 newest", and a model that correctly retrieved all 400 would be scored as low precision for being right.

## Decision

Sampled row queries are emitted with `limit = MAX_LIMIT` (1000). Any query that returns exactly `MAX_LIMIT` rows is **rejected** (`truncated_rows`), because the true match set may be larger. Gold row IDs are therefore always the complete set of rows the filter matches, independent of `limit` and `order`. Aggregate queries are treated the same way: reject at `MAX_LIMIT` groups (`truncated_aggregate`).

Separately, a row query matching more than 25% of its split is rejected (`too_broad`). At this point the "answer" is most of the corpus, and the question is not a retrieval question.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Keep the sampled `limit`/`order` and let gold be the truncated page | Makes the reward punish correct recall, and makes `limit` a hidden part of the answer that no natural question expresses ("show me errors" does not say "the 50 newest") |
| Gold = full match set, but sampler still emits small limits | The gold plan would not reproduce its own gold, which breaks the invariant that `execute(gold_plan) == gold` — the cheapest end-to-end check on the whole pipeline |
| Allow broad plans and have the author ask for "the latest N" | Expressible, but teaches the planner that limit/order carry meaning in most questions, when in real use they rarely do. If "latest N" questions turn out to matter, add them as their own stratum |

## Consequences

- Every gold plan re-executes to exactly its gold (pinned by a test), so data bugs show up as a test failure, not as a quietly wrong benchmark.
- Very broad questions ("all INFO lines") are excluded from the row-query distribution. Aggregates cover the "how much of X" shape instead.
- The reward in slice 005 must not penalise a predicted plan for choosing a different `limit`, except where the limit truncates its own result.

## Reversal trigger

If the slice 005 hand-curated eval set contains a meaningful share of "latest N" / "first N" questions, add an ordered-page stratum with gold defined as that page, alongside this rule rather than replacing it.
