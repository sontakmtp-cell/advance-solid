"""Offline B-Rep backend built around optional CadQuery/OCP dependencies."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

from solidworks_mcp.config import Settings, load_settings
from solidworks_mcp.core.backend import Backend
from solidworks_mcp.core.errors import ErrorCode, McpCadError, unsupported
from solidworks_mcp.schemas.common import Capability, CapabilityMap
from solidworks_mcp.schemas.documents import DocumentInfo


SUPPORTED_IMPORTS = {"step", "stp", "iges", "igs"}
SUPPORTED_EXPORTS = {"step", "stp", "iges", "igs", "stl"}
SIDECAR_SUFFIX = ".swmcp.json"


@dataclass
class CadDocument:
    path: Path | None = None
    shape: Any | None = None
    workplane: Any | None = None
    document_type: str = "part"
    units: str = "mm"
    material: str | None = None
    custom_properties: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CadQueryRuntime:
    cadquery: Any
    importers: Any
    exporters: Any


class HeadlessBackend(Backend):
    """Headless backend for file exchange, primitive modeling, and geometry analysis.

    It intentionally does not emulate SolidWorks document semantics such as feature
    trees, assemblies, drawings, design tables, mates, Hole Wizard, or Routing.
    """

    name = "headless"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self._runtime: CadQueryRuntime | None = None
        self._runtime_error: str | None = None
        self._document: CadDocument | None = None

    async def backend_info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": "offline_brep",
            "transport": "in_process_python",
            "dependencies": {
                "cadquery": self._module_available("cadquery"),
                "ocp": self._module_available("OCP"),
            },
            "active_document": (
                str(self._document.path) if self._document and self._document.path else None
            ),
            "workspace_roots": [str(root) for root in self.settings.workspace_roots],
            "constraints": [
                "No SolidWorks feature tree, drawings, assemblies, mates, "
                "design tables, or Routing.",
                "B-Rep operations require CadQuery/OCP to be installed.",
            ],
        }

    async def capabilities(self) -> CapabilityMap:
        return CapabilityMap(
            backend=self.name,
            categories={
                "system": {
                    "backend_info": Capability(supported=True, level="full"),
                    "health": Capability(supported=True, level="full"),
                    "attach": Capability(
                        supported=True,
                        level="partial",
                        notes="Initializes optional CadQuery/OCP runtime; no external CAD session.",
                    ),
                },
                "documents": {
                    "open_document": Capability(
                        supported=True,
                        level="partial",
                        notes="Imports STEP/IGES as offline B-Rep when CadQuery is available.",
                    ),
                    "save_document": Capability(
                        supported=True,
                        level="partial",
                        notes=(
                            "Writes exchange files through export_document; "
                            "native SLD* save is unsupported."
                        ),
                    ),
                    "document_info": Capability(supported=True, level="partial"),
                    "rebuild": Capability(
                        supported=True,
                        level="partial",
                        notes="No parametric rebuild; validates that an active shape exists.",
                    ),
                    "export_document": Capability(
                        supported=True,
                        level="partial",
                        notes="Exports STEP/IGES/STL when CadQuery exporters are available.",
                    ),
                },
                "metadata": {
                    "get_custom_properties": Capability(
                        supported=True,
                        level="partial",
                        notes="File-level sidecar metadata only.",
                    ),
                    "set_custom_properties": Capability(
                        supported=True,
                        level="partial",
                        notes=(
                            "Stores file-level sidecar metadata; "
                            "cut-list/config scopes unsupported."
                        ),
                    ),
                    "mass_properties": Capability(supported=True, level="partial"),
                    "material_info": Capability(
                        supported=True,
                        level="partial",
                        notes="Stores material name as metadata; no SolidWorks material database.",
                    ),
                },
                "modeling": {
                    "primitive_box": Capability(supported=True, level="partial"),
                    "primitive_cylinder": Capability(supported=True, level="partial"),
                    "primitive_sphere": Capability(supported=True, level="partial"),
                    "extrude": Capability(supported=True, level="partial"),
                    "fillet": Capability(supported=True, level="partial"),
                    "chamfer": Capability(supported=True, level="partial"),
                    "boolean": Capability(
                        supported=True,
                        level="partial",
                        notes="Union/cut/intersect scaffold for CadQuery solids.",
                    ),
                },
                "solidworks_only": {
                    "feature_tree": Capability(
                        supported=False,
                        level="unsupported",
                        next_step=(
                            "Switch to the solidworks backend for parametric "
                            "feature tree operations."
                        ),
                    ),
                    "assemblies_mates_drawings_design_tables_routing": Capability(
                        supported=False,
                        level="unsupported",
                        next_step=(
                            "Switch to the solidworks backend with the needed "
                            "license/add-ins."
                        ),
                    ),
                },
                "semantic": {
                    "geometry": Capability(supported=True, level="partial"),
                    "feature_recognition": Capability(
                        supported=True,
                        level="partial",
                        notes="Heuristic recognition from B-Rep counts and operation metadata.",
                    ),
                    "manufacturing_method": Capability(supported=True, level="partial"),
                    "dimension_plan": Capability(
                        supported=True,
                        level="partial",
                        notes="Bounding-box dimension plan only.",
                    ),
                    "dimension_layout_score": Capability(supported=True, level="partial"),
                    "design_rule_check": Capability(supported=True, level="partial"),
                    "dfm": Capability(supported=True, level="partial"),
                },
                "routing": {
                    "piping": Capability(
                        supported=False,
                        level="unsupported",
                        next_step="Switch to the solidworks backend with the Routing add-in enabled.",
                    ),
                },
            },
        )

    async def health(self) -> dict[str, Any]:
        cadquery_available = self._module_available("cadquery")
        ocp_available = self._module_available("OCP")
        return {
            "ok": cadquery_available,
            "backend": self.name,
            "dependency_status": "available" if cadquery_available else "missing",
            "dependency_error": self._runtime_error,
            "active_document": self._document is not None,
            "dependencies": {"cadquery": cadquery_available, "ocp": ocp_available},
            "next_step": None
            if cadquery_available
            else "Install the headless extra, for example: pip install 'solidworks-mcp[headless]'.",
        }

    async def attach(self) -> dict[str, Any]:
        runtime = self._load_runtime(required=True)
        return {
            "ok": True,
            "backend": self.name,
            "runtime": "cadquery",
            "cadquery_version": getattr(runtime.cadquery, "__version__", "unknown"),
        }

    async def open_document(self, path: str, document_type: str | None = None) -> DocumentInfo:
        source = self._allowed_path(path, must_exist=True)
        runtime = self._load_runtime(required=True)
        ext = source.suffix.lower().lstrip(".")
        if ext not in SUPPORTED_IMPORTS:
            raise unsupported(
                f"import {ext or 'unknown'}",
                self.name,
                suggestion=(
                    "Use STEP or IGES for headless import, or switch to the "
                    "solidworks backend."
                ),
            )

        started = perf_counter()
        try:
            shape = self._import_exchange_shape(runtime, source, ext)
        except Exception as exc:  # pragma: no cover - exact CadQuery exceptions vary by version
            raise McpCadError(
                ErrorCode.OPERATION_FAILED,
                f"Failed to import {source.name}: {exc}",
                "Verify the file is a valid STEP/IGES B-Rep and retry, or open "
                "it with the solidworks backend.",
                {"path": str(source), "format": ext},
            ) from exc

        self._document = CadDocument(
            path=source,
            shape=shape,
            workplane=self._as_workplane(runtime, shape),
            document_type=document_type or "part",
            metadata={
                "import_seconds": round(perf_counter() - started, 4),
                "source_format": ext,
            },
        )
        self._load_sidecar()
        return await self.document_info(detail="concise")

    async def save_document(self, path: str | None = None) -> dict[str, Any]:
        self._require_document()
        target = self._allowed_path(path) if path else self._document.path
        if target is None:
            raise McpCadError(
                ErrorCode.INVALID_INPUT,
                "Headless save requires a target path when the active model was created in memory.",
                "Call export_document with a STEP, IGES, or STL path.",
            )
        ext = target.suffix.lower().lstrip(".")
        if ext in {"sldprt", "sldasm", "slddrw"}:
            raise unsupported(
                f"save {ext}",
                self.name,
                suggestion=(
                    "Export STEP/STL from headless or switch to the solidworks "
                    "backend for native files."
                ),
            )
        return await self.export_document(str(target), ext)

    async def document_info(self, path: str | None = None, detail: str = "concise") -> DocumentInfo:
        if path:
            source = self._allowed_path(path, must_exist=True)
            return DocumentInfo(
                path=str(source),
                title=source.name,
                document_type=self._document_type_from_suffix(source),
                metadata={"format": source.suffix.lower().lstrip(".")},
            )

        document = self._require_document()
        mass = None
        volume = None
        if document.shape is not None:
            props = self._shape_mass_properties(document.shape)
            mass = props.get("mass")
            volume = props.get("volume")

        metadata = dict(document.metadata)
        if detail == "detailed" and document.shape is not None:
            metadata["geometry"] = self._geometry_summary(document.shape)

        return DocumentInfo(
            path=str(document.path) if document.path else None,
            title=document.path.name if document.path else "in_memory_model",
            document_type=document.document_type,  # type: ignore[arg-type]
            units=document.units,
            material=document.material,
            mass=mass,
            volume=volume,
            configurations=["Default"],
            active_configuration="Default",
            metadata=metadata,
        )

    async def rebuild(self, force: bool = False) -> dict[str, Any]:
        document = self._require_document()
        return {
            "ok": True,
            "backend": self.name,
            "rebuilt": False,
            "validated": document.shape is not None or document.workplane is not None,
            "force_requested": force,
            "notes": (
                "Headless backend has no SolidWorks parametric rebuild; active "
                "B-Rep was validated."
            ),
        }

    async def export_document(
        self, path: str, format: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        target = self._allowed_path(path)
        runtime = self._load_runtime(required=True)
        document = self._require_document()
        export_format = (format or target.suffix.lstrip(".")).lower()
        if export_format not in SUPPORTED_EXPORTS:
            raise unsupported(
                f"export {export_format}",
                self.name,
                suggestion=(
                    "Use STEP, IGES, or STL for headless export, or switch to "
                    "the solidworks backend."
                ),
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        started = perf_counter()
        export_object = document.workplane or document.shape
        try:
            self._export_exchange_shape(
                runtime, export_object, target, export_format, options or {}
            )
        except Exception as exc:  # pragma: no cover - exact CadQuery exceptions vary by version
            raise McpCadError(
                ErrorCode.OPERATION_FAILED,
                f"Failed to export {target.name}: {exc}",
                "Retry with a simpler shape or another supported exchange format.",
                {"path": str(target), "format": export_format},
            ) from exc

        document.path = target
        document.metadata["last_export_format"] = export_format
        self._write_sidecar()
        return {
            "ok": True,
            "backend": self.name,
            "path": str(target),
            "format": export_format,
            "elapsed_seconds": round(perf_counter() - started, 4),
        }

    async def get_custom_properties(
        self, scope: str = "file", configuration: str | None = None
    ) -> dict[str, Any]:
        if scope != "file":
            raise unsupported(
                f"custom properties scope {scope}",
                self.name,
                suggestion="Use file scope in headless mode or switch to the solidworks backend.",
            )
        document = self._require_document()
        return {
            "ok": True,
            "backend": self.name,
            "scope": scope,
            "configuration": configuration,
            "properties": dict(document.custom_properties),
        }

    async def set_custom_properties(
        self,
        properties: dict[str, Any],
        scope: str = "file",
        configuration: str | None = None,
    ) -> dict[str, Any]:
        if scope != "file":
            raise unsupported(
                f"custom properties scope {scope}",
                self.name,
                suggestion="Use file scope in headless mode or switch to the solidworks backend.",
            )
        if not properties:
            raise McpCadError(
                ErrorCode.INVALID_INPUT,
                "At least one custom property is required.",
                "Pass a non-empty properties object.",
            )
        document = self._require_document()
        document.custom_properties.update(properties)
        self._write_sidecar()
        return {
            "ok": True,
            "backend": self.name,
            "scope": scope,
            "configuration": configuration,
            "updated": sorted(properties),
            "properties": dict(document.custom_properties),
        }

    async def mass_properties(self) -> dict[str, Any]:
        document = self._require_document()
        if document.shape is None:
            raise McpCadError(
                ErrorCode.OPERATION_FAILED,
                "No B-Rep shape is available for mass property analysis.",
                "Open/import a STEP or IGES file, or create a primitive first.",
            )
        return {
            "ok": True,
            "backend": self.name,
            **self._shape_mass_properties(document.shape),
        }

    async def material_info(self, material: str | None = None) -> dict[str, Any]:
        document = self._require_document()
        if material is not None:
            document.material = material
            self._write_sidecar()
        return {
            "ok": True,
            "backend": self.name,
            "material": document.material,
            "notes": (
                "Headless material is metadata only; density database and "
                "SolidWorks appearances are unsupported."
            ),
        }

    async def feature_operation(self, operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Run offline feature-like B-Rep operations exposed through the grouped MCP tool."""

        if operation == "create_sketch":
            primitive = str(parameters.get("primitive") or parameters.get("type") or "").lower()
            if primitive in {"box", "cylinder", "sphere"}:
                return await self.create_primitive(primitive, parameters)
            profile = parameters.get("profile")
            distance = parameters.get("distance")
            if isinstance(profile, dict) and distance is not None:
                return await self.extrude(profile, float(distance))
            raise McpCadError(
                ErrorCode.INVALID_INPUT,
                "Headless create_sketch needs either a primitive or an extrudable profile.",
                "Pass primitive='box'/'cylinder'/'sphere' with dimensions, or pass "
                "profile={'type':'rectangle'|'circle', ...} and distance.",
                {"operation": operation, "parameters": parameters},
            )
        if operation == "extrude_boss":
            profile = parameters.get("profile")
            if not isinstance(profile, dict):
                profile = {key: value for key, value in parameters.items() if key != "distance"}
            distance = parameters.get("distance")
            if distance is None:
                raise McpCadError(
                    ErrorCode.INVALID_INPUT,
                    "extrude_boss requires a numeric distance.",
                    "Pass distance plus a rectangle or circle profile.",
                    {"parameters": parameters},
                )
            return await self.extrude(profile, float(distance))
        if operation == "fillet":
            radius = parameters.get("radius")
            if radius is None:
                raise McpCadError(
                    ErrorCode.INVALID_INPUT,
                    "fillet requires a radius.",
                    "Pass radius and optionally selector, for example {'radius': 1.0, 'selector': '|Z'}.",
                )
            return await self.fillet(float(radius), str(parameters.get("selector", "|Z")))
        if operation == "chamfer":
            distance = parameters.get("distance")
            if distance is None:
                raise McpCadError(
                    ErrorCode.INVALID_INPUT,
                    "chamfer requires a distance.",
                    "Pass distance and optionally selector, for example {'distance': 1.0, 'selector': '|Z'}.",
                )
            return await self.chamfer(float(distance), str(parameters.get("selector", "|Z")))
        if operation == "extrude_cut":
            tool_path = parameters.get("tool_path")
            if tool_path:
                return await self.boolean("cut", str(tool_path))
            raise unsupported(
                "headless extrude_cut without a tool body",
                self.name,
                suggestion=(
                    "Pass tool_path to a STEP/IGES cutting body for boolean cut, "
                    "or switch to the solidworks backend for sketch-based cuts."
                ),
            )
        if operation in {"pattern", "mirror", "hole", "revolve", "suppress", "unsuppress", "delete", "list_tree"}:
            raise unsupported(
                f"feature operation {operation}",
                self.name,
                suggestion=(
                    "Use SolidWorks backend for parametric feature-tree operations, "
                    "or use headless primitive/extrude/fillet/chamfer/boolean workflows."
                ),
            )
        raise unsupported(f"feature operation {operation}", self.name)

    async def assembly_operation(self, operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
        raise unsupported(
            f"assembly operation {operation}",
            self.name,
            suggestion="Switch to the solidworks backend for assemblies, components, and mates.",
        )

    async def drawing_operation(self, operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
        raise unsupported(
            f"drawing operation {operation}",
            self.name,
            suggestion="Switch to the solidworks backend for SolidWorks drawings and annotations.",
        )

    async def appearance_operation(self, operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
        if operation == "zoom":
            document = self._require_document()
            return {
                "ok": True,
                "backend": self.name,
                "operation": "zoom",
                "notes": "Headless mode has no viewport; returned active model bounds instead.",
                "geometry": self._geometry_summary(document.shape) if document.shape is not None else {},
            }
        raise unsupported(
            f"appearance operation {operation}",
            self.name,
            suggestion="Switch to the solidworks backend for viewport, color, show/hide, and screenshots.",
        )

    async def import_export_operation(self, operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
        if operation == "import":
            path = parameters.get("path")
            if not path:
                raise McpCadError(
                    ErrorCode.INVALID_INPUT,
                    "import requires path.",
                    "Pass {'path': '<allowlisted STEP/IGES path>'}.",
                )
            info = await self.open_document(str(path), parameters.get("document_type"))
            return {"ok": True, "backend": self.name, "operation": "import", "document": info.model_dump()}
        if operation == "export":
            path = parameters.get("path")
            export_format = parameters.get("format")
            if not path or not export_format:
                raise McpCadError(
                    ErrorCode.INVALID_INPUT,
                    "export requires path and format.",
                    "Pass {'path': '<allowlisted target>', 'format': 'step'|'iges'|'stl'}.",
                )
            return await self.export_document(
                str(path),
                str(export_format),
                parameters.get("options") if isinstance(parameters.get("options"), dict) else {},
            )
        raise unsupported(
            f"import/export operation {operation}",
            self.name,
            suggestion="Use import/export in headless mode; Pack and Go and batch native export require SolidWorks.",
        )

    async def semantic_analysis(
        self,
        analysis: str,
        detail: str = "concise",
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        parameters = parameters or {}
        document = self._require_document()
        geometry = self._geometry_summary(document.shape) if document.shape is not None else {}
        if analysis == "geometry":
            return {
                "ok": True,
                "backend": self.name,
                "analysis": analysis,
                "detail": detail,
                "geometry": geometry,
            }
        if analysis == "feature_recognition":
            return {
                "ok": True,
                "backend": self.name,
                "analysis": analysis,
                "features": self._recognized_features(document, geometry),
                "notes": "Headless recognition is heuristic; use SolidWorks for feature tree intent.",
            }
        if analysis == "manufacturing_method":
            return {
                "ok": True,
                "backend": self.name,
                "analysis": analysis,
                "recommendations": self._manufacturing_recommendations(document, geometry),
            }
        if analysis == "dimension_plan":
            return {
                "ok": True,
                "backend": self.name,
                "analysis": analysis,
                "dimension_plan": self._dimension_plan(geometry),
            }
        if analysis == "dimension_layout_score":
            return self._dimension_layout_score(parameters)
        if analysis == "design_rule_check":
            return {
                "ok": True,
                "backend": self.name,
                "analysis": analysis,
                "checks": self._design_rule_checks(geometry, parameters),
            }
        if analysis == "dfm":
            return {
                "ok": True,
                "backend": self.name,
                "analysis": analysis,
                "geometry": geometry if detail == "detailed" else {"bounding_box": geometry.get("bounding_box")},
                "features": self._recognized_features(document, geometry),
                "checks": self._design_rule_checks(geometry, parameters),
                "recommendations": self._manufacturing_recommendations(document, geometry),
            }
        raise unsupported(
            f"semantic analysis {analysis}",
            self.name,
            suggestion="Use geometry, feature_recognition, manufacturing_method, dimension_plan, dimension_layout_score, design_rule_check, or dfm.",
        )

    async def routing_operation(self, operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
        raise unsupported(
            f"routing operation {operation}",
            self.name,
            suggestion=(
                "Routing/Piping requires SolidWorks Routing. Switch to the solidworks "
                "backend with the Routing add-in/license enabled."
            ),
        )

    async def create_primitive(self, primitive: str, parameters: dict[str, Any]) -> dict[str, Any]:
        runtime = self._load_runtime(required=True)
        cq = runtime.cadquery
        primitive = primitive.lower()
        try:
            if primitive == "box":
                wp = cq.Workplane("XY").box(
                    float(parameters["length"]),
                    float(parameters["width"]),
                    float(parameters["height"]),
                )
            elif primitive == "cylinder":
                wp = cq.Workplane("XY").cylinder(
                    float(parameters["height"]),
                    float(parameters["radius"]),
                )
            elif primitive == "sphere":
                wp = cq.Workplane("XY").sphere(float(parameters["radius"]))
            else:
                raise unsupported(
                    f"primitive {primitive}",
                    self.name,
                    suggestion="Use box, cylinder, or sphere for headless primitive creation.",
                )
        except KeyError as exc:
            raise McpCadError(
                ErrorCode.INVALID_INPUT,
                f"Missing primitive parameter: {exc.args[0]}",
                "Provide the required numeric dimensions for the requested primitive.",
                {"primitive": primitive},
            ) from exc

        self._document = CadDocument(
            shape=wp.val(),
            workplane=wp,
            metadata={"created_by": "primitive", "primitive": primitive},
        )
        return {
            "ok": True,
            "backend": self.name,
            "primitive": primitive,
            "info": self._geometry_summary(self._document.shape),
        }

    async def extrude(self, profile: dict[str, Any], distance: float) -> dict[str, Any]:
        runtime = self._load_runtime(required=True)
        cq = runtime.cadquery
        kind = profile.get("type")
        try:
            wp = cq.Workplane("XY")
            if kind == "rectangle":
                wp = wp.rect(float(profile["width"]), float(profile["height"]))
            elif kind == "circle":
                wp = wp.circle(float(profile["radius"]))
            else:
                raise unsupported(
                    f"extrude profile {kind}",
                    self.name,
                    suggestion="Use rectangle or circle profiles in the MVP headless backend.",
                )
            wp = wp.extrude(float(distance))
        except KeyError as exc:
            raise McpCadError(
                ErrorCode.INVALID_INPUT,
                f"Missing profile parameter: {exc.args[0]}",
                "Provide all required profile dimensions.",
                {"profile": profile},
            ) from exc

        self._document = CadDocument(
            shape=wp.val(),
            workplane=wp,
            metadata={"created_by": "extrude", "profile": profile},
        )
        return {
            "ok": True,
            "backend": self.name,
            "operation": "extrude",
            "info": self._geometry_summary(self._document.shape),
        }

    async def fillet(self, radius: float, selector: str = "|Z") -> dict[str, Any]:
        document = self._require_document()
        if document.workplane is None:
            raise unsupported(
                "fillet imported shape without selector context",
                self.name,
                suggestion=(
                    "Create a primitive/extrude in headless mode, or use "
                    "SolidWorks for robust feature editing."
                ),
            )
        document.workplane = document.workplane.edges(selector).fillet(float(radius))
        document.shape = document.workplane.val()
        return {"ok": True, "backend": self.name, "operation": "fillet", "radius": radius}

    async def chamfer(self, distance: float, selector: str = "|Z") -> dict[str, Any]:
        document = self._require_document()
        if document.workplane is None:
            raise unsupported(
                "chamfer imported shape without selector context",
                self.name,
                suggestion=(
                    "Create a primitive/extrude in headless mode, or use "
                    "SolidWorks for robust feature editing."
                ),
            )
        document.workplane = document.workplane.edges(selector).chamfer(float(distance))
        document.shape = document.workplane.val()
        return {"ok": True, "backend": self.name, "operation": "chamfer", "distance": distance}

    async def boolean(self, operation: str, tool_path: str) -> dict[str, Any]:
        runtime = self._load_runtime(required=True)
        document = self._require_document()
        tool_source = self._allowed_path(tool_path, must_exist=True)
        tool_ext = tool_source.suffix.lower().lstrip(".")
        if tool_ext not in SUPPORTED_IMPORTS:
            raise unsupported(
                f"boolean tool import {tool_ext or 'unknown'}",
                self.name,
                suggestion="Use a STEP or IGES file as the boolean tool body.",
            )
        try:
            tool_shape = self._import_exchange_shape(runtime, tool_source, tool_ext)
        except Exception as exc:  # pragma: no cover - exact CadQuery exceptions vary by version
            raise McpCadError(
                ErrorCode.OPERATION_FAILED,
                f"Failed to import boolean tool {tool_source.name}: {exc}",
                "Verify the tool body is a valid STEP/IGES B-Rep and retry.",
                {"path": str(tool_source), "format": tool_ext},
            ) from exc
        tool = self._as_workplane(runtime, tool_shape)
        base = self._as_workplane(runtime, document.shape)
        if operation == "union":
            result = base.union(tool)
        elif operation == "cut":
            result = base.cut(tool)
        elif operation in {"intersect", "intersection"}:
            result = base.intersect(tool)
        else:
            raise unsupported(
                f"boolean {operation}",
                self.name,
                suggestion="Use union, cut, or intersect for headless boolean operations.",
            )
        self._document = CadDocument(
            path=document.path,
            workplane=result,
            shape=result.val(),
            material=document.material,
            custom_properties=document.custom_properties,
            metadata={"operation": f"boolean_{operation}", "tool": str(tool_source)},
        )
        return {
            "ok": True,
            "backend": self.name,
            "operation": operation,
            "info": self._geometry_summary(self._document.shape),
        }

    def _load_runtime(self, *, required: bool) -> CadQueryRuntime | None:
        if self._runtime is not None:
            return self._runtime
        try:
            cadquery = importlib.import_module("cadquery")
            importers = importlib.import_module("cadquery.occ_impl.importers")
            exporters = importlib.import_module("cadquery.occ_impl.exporters")
        except Exception as exc:
            self._runtime_error = str(exc)
            if required:
                raise McpCadError(
                    ErrorCode.DEPENDENCY_MISSING,
                    "CadQuery/OCP is required for headless B-Rep operations but is not available.",
                    "Install the headless extra, for example: "
                    "pip install 'solidworks-mcp[headless]'.",
                    {"dependency": "cadquery", "import_error": str(exc)},
                ) from exc
            return None
        self._runtime = CadQueryRuntime(
            cadquery=cadquery,
            importers=importers,
            exporters=exporters,
        )
        self._runtime_error = None
        return self._runtime

    def _module_available(self, module_name: str) -> bool:
        try:
            return importlib.util.find_spec(module_name) is not None
        except (ImportError, ValueError):
            return False

    def _allowed_path(self, path: str | Path, *, must_exist: bool = False) -> Path:
        try:
            return self.settings.ensure_allowed_path(path, must_exist=must_exist)
        except ValueError as exc:
            raise McpCadError(
                ErrorCode.PATH_NOT_ALLOWED
                if "outside allowed" in str(exc)
                else ErrorCode.INVALID_INPUT,
                str(exc),
                "Use a path under SOLIDWORKS_MCP_WORKSPACE_ROOTS.",
            ) from exc

    def _require_document(self) -> CadDocument:
        if self._document is None:
            raise McpCadError(
                ErrorCode.NOT_CONNECTED,
                "No active headless CAD document is loaded.",
                "Open/import a STEP or IGES file, or create a primitive first.",
            )
        return self._document

    def _as_workplane(self, runtime: CadQueryRuntime, shape: Any) -> Any:
        cq = runtime.cadquery
        if hasattr(shape, "val"):
            return shape
        return cq.Workplane("XY").add(shape)

    def _import_exchange_shape(self, runtime: CadQueryRuntime, path: Path, ext: str) -> Any:
        if ext in {"step", "stp"}:
            return runtime.importers.importStep(str(path))

        import_types = getattr(runtime.importers, "ImportTypes", None)
        iges_type = getattr(import_types, "IGES", None) if import_types else None
        if iges_type is not None:
            return runtime.importers.importShape(iges_type, str(path))
        return runtime.importers.importShape(str(path))

    def _export_exchange_shape(
        self,
        runtime: CadQueryRuntime,
        export_object: Any,
        path: Path,
        export_format: str,
        options: dict[str, Any],
    ) -> None:
        export_types = getattr(runtime.exporters, "ExportTypes", None)
        export_type_name = {
            "step": "STEP",
            "stp": "STEP",
            "iges": "IGES",
            "igs": "IGES",
            "stl": "STL",
        }[export_format]
        export_type = (
            getattr(export_types, export_type_name, export_type_name)
            if export_types
            else export_type_name
        )
        runtime.exporters.export(export_object, str(path), exportType=export_type, **options)

    def _shape_mass_properties(self, shape: Any) -> dict[str, Any]:
        volume = self._safe_call(shape, "Volume")
        area = self._safe_call(shape, "Area")
        center = self._safe_call(shape, "Center")
        bbox = self._safe_call(shape, "BoundingBox")
        return {
            "mass": volume,
            "volume": volume,
            "surface_area": area,
            "center_of_mass": self._point_to_list(center),
            "bounding_box": self._bbox_to_dict(bbox),
            "units": self._document.units if self._document else "mm",
            "notes": "Mass equals volume because no density model is applied in headless mode.",
        }

    def _recognized_features(self, document: CadDocument, geometry: dict[str, Any]) -> list[dict[str, Any]]:
        features: list[dict[str, Any]] = []
        created_by = document.metadata.get("created_by")
        if created_by:
            features.append({"type": str(created_by), "confidence": 0.9, "source": "metadata"})
        primitive = document.metadata.get("primitive")
        if primitive:
            features.append({"type": str(primitive), "confidence": 0.95, "source": "metadata"})
        faces = geometry.get("faces")
        edges = geometry.get("edges")
        if faces == 6 and edges == 12:
            features.append({"type": "box_like_prismatic_body", "confidence": 0.7, "source": "brep_counts"})
        if geometry.get("solids") == 1 and not features:
            features.append({"type": "single_solid", "confidence": 0.5, "source": "brep_counts"})
        return features

    def _manufacturing_recommendations(
        self,
        document: CadDocument,
        geometry: dict[str, Any],
    ) -> list[dict[str, Any]]:
        bbox = geometry.get("bounding_box") or {}
        size = self._bbox_size(bbox)
        recommendations = [
            {
                "method": "3_axis_milling",
                "confidence": 0.55,
                "reason": "B-Rep is a single prismatic solid; verify setups and hidden undercuts.",
            }
        ]
        if document.metadata.get("created_by") in {"primitive", "extrude"}:
            recommendations[0]["confidence"] = 0.7
            recommendations[0]["reason"] = "Model was created from simple primitive/extrude metadata."
        if size and min(size) < float(geometry.get("volume") or 0.0) ** (1 / 3) * 0.05:
            recommendations.append(
                {
                    "method": "sheet_or_plate_process",
                    "confidence": 0.45,
                    "reason": "Bounding box has one axis much thinner than the others.",
                }
            )
        return recommendations

    def _dimension_plan(self, geometry: dict[str, Any]) -> list[dict[str, Any]]:
        bbox = geometry.get("bounding_box") or {}
        if not bbox:
            return []
        return [
            {"id": "overall_length", "axis": "x", "value": bbox["xmax"] - bbox["xmin"]},
            {"id": "overall_width", "axis": "y", "value": bbox["ymax"] - bbox["ymin"]},
            {"id": "overall_height", "axis": "z", "value": bbox["zmax"] - bbox["zmin"]},
        ]

    def _dimension_layout_score(self, parameters: dict[str, Any]) -> dict[str, Any]:
        dimensions = parameters.get("dimensions")
        if not isinstance(dimensions, list):
            raise McpCadError(
                ErrorCode.INVALID_INPUT,
                "dimension_layout_score requires a dimensions list.",
                "Pass dimensions as boxes with id, x, y, width, and height.",
            )
        boxes = [self._layout_box(item, index) for index, item in enumerate(dimensions)]
        min_gap = float(parameters.get("min_gap", 0.0))
        issues: list[dict[str, Any]] = []
        for index, first in enumerate(boxes):
            for second in boxes[index + 1 :]:
                if self._layout_boxes_overlap(first, second, min_gap):
                    issues.append({"code": "overlap", "items": [first["id"], second["id"]]})
        return {
            "ok": True,
            "backend": self.name,
            "analysis": "dimension_layout_score",
            "score": max(0, 100 - 20 * len(issues)),
            "issues": issues,
        }

    def _design_rule_checks(
        self,
        geometry: dict[str, Any],
        parameters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        bbox = geometry.get("bounding_box") or {}
        size = self._bbox_size(bbox)
        checks: list[dict[str, Any]] = []
        min_wall = parameters.get("min_wall_thickness")
        if size and min_wall is not None:
            checks.append(
                {
                    "rule": "minimum_wall_proxy",
                    "status": "pass" if min(size) >= float(min_wall) else "warning",
                    "measured": min(size),
                    "threshold": float(min_wall),
                    "next_step": "Use real wall-thickness analysis in SolidWorks for production DFM.",
                }
            )
        checks.append(
            {
                "rule": "undercut_detection",
                "status": "unknown",
                "next_step": "Headless MVP does not classify undercuts; inspect in SolidWorks for tooling decisions.",
            }
        )
        return checks

    def _bbox_size(self, bbox: dict[str, Any]) -> tuple[float, float, float] | None:
        try:
            return (
                float(bbox["xmax"]) - float(bbox["xmin"]),
                float(bbox["ymax"]) - float(bbox["ymin"]),
                float(bbox["zmax"]) - float(bbox["zmin"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _layout_box(self, item: Any, index: int) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise McpCadError(
                ErrorCode.INVALID_INPUT,
                f"dimensions[{index}] must be an object.",
                "Use boxes shaped like {'id': 'D1', 'x': 0.1, 'y': 0.2, 'width': 0.03, 'height': 0.01}.",
            )
        return {
            "id": str(item.get("id") or item.get("name") or f"D{index + 1}"),
            "x": float(item["x"]),
            "y": float(item["y"]),
            "width": float(item["width"]),
            "height": float(item["height"]),
        }

    @staticmethod
    def _layout_boxes_overlap(first: dict[str, Any], second: dict[str, Any], min_gap: float) -> bool:
        return not (
            first["x"] + first["width"] + min_gap <= second["x"]
            or second["x"] + second["width"] + min_gap <= first["x"]
            or first["y"] + first["height"] + min_gap <= second["y"]
            or second["y"] + second["height"] + min_gap <= first["y"]
        )

    def _geometry_summary(self, shape: Any) -> dict[str, Any]:
        solids = self._safe_sequence(shape, "Solids")
        faces = self._safe_sequence(shape, "Faces")
        edges = self._safe_sequence(shape, "Edges")
        vertices = self._safe_sequence(shape, "Vertices")
        return {
            "solids": len(solids) if solids is not None else None,
            "faces": len(faces) if faces is not None else None,
            "edges": len(edges) if edges is not None else None,
            "vertices": len(vertices) if vertices is not None else None,
            **self._shape_mass_properties(shape),
        }

    def _safe_call(self, obj: Any, name: str) -> Any:
        attr = getattr(obj, name, None)
        if attr is None:
            return None
        try:
            return attr() if callable(attr) else attr
        except Exception:
            return None

    def _safe_sequence(self, obj: Any, name: str) -> list[Any] | None:
        value = self._safe_call(obj, name)
        if value is None:
            return None
        try:
            return list(value)
        except TypeError:
            return None

    def _point_to_list(self, point: Any) -> list[float] | None:
        if point is None:
            return None
        values = []
        for attr in ("x", "y", "z"):
            values.append(float(getattr(point, attr, 0.0)))
        return values

    def _bbox_to_dict(self, bbox: Any) -> dict[str, float] | None:
        if bbox is None:
            return None
        fields = {
            "xmin": "xmin",
            "ymin": "ymin",
            "zmin": "zmin",
            "xmax": "xmax",
            "ymax": "ymax",
            "zmax": "zmax",
        }
        result: dict[str, float] = {}
        for key, attr in fields.items():
            value = getattr(bbox, attr, None)
            if value is None:
                return None
            result[key] = float(value)
        return result

    def _document_type_from_suffix(self, path: Path) -> str:
        ext = path.suffix.lower()
        if ext in {".step", ".stp", ".iges", ".igs", ".stl", ".x_t", ".x_b"}:
            return "part"
        return "unknown"

    def _sidecar_path(self) -> Path | None:
        if not self._document or not self._document.path:
            return None
        return self._document.path.with_name(self._document.path.name + SIDECAR_SUFFIX)

    def _load_sidecar(self) -> None:
        sidecar = self._sidecar_path()
        if not sidecar or not sidecar.exists() or not self._document:
            return
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self._document.custom_properties = dict(payload.get("custom_properties") or {})
        self._document.material = payload.get("material")

    def _write_sidecar(self) -> None:
        sidecar = self._sidecar_path()
        if not sidecar or not self._document:
            return
        payload = {
            "custom_properties": self._document.custom_properties,
            "material": self._document.material,
        }
        sidecar.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
