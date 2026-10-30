"""Stratified sampling over the frozen DSL.

Uniform sampling over plan shapes overproduces trivial single-filter plans
(decision 0004), so the sampler picks a **stratum** first, at a target rate,
and builds a plan of that shape. Every plan is grounded in a real *anchor row*
of the split, so its leaves are satisfiable; whether the plan as a whole is
any good is decided after execution, in `gold`.

The sampler only proposes. It never sees question text and never judges.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta

from common import (
    MAX_LIMIT,
    Aggregate,
    AndNode,
    GroupByField,
    Having,
    LocationKeyNode,
    Node,
    NotNode,
    OrNode,
    Query,
    QueryPlan,
    SeverityNode,
    TemplateIdNode,
    TermNode,
    TimeRangeNode,
)
from logger import timeutil

from planner_rl.data.corpus import AnchorRow, CorpusView, literal_words

# Target share of *accepted* examples per stratum. Rejection rates differ by
# stratum, so the pipeline tracks accepted counts and re-weights toward the
# strata that are under target, rather than trusting these as draw rates.
DEFAULT_MIX: dict[str, float] = {
    "single_leaf": 0.10,
    "conjunction": 0.15,
    "negation": 0.15,
    "disjunction": 0.15,
    "time_range": 0.15,
    "aggregate": 0.15,
    "multi_query": 0.15,
}

_WINDOWS = [timedelta(minutes=10), timedelta(hours=1), timedelta(hours=6), timedelta(days=1)]

# Function words make term leaves nobody would search for ("such", "the"); the
# first pilot audit had questions built around TERM=such.
_TERM_STOP = frozenset(
    "a an the and or of to in on at for from with without by is are was were be been "
    "has have had not no but if then than so such as it its this that these those there "
    "here into onto over under up down out off all any some each per via can could will "
    "would should may might must do does did done being about".split()
)


def term_words(template: str) -> list[str]:
    """Literal template words worth searching for: no function words, nothing under 3 chars."""
    return [w for w in literal_words(template) if len(w) >= 3 and w.lower() not in _TERM_STOP]


@dataclass(frozen=True)
class SampledPlan:
    plan: QueryPlan
    stratum: str
    anchor_ids: tuple[int, ...]


class PlanSampler:
    def __init__(self, view: CorpusView, rng: random.Random) -> None:
        self.view = view
        self.rng = rng
        self._now = view.timestamp_bounds()[1]

    def sample(self, stratum: str) -> SampledPlan | None:
        """One plan of the given shape, or None if this anchor cannot support it."""
        build = getattr(self, f"_{stratum}", None)
        if build is None:
            raise ValueError(f"unknown stratum {stratum!r}")
        anchor = self.view.anchor(self.rng)
        result = build(anchor)
        if result is None:
            return None
        queries, anchors = result
        return SampledPlan(
            plan=QueryPlan(queries=queries),
            stratum=stratum,
            anchor_ids=tuple(a.id for a in anchors),
        )

    # --- leaves ----------------------------------------------------------------

    def _leaf(self, anchor: AnchorRow, kinds: list[str] | None = None) -> Node | None:
        """A positive predicate the anchor row satisfies."""
        options = list(kinds or ["term", "severity", "template_id", "location_key"])
        self.rng.shuffle(options)
        for kind in options:
            if kind == "term":
                words = term_words(self.view.template_text(anchor.template_id))
                if words:
                    return TermNode(value=self.rng.choice(words))
            elif kind == "severity" and anchor.severity:
                return SeverityNode(value=anchor.severity)
            elif kind == "template_id":
                return TemplateIdNode(value=anchor.template_id)
            elif kind == "location_key" and anchor.location_key:
                return LocationKeyNode(value=anchor.location_key)
        return None

    def _other_value_leaf(self, anchor: AnchorRow) -> Node | None:
        """A predicate the anchor does NOT satisfy: material for `not` and `or`."""
        kinds = ["severity", "location_key", "template_id", "term"]
        self.rng.shuffle(kinds)
        for kind in kinds:
            if kind == "severity":
                pool = [s for s in self.view.severities if s != anchor.severity]
                if pool:
                    return SeverityNode(value=self.rng.choice(pool))
            elif kind == "location_key":
                pool = [k for k in self.view.location_keys if k != anchor.location_key]
                if pool:
                    return LocationKeyNode(value=self.rng.choice(pool))
            elif kind == "template_id":
                pool = [t for t in self.view.template_ids if t != anchor.template_id]
                if pool:
                    return TemplateIdNode(value=self.rng.choice(pool))
            elif kind == "term":
                other = self.view.anchor(self.rng)
                words = [w for w in term_words(self.view.template_text(other.template_id)) if w not in anchor.raw]
                if words:
                    return TermNode(value=self.rng.choice(words))
        return None

    def _time_leaf(self, anchor: AnchorRow) -> Node | None:
        stamp = timeutil.parse_instant(anchor.timestamp) if anchor.timestamp else None
        if stamp is None:
            return None
        window = self.rng.choice(_WINDOWS)
        now = timeutil.parse_instant(self._now) if self._now else None
        # Relative bounds only make sense near the end of the split, where a
        # person would say "in the last N hours".
        if now is not None and now - stamp <= window and self.rng.random() < 0.5:
            hours = max(1, int(window.total_seconds() // 3600))
            unit = "h" if window >= timedelta(hours=1) else "m"
            amount = hours if unit == "h" else int(window.total_seconds() // 60)
            return TimeRangeNode(since=f"-{amount}{unit}")
        offset = window * self.rng.random()
        since = (stamp - offset).replace(microsecond=0)
        until = since + window
        return TimeRangeNode(since=since.isoformat(), until=until.isoformat())

    # --- strata ---------------------------------------------------------------

    def _row_query(self, where: Node | None) -> Query:
        # Gold is the complete matching set (decision 0013); the limit is set
        # high so it never truncates, and `gold` rejects plans that hit it.
        return Query(where=where, limit=MAX_LIMIT)

    def _single_leaf(self, a: AnchorRow):
        leaf = self._leaf(a)
        return ([self._row_query(leaf)], [a]) if leaf else None

    def _conjunction(self, a: AnchorRow):
        first = self._leaf(a)
        second = self._leaf(a)
        if first is None or second is None or first == second:
            return None
        children = [first, second]
        if self.rng.random() < 0.3 and (third := self._leaf(a)) and third not in children:
            children.append(third)
        return [self._row_query(AndNode(of=children))], [a]

    def _negation(self, a: AnchorRow):
        positive = self._leaf(a)
        negated = self._other_value_leaf(a)
        if positive is None or negated is None:
            return None
        return [self._row_query(AndNode(of=[positive, NotNode(of=[negated])]))], [a]

    def _disjunction(self, a: AnchorRow):
        b = self.view.anchor(self.rng)
        left, right = self._leaf(a), self._leaf(b)
        if left is None or right is None or left == right:
            return None
        either: Node = OrNode(of=[left, right])
        if self.rng.random() < 0.5 and a.severity and a.severity == b.severity:
            either = AndNode(of=[SeverityNode(value=a.severity), either])
        return [self._row_query(either)], [a, b]

    def _time_range(self, a: AnchorRow):
        window = self._time_leaf(a)
        if window is None:
            return None
        other = self._leaf(a)
        where = AndNode(of=[window, other]) if other else window
        return [self._row_query(where)], [a]

    def _aggregate(self, a: AnchorRow):
        group_by = [self.rng.choice(list(GroupByField))]
        if self.rng.random() < 0.2:
            second = self.rng.choice([f for f in GroupByField if f not in group_by])
            group_by.append(second)
        where: Node | None = None
        roll = self.rng.random()
        if roll < 0.4:
            where = self._time_leaf(a)
        elif roll < 0.8:
            where = self._leaf(a, ["severity", "location_key", "term"])
        having = None
        if self.rng.random() < 0.3:
            having = Having(min_count=self.rng.choice([2, 5, 10, 50]))
        query = Query(
            where=where,
            limit=MAX_LIMIT,
            aggregate=Aggregate(group_by=group_by, having=having),
        )
        return [query], [a]

    def _multi_query(self, a: AnchorRow):
        count = 2 if self.rng.random() < 0.75 else 3
        anchors = [a, *(self.view.anchor(self.rng) for _ in range(count - 1))]
        queries: list[Query] = []
        for i, anchor in enumerate(anchors):
            # Mix shapes inside one plan; one aggregate at most, never first.
            if i > 0 and self.rng.random() < 0.25 and not any(q.aggregate for q in queries):
                built = self._aggregate(anchor)
            else:
                builder = self.rng.choice([self._single_leaf, self._conjunction, self._negation])
                built = builder(anchor)
            if built is None or any(q.where == built[0][0].where for q in queries):
                return None
            queries.append(built[0][0].model_copy(update={"label": f"q{i + 1}"}))
        return queries, anchors
