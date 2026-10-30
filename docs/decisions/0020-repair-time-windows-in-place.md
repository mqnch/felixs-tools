# 0020 — Absolute time windows are whole minutes; the existing dataset is repaired in place, not regenerated

**Date:** 2026-10-30
**Status:** Accepted
**Affects:** `packages/planner-rl` (`data.sampler`, `data.repair`, `repair-data`)
**Slice:** [004](../slices/004-reverse-generated-dataset.md), found in [005](../slices/005-eval-harness-and-baselines.md)

## Context

The sampler drew absolute time bounds to the second (`17:45:24`), while the author wrote them to the minute ("between 17:45 and 18:45"). The audit read this as fine. Eval showed the gold could not be recovered from the question: 10–25% of examples per corpus had a window with seconds the question never states. Training on them would teach a planner to make up seconds.

## Decision

- **Going forward:** the sampler floors absolute bounds to the whole minute.
- **Existing data:** `planner-rl repair-data DIR` fixes it in place.
  - It touches only examples whose question contains no `H:MM:SS`, and floors their absolute bounds.
  - It recomputes gold with the same `compute_gold` rejection rules and drops examples that fail them or become duplicate plans.
  - Questions are never edited.
  - Originals are kept as `<split>.pre-floor_time_windows.jsonl`, and the manifest records the repair with per-split counts. Changed examples carry `"repairs": ["floor_time_windows"]`.

Applied to the three full datasets on 2026-10-30:
- 2,446 examples floored. Gold changed for 729; for the rest no row fell inside the dropped seconds.
- 21 examples dropped: 18 failed a rejection rule, 3 became duplicate plans.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Regenerate the dataset | ~$8 and ~10 h to fix a deterministic, local defect. Regeneration would also re-roll every other example, so the slice-004 audit and the slice-005 baselines would no longer describe the data |
| Edit the questions to state seconds | People don't ask for "17:45:24". That moves the data away from realistic questions, which is what the audit was for |
| Score windows with a ±1 minute tolerance | Hides the defect in eval but leaves it in the training data, where it does the damage |
| Floor every absolute bound, even when the question states seconds | Would break the examples that were already right |

## Consequences

- `rescore` drops records for removed examples and notes which repairs the data has. Pre-repair results are kept next to the repaired ones.
- Datasets generated after this change don't need the repair.
- Also seen in the 45 Sonnet failures and **not** fixed here: questions that add detail gold lacks (~2%), one AND/OR flip and one wrong-date window. They need an authoring-prompt change and a regeneration, and are tracked in slice 005.

## Reversal trigger

None expected. The repair is a one-off. Revisit only if a future corpus has sub-minute windows that matter (e.g. bursts within one minute), in which case the author has to be made to state seconds.
