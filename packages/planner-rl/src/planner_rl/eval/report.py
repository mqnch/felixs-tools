"""Compare results files side by side, and apply the slice-005 difficulty gate."""

from __future__ import annotations

import json
from pathlib import Path

from planner_rl.eval.harness import summarize

# Slice 005's go/no-go: a stock model at or above this answer score means the
# task is too easy for RL to show a curve; harden the DSL before training.
GATE_THRESHOLD = 0.85


def load(paths: list[Path]) -> list[dict]:
    """Load results and restrict them all to the examples every file scored.

    A full run and a seeded sample of the same split then compare on the
    sample, instead of rerunning the full model on it.
    """
    results = [json.loads(p.read_text()) for p in paths]
    versions = {r["prompt_version"] for r in results}
    if len(versions) > 1:
        raise ValueError(f"results use different prompt versions {sorted(versions)}; not comparable")
    scorers = {r.get("scorer_version") for r in results}
    if len(scorers) > 1:
        raise ValueError(f"results use different scorer versions {sorted(map(str, scorers))}; run `planner-rl rescore`")
    common = set.intersection(*({rec["id"] for rec in r["records"]} for r in results))
    if not common:
        raise ValueError("results share no examples")
    for r in results:
        if len(common) < len(r["records"]):
            r["records"] = [rec for rec in r["records"] if rec["id"] in common]
            r["summary"] = summarize(r["records"])
    return results


def table(results: list[dict]) -> str:
    groups = sorted(g for g in results[0]["summary"] if g != "all")
    header = ["model", "answer", "format", "exec", "row_f1", "group_f1", "q/plan", "p50 s", "cost $"]
    rows = [header]
    for r in results:
        s = r["summary"]["all"]
        rows.append([
            _name(r),
            _f(s["answer"]),
            _f(s["format_valid"]),
            _f(s["executed"]),
            _f(s["row_f1"]),
            _f(s["group_f1"]),
            _f(s["query_count"], 2),
            _f(s["latency_p50_s"], 2),
            _f(s["cost_usd"], 2),
        ])
    out = [f"n={results[0]['summary']['all']['n']}", _render(rows), "", "answer by group:"]
    breakdown = [["group", *(_name(r) for r in results)]]
    for g in groups:
        breakdown.append([f"{g} (n={results[0]['summary'][g]['n']})", *(_f(r["summary"][g]["answer"]) for r in results)])
    out.append(_render(breakdown))
    return "\n".join(out)


def over_gate(results: list[dict]) -> list[str]:
    return [_name(r) for r in results if (r["summary"]["all"]["answer"] or 0) >= GATE_THRESHOLD]


def _name(r: dict) -> str:
    if r.get("effort"):
        return f"{r['model']} +think:{r['effort']}"
    return r["model"] + (" +think" if r.get("thinking") else "")


def _f(v, digits: int = 3) -> str:
    return "-" if v is None else f"{v:.{digits}f}"


def _render(rows: list[list[str]]) -> str:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)) for row in rows)
