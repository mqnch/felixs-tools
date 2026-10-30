"""In-place repairs of a generated dataset, recorded in its manifest (decision 0020).

`floor_time_windows`: the slice-004 sampler drew absolute time bounds to the
second, while authors wrote them to the minute ("between 17:45 and 18:45" over
a gold window of 17:45:24..18:45:24). Where the question states no seconds,
the bounds are floored to the minute, so the question is exact again. Gold is
then recomputed with the same rejection rules generation used, and an example
that no longer passes them is dropped. Questions are never edited.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from common import QueryPlan
from logger import timeutil
from logger.index import LogIndex

from planner_rl.data.corpus import SPLITS
from planner_rl.data.gold import compute_gold

REPAIR = "floor_time_windows"
_SECONDS_IN_QUESTION = re.compile(r"\d:\d\d:\d\d")


def floor_time_windows(data_dir: str | Path) -> dict[str, dict]:
    """Repair every split of ``data_dir``; return per-split counts."""
    data_dir = Path(data_dir)
    manifest_path = data_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if any(r.get("name") == REPAIR for r in manifest.get("repairs", [])):
        raise ValueError(f"{data_dir} already has the {REPAIR} repair")

    seen_plans: set[str] = set()
    report: dict[str, dict] = {}
    for split in SPLITS:
        path = data_dir / f"{split}.jsonl"
        if not path.exists():
            continue
        examples = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        counts: Counter = Counter()
        kept: list[dict] = []
        index = LogIndex(data_dir / f"{split}.db")
        with sqlite3.connect(data_dir / f"{split}.db") as conn:
            row_count = int(conn.execute("SELECT COUNT(*) FROM log_entries").fetchone()[0])
        try:
            for ex in examples:
                plan = ex["plan"]
                if _needs_flooring(plan, ex.get("question") or ""):
                    plan = _floored(plan)
                    gold, reason = compute_gold(
                        index,
                        QueryPlan.model_validate(plan),
                        now=timeutil.parse_instant(ex["reference_now"]),
                        row_count=row_count,
                    )
                    if gold is None:
                        counts[f"dropped:{reason}"] += 1
                        continue
                    if gold.to_dict()["row_ids"] == ex["gold"]["row_ids"] and gold.groups == ex["gold"]["groups"]:
                        counts["floored_same_gold"] += 1
                    else:
                        counts["floored_new_gold"] += 1
                    ex = {**ex, "plan": plan, "gold": gold.to_dict(), "repairs": [*ex.get("repairs", []), REPAIR]}
                key = json.dumps(ex["plan"], sort_keys=True)
                if key in seen_plans:
                    # Flooring can make two plans identical; generation never kept duplicates.
                    counts["dropped:duplicate_plan"] += 1
                    continue
                seen_plans.add(key)
                kept.append(ex)
        finally:
            index.close()

        backup = data_dir / f"{split}.pre-{REPAIR}.jsonl"
        path.rename(backup)
        path.write_text("".join(json.dumps(ex, sort_keys=True) + "\n" for ex in kept))
        report[split] = {
            "before": len(examples),
            "after": len(kept),
            **dict(sorted(counts.items())),
            "strata": dict(sorted(Counter(ex["stratum"] for ex in kept).items())),
        }

    manifest.setdefault("repairs", []).append(
        {
            "name": REPAIR,
            "decision": "0020",
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "splits": report,
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return report


def _bounds(node, out: list[dict]) -> None:
    if isinstance(node, dict):
        if node.get("op") == "time_range":
            out.append(node)
        for child in node.get("of") or []:
            _bounds(child, out)


def _absolute_with_seconds(value: str | None) -> bool:
    if not value or value.startswith("-"):
        return False
    stamp = timeutil.parse_instant(value)
    return stamp is not None and (stamp.second or stamp.microsecond)


def _needs_flooring(plan: dict, question: str) -> bool:
    if _SECONDS_IN_QUESTION.search(question):
        return False
    nodes: list[dict] = []
    for q in plan["queries"]:
        _bounds(q.get("where"), nodes)
    return any(_absolute_with_seconds(n.get(k)) for n in nodes for k in ("since", "until"))


def _floored(plan: dict) -> dict:
    plan = json.loads(json.dumps(plan))
    nodes: list[dict] = []
    for q in plan["queries"]:
        _bounds(q.get("where"), nodes)
    for node in nodes:
        for k in ("since", "until"):
            if _absolute_with_seconds(node.get(k)):
                stamp = timeutil.parse_instant(node[k])
                node[k] = stamp.replace(second=0, microsecond=0).isoformat()
    return plan
