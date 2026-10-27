# 0010 — Relative time bounds resolve against the corpus's newest timestamp, not wall-clock

**Date:** 2026-08-15
**Status:** Accepted
**Affects:** `packages/logger` (index, timeutil); source of truth §3.1
**Slice:** [002](../slices/002-extended-query-dsl.md)

## Context

The DSL accepts relative bounds (`-24h`, `-30m`). Something has to supply the "now" they are subtracted from, and the obvious answer — `datetime.now()` — breaks both halves of this project at once.

- **Training:** reward must be replayable. The same plan executed on Tuesday and on Thursday would return different row sets, so gold row IDs computed at dataset-generation time silently stop matching. Decision [0002](0002-post-train-the-query-planner.md) depends on reward being deterministic given a fixed corpus and seed.
- **Benchmarking:** LogHub corpora ([0004](0004-reverse-generated-gold-over-loghub.md)) are archival — HDFS is from 2008. Against wall-clock, *every* relative query returns zero rows, so the whole time-range feature would train the model that time filters are a way to return nothing.

## Decision

`LogIndex.reference_now()` returns `MAX(timestamp)` over the index, falling back to wall-clock UTC only when the index holds no timestamps at all. Relative bounds resolve against that instant. Callers can override it per execution (`index.execute(plan, now=...)`), which is what the eval harness and the dataset generator will pin.

Supporting change: timestamps are normalized to fixed-width canonical UTC ISO-8601 **at ingest**, so SQLite's lexicographic string comparison is chronological comparison. Unparseable timestamps are stored verbatim and simply never match a time range.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Wall-clock `datetime.now()` | Non-replayable reward, and returns nothing on every archival corpus — it would teach the model that time filters are a way to produce empty results |
| Absolute ISO bounds only | Fully deterministic, but "errors in the last hour" is the single most common real log question, and forcing the planner to synthesize an absolute instant it cannot know makes the tool worse to use interactively |
| A `now` field inside the plan itself | Makes each plan self-contained, but puts a value the model must invent into the training target — the model would be rewarded for guessing a timestamp rather than for planning |
| Store epoch integers instead of ISO text | Cleaner comparison semantics, but breaks the existing `timestamp TEXT` column and its readability in `felix logger query` output, for a problem fixed-width normalization already solves |

## Consequences

- A corpus's "now" moves as it is ingested. Within a frozen corpus (slice 003 writes a manifest with a content digest) it is stable, which is the property that matters.
- The eval harness must pass an explicit `now` so that a re-run against a re-ingested corpus is bit-identical.
- Ingest normalization means a database written before this slice has non-canonical timestamps and will compare wrongly. There are no such databases outside local dev, so no migration was written — this is the accepted shortcut.

## Reversal trigger

If a real interactive use of Logger on *live* logs makes corpus-relative "now" feel wrong (yesterday's tail is treated as "now"), add an explicit `--now` CLI flag rather than switching the default — the training path needs the deterministic default to stay the default.
