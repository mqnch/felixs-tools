# 0017 — The evaluated planner sees a corpus card: templates, severities, components, files and time span

**Date:** 2026-10-30
**Status:** Accepted
**Affects:** `packages/planner-rl` (`eval.prompt`); slice 007/008 training prompts inherit it
**Slice:** [005](../slices/005-eval-harness-and-baselines.md)

## Context

Gold plans use `template_id` and exact `component:file` location keys. No model can guess template 186, or `org.apache.hadoop.mapred.MapTask:container_…_000017.log`, from the question alone. A question-only prompt would measure missing context, not planning skill. Logger at serving time has the same catalogue in its index.

## Decision

Every evaluated model gets the same prompt:
- the DSL spec and three rules;
- a **corpus card** built from the split DB:
  - every template as `ID: text`, using the most general Drain text, as authoring did;
  - the severities present;
  - components and files listed separately, since a location key is `component:file`;
  - the time span;
- `Now:` set to the example's reference time;
- the question.

The card comes before the question, so prompt caches can reuse it. The prompt is versioned (`EVAL_PROMPT_VERSION`), and `compare` refuses to mix versions.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Question only (the Logger planner's slice-001 prompt) | Template IDs and location keys become unguessable. Every model scores near zero on those strata for a reason training can't fix |
| Full `location_key` list | Hadoop has 553 keys of about 90 chars each, roughly 16k tokens. Listing 44 components and 97 files carries the same information in about 3k |
| Retrieve the top-k templates per question | That's a second system to evaluate. Its recall errors would show up as planner errors |

## Consequences

- Hadoop prompts are about 4.8k tokens, BGL about 1.6k and OpenStack about 1.3k. Training prompts in 007/008 must use the same card, or the baselines aren't comparable.
- A corpus with thousands of templates would not fit. None of the three in use comes close.

## Reversal trigger

A corpus whose card exceeds ~16k tokens, or slice 011 (wiring the planner into Logger) needs a prompt that can't carry the full card.
