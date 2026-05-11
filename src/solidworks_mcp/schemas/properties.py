"""Schemas for metadata, BOM, material, and configuration operations."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from solidworks_mcp.schemas.common import ResponseFormat, StrictModel


PropertyScope = Literal["file", "configuration", "cut_list"]


class CustomPropertiesInput(StrictModel):
    backend: Literal["auto", "solidworks", "headless"] = "auto"
    scope: PropertyScope = "file"
    configuration: str | None = None
    response_format: ResponseFormat = ResponseFormat.JSON


class SetCustomPropertiesInput(CustomPropertiesInput):
    properties: dict[str, Any] = Field(..., min_length=1)
    replace: bool = Field(default=False, description="If true, remove existing properties not present in input when supported.")


class MaterialInput(StrictModel):
    backend: Literal["auto", "solidworks", "headless"] = "auto"
    material: str | None = Field(default=None, description="Optional material to set; omit for read-only get.")
    response_format: ResponseFormat = ResponseFormat.JSON


class ConfigurationInput(StrictModel):
    backend: Literal["auto", "solidworks", "headless"] = "auto"
    action: Literal["list", "create", "delete", "activate", "rename"]
    name: str | None = None
    new_name: str | None = None
    response_format: ResponseFormat = ResponseFormat.JSON


class BomInput(StrictModel):
    backend: Literal["auto", "solidworks", "headless"] = "auto"
    source: Literal["active_document", "assembly", "drawing"] = "active_document"
    response_format: ResponseFormat = ResponseFormat.JSON

