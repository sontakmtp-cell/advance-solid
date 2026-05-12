"""Schemas for feature, assembly, drawing, semantic, and routing tool requests."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from solidworks_mcp.schemas.common import DetailLevel, ResponseFormat, StrictModel


class FeatureOperationInput(StrictModel):
    backend: Literal["auto", "solidworks", "headless"] = "auto"
    operation: Literal[
        "create_sketch",
        "extrude_boss",
        "extrude_cut",
        "revolve",
        "fillet",
        "chamfer",
        "hole",
        "pattern",
        "mirror",
        "list_tree",
        "suppress",
        "unsuppress",
        "delete",
    ]
    parameters: dict[str, Any] = Field(default_factory=dict)
    response_format: ResponseFormat = ResponseFormat.JSON


class AssemblyOperationInput(StrictModel):
    backend: Literal["auto", "solidworks", "headless"] = "auto"
    operation: Literal[
        "insert_component",
        "add_mate",
        "move_component",
        "rotate_component",
        "list_components",
        "suppress_component",
        "unsuppress_component",
        "interference_detection",
        "exploded_view",
    ]
    parameters: dict[str, Any] = Field(default_factory=dict)
    response_format: ResponseFormat = ResponseFormat.JSON


class DrawingOperationInput(StrictModel):
    backend: Literal["auto", "solidworks", "headless"] = "auto"
    operation: Literal[
        "create_from_model",
        "insert_view",
        "add_dimension",
        "add_annotation",
        "insert_bom",
        "validate_layout",
        "title_block",
        "sheet_management",
    ]
    parameters: dict[str, Any] = Field(default_factory=dict)
    response_format: ResponseFormat = ResponseFormat.JSON


class AppearanceOperationInput(StrictModel):
    backend: Literal["auto", "solidworks", "headless"] = "auto"
    operation: Literal["set_color", "show_hide", "section_view", "named_view", "zoom", "screenshot"]
    parameters: dict[str, Any] = Field(default_factory=dict)
    response_format: ResponseFormat = ResponseFormat.JSON


class SemanticAnalysisInput(StrictModel):
    backend: Literal["auto", "solidworks", "headless"] = "auto"
    analysis: Literal[
        "geometry",
        "feature_recognition",
        "manufacturing_method",
        "dimension_plan",
        "dimension_layout_score",
        "design_rule_check",
        "dfm",
    ]
    detail: DetailLevel = "concise"
    parameters: dict[str, Any] = Field(default_factory=dict)
    response_format: ResponseFormat = ResponseFormat.JSON


class PartInspectInput(StrictModel):
    backend: Literal["auto", "solidworks", "headless"] = "auto"
    detail: DetailLevel = "detailed"
    include_features: bool = True
    include_sub_features: bool = True
    include_bodies: bool = True
    include_custom_properties: bool = True
    feature_limit: int = Field(default=250, ge=1, le=1000)
    sub_feature_limit: int = Field(default=50, ge=0, le=250)
    response_format: ResponseFormat = ResponseFormat.JSON


class RoutingOperationInput(StrictModel):
    backend: Literal["auto", "solidworks", "headless"] = "auto"
    operation: Literal["create_route", "insert_fitting", "pipe_spec", "isometric_drawing", "piping_bom"]
    parameters: dict[str, Any] = Field(default_factory=dict)
    response_format: ResponseFormat = ResponseFormat.JSON
