# 0022 — The author no longer sees sample lines; questions that described them are re-authored in place

**Date:** 2026-10-30
**Status:** Accepted
**Affects:** `packages/planner-rl` (`data.author` prompt q-2026-10-30.4, `data.filters`, `data.repair`, `repair-data --fix reauthor-unsupported-detail`)
**Slice:** [004](../slices/004-reverse-generated-dataset.md), found in [005](../slices/005-eval-harness-and-baselines.md)

## Context

Reviewing Sonnet's eval failures turned up questions that narrow what the plan returns: "the task progress lines from X" when the plan returns every line from X, or "GET requests to servers/detail" when the plan returns the whole HTTP-request template. The words come from the sample lines the author was shown, despite an explicit rule against describing them. This is the third time a prompt rule lost to visible data. The first two were limit/order and the aggregate group keys, and both times hiding the data fixed it.

## Decision

1. **Prompt q-2026-10-30.4.** The author sees the plan, its template texts, locations and windows, but **no sample lines**. Two rules are added:
   - a location means every line from it, so don't narrow it or list examples;
   - an `or` must read as either/or.
2. **Detector** `filters.unsupported_detail`: a question word that appears in some returned line but nowhere in what the plan filters on (term values, template texts, location keys). It is tuned for recall, because each false positive costs one ~$0.0005 re-author call.
3. **Repair:** `repair-data --fix reauthor-unsupported-detail` writes a new question for every flagged example.
   - New questions go through the same filters as generation, plus a new `shape_mismatch` filter ("how many" over a plan that returns rows).
   - If the new question rounds a window that has seconds, the window is floored as in [0020](0020-repair-time-windows-in-place.md) and gold is recomputed.
   - Plans and gold are otherwise untouched. The old question is kept as `replaced_question`, originals are kept as `<split>.pre-reauthor_unsupported_detail.jsonl`, and the manifest records the run.
4. **Near-duplicate filter fix.** Its word sets dropped tokens under 3 characters, which erased times. Questions about the same component over different windows (different gold) looked identical, and 418 of the first 1,158 re-authored questions were rejected for it. Numbers now count.

Applied 2026-10-30:
- 1,158 flagged, 1,067 re-authored, 77 of those with floored windows.
- 91 dropped: 68 near-duplicate, 10 dsl_leak, 8 shape_mismatch, 3 author_declined, 2 keyword_trivial.
- 14,702 examples remain.
- The detector still flags 72 re-authored questions. On inspection these are mostly descriptions of a pattern's fixed words, which is fine.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Strengthen the prompt rule and keep the sample lines | That rule already existed and lost; prompt rules lost to visible data twice before ([friction](../friction.md)) |
| LLM judge to pick which questions to re-author | Costs as much as re-authoring them, and adds a second model's judgment to the data |
| Only re-author the "narrowing" subset (words in some but not all lines) | It still couldn't tell harmless "such as…" asides from real narrowing; re-authoring a fine question is harmless and cheap |
| Regenerate everything under q-2026-10-30.4 | ~$8 and a fresh draw invalidates the audit and baselines for a defect in ~8% of examples |

## Consequences

- The dataset now mixes prompt versions: examples carry `q-2026-10-30.3` or `.4`, and re-authored ones carry `repairs`.
- Generation was affected by the near-duplicate bug too. Some legitimate time-window variants were rejected during the original 20k run, and later runs keep them.
- 19 "how many" questions over row plans remain from the original run. Generation now rejects them as `shape_mismatch`, but this repair only touched flagged examples.
- Baselines were rerun only for the 101 changed test examples; all other records were reused.

## Reversal trigger

A second audit of re-authored examples finds them less natural than the originals, or the detector flags a share of new generations high enough that the prompt is the real problem.
