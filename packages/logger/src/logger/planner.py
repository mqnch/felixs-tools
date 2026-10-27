"""NL query planner: translates a question into a structured query plan."""

from __future__ import annotations

import json
import re
from typing import Any

from common import (
    SCHEMA_VERSION,
    AndNode,
    LocationKeyNode,
    Query,
    QueryPlan,
    RouterRequest,
    SeverityNode,
    TaskType,
    TemplateIdNode,
    TermNode,
)
from router import complete

from logger.index import IndexedEntry, LogIndex, PlanResult
from logger.validator import validate_plan

_SYSTEM_PROMPT = f"""\
Translate the user's log question into a query plan for schema {SCHEMA_VERSION}.
Reply with JSON only:
{{"version":"{SCHEMA_VERSION}","queries":[{{"label":"...","where":<node>,"limit":50,
"order":"newest","aggregate":null}}]}}
A <node> is one of:
{{"op":"and","of":[<node>,...]}} {{"op":"or","of":[<node>,...]}} {{"op":"not","of":[<node>]}}
{{"op":"term","value":"..."}} {{"op":"severity","value":"ERROR"}}
{{"op":"template_id","value":7}} {{"op":"location_key","value":"api:svc/app.log"}}
{{"op":"time_range","since":"-24h","until":null}}
aggregate is {{"op":"count","group_by":["template_id"],"having":{{"min_count":10}}}} or null.
"""

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


class QueryPlanner:
    """Plans a small set of targeted queries against LogIndex via Router."""

    def __init__(self, index: LogIndex) -> None:
        self._index = index

    def plan(self, question: str) -> QueryPlan:
        """Ask Router for a plan; fall back to a keyword plan if it is not valid."""
        request = RouterRequest(
            task_type=TaskType.LOG_QUERY_PLANNING,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
        )
        response = complete(request)
        plan = _plan_from_content(response.content)
        return plan if plan is not None else fallback_plan(question)

    def execute(self, question: str) -> PlanResult:
        return self._index.execute(self.plan(question))

    def search(self, question: str) -> list[IndexedEntry]:
        return self.execute(question).rows


def fallback_plan(question: str, *, limit: int = 50) -> QueryPlan:
    """Deterministic keyword plan. Keeps `felix logger search` usable with no model."""
    children: list[Any] = [TermNode(value=word) for word in _keywords(question)]
    severity = _severity_hint(question)
    if severity is not None:
        children.append(SeverityNode(value=severity))
    where = children[0] if len(children) == 1 else (AndNode(of=children) if children else None)
    return QueryPlan(queries=[Query(label="fallback", where=where, limit=limit)])


def _plan_from_content(content: str) -> QueryPlan | None:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict) and _looks_legacy(data):
        data = _from_legacy(data)
    result = validate_plan(data)
    return result.plan if result.ok else None


def _looks_legacy(data: dict[str, Any]) -> bool:
    """Slice-001 shape: `{"queries":[{"terms":[...],"filters":{...},"limit":N}]}`.

    The Router stub still emits it, and Router is not this slice's to change.
    """
    queries = data.get("queries")
    if not isinstance(queries, list) or not queries:
        return False
    first = queries[0]
    return isinstance(first, dict) and ("terms" in first or "filters" in first)


def _from_legacy(data: dict[str, Any]) -> dict[str, Any]:
    queries: list[Query] = []
    for raw in data.get("queries") or []:
        if not isinstance(raw, dict):
            continue
        filters = raw.get("filters") if isinstance(raw.get("filters"), dict) else {}
        children: list[Any] = [
            TermNode(value=str(t)) for t in (raw.get("terms") or []) if str(t).strip()
        ]
        severity = _severity_hint(str(filters.get("severity") or ""))
        if severity is not None:
            children.append(SeverityNode(value=severity))
        if filters.get("location_key"):
            children.append(LocationKeyNode(value=str(filters["location_key"])))
        if isinstance(filters.get("template_id"), int):
            children.append(TemplateIdNode(value=int(filters["template_id"])))
        where = children[0] if len(children) == 1 else (AndNode(of=children) if children else None)
        try:
            limit = int(raw.get("limit") or 50)
        except (TypeError, ValueError):
            limit = 50
        queries.append(Query(where=where, limit=max(1, limit)))
    return QueryPlan(queries=queries).model_dump(mode="json")


def _severity_hint(text: str) -> str | None:
    upper = text.upper()
    for candidate in ("CRITICAL", "FATAL", "ERROR", "WARNING", "WARN", "DEBUG", "INFO"):
        if candidate in upper:
            return "WARN" if candidate == "WARNING" else candidate
    return None


_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "find", "show",
    "logs", "log", "error", "errors", "about", "what", "when", "where", "all",
}


def _keywords(text: str, *, cap: int = 6) -> list[str]:
    out: list[str] = []
    for token in _WORD_RE.findall(text.lower()):
        if token in _STOP or token in out:
            continue
        out.append(token)
        if len(out) >= cap:
            break
    return out
