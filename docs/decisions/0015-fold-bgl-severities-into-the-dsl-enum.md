# 0015 — Fold BGL's SEVERE and FAILURE into the frozen severity enum at ingest

**Date:** 2026-10-30
**Status:** Accepted
**Affects:** `packages/logger` (`corpora.loghub.BglAdapter`, `corpora.base.normalise_severity`)
**Slice:** [004](../slices/004-reverse-generated-dataset.md)

## Context

Slice 003 kept BGL's full level vocabulary (`INFO WARN ERROR SEVERE FATAL FAILURE`) on purpose, so as not to lose a distinction in the source. Slice 002 then froze the DSL with a severity enum of `DEBUG INFO WARN ERROR CRITICAL FATAL`. The two were never checked against each other. The first real `gen-data --dry-run` on BGL crashed when the sampler built `SeverityNode(value="SEVERE")`. It affects 214 of 50,000 sampled rows (191 `SEVERE`, 23 `FAILURE`), but any anchor row with one of those levels can trigger it.

## Decision

`BglAdapter` folds `SEVERE → ERROR` and `FAILURE → FATAL`, using each level's nearest neighbour in BGL's own ordering (`INFO < WARN < SEVERE < ERROR < FATAL < FAILURE`). The raw level is kept in `extra["level"]` for folded rows only. The fold lives in the adapter, not in the shared `normalise_severity`, because it changes meaning and only BGL needs it.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Add `SEVERE` and `FAILURE` to the DSL enum | Breaks the slice 002 freeze. It's cheap now since nothing is trained, but the values would be BGL-only, and the model would learn enum members that no other corpus uses |
| Drop SEVERE/FAILURE rows at ingest | These are among the most alert-like lines in BGL, and dropping them biases the corpus toward routine traffic |
| `FAILURE → CRITICAL` | The DSL orders `CRITICAL` below `FATAL`, so this would rank BGL's most severe level below its second most severe |
| Have the sampler skip severities that aren't in the enum | Leaves rows in the index whose severity no plan can express, so gold for severity filters would silently miss them |

## Consequences

- The 50k BGL corpus was rebuilt after this change, so its content digest differs from the pre-fold build.
- The distinction is preserved in the `corpus_records` sidecar but is not queryable. A question that depends on "SEVERE vs ERROR" cannot be expressed, and none will be generated.
- Ingest still does not check adapter severities against the DSL enum in general. A future adapter could reintroduce this bug, and the adapter test only checks each adapter's own declared vocabulary.

## Reversal trigger

The DSL is reopened for any other reason before training starts. At that point, decide whether a finer severity scale is worth adding at the same time.
