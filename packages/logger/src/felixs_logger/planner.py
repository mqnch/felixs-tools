"""NL query planner: translates a question into structured index queries."""

from __future__ import annotations

import json
from typing import Any

from felixs_common import RouterRequest, TaskType
from felixs_router import complete

from felixs_logger.index import IndexedEntry, LogIndex


class QueryPlanner:
    """Plans parallel structured queries against LogIndex via Router."""

    def __init__(self, index: LogIndex) -> None:
        self._index = index

    def plan(self, question: str) -> list[dict[str, Any]]:
        request = RouterRequest(
            task_type=TaskType.LOG_QUERY_PLANNING,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Translate the user log question into JSON: "
                        '{"queries":[{"filters":{"severity":"..."},'
                        '"terms":["..."],"limit":50}]}. Reply JSON only.'
                    ),
                },
                {"role": "user", "content": question},
            ],
        )
        response = complete(request)
        return _parse_plan(response.content)

    def search(self, question: str) -> list[IndexedEntry]:
        plans = self.plan(question)
        seen: set[int] = set()
        results: list[IndexedEntry] = []
        for plan in plans:
            filters = plan.get("filters") or {}
            entries = self._index.query(
                terms=list(plan.get("terms") or []),
                severity=filters.get("severity"),
                location_key=filters.get("location_key"),
                template_id=filters.get("template_id"),
                limit=int(plan.get("limit") or 50),
            )
            for entry in entries:
                if entry.id in seen:
                    continue
                seen.add(entry.id)
                results.append(entry)
        return results


def _parse_plan(content: str) -> list[dict[str, Any]]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [{"terms": [], "filters": {}, "limit": 50}]
    queries = data.get("queries") if isinstance(data, dict) else data
    if not isinstance(queries, list) or not queries:
        return [{"terms": [], "filters": {}, "limit": 50}]
    return [q for q in queries if isinstance(q, dict)]
