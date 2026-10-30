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

First real dry runs (2026-10-30, `--n 300`), one gen-data run per corpus, train examples accepted out of 240:

| Corpus | Templates | Train accepted |
|---|---|---|
| HDFS, 200k-row sample | 29 | stalled; `--n 20000` was killed after 25 min at 3.5k |
| HDFS, 20k-row sample | 20 | 166 (gave up; 8355/9600 attempts `truncated_rows`) |
| OpenStack, 50k → 20k | 49 → 40 | 198 → **240** |
| BGL, 50k → 20k | 258 → 203 | crashed → 231 → **240** (after decision [0015](../decisions/0015-fold-bgl-severities-into-the-dsl-enum.md)) |
| Hadoop, 50k | 261 | **240** |

HDFS is too low-diversity for row queries under `MAX_LIMIT` at any useful size. The other three fill every stratum at 20–50k rows. Details are in [friction.md](../friction.md). The OpenStack, Spark and Thunderbird archive URLs were also wrong (404) and are now fixed. One design misjudgment was caught in testing before it shipped: the first breadth cap (5% of the split) rejected >90% of sampled plans on small corpora. The spec only asked to reject "nearly the whole corpus".

## What this unlocks

Slice 005 (eval harness + baselines) once a real dataset exists and has passed the audit. Next steps, in order:

1. `felix logger ingest-corpus` one LogHub dataset (HDFS is the smallest that is realistic).
2. `gen-data --dry-run`, then check the strata and rejection mix in the manifest.
3. A small paid run (`--n 300`), then audit 100. Only scale to 20k if the audit passes.

### Paid pilots and audit (2026-10-30)

`--n 300` per corpus on Hadoop-50k, BGL-20k and OpenStack-20k, with `claude-haiku-5.5` via OpenRouter ([0016](../decisions/0016-openrouter-as-a-second-authoring-provider.md)). Each audit is 34 rows per corpus on a fresh seed. **The audits were a Claude first pass, not a human**, and are marked `[claude first pass]` in each sheet's notes. A human spot-check is still owed before the 20k run.

| Run | Prompt | Change | natural | answerable |
|---|---|---|---|---|
| pilot | q-2026-10-27.1 | (baseline) | not audited: 70% said "up to 1000" | |
| pilot2 | q-2026-10-30.1 | hide default limit/order | 85% | **75%** (fails) |
| pilot3 | q-2026-10-30.2 | location/window rendering, shape and sample rules, `noop_conjunct`, term stoplist | not audited: author saw stale templates | |
| pilot4 | q-2026-10-30.2 | general template text (`CorpusView.template_text`) | 90% | **86%** (BGL 76%) |
| pilot5 | q-2026-10-30.3 | hide aggregate group keys from the author | 92% | **99%** |

Total spend across all pilots: $1.25. Remaining weak spot: `multi_query` naturalness (60–89%), because the sampler composes unrelated queries into one question. OpenStack train fills 164/240, since most of its AND plans are now correctly rejected as `noop_conjunct`.

### Full run (2026-10-30)

Prompt `q-2026-10-30.3`, `anthropic/claude-haiku-5.5` via OpenRouter, ~$7.75 (about $0.52 per 1k accepted). 14,815 examples total.

| Corpus | train | val | test | Weak strata (train) |
|---|---|---|---|---|
| Hadoop-50k | 6400/6400 | 800/800 | 800/800 | none |
| BGL-20k | 3473/5600 | 377/700 | 436/700 | conjunction 264, negation 161 |
| OpenStack-20k | 1951/4000 | 330/500 | 248/500 | conjunction 55, negation 64; test has 0 conjunction |

BGL and OpenStack hit the attempt cap. The main losses were `truncated_rows`, `too_broad` and `noop_conjunct`. Only Hadoop is balanced across strata. Conjunction and negation scores on BGL and OpenStack test sets will be too noisy to report alone in slice 005.
