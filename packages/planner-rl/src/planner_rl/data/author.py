"""Frontier-model question authoring — the only model call in data generation.

The model writes the *input* (the question), never the gold (decision 0004).
It is called with the Anthropic SDK directly rather than through Router
(decision 0014): the manifest must pin the exact model and prompt version that
produced every question, and a routing policy that may swap models underneath
would make that record a guess.

Bump `PROMPT_VERSION` on any change to the prompt text; it is written into
every example and the dataset manifest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field

from planner_rl.data.corpus import AnchorRow

PROMPT_VERSION = "q-2026-10-27.1"
DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """\
You write realistic search questions for a log-search benchmark.

You are shown a structured query plan that was executed against a corpus of \
production logs, plus a sample of the log lines it returned. Write the single \
question an on-call engineer would plausibly type into a log search tool to \
get exactly that result.

Rules:
- Plain English, the way a person types into a search box. One or two sentences.
- Describe log messages by what they say, not by internal identifiers. Never \
mention template IDs, field names (severity, location_key, template_id, \
time_range, group_by), JSON, or the word "template".
- Express every constraint in the plan, and nothing it does not contain. \
Exclusions, alternatives, time windows and counting/grouping must all be \
recoverable from your question.
- Write times the way a person would ("between 20:10 and 20:40 on June 9", \
"in the last 6 hours"), never as ISO timestamps.
- If the plan has several queries, the question asks for all of them together.
- If no natural question could ask for exactly this result, set expressible \
to false and leave question empty. Do not force it."""


class AuthoredQuestion(BaseModel):
    expressible: bool = Field(description="False if no natural question fits this plan")
    question: str = Field(description="The question, or empty when not expressible")


@dataclass(frozen=True)
class AuthorRequest:
    dataset: str
    plan_json: str
    reference_now: str | None
    sample_rows: list[AnchorRow]
    template_texts: dict[int, str]
    groups: list[dict]


@dataclass(frozen=True)
class AuthorResult:
    question: str | None
    model: str
    reason: str | None = None


class QuestionAuthor(Protocol):
    model: str

    def author(self, request: AuthorRequest) -> AuthorResult: ...


def render_user_prompt(request: AuthorRequest) -> str:
    lines = [
        f"Dataset: LogHub {request.dataset}",
        f"Latest timestamp in this corpus (\"now\" for relative times): {request.reference_now}",
        "",
        "Plan:",
        request.plan_json,
    ]
    if request.template_texts:
        lines += ["", "Message patterns referenced by template ID in the plan (<*> is a variable):"]
        lines += [f"- {tid}: {text}" for tid, text in sorted(request.template_texts.items())]
    if request.sample_rows:
        lines += ["", "Sample of returned log lines:"]
        lines += [f"- {row.raw}" for row in request.sample_rows]
    if request.groups:
        lines += ["", "Top aggregate groups returned (key -> count):"]
        lines += [f"- {json.dumps(g['key'])} -> {g['count']}" for g in request.groups[:10]]
    return "\n".join(lines)


class AnthropicAuthor:
    """Authors questions with Claude via structured outputs."""

    def __init__(self, model: str = DEFAULT_MODEL, *, client=None) -> None:
        import anthropic

        self.model = model
        self._anthropic = anthropic
        self._client = client or anthropic.Anthropic()

    def author(self, request: AuthorRequest) -> AuthorResult:
        anthropic = self._anthropic
        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=4000,
                # Set explicitly: question quality caps every downstream result,
                # so this is not a place to trade effort for cost silently.
                output_config={"effort": "medium"},
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": render_user_prompt(request)}],
                output_format=AuthoredQuestion,
            )
        except (anthropic.RateLimitError, anthropic.APIConnectionError) as exc:
            # The SDK already retried; surface it rather than silently dropping.
            raise RuntimeError(f"question authoring failed after retries: {exc}") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise
            return AuthorResult(question=None, model=self.model, reason="author_error")

        if response.stop_reason == "refusal":
            return AuthorResult(question=None, model=self.model, reason="author_refused")
        parsed = response.parsed_output
        if parsed is None:
            return AuthorResult(question=None, model=self.model, reason="author_unparseable")
        if not parsed.expressible or not parsed.question.strip():
            return AuthorResult(question=None, model=self.model, reason="author_declined")
        return AuthorResult(question=parsed.question.strip(), model=self.model)
