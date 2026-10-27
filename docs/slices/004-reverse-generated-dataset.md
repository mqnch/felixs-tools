# 004 — Reverse-generated training dataset

**Date:** 2026-10-27 (planned 2026-08-15)
**Status:** In progress — pipeline built and tested; first real-corpus run and the manual audit are still to do
**Touches:** `packages/planner-rl` (new package: `planner_rl.data`, `cli`)
**Source of truth:** §3.1, §3.3, §7 step 2a
**Decisions:** [0004](../decisions/0004-reverse-generated-gold-over-loghub.md), [0003](../decisions/0003-extend-the-query-dsl.md), [0013](../decisions/0013-gold-is-the-complete-match-set.md), [0014](../decisions/0014-question-authoring-bypasses-router.md)
**Depends on:** 002 (DSL frozen), 003 (corpus indexed)

## What a person can now do

Generate `(question, gold_plan, gold_row_ids)` triples from any slice-003 corpus, with time-window train/val/test splits and a manifest. Then audit a sample by hand and get a pass/fail against decision 0004's reversal trigger.

```bash
uv run planner-rl gen-data --corpus corpora/hdfs.db --n 20000 --out data/hdfs/ --dry-run   # free: strata + rejections only
uv run planner-rl gen-data --corpus corpora/hdfs.db --n 20000 --out data/hdfs/             # authors questions (paid)
uv run planner-rl audit-data data/hdfs/ --sample 100                                       # writes data/hdfs/audit.csv
uv run planner-rl audit-data data/hdfs/ --score data/hdfs/audit.csv                        # exit 1 if the trigger fires
```

## How it works

`sample a plan → execute it → gold → author the question → filter`, per split, in `planner_rl/data/`:

- **`corpus`**: cuts the corpus by timestamp into 80/10/10 windows, giving `train.db`, `val.db` and `test.db`, each a full `LogIndex` with row IDs preserved. Gold is defined against the split DB, so test gold cannot reference training rows, and `-6h` resolves against the split's own newest row.
- **`sampler`**: seven strata (`single_leaf`, `conjunction`, `negation`, `disjunction`, `time_range`, `aggregate`, `multi_query`). Each plan is grounded in a random *anchor row*, so its leaves can match. The pipeline draws toward whichever stratum is furthest under its target share of *accepted* examples. That matters because rejection rates differ a lot by stratum.
- **`gold`**: executes the plan and rejects anything that is empty, truncated (0013), more than 25% of the split, or redundant. Redundant covers a `not` that excludes nothing, an `or` branch that adds nothing, and a query that is a subset of a sibling. All of this happens before any model call.
- **`author`**: Claude Opus 5.5 writes only the question, via structured output, and may decline with `expressible: false`. Calls go direct, not through Router (0014). `PROMPT_VERSION` goes on every example.
- **`filters`**: DSL-vocabulary leaks; keyword-trivial questions (for any non-single-leaf plan, one content word alone reaching F1 ≥ 0.9 against gold); near-duplicates (Jaccard ≥ 0.8 on content words, one index shared across all splits).
- **`audit`**: CSV sheet with three y/n judgments (natural, answerable, best plan), scored overall and per stratum.

The invariant `execute(gold_plan) == gold`, and that gold stays inside its split, is pinned by a test.

## Deliberately not in this slice

- **No real-corpus run yet.** No LogHub corpus is staged in this checkout and generation costs API money. The first real run, and the audit of it, is what moves this slice to Shipped.
- **No hold-out by corpus inside one dataset.** One `gen-data` run covers one corpus. Holding a whole corpus out (e.g. train on HDFS+BGL, test on Spark) is done in slice 005 by choosing which corpus directories to evaluate on.
- **Synchronous authoring, one call at a time.** The Batch API would halve the cost and concurrency would cut the wall-clock, but neither is worth building before the first audit says the questions are good.
- **No hand-written training data, no curriculum, no multi-turn traces, no paraphrase augmentation**, all as planned.
- **The 25% breadth cap is a guess.** On a 200k-row corpus `MAX_LIMIT` binds long before it does. It only matters for small corpora.

## Decisions made here

- [0013](../decisions/0013-gold-is-the-complete-match-set.md): gold is the complete match set; sampled row queries use `MAX_LIMIT` and are rejected if they hit it.
- [0014](../decisions/0014-question-authoring-bypasses-router.md): question authoring calls the Anthropic SDK directly, so the manifest can pin the exact model.

## Friction observed

None yet, since this has not been run on a real corpus. One design misjudgment was caught in testing before it shipped: the first breadth cap (5% of the split) rejected >90% of sampled plans on small corpora. The spec only asked to reject "nearly the whole corpus".

## What this unlocks

Slice 005 (eval harness + baselines) once a real dataset exists and has passed the audit. Next steps, in order:

1. `felix logger ingest-corpus` one LogHub dataset (HDFS is the smallest that is realistic).
2. `gen-data --dry-run`, then check the strata and rejection mix in the manifest.
3. A small paid run (`--n 300`), then audit 100. Only scale to 20k if the audit passes.
