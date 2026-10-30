# 0018 — Scoring: binary format, row set-F1 and group multiset-F1 as two components, averaged

**Date:** 2026-10-30
**Status:** Accepted
**Affects:** `packages/planner-rl` (`eval.score`); slice 008's reward
**Slice:** [005](../slices/005-eval-harness-and-baselines.md)

## Context

Decision [0012](0012-aggregates-as-groups-not-rows.md) made aggregates return groups and no rows, so row-ID F1 is undefined for them. Slice 005 has to fix a combination rule, because slice 008's reward inherits it. It also has to choose how fine-grained the format signal is.

## Decision

The output is reduced to a JSON object first: think blocks, code fences and prose around it are dropped. When a reply holds several objects (a plan, then "Correction: …"), the last one that validates is the answer. Then:
- **Format** is binary: the object passes `validate_plan` or it doesn't. An invalid plan scores 0.
- **Rows:** set precision, recall and F1 of the executed row IDs against gold.
- **Groups:** multiset F1 over exact `(key, count)` pairs, after dropping key fields that take a single value across all of one side's groups. "How many lines did X write?" can then be answered with a plain total or grouped by X's location key; both mean the same.
- A component counts when either gold or the prediction is non-empty in it. Rows returned for an aggregate-only question therefore score 0 on the rows component.
- **`answer`** is the mean of the components that count. It is the headline number and the gate metric.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Synthesize row IDs for aggregates | F1 would report differences that don't exist (slice 005 spec) |
| Graded format score from the error count | The validator skips its semantic stage when the structural stage fails, so "1 structural error" would outrank "3 semantic errors" for no real reason |
| Partial credit for a right group key with a wrong count | A count is the whole answer to "how many". Being off by one is wrong, not mostly right |
| Score only gold's components, ignoring extra output | Lets a planner append rows to every aggregate answer for free |
| Strict JSON with no fence or prose stripping | Measures chat formatting habits, not planning. SFT fixes those in an hour |

## Consequences

- Rule versions are tracked in `SCORER_VERSION`. `compare` refuses to mix versions, and `planner-rl rescore` re-scores saved outputs for free. Version 2 (same day) added the last-valid-object and constant-key rules, after reviewing all 45 Sonnet failures found 4 correct answers scored 0 and 4 self-corrected replies scored invalid.

- A gold plan scores exactly 1.0 on all 1,484 test examples (checked on the full run).
- Precision and recall are both recorded, so slice 008 can weight them differently without rescoring.

## Reversal trigger

Slice 008 shows reward hacking through one component, e.g. a planner farming group-F1 with very broad aggregates.
