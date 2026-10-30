# 0016 — OpenRouter as a second direct provider for question authoring; auth and billing errors abort the run

**Date:** 2026-10-30
**Status:** Accepted
**Affects:** `packages/planner-rl` (`data.author`, `cli gen-data --provider`)
**Slice:** [004](../slices/004-reverse-generated-dataset.md)

## Context

Decision [0014](0014-question-authoring-bypasses-router.md) had `gen-data` call the Anthropic SDK directly. The first paid run had no Anthropic API account behind it; the available account is OpenRouter. Pilot cost for about 900 questions is under $1 on any small model listed there, so the choice is about quality and reproducibility, not price.

Separately, `AnthropicAuthor` turned every 4xx into a per-example `author_error` rejection. A missing key or an empty balance would therefore run thousands of attempts and finish with zero questions instead of failing.

## Decision

Add `OpenRouterAuthor`, selected with `gen-data --provider openrouter`. It calls OpenRouter's OpenAI-compatible chat completions with a strict JSON schema derived from `AuthoredQuestion`, the same system prompt, `PROMPT_VERSION` and reasoning effort as the Anthropic path, and stdlib `urllib`, so no new dependency. The default model is `anthropic/claude-haiku-5.5`. Floating `~...-latest` aliases are refused, so the manifest always names an exact model. Decision 0014's core point (no Router, exact model pinned) still holds.

In both authors, HTTP 401/402/403 now raise and stop the run. Other 4xx are still a per-example `author_error`.

## Alternatives rejected

| Option | Why rejected |
|---|---|
| Anthropic API only | Needs a second paid account for no gain at pilot scale |
| Route authoring through Router | Rejected by 0014 for the same reason: a routing layer can swap models underneath and make the manifest's model a guess |
| Free OpenRouter models | The only free models with structured output are small or obscure, rate-limited and unreliable, to save under $1 |
| `openai` SDK | A new dependency for one POST; `urllib` is already used by corpus staging |
| Author questions in a Claude Code session on the subscription | Fine for ~100 examples, but it needs an import path and can't reach 20k within plan limits |

## Consequences

- `author_model` in the manifest is now an OpenRouter slug (`anthropic/claude-haiku-5.5`) or an Anthropic model ID, depending on provider. The slash distinguishes them.
- OpenRouter picks the upstream provider for a slug. For Anthropic models that is Anthropic, but for open-weight models the serving provider (and its quantization) can vary between calls, which is a weaker reproducibility guarantee than the model name suggests.
- Retries: network errors (timeouts, dropped connections), 429 and 5xx back off exponentially, up to 8 retries (~4 min), then raise.

## Reversal trigger

An Anthropic API account exists and the audit shows a reason to prefer a model only available there, or OpenRouter's routing makes an open-weight author irreproducible in a way the audit catches.
