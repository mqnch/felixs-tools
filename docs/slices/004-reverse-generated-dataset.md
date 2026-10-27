# 004 — Reverse-generated training dataset

**Date:** planned
**Status:** Planned
**Touches:** `packages/planner-rl`
**Decisions:** [0004](../decisions/0004-reverse-generated-gold-over-loghub.md), [0003](../decisions/0003-extend-the-query-dsl.md)
**Depends on:** 002 (DSL frozen), 003 (corpus indexed)

## What a person can now do

Generate `(question, gold_plan, gold_row_ids)` triples at scale, with train/val/test splits and a manifest.

```bash
uv run planner-rl gen-data --corpus corpora/hdfs.db --n 20000 --out data/hdfs/
uv run planner-rl audit-data data/hdfs/ --sample 100
```

## Scope

The pipeline, in order: **sample a plan → execute it → row IDs become gold → frontier model writes the question.** Gold is defined by execution, never by a teacher's judgment — that is what keeps the "matches frontier" claim non-circular.

- **Stratified sampling** across DSL features, so time ranges, negation, OR groups, aggregation, and multi-query all appear at target rates. Uniform sampling will overproduce trivial single-filter plans.
- Rejection filters: plans returning zero rows, or nearly the whole corpus; questions that leak DSL vocabulary (`template_id`, `severity=`); questions answerable by a single keyword match when the gold plan is complex; near-duplicate questions.
- **Contamination control:** split by corpus and time window, never randomly by row, so test questions are not near-duplicates of training ones.
- **Manual audit** of a sampled subset — naturalness, answerability, and whether the gold plan is genuinely the best plan for the question.
- Manifest: generator model, prompt version, seed, DSL schema version, per-feature counts.

## Deliberately not in this slice

- **No hand-written training data.** Hand curation is reserved for the held-out eval set in slice 005.
- **No difficulty curriculum.** Flat sampling first; curriculum only if RL stalls.
- **No multi-turn / refinement traces.** Single-shot planning only — multi-turn was considered and set aside as high-risk.
- **No paraphrase augmentation.** Adds volume without adding signal, and risks inflating apparent test performance.

## Risk

This is the highest-risk slice in the workstream. Data quality caps every downstream result, and its failures are quiet — a subtly leaky question distribution produces good benchmark numbers and a model that fails on real questions. The manual audit is not optional polish.

## What this unlocks

Slice 005's eval harness and every training slice.
