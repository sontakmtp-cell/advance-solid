"""Common schemas and constrained enums."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)


class ResponseFormat(str, Enum):
    JSON = "json"
    MARKDOWN = "markdown"


DetailLevel = Literal["concise", "detailed"]
BackendName = Literal["solidworks", "headless"]


class Capability(StrictModel):
    supported: bool
    level: Literal["full", "partial", "unsupported"] = "unsupported"
    notes: str | None = None
    next_step: str | None = None


class CapabilityMap(StrictModel):
    backend: str
    categories: dict[str, dict[str, Capability]] = Field(default_factory=dict)


class ToolResult(StrictModel):
    ok: bool = True
    backend: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class Pagination(StrictModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)

