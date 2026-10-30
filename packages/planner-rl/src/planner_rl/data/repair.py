"""In-place repairs of a generated dataset, each recorded in its manifest.

`floor_time_windows` (decision 0020): the slice-004 sampler drew absolute time bounds to the
second, while authors wrote them to the minute ("between 17:45 and 18:45" over
a gold window of 17:45:24..18:45:24). Where the question states no seconds,
the bounds are floored to the minute, so the question is exact again. Gold is
then recomputed with the same rejection rules generation used, and an example
that no longer passes them is dropped. Questions are never edited.

`reauthor_unsupported_detail` (decision 0022): under prompts up to
q-2026-10-30.3 the author saw sample lines and described them ("the GET
requests to servers/detail") where the plan has no such filter. Examples whose
question uses words found in the returned lines but nowhere in the plan get a
new question from the current prompt, which shows no lines. The new question
goes through the same filters as at generation; an example that fails them is
dropped. Plans and gold are never edited.
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

from planner_rl.data import filters
from planner_rl.data.author import PROMPT_VERSION, AuthorRequest, QuestionAuthor
from planner_rl.data.corpus import SPLITS, CorpusView
from planner_rl.data.gold import compute_gold

REPAIR = "floor_time_windows"
REAUTHOR = "reauthor_unsupported_detail"
_ROWS_CHECKED = 500
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


def reauthor_unsupported_detail(
    data_dir: str | Path, author: QuestionAuthor, *, concurrency: int = 8
) -> dict[str, dict]:
    """Re-author every example whose question describes lines the plan does not filter on."""
    from concurrent.futures import ThreadPoolExecutor

    data_dir = Path(data_dir)
    manifest_path = data_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if any(r.get("name") == REAUTHOR for r in manifest.get("repairs", [])):
        raise ValueError(f"{data_dir} already has the {REAUTHOR} repair")

    splits = {s: data_dir / f"{s}.jsonl" for s in SPLITS if (data_dir / f"{s}.jsonl").exists()}
    examples = {s: [json.loads(x) for x in p.read_text().splitlines() if x.strip()] for s, p in splits.items()}

    flagged: dict[str, list[int]] = {}
    requests: dict[tuple[str, int], AuthorRequest] = {}
    for split, exs in examples.items():
        view = CorpusView(data_dir / f"{split}.db")
        try:
            flagged[split] = []
            for i, ex in enumerate(exs):
                texts = {tid: view.template_text(tid) for tid in _template_ids(ex["plan"])}
                rows = [r.raw for r in view.rows(ex["gold"]["row_ids"][:_ROWS_CHECKED])]
                if not filters.unsupported_detail(ex["question"], _plan_text(ex["plan"], texts), rows):
                    continue
                flagged[split].append(i)
                requests[(split, i)] = AuthorRequest(
                    dataset=manifest["dataset"],
                    plan_json=json.dumps(ex["plan"], indent=2),
                    reference_now=ex["reference_now"],
                    template_texts=texts,
                    groups=ex["gold"]["groups"],
                )
        finally:
            view.close()

    keys = list(requests)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = dict(zip(keys, pool.map(author.author, (requests[k] for k in keys)), strict=True))

    # Near-duplicates are checked against every question that is staying as it is.
    dedupe = filters.NearDuplicateIndex()
    for split, exs in examples.items():
        skip = set(flagged[split])
        for i, ex in enumerate(exs):
            if i not in skip:
                dedupe.add(ex["question"])

    report: dict[str, dict] = {}
    for split, exs in examples.items():
        counts: Counter = Counter()
        drop: set[int] = set()
        index = LogIndex(data_dir / f"{split}.db")
        view = CorpusView(data_dir / f"{split}.db")
        row_count = view.row_count
        try:
            for i in flagged[split]:
                ex, result = exs[i], results[(split, i)]
                question = result.question
                reason = result.reason if question is None else _question_rejection(ex, question, index, dedupe)
                if reason:
                    counts[f"dropped:{reason}"] += 1
                    drop.add(i)
                    continue
                plan, gold, repairs = ex["plan"], ex["gold"], [*ex.get("repairs", []), REAUTHOR]
                if _needs_flooring(plan, question):
                    # The new question rounds a window the old one stated to the
                    # second: the same mismatch decision 0020 repaired.
                    plan = _floored(plan)
                    fresh, reason = compute_gold(
                        index,
                        QueryPlan.model_validate(plan),
                        now=timeutil.parse_instant(ex["reference_now"]),
                        row_count=row_count,
                    )
                    if fresh is None:
                        counts[f"dropped:{reason}"] += 1
                        drop.add(i)
                        continue
                    gold, repairs = fresh.to_dict(), [*repairs, REPAIR]
                    counts["reauthored_floored"] += 1
                dedupe.add(question)
                texts = {tid: view.template_text(tid) for tid in _template_ids(ex["plan"])}
                rows = [r.raw for r in view.rows(ex["gold"]["row_ids"][:_ROWS_CHECKED])]
                if filters.unsupported_detail(question, _plan_text(ex["plan"], texts), rows):
                    counts["reauthored_still_flagged"] += 1
                counts["reauthored"] += 1
                exs[i] = {
                    **ex,
                    "plan": plan,
                    "gold": gold,
                    "question": question,
                    "replaced_question": ex["question"],
                    "author_model": result.model,
                    "prompt_version": PROMPT_VERSION,
                    "repairs": repairs,
                }
        finally:
            index.close()
            view.close()

        kept = [ex for i, ex in enumerate(exs) if i not in drop]
        splits[split].rename(data_dir / f"{split}.pre-{REAUTHOR}.jsonl")
        splits[split].write_text("".join(json.dumps(ex, sort_keys=True) + "\n" for ex in kept))
        report[split] = {
            "before": len(exs),
            "flagged": len(flagged[split]),
            "after": len(kept),
            **dict(sorted(counts.items())),
            "strata": dict(sorted(Counter(ex["stratum"] for ex in kept).items())),
        }

    manifest.setdefault("repairs", []).append(
        {
            "name": REAUTHOR,
            "decision": "0022",
            "prompt_version": PROMPT_VERSION,
            "author_model": getattr(author, "model", None),
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "splits": report,
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return report


def _question_rejection(ex: dict, question: str, index: LogIndex, dedupe: filters.NearDuplicateIndex) -> str | None:
    """The generation-time question filters, in the same order (pipeline._one_example)."""
    if filters.leaks_dsl(question):
        return "dsl_leak"
    if filters.asks_count_for_rows(question, any(q.get("aggregate") for q in ex["plan"]["queries"])):
        return "shape_mismatch"
    if ex["stratum"] not in filters.SIMPLE_STRATA and filters.keyword_trivial(
        index, question, ex["gold"]["row_ids"], now=timeutil.parse_instant(ex["reference_now"])
    ):
        return "keyword_trivial"
    if dedupe.is_duplicate(question):
        return "near_duplicate"
    return None


def _leaves(plan: dict):
    def walk(node):
        if isinstance(node, dict):
            yield node
            for child in node.get("of") or []:
                yield from walk(child)

    for q in plan["queries"]:
        yield from walk(q.get("where"))


def _template_ids(plan: dict) -> set[int]:
    return {n["value"] for n in _leaves(plan) if n.get("op") == "template_id"}


def _plan_text(plan: dict, template_texts: dict[int, str]) -> str:
    parts = [str(n["value"]) for n in _leaves(plan) if n.get("op") in ("term", "location_key", "severity")]
    return " ".join([*parts, *template_texts.values()])
