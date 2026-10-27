"""`gen-data`: sample a plan → execute it → gold → author the question → filter.

Output layout, one directory per corpus:

    <out>/train.db  val.db  test.db      split corpora; gold is defined against these
    <out>/train.jsonl val.jsonl test.jsonl
    <out>/manifest.json                   generator, prompt version, seed, counts

Each split is generated in turn, against its own database, with its own target
count. The near-duplicate index is shared across splits.
"""

from __future__ import annotations

import json
import random
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from common import SCHEMA_VERSION, TemplateIdNode
from logger import timeutil
from logger.index import LogIndex

from planner_rl.data import filters
from planner_rl.data.author import PROMPT_VERSION, AuthorRequest, QuestionAuthor
from planner_rl.data.corpus import (
    DEFAULT_FRACTIONS,
    SPLITS,
    CorpusView,
    build_splits,
)
from planner_rl.data.gold import compute_gold
from planner_rl.data.sampler import DEFAULT_MIX, PlanSampler, SampledPlan

DEFAULT_SEED = 20261027
MAX_ATTEMPTS_PER_EXAMPLE = 40
SAMPLE_ROWS_FOR_AUTHOR = 6


@dataclass
class SplitStats:
    target: int = 0
    accepted: int = 0
    attempts: int = 0
    strata: Counter = field(default_factory=Counter)
    rejections: Counter = field(default_factory=Counter)


@dataclass
class DatasetManifest:
    dataset: str
    corpus_db: str
    corpus_digest: str | None
    corpus_license: dict | None
    schema_version: str
    generator_model: str | None
    prompt_version: str
    seed: int
    mix: dict[str, float]
    fractions: list[float]
    windows: list[dict]
    splits: dict[str, dict]
    created_at: str
    dry_run: bool

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n")


def generate_dataset(
    *,
    corpus_db: str | Path,
    out_dir: str | Path,
    n: int,
    author: QuestionAuthor | None,
    seed: int = DEFAULT_SEED,
    mix: dict[str, float] | None = None,
    fractions: tuple[float, float, float] = DEFAULT_FRACTIONS,
    progress=None,
) -> DatasetManifest:
    """Build the dataset. `author=None` is a dry run: plans and gold, no questions.

    A dry run exercises everything except the paid model call, so stratum
    coverage and structural rejection rates can be checked before spending.
    """
    mix = dict(mix or DEFAULT_MIX)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dataset, corpus_manifest = _corpus_identity(corpus_db)
    windows = build_splits(corpus_db, out, fractions=fractions)
    rng = random.Random(seed)
    dedupe = filters.NearDuplicateIndex()
    seen_plans: set[str] = set()
    stats: dict[str, SplitStats] = {}

    for split, frac in zip(SPLITS, fractions, strict=True):
        target = max(1, round(n * frac))
        stats[split] = _generate_split(
            split=split,
            db=out / f"{split}.db",
            out_path=out / f"{split}.jsonl",
            target=target,
            dataset=dataset,
            author=author,
            rng=random.Random(rng.getrandbits(64)),
            mix=mix,
            dedupe=dedupe,
            seen_plans=seen_plans,
            progress=progress,
        )

    manifest = DatasetManifest(
        dataset=dataset,
        corpus_db=str(corpus_db),
        corpus_digest=corpus_manifest.get("content_digest"),
        corpus_license=corpus_manifest.get("license"),
        schema_version=SCHEMA_VERSION,
        generator_model=author.model if author else None,
        prompt_version=PROMPT_VERSION,
        seed=seed,
        mix=mix,
        fractions=list(fractions),
        windows=[asdict(w) for w in windows],
        splits={
            s: {
                "target": st.target,
                "accepted": st.accepted,
                "attempts": st.attempts,
                "strata": dict(sorted(st.strata.items())),
                "rejections": dict(sorted(st.rejections.items())),
            }
            for s, st in stats.items()
        },
        created_at=timeutil.canonical(timeutil.utcnow()),
        dry_run=author is None,
    )
    manifest.write(out / "manifest.json")
    return manifest


def _generate_split(
    *,
    split: str,
    db: Path,
    out_path: Path,
    target: int,
    dataset: str,
    author: QuestionAuthor | None,
    rng: random.Random,
    mix: dict[str, float],
    dedupe: filters.NearDuplicateIndex,
    seen_plans: set[str],
    progress,
) -> SplitStats:
    stats = SplitStats(target=target)
    view = CorpusView(db)
    index = LogIndex(db)
    now = index.reference_now()
    sampler = PlanSampler(view, rng)
    try:
        with out_path.open("w") as fh:
            while stats.accepted < target:
                if stats.attempts >= target * MAX_ATTEMPTS_PER_EXAMPLE:
                    stats.rejections["gave_up"] += 1
                    break
                stats.attempts += 1
                stratum = _next_stratum(rng, mix, stats, target)
                example, reason = _one_example(
                    stratum, sampler, view, index, now, dataset, author, dedupe, seen_plans
                )
                if example is None:
                    stats.rejections[reason or "unknown"] += 1
                    continue
                example["id"] = f"{dataset}-{split}-{stats.accepted:06d}"
                example["split"] = split
                fh.write(json.dumps(example, sort_keys=True) + "\n")
                stats.accepted += 1
                stats.strata[stratum] += 1
                if progress:
                    progress(split, stats.accepted, target)
    finally:
        index.close()
        view.close()
    return stats


def _next_stratum(rng: random.Random, mix: dict[str, float], stats: SplitStats, target: int) -> str:
    """Draw toward strata that are furthest under their target share."""
    deficits = {
        s: max(0.0, share * target - stats.strata[s]) for s, share in mix.items() if share > 0
    }
    total = sum(deficits.values())
    if total <= 0:
        return rng.choice([s for s, share in mix.items() if share > 0])
    roll = rng.random() * total
    for s, d in deficits.items():
        roll -= d
        if roll <= 0:
            return s
    return next(iter(deficits))


def _one_example(
    stratum: str,
    sampler: PlanSampler,
    view: CorpusView,
    index: LogIndex,
    now,
    dataset: str,
    author: QuestionAuthor | None,
    dedupe: filters.NearDuplicateIndex,
    seen_plans: set[str],
) -> tuple[dict | None, str | None]:
    sampled = sampler.sample(stratum)
    if sampled is None:
        return None, "unsampleable"
    plan_json = sampled.plan.model_dump_json(exclude_none=True)
    if plan_json in seen_plans:
        return None, "duplicate_plan"

    gold, reason = compute_gold(index, sampled.plan, now=now, row_count=view.row_count)
    if gold is None:
        return None, reason
    seen_plans.add(plan_json)

    example = {
        "dataset": dataset,
        "stratum": stratum,
        "features": sorted(_features(sampled)),
        "plan": json.loads(plan_json),
        "gold": gold.to_dict(),
        "reference_now": timeutil.canonical(now),
        "schema_version": SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "question": None,
        "author_model": None,
    }
    if author is None:
        return example, None

    request = AuthorRequest(
        dataset=dataset,
        plan_json=sampled.plan.model_dump_json(exclude_none=True, indent=2),
        reference_now=timeutil.canonical(now),
        sample_rows=view.rows(_spread(gold.row_ids, SAMPLE_ROWS_FOR_AUTHOR)),
        template_texts={tid: view.template_text(tid) for tid in _template_ids(sampled)},
        groups=gold.groups,
    )
    result = author.author(request)
    if result.question is None:
        return None, result.reason or "author_failed"
    question = result.question

    if filters.leaks_dsl(question):
        return None, "dsl_leak"
    if stratum not in filters.SIMPLE_STRATA and filters.keyword_trivial(
        index, question, gold.row_ids, now=now
    ):
        return None, "keyword_trivial"
    if dedupe.is_duplicate(question):
        return None, "near_duplicate"
    dedupe.add(question)

    example["question"] = question
    example["author_model"] = result.model
    return example, None


def _features(sampled: SampledPlan) -> set[str]:
    """DSL features actually present, independent of the stratum label."""
    text = sampled.plan.model_dump_json()
    feats = {f'op:{op}' for op in ("and", "or", "not", "term", "severity", "template_id",
                                   "location_key", "time_range") if f'"op":"{op}"' in text}
    if any(q.aggregate for q in sampled.plan.queries):
        feats.add("aggregate")
    if any(q.aggregate and q.aggregate.having for q in sampled.plan.queries):
        feats.add("having")
    if len(sampled.plan.queries) > 1:
        feats.add("multi_query")
    if '"since":"-' in text:
        feats.add("relative_time")
    return feats


def _template_ids(sampled: SampledPlan) -> set[int]:
    found: set[int] = set()

    def walk(node) -> None:
        if isinstance(node, TemplateIdNode):
            found.add(node.value)
        for child in getattr(node, "of", []) or []:
            walk(child)

    for q in sampled.plan.queries:
        if q.where is not None:
            walk(q.where)
    return found


def _spread(ids: list[int], k: int) -> list[int]:
    """Evenly spaced sample, so the author sees the range of the result, not its head."""
    if len(ids) <= k:
        return ids
    step = len(ids) / k
    return [ids[int(i * step)] for i in range(k)]


def _corpus_identity(corpus_db: str | Path) -> tuple[str, dict]:
    """Dataset name and stored manifest from the slice-003 manifest table."""
    conn = sqlite3.connect(f"file:{corpus_db}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT dataset, manifest_json FROM corpus_manifest LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        conn.close()
    if row is None:
        return Path(corpus_db).stem, {}
    return row[0], json.loads(row[1])
