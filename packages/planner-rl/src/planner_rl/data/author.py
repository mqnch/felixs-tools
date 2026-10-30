"""Frontier-model question authoring — the only model call in data generation.

The model writes the *input* (the question), never the gold (decision 0004).
It is called directly rather than through Router (decision 0014): the manifest
must pin the exact model and prompt version that produced every question, and a
routing policy that may swap models underneath would make that record a guess.
Two direct providers exist: the Anthropic SDK and OpenRouter (decision 0016).

Bump `PROMPT_VERSION` on any change to the prompt text; it is written into
every example and the dataset manifest.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from common import MAX_LIMIT
from pydantic import BaseModel, Field

from planner_rl.data.corpus import AnchorRow

PROMPT_VERSION = "q-2026-10-30.3"
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-haiku-5.5"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Bad key, no credit, no access: every later call fails the same way, so these
# abort the run instead of being counted as one example's rejection.
FATAL_STATUSES = frozenset({401, 402, 403})
# Pseudo-status for a request that never got an HTTP response.
NETWORK_ERROR = 0

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
- The sample lines only illustrate the result. Do not describe what they say \
("about spills", "such as retries") unless the plan itself filters on it: \
words like "about" or "mentioning" add a filter the plan does not have.
- A location is one component writing to one file. Name the component, and \
the file only if it disambiguates ("the MapTask logger in container \
container_..._000007's log"). Do not name only the file, which also contains \
other components, and never write the raw component:file key.
- Copy IDs (containers, applications, instances, hosts, hashes) in full. A \
shortened ID is ambiguous.
- Write absolute time windows with dates and times ("between 20:10 and 20:40 \
on June 9"; across midnight, "from 00:20 on October 17 to 00:20 on October \
18"). Say "in the last N hours" only when the plan's window is relative. \
Never write ISO timestamps.
- Match the result's shape. A row query returns log lines: ask to find or \
list them, not "how many". An aggregate returns counts per group: ask how \
many, and name every grouping dimension. Do not add a filter (such as a \
severity) just because every returned group happens to have that value.
- Do not mention how many results to return or what order to sort them in. \
Those are search-tool defaults, not part of what the person is looking for.
- Vary the phrasing the way real people do: a bare keyword-style query, a \
question ("which nodes...?", "how many..."), or a request. Do not start every \
question with "Show me".
- If the plan has several queries, the question asks for all of them together, \
keeping each one's own constraints attached to it.
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


def author_view_of_plan(plan_json: str) -> str:
    """The plan as the author sees it: sampler defaults removed.

    Every sampled row query carries ``limit=MAX_LIMIT`` and ``order="newest"``
    so gold is the complete match set (decision 0013). They are not constraints
    a person asked for, and leaving them in made 70% of questions say "up to
    1000" (prompt q-2026-10-27.1 pilot). Non-default values stay visible.
    """
    plan = json.loads(plan_json)
    for query in plan.get("queries", []):
        if query.get("limit") == MAX_LIMIT:
            query.pop("limit")
        if query.get("order") == "newest":
            query.pop("order")
    return json.dumps(plan)


def _walk(node: dict):
    yield node
    for child in node.get("of", []) or []:
        yield from _walk(child)


def _plan_leaves(plan: dict, op: str) -> list[dict]:
    seen: list[dict] = []
    for query in plan.get("queries", []):
        if query.get("where"):
            for leaf in _walk(query["where"]):
                if leaf.get("op") == op and leaf not in seen:
                    seen.append(leaf)
    return seen


def render_user_prompt(request: AuthorRequest) -> str:
    plan = json.loads(request.plan_json)
    lines = [
        f"Dataset: LogHub {request.dataset}",
        f"Latest timestamp in this corpus (\"now\" for relative times): {request.reference_now}",
        "",
        "Plan:",
        author_view_of_plan(request.plan_json),
    ]
    locations = _plan_leaves(plan, "location_key")
    if locations:
        lines += ["", "Locations in the plan (each is one component writing to one file):"]
        for leaf in locations:
            component, _, path = leaf["value"].rpartition(":")
            lines.append(f"- component {component or '(none)'} in file {path}")
    windows = _plan_leaves(plan, "time_range")
    if windows:
        lines += ["", "Time windows in the plan:"]
        for leaf in windows:
            since, until = leaf.get("since"), leaf.get("until")
            kind = "relative to now" if str(since).startswith("-") else "absolute"
            lines.append(f"- {kind}: since {since} until {until or 'now'}")
    if request.template_texts:
        lines += ["", "Message patterns referenced by template ID in the plan (<*> is a variable):"]
        lines += [f"- {tid}: {text}" for tid, text in sorted(request.template_texts.items())]
    if request.sample_rows:
        lines += ["", "Sample of returned log lines (illustration only, not filters):"]
        lines += [f"- {row.raw}" for row in request.sample_rows]
    if request.groups:
        # Counts only, never the group keys: shown "KERNEL -> 56", the author
        # turned the result into a filter ("how many KERNEL lines...") in 6 of
        # 34 BGL audit rows under q-2026-10-30.2.
        lines += ["", f"The aggregate returned {len(request.groups)} group(s)."]
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
            if exc.status_code >= 500 or exc.status_code in FATAL_STATUSES:
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


REQUEST_DEADLINE_S = 90


def _read_with_deadline(resp, deadline: float) -> bytes:
    """Read the whole body, giving up at ``deadline`` (a ``time.monotonic()`` value).

    OpenRouter writes keep-alive whitespace while an upstream provider works, so
    the socket timeout never fires on a request whose provider has hung: each
    keep-alive byte resets it. Only a deadline over the whole read catches that.
    """
    chunks = []
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError(f"no complete response within {REQUEST_DEADLINE_S}s")
        chunk = resp.read1(65536)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _post_json(url: str, headers: dict[str, str], body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    deadline = time.monotonic() + REQUEST_DEADLINE_S
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(_read_with_deadline(resp, deadline))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read())
        except ValueError:
            payload = {}
        return exc.code, payload
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as exc:
        # No usable HTTP response: a timeout, a dropped connection or a body that
        # is not JSON. Retryable, like a 5xx; uncaught, one of these killed all
        # three 20k runs at once.
        return NETWORK_ERROR, {"error": repr(exc)}


class OpenRouterAuthor:
    """Authors questions through OpenRouter's OpenAI-compatible API (decision 0016).

    ``model`` is an exact OpenRouter slug, never a ``~...-latest`` alias, so the
    manifest still names the model that wrote every question.
    """

    def __init__(
        self,
        model: str = DEFAULT_OPENROUTER_MODEL,
        *,
        api_key: str | None = None,
        post=_post_json,
        max_retries: int = 8,
        sleep=time.sleep,
    ) -> None:
        if model.startswith("~"):
            raise ValueError(f"{model!r} is a floating alias; pin an exact slug")
        key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        self.model = model
        self._headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        self._post = post
        self._max_retries = max_retries
        self._sleep = sleep

    def author(self, request: AuthorRequest) -> AuthorResult:
        body = {
            "model": self.model,
            "max_tokens": 4000,
            "reasoning": {"effort": "medium"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": render_user_prompt(request)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "authored_question", "strict": True, "schema": _QUESTION_SCHEMA},
            },
        }
        for attempt in range(self._max_retries + 1):
            status, payload = self._post(OPENROUTER_URL, self._headers, body)
            if status in (NETWORK_ERROR, 429) or status >= 500:
                if attempt == self._max_retries:
                    raise RuntimeError(f"question authoring failed after retries: HTTP {status} {payload}")
                self._sleep(2**attempt)
                continue
            break
        if status in FATAL_STATUSES:
            raise RuntimeError(f"OpenRouter rejected the request (HTTP {status}): {payload}")
        if status != 200:
            return AuthorResult(question=None, model=self.model, reason="author_error")

        choices = payload.get("choices") or [{}]
        message = choices[0].get("message") or {}
        if message.get("refusal"):
            return AuthorResult(question=None, model=self.model, reason="author_refused")
        try:
            parsed = AuthoredQuestion.model_validate_json(message.get("content") or "")
        except ValueError:
            return AuthorResult(question=None, model=self.model, reason="author_unparseable")
        if not parsed.expressible or not parsed.question.strip():
            return AuthorResult(question=None, model=self.model, reason="author_declined")
        return AuthorResult(question=parsed.question.strip(), model=self.model)


_QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        name: {"type": "boolean" if name == "expressible" else "string", "description": field.description}
        for name, field in AuthoredQuestion.model_fields.items()
    },
    "required": list(AuthoredQuestion.model_fields),
    "additionalProperties": False,
}
