# 0004 — Reverse-generated gold data over LogHub corpora

**Date:** 2026-08-15
**Status:** Accepted
**Affects:** `packages/planner-rl` (data generation), `packages/logger` (ingest adapters)
**Slice:** [003](../slices/003-loghub-corpus-ingest.md), [004](../slices/004-reverse-generated-dataset.md)

## Context

Training needs (question, gold plan, gold row-IDs) triples at RL scale. The direction data is generated in determines whether the artifact's headline claim survives scrutiny.

The obvious approach — ask a frontier model to plan for a set of questions and treat its output as gold — quietly destroys the claim. If gold *is* the teacher's output, then "a small model matches the frontier model" reduces to "a small model imitates its teacher," which is both circular and unremarkable.

## Decision

**Generate backwards.** Sample a structured plan from the DSL space → execute it against the indexed corpus → the returned row IDs *are* the gold answer → then have a frontier model write the natural-language question a human would have asked to get that result.

Gold is therefore defined by **execution**, never by a teacher's judgment. The frontier model authors only the question — the input — so comparing against it later is a genuine comparison.

**Corpus:** LogHub public datasets (HDFS, BGL, Thunderbird, OpenStack, Spark, Hadoop). Public and citable means a stranger can reproduce the benchmark, which is what makes a portfolio result checkable rather than merely asserted. Per-dataset licensing must be verified before publishing anything derived from them.

**Eval:** a few hundred hand-audited pairs held out as the reported benchmark, separate from the auto-generated training pool.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Forward distillation from a frontier model | Circular against the headline claim, and hard-caps the student at teacher quality |
| Hand-curated pairs as training data | Realistic but orders of magnitude too slow to reach RL data volume; kept as the eval set instead |
| Synthetic generated log corpus | Perfect ground truth and controllable difficulty, but reviewers discount synthetic-only results heavily — the messiness of real logs is precisely the hard part being omitted |
| Own real work logs as the corpus | Not reproducible by anyone else, likely insufficient volume, and drags in the §2.4 governance question about work data |

## Consequences

- Question quality becomes the main data risk: reverse-generated questions can leak DSL vocabulary, be unanswerable, or be trivially keyword-matchable. Slice 004 needs explicit filters and a manual audit sample, not just volume.
- Sampling must be **stratified across DSL features** (decision [0003](0003-extend-the-query-dsl.md)), or the generator will overproduce trivial plans.
- Splits need contamination control — split by corpus and time window, not randomly by row, so test questions aren't near-duplicates of training ones.
- Requires frontier-model API spend for question authoring. Bounded and one-time per dataset regeneration.

## Reversal trigger

If the manual audit in slice 004 finds a high rate of unnatural or unanswerable questions, add a filtering pass or fall back to hand-curating a smaller, higher-quality training set. The reverse *direction* is not up for reconsideration — only the question-authoring quality.
