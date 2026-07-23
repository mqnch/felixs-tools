"""Anomaly scorer: flags novel or spiking templates."""

from __future__ import annotations

import json
from dataclasses import dataclass

from felixs_common import RouterRequest, TaskType
from felixs_router import complete

from felixs_logger.index import LogIndex
from felixs_logger.parser import ParsedLine


@dataclass(frozen=True)
class AnomalyScore:
    template_id: int
    template: str
    score: float
    novel: bool
    reason: str


class AnomalyScorer:
    """Scores incoming lines. Classical frequency first; Router for optional judgment."""

    def __init__(self, index: LogIndex, *, spike_ratio: float = 3.0) -> None:
        self._index = index
        self._spike_ratio = spike_ratio
        self._seen_templates: set[int] = set(index.template_counts())

    def score(self, parsed: ParsedLine) -> AnomalyScore:
        counts = self._index.template_counts()
        count = counts.get(parsed.template_id, 0)
        is_new = parsed.template_id not in self._seen_templates
        self._seen_templates.add(parsed.template_id)

        total = sum(counts.values()) or 1
        mean = total / max(len(counts), 1)
        freq_score = count / mean if mean else 0.0
        novel = is_new or freq_score >= self._spike_ratio

        reason = "new_template" if is_new else (
            "frequency_spike" if freq_score >= self._spike_ratio else "normal"
        )
        score = 1.0 if is_new else min(freq_score / self._spike_ratio, 1.0)

        # Optional model judgment layered on top; stub may return non-novel.
        request = RouterRequest(
            task_type=TaskType.ANOMALY_SCORING,
            messages=[
                {
                    "role": "system",
                    "content": (
                        'Judge if this log template is anomalous. '
                        'Reply JSON: {"novel":bool,"score":float,"reason":str}'
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "template": parsed.template,
                            "template_id": parsed.template_id,
                            "count": count,
                            "classical_novel": novel,
                            "classical_score": score,
                        }
                    ),
                },
            ],
        )
        response = complete(request)
        model = _parse_model_score(response.content)
        if model is not None:
            # Prefer classical novelty signal; let model adjust score/reason.
            return AnomalyScore(
                template_id=parsed.template_id,
                template=parsed.template,
                score=max(score, float(model.get("score", score))),
                novel=novel or bool(model.get("novel", False)),
                reason=str(model.get("reason") or reason),
            )

        return AnomalyScore(
            template_id=parsed.template_id,
            template=parsed.template,
            score=score,
            novel=novel,
            reason=reason,
        )


def _parse_model_score(content: str) -> dict | None:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
