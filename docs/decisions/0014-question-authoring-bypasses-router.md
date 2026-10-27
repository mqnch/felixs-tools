# 0014 — Dataset question authoring calls the Anthropic SDK directly, not through Router

**Date:** 2026-10-27
**Status:** Accepted
**Affects:** `packages/planner-rl`, source of truth §3.3 (Callers)
**Slice:** [004](../slices/004-reverse-generated-dataset.md)

## Context

Slice 004 needs a frontier model to write the natural-language question for every sampled plan. §3.3 says model calls go through Router. But Router is still a stub: Ollama, with a heuristic fallback when that fails. Making it real (a LiteLLM wrapper) is §7 step 4, behind Brain.

## Decision

`planner_rl.data.author.AnthropicAuthor` calls `anthropic.Anthropic().messages.parse(...)` directly, with model `claude-opus-5-5` by default, structured output, and explicit `effort: medium`. The exact model ID and a `PROMPT_VERSION` string are written into every example and into the dataset manifest. Authors sit behind a small `QuestionAuthor` protocol, so tests and a future Router-backed author swap in without touching the pipeline.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Route through the Router stub | The stub is Ollama-only and **silently** falls back to a heuristic on connection failure. A dataset generated through it could be partly authored by a regex, and the manifest would not know |
| Make Router real now (LiteLLM + cache) | §7 step 4, out of order, for one offline caller. Router's value is task-type policy and caching across live callers; neither applies to a one-time generation job |
| Add an Anthropic path to the Router stub | Grows the stub into a half-built Router, the speculative generalisation §2.2 forbids. Router policy could also swap the model, while the dataset manifest has to state the exact model that wrote each question |

## Consequences

- Data generation needs Anthropic credentials (`ANTHROPIC_API_KEY` or an `ant auth login` profile) and costs real money. The `--dry-run` flag runs everything except the model call, so the strata mix and rejection rates can be checked first.
- Router's caller list in §3.3 now has a documented exception.
- Slice 010's frontier baseline (the frontier model *planning*, not authoring) is a different call path and is not decided by this record.

## Reversal trigger

Router becomes real (§7 step 4) and supports pinning an exact model per call. Data generation can then route through it with no loss of provenance.
