"""Question-level rejection filters (slice 004).

These run after authoring, on the question text. They catch the quiet failure
modes of reverse generation: questions that leak DSL vocabulary, questions a
single keyword search already answers, and near-duplicates.
"""

from __future__ import annotations

import re
from datetime import datetime

from common import MAX_LIMIT, Query, TermNode
from logger.index import LogIndex

_LEAK_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\btemplate[_ ]?ids?\b",
        r"\btemplates?\b",
        r"\blocation[_ ]key\b",
        r"\bseverity\s*[=:]",
        r"\btime_range\b",
        r"\bgroup_by\b",
        r"\bhaving\b",
        r"\bmin_count\b",
        r'"op"',
        r"<\*>",
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}",  # ISO instants: a person does not type these
        r"\bquer(y|ies)\s+plan\b",
    )
]

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an the and or of to in on at for from with without by is are was were be been show me "
    "find list all any what which when where who how many much give get logs log lines line "
    "entries entry messages message events event that this those these there their it its "
    "not no but only last past during between within since until per each every do does did "
    "i we you can could would should".split()
)

# Words a question uses about the search itself, never about log content.
_FRAMING = frozenset(
    "logged logger write wrote written writes containing contains contain mention mentions "
    "mentioning saying says said word words term terms hours hour minutes minute days day "
    "today count counts counting times plus also both either other except excluding "
    "january february march april june july august september october november december utc "
    "level levels severity component components file files appear appeared appearing distinct "
    "pattern patterns type types kind kinds broken down grouped group number total overall "
    "least most across about whose".split()
)

SIMPLE_STRATA = frozenset({"single_leaf"})
KEYWORD_F1_CEILING = 0.9
NEAR_DUP_JACCARD = 0.8


def leaks_dsl(question: str) -> bool:
    return any(p.search(question) for p in _LEAK_PATTERNS)


def unsupported_detail(question: str, plan_text: str, returned_rows: list[str]) -> list[str]:
    """Question words that describe returned lines but appear nowhere in the plan.

    ``plan_text`` is everything the plan filters on, as text: term values,
    template texts and location keys. A word found in some returned line but
    not in ``plan_text`` came from the lines, not the plan, which is how an
    author narrows "every line from X" into "the task progress lines from X".
    Recall over precision: it picks examples to re-author, where a false
    positive costs one call (decision 0022).
    """
    allowed = set(_TOKEN_RE.findall(plan_text.lower()))
    in_rows = set(_TOKEN_RE.findall(" ".join(returned_rows).lower()))
    return [
        w
        for w in content_words(question)
        if w not in allowed and w not in _FRAMING and w in in_rows and not w.isdigit()
    ]


_COUNT_QUESTION = re.compile(r"^\W*(how many|count|what (is|was) the (number|count))\b", re.IGNORECASE)


def asks_count_for_rows(question: str, has_aggregate: bool) -> bool:
    """A "how many" question over a plan that returns rows has the wrong shape.

    The author prompt says to match the result's shape; the q-2026-10-30.4
    re-author still did this in 9 of 1084 questions (decision 0022).
    """
    return not has_aggregate and bool(_COUNT_QUESTION.search(question))


def content_words(question: str) -> list[str]:
    seen: list[str] = []
    for tok in _TOKEN_RE.findall(question.lower()):
        if len(tok) > 2 and tok not in _STOP and tok not in seen:
            seen.append(tok)
    return seen


def keyword_trivial(
    index: LogIndex, question: str, gold_ids: list[int], *, now: datetime
) -> bool:
    """True if one keyword from the question alone recovers the gold set.

    Only meaningful for complex plans: if a bare term search already scores
    F1 >= 0.9, the plan's structure is not what the example is teaching.
    """
    if not gold_ids:
        return False
    gold = set(gold_ids)
    for word in content_words(question):
        query = Query(where=TermNode(value=word), limit=MAX_LIMIT)
        got = set(index.query(query, now=now).row_ids)
        if _f1(got, gold) >= KEYWORD_F1_CEILING:
            return True
    return False


def _f1(got: set[int], gold: set[int]) -> float:
    hit = len(got & gold)
    if hit == 0:
        return 0.0
    precision, recall = hit / len(got), hit / len(gold)
    return 2 * precision * recall / (precision + recall)


def _dedupe_words(question: str) -> frozenset[str]:
    """Content words plus every number. `content_words` drops tokens under 3
    characters, which erased times: "17:49 to 17:59" and "18:10 to 18:20" over
    the same component looked identical, so time-window variants with different
    gold were rejected as near-duplicates (decision 0022)."""
    numbers = [t for t in _TOKEN_RE.findall(question.lower()) if t.isdigit()]
    return frozenset([*content_words(question), *numbers])


class NearDuplicateIndex:
    """Jaccard over content-word sets, with an inverted index to stay sub-quadratic.

    Shared across all splits, so a test question cannot be a paraphrase-level
    twin of a training one.
    """

    def __init__(self, threshold: float = NEAR_DUP_JACCARD) -> None:
        self.threshold = threshold
        self._sets: list[frozenset[str]] = []
        self._postings: dict[str, list[int]] = {}

    def __len__(self) -> int:
        return len(self._sets)

    def is_duplicate(self, question: str) -> bool:
        words = _dedupe_words(question)
        if not words:
            return True
        candidates: set[int] = set()
        for w in words:
            candidates.update(self._postings.get(w, ()))
        for i in candidates:
            other = self._sets[i]
            if len(words & other) / len(words | other) >= self.threshold:
                return True
        return False

    def add(self, question: str) -> None:
        words = _dedupe_words(question)
        idx = len(self._sets)
        self._sets.append(words)
        for w in words:
            self._postings.setdefault(w, []).append(idx)
