"""Manual audit of a generated dataset (slice 004).

The audit is done by a person. This module only draws the sample, writes a
sheet to fill in, and scores it. The three judgments are the ones slice 004
names: is the question natural, is it answerable from the logs, and is the
gold plan genuinely the best plan for it.

Decision 0004's reversal trigger reads off the scored sheet: a high rate of
unnatural or unanswerable questions means add a filtering pass or fall back to
a smaller hand-curated training set.
"""

from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path

JUDGMENTS = ("natural", "answerable", "best_plan")
COLUMNS = ("id", "split", "stratum", "question", "plan", "gold_summary", *JUDGMENTS, "notes")

# Below this pass rate on natural/answerable, decision 0004's reversal trigger fires.
PASS_THRESHOLD = 0.85


def write_audit_sheet(data_dir: str | Path, *, sample: int, seed: int, out: str | Path) -> Path:
    """Sample examples stratified by split and write a CSV to fill in."""
    data = Path(data_dir)
    rows: list[dict] = []
    for path in sorted(data.glob("*.jsonl")):
        rows.extend(json.loads(line) for line in path.open() if line.strip())
    rows = [r for r in rows if r.get("question")]
    if not rows:
        raise ValueError(f"no authored examples in {data}; was this a dry run?")

    rng = random.Random(seed)
    rng.shuffle(rows)
    picked = sorted(rows[:sample], key=lambda r: r["id"])

    dest = Path(out)
    with dest.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for r in picked:
            writer.writerow(
                {
                    "id": r["id"],
                    "split": r["split"],
                    "stratum": r["stratum"],
                    "question": r["question"],
                    "plan": json.dumps(r["plan"], sort_keys=True),
                    "gold_summary": _gold_summary(r["gold"]),
                    **{j: "" for j in JUDGMENTS},
                    "notes": "",
                }
            )
    return dest


def _gold_summary(gold: dict) -> str:
    parts = [f"{len(gold['row_ids'])} rows"]
    if gold.get("groups"):
        parts.append(f"{len(gold['groups'])} groups")
    return ", ".join(parts)


@dataclass(frozen=True)
class AuditScore:
    judged: int
    unjudged: int
    rates: dict[str, float]
    by_stratum: dict[str, dict[str, float]]

    @property
    def reversal_trigger(self) -> bool:
        return any(self.rates.get(j, 1.0) < PASS_THRESHOLD for j in ("natural", "answerable"))


def score_audit_sheet(path: str | Path) -> AuditScore:
    """Score a filled-in sheet. A row counts only once all three judgments are y/n."""
    judged: list[dict] = []
    unjudged = 0
    with Path(path).open(newline="") as fh:
        for row in csv.DictReader(fh):
            marks = {j: _mark(row.get(j, "")) for j in JUDGMENTS}
            if any(v is None for v in marks.values()):
                unjudged += 1
                continue
            judged.append({"stratum": row["stratum"], **marks})

    def rates(rows: list[dict]) -> dict[str, float]:
        if not rows:
            return {}
        return {j: sum(r[j] for r in rows) / len(rows) for j in JUDGMENTS}

    strata = sorted({r["stratum"] for r in judged})
    return AuditScore(
        judged=len(judged),
        unjudged=unjudged,
        rates=rates(judged),
        by_stratum={s: rates([r for r in judged if r["stratum"] == s]) for s in strata},
    )


def _mark(value: str) -> bool | None:
    v = value.strip().lower()
    if v in {"y", "yes", "1", "true"}:
        return True
    if v in {"n", "no", "0", "false"}:
        return False
    return None
