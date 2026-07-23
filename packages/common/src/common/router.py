"""Router request/response shapes (used even while Router is a stub)."""

from typing import Any

from pydantic import BaseModel, Field

from common.tasks import TaskType


class RouterRequest(BaseModel):
    """One model call routed through the thin Router wrapper."""

    task_type: TaskType = Field(description="Caller-tagged task type for policy")
    messages: list[dict[str, Any]] = Field(
        description="Chat messages in OpenAI-compatible shape",
    )
    model: str | None = Field(
        default=None,
        description="Optional explicit model override; policy may ignore this",
    )
    temperature: float | None = Field(default=None)
    max_tokens: int | None = Field(default=None)
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Passthrough kwargs for the underlying completion call",
    )


class RouterResponse(BaseModel):
    """Normalized completion result from Router."""

    content: str = Field(description="Primary text content from the model")
    model: str = Field(description="Model that produced the response")
    cached: bool = Field(default=False, description="True if served from cache")
    raw: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific payload when callers need it",
    )
