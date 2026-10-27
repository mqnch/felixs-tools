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

SIMPLE_STRATA = frozenset({"single_leaf"})
KEYWORD_F1_CEILING = 0.9
NEAR_DUP_JACCARD = 0.8


def leaks_dsl(question: str) -> bool:
    return any(p.search(question) for p in _LEAK_PATTERNS)


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
        words = frozenset(content_words(question))
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
        words = frozenset(content_words(question))
        idx = len(self._sets)
        self._sets.append(words)
        for w in words:
            self._postings.setdefault(w, []).append(idx)
