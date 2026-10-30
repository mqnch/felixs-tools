"""Execution-verified scoring of one planner output against gold (slice 005).

This is also the reward slice 008 trains against, so the rules here are
decision 0018 and change only with a new decision:

- **Format** is binary: the output parses and passes `validate_plan`, or not.
  When a reply holds several JSON objects (a plan, then "Correction: ..."),
  the last one that validates is the answer.
  The validator skips its semantic stage when the structural stage fails, so an
  error count would rank "one structural error" above "three semantic ones" for
  no real reason.
- **Rows and groups are two components** (decision 0012: aggregates return
  groups, no rows). Rows score set-F1 against gold row IDs; groups score
  multiset-F1 over exact `(key, count)` pairs, after dropping key fields that
  take one value across all of that side's groups. Grouping by a field the
  filter already pins (`group_by: [location_key]` under `location_key = X`)
  then matches the plain total it is equivalent to. A component counts when gold or
  the prediction has anything in it, so returning rows for an aggregate-only
  question costs a 0 on the rows component. `answer` is the mean of the
  components that count.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime

from common import QueryPlan
from logger.index import LogIndex
from logger.validator import validate_plan

# Bump on any change to the rules above; results carry it and `compare`
# refuses to mix versions. Old results are brought forward with `rescore`.
SCORER_VERSION = "s-2026-10-30.2"

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


@dataclass(frozen=True)
class Score:
    format_valid: bool
    executed: bool = False
    answer: float = 0.0
    row_precision: float | None = None
    row_recall: float | None = None
    row_f1: float | None = None
    group_f1: float | None = None
    query_count: int = 0
    rows_scanned: int = 0
    error_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def extract_json(text: str) -> str:
    """The JSON object in a model reply: drop think blocks, fences and prose around it."""
    body = _THINK_RE.sub("", text)
    start, end = body.find("{"), body.rfind("}")
    return body[start : end + 1] if start != -1 and end > start else body.strip()


def _json_objects(text: str) -> list[dict]:
    """Every top-level JSON object in ``text``, in order."""
    body = _THINK_RE.sub("", text)
    decoder = json.JSONDecoder()
    found, i = [], body.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(body, i)
        except ValueError:
            i = body.find("{", i + 1)
            continue
        if isinstance(obj, dict):
            found.append(obj)
        i = body.find("{", end)
    return found


def parse_plan(text: str) -> tuple[QueryPlan | None, list[str]]:
    candidates = _json_objects(text)
    for obj in reversed(candidates):
        result = validate_plan(obj)
        if result.ok and result.plan is not None:
            return result.plan, []
    # Nothing validates: report the errors of the last object, or of the raw text.
    result = validate_plan(candidates[-1] if candidates else extract_json(text))
    return None, sorted({str(e.code) for e in result.errors})


def score_output(text: str, gold: dict, index: LogIndex, *, now: datetime) -> Score:
    plan, codes = parse_plan(text)
    if plan is None:
        return Score(format_valid=False, error_codes=codes)
    try:
        result = index.execute(plan, now=now)
    except Exception as exc:  # noqa: BLE001 - any execution failure scores 0, never crashes a run
        return Score(format_valid=True, error_codes=[f"execution:{type(exc).__name__}"])

    components: list[float] = []
    p = r = f = None
    pred_rows, gold_rows = set(result.row_ids), set(gold.get("row_ids") or [])
    if pred_rows or gold_rows:
        p, r, f = _prf(len(pred_rows & gold_rows), len(pred_rows), len(gold_rows))
        components.append(f)
    g = None
    pred_groups = _groups([(x.key, x.count) for x in result.groups])
    gold_groups = _groups([(x["key"], x["count"]) for x in gold.get("groups") or []])
    if pred_groups or gold_groups:
        _, _, g = _prf(sum((pred_groups & gold_groups).values()), pred_groups.total(), gold_groups.total())
        components.append(g)

    return Score(
        format_valid=True,
        executed=True,
        answer=sum(components) / len(components) if components else 1.0,
        row_precision=p,
        row_recall=r,
        row_f1=f,
        group_f1=g,
        query_count=result.query_count,
        rows_scanned=result.rows_scanned,
    )


def _groups(pairs: list[tuple[dict, int]]) -> Counter:
    constant = {
        field
        for field in {f for key, _ in pairs for f in key}
        if len({json.dumps(key.get(field), default=str) for key, _ in pairs}) == 1
    }
    return Counter(
        (json.dumps({f: v for f, v in key.items() if f not in constant}, sort_keys=True, default=str), int(count))
        for key, count in pairs
    )


def _prf(hit: int, predicted: int, gold: int) -> tuple[float, float, float]:
    precision = hit / predicted if predicted else 0.0
    recall = hit / gold if gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1
