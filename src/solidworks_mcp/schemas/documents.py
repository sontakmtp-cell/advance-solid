"""Document and file operation schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from solidworks_mcp.schemas.common import DetailLevel, ResponseFormat, StrictModel


DocumentType = Literal["part", "assembly", "drawing", "unknown"]
ExportFormat = Literal["sldprt", "sldasm", "slddrw", "step", "iges", "pdf", "dxf", "dwg", "stl", "3mf", "x_t", "x_b"]


class BackendSelectInput(StrictModel):
    backend: Literal["auto", "solidworks", "headless"] = Field(
        default="auto",
        description="Backend to use. 'auto' uses SOLIDWORKS_MCP_BACKEND.",
    )
    response_format: ResponseFormat = ResponseFormat.JSON


class PathInput(BackendSelectInput):
    path: str = Field(..., min_length=1, description="File path inside SOLIDWORKS_MCP_WORKSPACE_ROOTS.")


class OpenDocumentInput(PathInput):
    document_type: DocumentType | None = Field(default=None)
    read_only: bool = Field(default=False)


class SaveDocumentInput(BackendSelectInput):
    path: str | None = Field(default=None, description="Optional target path inside allowlisted workspace roots.")


class ExportDocumentInput(PathInput):
    format: ExportFormat
    options: dict[str, Any] = Field(default_factory=dict)


class DocumentInfoInput(BackendSelectInput):
    path: str | None = None
    detail: DetailLevel = "concise"


class RebuildInput(BackendSelectInput):
    force: bool = Field(default=False)


class DocumentInfo(StrictModel):
    path: str | None = None
    title: str | None = None
    document_type: DocumentType = "unknown"
    units: str | None = None
    material: str | None = None
    mass: float | None = None
    volume: float | None = None
    configurations: list[str] = Field(default_factory=list)
    active_configuration: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def normalize_empty_path(cls, value: str | None) -> str | None:
        return value or None

