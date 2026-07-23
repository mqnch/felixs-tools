"""Coarse Brain query result shapes. Exact query language is still open."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from felixs_common.location import LocationId


class BrainNodeKind(StrEnum):
    FILE = "file"
    FUNCTION = "function"
    CLASS = "class"
    OWNER = "owner"


class BrainNode(BaseModel):
    """A node in Brain's structural / ownership graph."""

    id: str
    kind: BrainNodeKind
    location: LocationId | None = None
    label: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class BrainEdge(BaseModel):
    """A directed edge between Brain nodes."""

    source_id: str
    target_id: str
    kind: str = Field(description="e.g. calls, imports, co_changes, owns")
    weight: float | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class BrainQueryResult(BaseModel):
    """Structured result of a Brain graph query (blast radius, ownership, etc.)."""

    query: str = Field(description="Opaque query identifier or description")
    nodes: list[BrainNode] = Field(default_factory=list)
    edges: list[BrainEdge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
