"""Run a planner over dataset splits, score by execution, write a results file.

Records are appended to `<out>.partial.jsonl` as they finish, so a long local
run that dies resumes where it stopped instead of starting over.
"""

from __future__ import annotations

import json
import random
import statistics
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from logger.index import LogIndex

from planner_rl.eval.backend import ChatBackend
from planner_rl.eval.prompt import EVAL_PROMPT_VERSION, SYSTEM_PROMPT, corpus_card, user_prompt
from planner_rl.eval.score import SCORER_VERSION, score_output

DEFAULT_SEED = 20261030
# If this many calls in a row fail at the HTTP level, the request itself is
# wrong (a rejected parameter, a bad model name): stop instead of scoring zeros.
ABORT_AFTER_CALL_ERRORS = 5


def load_examples(data_dir: Path, split: str) -> list[dict]:
    with open(data_dir / f"{split}.jsonl") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def sample_examples(examples: list[dict], n: int | None, seed: int) -> list[dict]:
    """A seeded subset, the same for every model given the same seed."""
    if n is None or n >= len(examples):
        return examples
    picked = random.Random(seed).sample(sorted(examples, key=lambda e: e["id"]), n)
    return sorted(picked, key=lambda e: e["id"])


def run_eval(
    data_dirs: list[Path],
    *,
    split: str,
    backend: ChatBackend,
    out: Path,
    per_corpus: int | None = None,
    seed: int = DEFAULT_SEED,
    concurrency: int = 1,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    partial = out.with_suffix(".partial.jsonl")
    done = {}
    if partial.exists():
        for line in partial.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                if not rec.get("call_error"):  # a failed call is retried on resume
                    done[rec["id"]] = rec
    out.parent.mkdir(parents=True, exist_ok=True)

    datasets = []
    total = 0
    for data_dir in data_dirs:
        manifest = json.loads((data_dir / "manifest.json").read_text())
        examples = sample_examples(load_examples(data_dir, split), per_corpus, seed)
        datasets.append((data_dir, manifest, examples))
        total += len(examples)

    finished = len(done)
    failing = 0
    with open(partial, "a") as sink:
        for data_dir, manifest, examples in datasets:
            db = data_dir / f"{split}.db"
            card = corpus_card(db, dataset=manifest["dataset"])
            index = LogIndex(db)
            todo = [e for e in examples if e["id"] not in done]
            try:
                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    futures = {}
                    for e in todo:
                        prefix, suffix = user_prompt(card, e["question"], e["reference_now"])
                        futures[pool.submit(backend.complete, SYSTEM_PROMPT, suffix, shared_prefix=prefix)] = e
                    for future in as_completed(futures):
                        ex = futures[future]
                        completion = future.result()
                        failing = failing + 1 if completion.error else 0
                        if failing >= ABORT_AFTER_CALL_ERRORS:
                            for f in futures:
                                f.cancel()
                            raise RuntimeError(f"{failing} model calls in a row failed; last: {completion.error}")
                        score = score_output(
                            completion.text,
                            ex["gold"],
                            index,
                            now=datetime.fromisoformat(ex["reference_now"]),
                        )
                        rec = {
                            "id": ex["id"],
                            "dataset": manifest["dataset"],
                            "stratum": ex["stratum"],
                            "output": completion.text,
                            "latency_s": round(completion.latency_s, 3),
                            "prompt_tokens": completion.prompt_tokens,
                            "completion_tokens": completion.completion_tokens,
                            "cost_usd": completion.cost_usd,
                            "call_error": completion.error,
                            **score.to_dict(),
                        }
                        done[ex["id"]] = rec
                        sink.write(json.dumps(rec) + "\n")
                        sink.flush()
                        finished += 1
                        if progress:
                            progress(finished, total)
            finally:
                index.close()

    wanted = [e["id"] for _, _, examples in datasets for e in examples]
    records = [done[i] for i in wanted]
    results = {
        "model": backend.model,
        "base_url": backend.base_url,
        "thinking": backend.thinking,
        "effort": getattr(backend, "effort", None),
        "prompt_version": EVAL_PROMPT_VERSION,
        "scorer_version": SCORER_VERSION,
        "split": split,
        "seed": seed,
        "per_corpus": per_corpus,
        "datasets": [
            {
                "dir": str(d),
                "dataset": m["dataset"],
                "corpus_digest": m["corpus_digest"],
                "data_prompt_version": m["prompt_version"],
                "examples": len(ex),
            }
            for d, m, ex in datasets
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary": summarize(records),
        "records": records,
    }
    out.write_text(json.dumps(results, indent=1))
    partial.unlink()
    return results


def rescore(path: Path) -> dict:
    """Re-score saved outputs under the current rules; no model calls."""
    results = json.loads(path.read_text())
    examples = {}
    indexes = {}
    try:
        for ds in results["datasets"]:
            data_dir = Path(ds["dir"])
            for ex in load_examples(data_dir, results["split"]):
                examples[ex["id"]] = ex
            indexes[ds["dataset"]] = LogIndex(data_dir / f"{results['split']}.db")
        # A repair may have dropped examples; their records go too, and the
        # file says how many.
        kept = [rec for rec in results["records"] if rec["id"] in examples]
        results["dropped_by_repair"] = results.get("dropped_by_repair", 0) + len(results["records"]) - len(kept)
        results["records"] = kept
        for rec in results["records"]:
            ex = examples[rec["id"]]
            score = score_output(
                rec["output"], ex["gold"], indexes[rec["dataset"]], now=datetime.fromisoformat(ex["reference_now"])
            )
            rec.update(score.to_dict())
    finally:
        for index in indexes.values():
            index.close()
    results["scorer_version"] = SCORER_VERSION
    results["data_repairs"] = sorted(
        {r["name"] for ds in results["datasets"] for r in _manifest(Path(ds["dir"])).get("repairs", [])}
    )
    results["summary"] = summarize(results["records"])
    path.write_text(json.dumps(results, indent=1))
    return results


def _manifest(data_dir: Path) -> dict:
    return json.loads((data_dir / "manifest.json").read_text())


def summarize(records: list[dict]) -> dict:
    by: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        by["all"].append(rec)
        by[f"dataset:{rec['dataset']}"].append(rec)
        by[f"stratum:{rec['stratum']}"].append(rec)
    return {name: _stats(group) for name, group in by.items()}


def _stats(recs: list[dict]) -> dict:
    def mean(values: list) -> float | None:
        vals = [v for v in values if v is not None]
        return round(statistics.fmean(vals), 4) if vals else None

    costs = [r["cost_usd"] for r in recs if r.get("cost_usd") is not None]
    return {
        "n": len(recs),
        "answer": mean([r["answer"] for r in recs]),
        "format_valid": mean([float(r["format_valid"]) for r in recs]),
        "executed": mean([float(r["executed"]) for r in recs]),
        "row_f1": mean([r["row_f1"] for r in recs]),
        "row_recall": mean([r["row_recall"] for r in recs]),
        "group_f1": mean([r["group_f1"] for r in recs]),
        "query_count": mean([r["query_count"] for r in recs if r["executed"]]),
        "rows_scanned": mean([r["rows_scanned"] for r in recs if r["executed"]]),
        "latency_p50_s": round(statistics.median(r["latency_s"] for r in recs), 3) if recs else None,
        "completion_tokens": mean([r["completion_tokens"] for r in recs]),
        "cost_usd": round(sum(costs), 4) if costs else None,
    }
