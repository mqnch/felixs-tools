"""The planner prompt every evaluated model gets: DSL spec + corpus card + question.

Every model sees the identical prompt, so a score difference is the model's,
not the prompt's. Bump `EVAL_PROMPT_VERSION` on any change; it is written into
every results file and `compare` refuses to mix versions.

The corpus card is decision 0017: a planner cannot guess template IDs or
`component:file` location keys from the question alone, and Logger at serving
time has the same catalogue to hand.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from common import MAX_LIMIT, SCHEMA_VERSION

from planner_rl.data.corpus import CorpusView

EVAL_PROMPT_VERSION = "p-2026-10-30.1"

SYSTEM_PROMPT = f"""\
You translate a question about a log corpus into a query plan. Reply with one JSON
object and nothing else.

Plan shape (schema {SCHEMA_VERSION}):
{{"version": "{SCHEMA_VERSION}", "queries": [<query>, ...]}}       1 to 8 queries; row results are unioned
<query> = {{"label": <string or null>, "where": <node or null>, "limit": <1..{MAX_LIMIT}>,
           "order": "newest" | "oldest", "aggregate": <aggregate or null>}}

<node> is one of:
  {{"op": "and", "of": [<node>, ...]}}       all children match (2-8 children)
  {{"op": "or",  "of": [<node>, ...]}}       any child matches (2-8 children)
  {{"op": "not", "of": [<node>]}}            the one child does not match
  {{"op": "term", "value": "<phrase>"}}      full-text phrase match on the line and its template
  {{"op": "severity", "value": "INFO"}}      one of DEBUG INFO WARN ERROR CRITICAL FATAL
  {{"op": "template_id", "value": 12}}       a template ID from the corpus card
  {{"op": "location_key", "value": "<component>:<file>"}}   exact; built from the card's components and files
  {{"op": "time_range", "since": <bound or null>, "until": <bound or null>}}
      a bound is an ISO-8601 instant ("2015-10-19T16:00:00+00:00") or an offset back from
      "now" ("-30m", "-6h", "-2d"); both bounds are inclusive

<aggregate> = {{"op": "count", "group_by": [<field>, ...], "having": {{"min_count": <int or null>,
               "max_count": <int or null>}} or null}}
  <field> is template_id, severity or location_key (at most 2). An aggregate query returns
  counts per group instead of rows; group_by [] gives one total count.

Rules:
- A question asking for matching lines wants every match: use "limit": {MAX_LIMIT} unless it asks
  for a specific number.
- Prefer template_id when a question describes a kind of message listed in the card; use term
  for a specific value (an ID, a host, a block) that appears inside messages.
- Use one query unless the question asks for separate things.
"""


@dataclass(frozen=True)
class CorpusCard:
    text: str


def corpus_card(split_db: str | Path, *, dataset: str) -> CorpusCard:
    """Templates, severities, locations and time span of one split database."""
    view = CorpusView(split_db)
    try:
        templates = "\n".join(f"  {tid}: {view.template_text(tid)}" for tid in view.template_ids)
        components = sorted({k.rpartition(":")[0] for k in view.location_keys})
        files = sorted({k.rpartition(":")[2] for k in view.location_keys})
        first, last = view.timestamp_bounds()
    finally:
        view.close()
    with sqlite3.connect(f"file:{split_db}?mode=ro", uri=True) as conn:
        severities = [r[0] for r in conn.execute(
            "SELECT DISTINCT severity FROM log_entries WHERE severity IS NOT NULL ORDER BY 1"
        )]
    text = (
        f"Corpus: {dataset}\n"
        f"Time span: {first} to {last}\n"
        f"Severities present: {', '.join(severities)}\n"
        f"Components: {', '.join(components)}\n"
        f"Files: {', '.join(files)}\n"
        f"Templates (ID: text, <*> is a variable part):\n{templates}"
    )
    return CorpusCard(text=text)


def user_prompt(card: CorpusCard, question: str, reference_now: str) -> tuple[str, str]:
    """(shared prefix, per-question suffix); the user message is their concatenation.

    The question goes last so a prompt cache can reuse the system prompt and
    card across every question on the same corpus.
    """
    return f"{card.text}\n\n", f"Now: {reference_now}\n\nQuestion: {question}"
