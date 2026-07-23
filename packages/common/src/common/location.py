"""Shared location/entity identifier for correlating Logger and Brain."""

from pydantic import BaseModel, Field


class LocationId(BaseModel):
    """Canonical reference to a place in a codebase.

    Logger tags indexed entries with this; Brain keys graph nodes the same way
    so Swarm presets can join anomalies to blast radius without guesswork.
    """

    path: str = Field(description="Repo-relative file path")
    service: str | None = Field(
        default=None,
        description="Optional service/component label mapped from the path",
    )

    def key(self) -> str:
        """Stable string key for indexes and joins."""
        if self.service:
            return f"{self.service}:{self.path}"
        return self.path
