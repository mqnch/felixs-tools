"""Minimal preset schema placeholder. Full fields come from real manual workflows."""

from typing import Any

from pydantic import BaseModel, Field


class PresetStep(BaseModel):
    """One step in a Swarm preset pipeline."""

    id: str
    uses: str = Field(
        description="Service/capability this step calls, e.g. logger, brain, llm, git",
    )
    with_: dict[str, Any] = Field(
        default_factory=dict,
        alias="with",
        description="Step inputs; may reference prior step outputs",
    )
    requires_approval: bool = Field(
        default=False,
        description="True for external side effects (PR, Slack, tickets)",
    )


class Preset(BaseModel):
    """Declarative Swarm pipeline. Schema will grow once presets are real."""

    name: str
    description: str = ""
    steps: list[PresetStep] = Field(default_factory=list)

    model_config = {"populate_by_name": True}
