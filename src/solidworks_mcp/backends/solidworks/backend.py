"""SolidWorks backend implementation over the COM dispatcher."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from solidworks_mcp.backends.solidworks.constants import (
    EXPORT_EXTENSIONS,
    SW_CUSTOM_INFO_TEXT,
    SW_CUSTOM_PROPERTY_REPLACE_VALUE,
    SW_OPEN_SILENT,
    SW_SAVE_AS_CURRENT_VERSION,
    SW_SAVE_AS_OPTIONS_SILENT,
    infer_document_type,
    normalize_document_type,
)
from solidworks_mcp.backends.solidworks.dispatcher import SolidWorksComDispatcher
from solidworks_mcp.backends.solidworks.inspect import inspect_active_or_document
from solidworks_mcp.bridges.solidworks_macro.named_pipe_client import MacroBridgeClient
from solidworks_mcp.config import Settings, load_settings
from solidworks_mcp.core.backend import Backend
from solidworks_mcp.core.errors import ErrorCode, McpCadError
from solidworks_mcp.domain.drawing import SolidWorksDrawingService
from solidworks_mcp.schemas.common import Capability, CapabilityMap
from solidworks_mcp.schemas.documents import DocumentInfo

LOGGER = logging.getLogger(__name__)


class SolidWorksBackend(Backend):
    """Full SolidWorks backend for SLDPRT/SLDASM/SLDDRW workflows."""

    name = "solidworks"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()
        self.dispatcher = SolidWorksComDispatcher(self.settings)
        self.macro_bridge = MacroBridgeClient(settings=self.settings)
        self.command_allowlist = {
            "rebuild",
            "force_rebuild",
            "zoom_to_fit",
            "traverse_feature_tree",
            "get_custom_properties",
            "set_custom_properties",
        }

    async def backend_info(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "transport": "stdio",
            "control_paths": {
                "primary": "Python MCP server -> pywin32 COM Automation -> SolidWorks",
                "in_process_optional": (
                    "Python MCP server -> named pipe IPC -> macro/add-in bridge "
                    "-> SolidWorks API"
                ),
            },
            "workspace_roots": [str(path) for path in self.settings.workspace_roots],
            "macros_enabled": self.settings.allow_macros,
            "macro_allowlist": list(self.settings.macro_allowlist),
            "timeouts": {
                "soft_seconds": self.settings.com_timeout_seconds,
                "hard_seconds": self.settings.com_hard_timeout_seconds,
            },
            "dispatcher": self.dispatcher.status(),
        }

    async def capabilities(self) -> CapabilityMap:
        full = Capability(supported=True, level="full")
        partial = Capability(
            supported=True,
            level="partial",
            notes="MVP coverage; deeper feature operations are phase 2.",
        )
        optional = Capability(
            supported=True,
            level="partial",
            notes=(
                "Requires allowlisted macro/add-in bridge or SolidWorks add-ins "
                "where applicable."
            ),
        )
        return CapabilityMap(
            backend=self.name,
            categories={
                "system": {
                    "attach": full,
                    "health": full,
                    "backend_info": full,
                    "execute_macro": optional,
                    "run_com_command": optional,
                },
                "documents": {
                    "open": full,
                    "save": full,
                    "info": full,
                    "rebuild": full,
                    "export": full,
                },
                "properties": {
                    "custom_properties": full,
                    "mass_properties": full,
                    "material": partial,
                    "bom": partial,
                    "configurations": partial,
                },
                "solidworks_advanced": {
                    "part_inspect": full,
                    "feature_tree": partial,
                    "drawings": partial,
                    "assemblies": partial,
                    "routing": optional,
                },
                "semantic": {
                    "geometry": partial,
                    "feature_recognition": partial,
                    "manufacturing_method": partial,
                    "dimension_plan": partial,
                    "dimension_layout_score": partial,
                    "design_rule_check": partial,
                    "dfm": partial,
                },
            },
        )

    async def health(self) -> dict[str, Any]:
        status = self.dispatcher.status()
        dependency_status = _dependency_status()
        if not status["connected"] and dependency_status["com_available"]:
            try:
                attach_info = self.dispatcher.attach(create_if_missing=False)
                status = self.dispatcher.status()
                status["attach_probe"] = attach_info
            except McpCadError as exc:
                status["attach_probe_error"] = exc.to_dict()["error"]
        return {
            "ok": status["connected"],
            "backend": self.name,
            "dependencies": dependency_status,
            "dispatcher": status,
            "macro_bridge": self.macro_bridge.status(),
        }

    async def attach(self) -> dict[str, Any]:
        return self.dispatcher.attach(create_if_missing=False)

    async def open_document(self, path: str, document_type: str | None = None) -> DocumentInfo:
        allowed = self.settings.ensure_allowed_path(path, must_exist=True)
        doc_type = infer_document_type(allowed, document_type)

        def _open(sw: Any) -> dict[str, Any]:
            if sw is None:
                raise _not_connected()
            errors = 0
            warnings = 0
            doc = sw.OpenDoc6(str(allowed), doc_type, SW_OPEN_SILENT, "", errors, warnings)
            if doc is None:
                raise McpCadError(
                    ErrorCode.OPERATION_FAILED,
                    f"SolidWorks could not open document: {allowed}",
                    "Verify the file type and SolidWorks license, then retry.",
                    details={"path": str(allowed), "errors": errors, "warnings": warnings},
                )
            try:
                sw.ActivateDoc3(doc.GetTitle(), False, 0, errors)
            except Exception:
                LOGGER.debug("Could not activate opened document", exc_info=True)
            return _document_info_from_model(doc)

        return DocumentInfo(**self.dispatcher.call("open_document", _open))

    async def save_document(self, path: str | None = None) -> dict[str, Any]:
        allowed = self.settings.ensure_allowed_path(path) if path else None

        def _save(sw: Any) -> dict[str, Any]:
            doc = _active_doc(sw)
            if allowed is None:
                errors = 0
                warnings = 0
                ok = bool(doc.Save3(SW_SAVE_AS_OPTIONS_SILENT, errors, warnings))
                return {
                    "saved": ok,
                    "path": _call(doc, "GetPathName"),
                    "errors": errors,
                    "warnings": warnings,
                }
            extension = _property_or_call(doc, "Extension")
            if extension is None:
                raise McpCadError(
                    ErrorCode.BACKEND_FAULT,
                    "Active document does not expose ModelDocExtension.SaveAs.",
                    "Use Save on a normal SolidWorks model document, or retry after reattaching.",
                )
            errors = 0
            warnings = 0
            ok = bool(
                extension.SaveAs(
                    str(allowed),
                    SW_SAVE_AS_CURRENT_VERSION,
                    SW_SAVE_AS_OPTIONS_SILENT,
                    None,
                    errors,
                    warnings,
                )
            )
            return {"saved": ok, "path": str(allowed), "errors": errors, "warnings": warnings}

        return self.dispatcher.call("save_document", _save)

    async def document_info(self, path: str | None = None, detail: str = "concise") -> DocumentInfo:
        if path:
            return await self.open_document(path)

        def _info(sw: Any) -> dict[str, Any]:
            doc = _active_doc(sw)
            data = _document_info_from_model(doc)
            if detail == "detailed":
                data["metadata"]["feature_tree"] = _feature_tree(doc, limit=250)
            return data

        return DocumentInfo(**self.dispatcher.call("document_info", _info))

    async def rebuild(self, force: bool = False) -> dict[str, Any]:
        def _rebuild(sw: Any) -> dict[str, Any]:
            doc = _active_doc(sw)
            ok = bool(doc.ForceRebuild3(False) if force else doc.EditRebuild3())
            return {"rebuilt": ok, "force": force, "title": _call(doc, "GetTitle")}

        return self.dispatcher.call("rebuild", _rebuild)

    async def export_document(
        self,
        path: str,
        format: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        allowed = self.settings.ensure_allowed_path(path)
        expected_ext = EXPORT_EXTENSIONS.get(format.lower())
        if expected_ext and allowed.suffix.lower() != expected_ext:
            allowed = allowed.with_suffix(expected_ext)
            self.settings.ensure_allowed_path(allowed)
        options = options or {}

        def _export(sw: Any) -> dict[str, Any]:
            doc = _active_doc(sw)
            extension = _property_or_call(doc, "Extension")
            if extension is None:
                raise McpCadError(
                    ErrorCode.BACKEND_FAULT,
                    "Active document does not expose export APIs.",
                    "Activate a model or drawing document and retry export.",
                )
            errors = 0
            warnings = 0
            ok = bool(
                extension.SaveAs(
                    str(allowed),
                    SW_SAVE_AS_CURRENT_VERSION,
                    SW_SAVE_AS_OPTIONS_SILENT,
                    None,
                    errors,
                    warnings,
                )
            )
            return {
                "exported": ok,
                "path": str(allowed),
                "format": format,
                "errors": errors,
                "warnings": warnings,
                "options_applied": options,
            }

        return self.dispatcher.call("export_document", _export)

    async def get_custom_properties(
        self,
        scope: str = "file",
        configuration: str | None = None,
    ) -> dict[str, Any]:
        def _get(sw: Any) -> dict[str, Any]:
            doc = _active_doc(sw)
            manager = _custom_property_manager(doc, scope=scope, configuration=configuration)
            names = list(_call(manager, "GetNames") or [])
            props: dict[str, Any] = {}
            for name in names:
                value = ""
                resolved = ""
                was_resolved = False
                try:
                    result = _call(manager, "Get5", name, False, value, resolved, was_resolved)
                    props[name] = {
                        "value": (
                            result[1]
                            if isinstance(result, tuple) and len(result) > 1
                            else value
                        ),
                        "resolved_value": (
                            result[2]
                            if isinstance(result, tuple) and len(result) > 2
                            else resolved
                        ),
                    }
                except Exception:
                    props[name] = {"value": _call(manager, "Get", name)}
            return {"scope": scope, "configuration": configuration, "properties": props}

        return self.dispatcher.call("get_custom_properties", _get)

    async def set_custom_properties(
        self,
        properties: dict[str, Any],
        scope: str = "file",
        configuration: str | None = None,
    ) -> dict[str, Any]:
        def _set(sw: Any) -> dict[str, Any]:
            doc = _active_doc(sw)
            manager = _custom_property_manager(doc, scope=scope, configuration=configuration)
            written: dict[str, str] = {}
            for key, value in properties.items():
                text = str(value)
                ok = _invoke(
                    manager,
                    "Add3",
                    key,
                    SW_CUSTOM_INFO_TEXT,
                    text,
                    SW_CUSTOM_PROPERTY_REPLACE_VALUE,
                )
                if not ok:
                    ok = _invoke(manager, "Set2", key, text)
                if not ok:
                    raise McpCadError(
                        ErrorCode.OPERATION_FAILED,
                        f"Could not write custom property '{key}'.",
                        "Verify the active document supports custom properties and retry.",
                        {"property": key},
                    )
                written[key] = text
            return {"scope": scope, "configuration": configuration, "written": written}

        return self.dispatcher.call("set_custom_properties", _set)

    async def mass_properties(self) -> dict[str, Any]:
        def _mass(sw: Any) -> dict[str, Any]:
            doc = _active_doc(sw)
            extension = _property_or_call(doc, "Extension")
            mass_property = _call(extension, "CreateMassProperty") if extension else None
            if mass_property is not None:
                center = _call(mass_property, "CenterOfMass")
                inertia = _call(mass_property, "GetMomentOfInertia")
                return {
                    "mass": _safe_attr(mass_property, "Mass"),
                    "volume": _safe_attr(mass_property, "Volume"),
                    "surface_area": _safe_attr(mass_property, "SurfaceArea"),
                    "center_of_mass": center,
                    "moment_of_inertia": inertia,
                }
            raw = _call(doc, "GetMassProperties")
            return {"raw_mass_properties": raw}

        return self.dispatcher.call("mass_properties", _mass)

    async def material_info(self, material: str | None = None) -> dict[str, Any]:
        def _material(sw: Any) -> dict[str, Any]:
            doc = _active_doc(sw)
            config = _active_configuration_name(doc)
            if material:
                try:
                    doc.SetMaterialPropertyName2(config or "", "", material)
                except Exception as exc:
                    raise McpCadError(
                        ErrorCode.OPERATION_FAILED,
                        f"Could not set material '{material}': {exc}",
                        "Use a material name from the active SolidWorks material database, "
                        "then retry.",
                        details={"material": material},
                    ) from exc
            current = _call(doc, "GetMaterialPropertyName2", config or "", "")
            return {"configuration": config, "material": current, "set": material is not None}

        return self.dispatcher.call("material_info", _material)

    async def inspect_part(
        self,
        *,
        detail: str = "detailed",
        include_features: bool = True,
        include_sub_features: bool = True,
        include_bodies: bool = True,
        include_custom_properties: bool = True,
        feature_limit: int = 250,
        sub_feature_limit: int = 50,
    ) -> dict[str, Any]:
        """Deep-inspect the active SolidWorks part using read-only COM calls."""

        def _inspect(sw: Any) -> dict[str, Any]:
            doc = _active_doc(sw)
            payload = inspect_active_or_document(
                doc,
                feature_limit=feature_limit if include_features else 0,
                subfeature_limit=sub_feature_limit if include_sub_features else 0,
            )
            if not include_features:
                payload.pop("features", None)
                payload["feature_count"] = 0
            elif not include_sub_features:
                for feature in payload.get("features", []):
                    feature.pop("subfeatures", None)
            if not include_bodies:
                payload.pop("solid_bodies", None)
                payload.pop("solid_body_count", None)
            if not include_custom_properties:
                payload.pop("custom_properties_file", None)
            if detail == "concise":
                return _concise_part_inspection(payload)
            return payload

        return self.dispatcher.call("inspect_part", _inspect)

    async def feature_operation(
        self,
        operation: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = parameters or {}
        operation = operation.lower()

        def _feature(sw: Any) -> dict[str, Any]:
            doc = _active_doc(sw)
            if operation == "list_tree":
                limit = int(params.get("limit", 250))
                return {
                    "ok": True,
                    "backend": self.name,
                    "operation": operation,
                    "features": _feature_tree(doc, limit=limit),
                }

            if operation in {"suppress", "unsuppress", "delete"}:
                name = _required_string(params, "name")
                feature = _find_feature(doc, name)
                if feature is None:
                    raise McpCadError(
                        ErrorCode.INVALID_INPUT,
                        f"Feature '{name}' was not found in the active document.",
                        (
                            "Call feature_operation list_tree, choose an exact feature name, "
                            "then retry."
                        ),
                        {"feature": name},
                    )
                if operation == "suppress":
                    ok = _set_feature_suppression(doc, feature, suppress=True)
                elif operation == "unsuppress":
                    ok = _set_feature_suppression(doc, feature, suppress=False)
                else:
                    ok = _delete_feature(doc, feature)
                return {
                    "ok": ok,
                    "backend": self.name,
                    "operation": operation,
                    "feature": name,
                }

            if operation in {"extrude_boss", "extrude_cut"}:
                depth = float(params.get("depth", params.get("distance", 0.0)))
                if depth <= 0:
                    raise McpCadError(
                        ErrorCode.INVALID_INPUT,
                        "Extrude requires a positive depth/distance.",
                        "Pass parameters.depth in model units and preselect a closed sketch.",
                        {"parameters": params},
                    )
                return _create_extrude(doc, operation=operation, depth=depth)

            if operation == "fillet":
                radius = float(params.get("radius", 0.0))
                if radius <= 0:
                    raise McpCadError(
                        ErrorCode.INVALID_INPUT,
                        "Fillet requires a positive radius.",
                        "Pass parameters.radius and preselect one or more edges/faces.",
                        {"parameters": params},
                    )
                return _create_fillet(doc, radius=radius)

            if operation == "chamfer":
                distance = float(params.get("distance", params.get("dist1", 0.0)))
                angle = float(params.get("angle", 45.0))
                if distance <= 0:
                    raise McpCadError(
                        ErrorCode.INVALID_INPUT,
                        "Chamfer requires a positive distance.",
                        "Pass parameters.distance and preselect one or more edges/faces.",
                        {"parameters": params},
                    )
                return _create_chamfer(doc, distance=distance, angle=angle)

            raise _unsupported_phase2("feature", operation)

        return self.dispatcher.call(f"feature_operation:{operation}", _feature)

    async def assembly_operation(
        self,
        operation: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = parameters or {}
        operation = operation.lower()

        if operation == "insert_component":
            self._allowed_path(_required_string(params, "path"), must_exist=True)

        def _assembly(sw: Any) -> dict[str, Any]:
            doc = _active_doc(sw)
            if operation == "list_components":
                return {
                    "ok": True,
                    "backend": self.name,
                    "operation": operation,
                    "components": _component_tree(doc),
                }

            if operation == "insert_component":
                path = self._allowed_path(_required_string(params, "path"), must_exist=True)
                x = float(params.get("x", 0.0))
                y = float(params.get("y", 0.0))
                z = float(params.get("z", 0.0))
                component = _call(doc, "AddComponent5", str(path), 0, "", False, "", x, y, z)
                if component is None:
                    component = _call(doc, "AddComponent4", str(path), "", x, y, z)
                if component is None:
                    raise McpCadError(
                        ErrorCode.OPERATION_FAILED,
                        "SolidWorks could not insert the component into the active assembly.",
                        "Activate an assembly document, verify the component path, then retry.",
                        {"path": str(path)},
                    )
                return {
                    "ok": True,
                    "backend": self.name,
                    "operation": operation,
                    "component": _component_summary(component),
                }

            if operation in {
                "move_component",
                "rotate_component",
                "suppress_component",
                "unsuppress_component",
            }:
                name = _required_string(params, "name")
                component = _find_component(doc, name)
                if component is None:
                    raise McpCadError(
                        ErrorCode.INVALID_INPUT,
                        f"Component '{name}' was not found in the active assembly.",
                        (
                            "Call assembly_operation list_components, choose an exact "
                            "component name, then retry."
                        ),
                        {"component": name},
                    )
                if operation == "move_component":
                    ok = _move_component(sw, component, params)
                elif operation == "rotate_component":
                    ok = _rotate_component(sw, component, params)
                else:
                    ok = _set_component_suppression(
                        component,
                        suppress=operation == "suppress_component",
                    )
                return {
                    "ok": ok,
                    "backend": self.name,
                    "operation": operation,
                    "component": _component_summary(component),
                }

            if operation == "interference_detection":
                return _interference_detection(doc)

            if operation == "add_mate":
                raise McpCadError(
                    ErrorCode.UNSUPPORTED,
                    (
                        "Assembly mate creation requires selected mate references and is "
                        "not safely generalized in the Phase 2 backend."
                    ),
                    (
                        "Preselect mate entities in SolidWorks and use an approved macro "
                        "bridge command, or provide a narrower typed mate workflow in a "
                        "later phase."
                    ),
                    {"operation": operation},
                )

            raise _unsupported_phase2("assembly", operation)

        return self.dispatcher.call(f"assembly_operation:{operation}", _assembly)

    async def drawing_operation(
        self,
        operation: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = dict(parameters or {})
        operation = operation.lower()
        self._validate_drawing_paths(params)

        def _drawing(sw: Any) -> dict[str, Any]:
            if sw is None:
                raise _not_connected()
            service = SolidWorksDrawingService(sw)
            result = service.drawing_operation(operation, params)
            if result.get("ok") is False:
                error = result.get("error") or {}
                code_value = error.get("code", ErrorCode.OPERATION_FAILED.value)
                try:
                    code = ErrorCode(code_value)
                except ValueError:
                    code = ErrorCode.OPERATION_FAILED
                raise McpCadError(
                    code,
                    str(error.get("message") or "SolidWorks drawing operation failed."),
                    str(
                        error.get("next_step")
                        or "Inspect the active drawing state, selection, and parameters, then retry."
                    ),
                    error.get("details") if isinstance(error.get("details"), dict) else None,
                )
            return result

        return self.dispatcher.call(f"drawing_operation:{operation}", _drawing)

    async def appearance_operation(
        self,
        operation: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = parameters or {}
        operation = operation.lower()

        if operation == "screenshot" and params.get("path"):
            self._allowed_path(str(params["path"]))

        def _appearance(sw: Any) -> dict[str, Any]:
            doc = _active_doc(sw)
            if operation == "zoom":
                mode = str(params.get("mode", "fit")).lower()
                if mode in {"fit", "zoom_to_fit", "to_fit"}:
                    ok = _invoke(doc, "ViewZoomtofit2")
                elif mode in {"selection", "selected"}:
                    ok = _invoke(doc, "ViewZoomToSelection")
                else:
                    raise McpCadError(
                        ErrorCode.UNSUPPORTED,
                        f"Zoom mode '{mode}' is not implemented.",
                        "Use mode='fit' or mode='selection'.",
                        {"mode": mode},
                    )
                return {"ok": ok, "backend": self.name, "operation": operation, "mode": mode}

            if operation == "show_hide":
                name = _required_string(params, "name")
                show = bool(params.get("show", True))
                component = _find_component(doc, name)
                if component is None:
                    raise McpCadError(
                        ErrorCode.INVALID_INPUT,
                        f"Component '{name}' was not found for show/hide.",
                        "Call assembly_operation list_components and pass an exact component name.",
                        {"component": name},
                    )
                ok = _show_hide_component(component, show=show)
                return {
                    "ok": ok,
                    "backend": self.name,
                    "operation": operation,
                    "component": _component_summary(component),
                    "show": show,
                }

            if operation == "named_view":
                name = str(params.get("name", "*Isometric"))
                orientation = int(params.get("orientation", 7))
                ok = _invoke(doc, "ShowNamedView2", name, orientation)
                _invoke(doc, "ViewZoomtofit2")
                if not ok:
                    raise McpCadError(
                        ErrorCode.UNSUPPORTED,
                        "Active document does not expose ShowNamedView2.",
                        "Use a normal SolidWorks model/drawing document and retry.",
                        {"view": name, "orientation": orientation},
                    )
                return {
                    "ok": ok,
                    "backend": self.name,
                    "operation": operation,
                    "view": name,
                    "orientation": orientation,
                }

            if operation == "screenshot":
                path_value = params.get("path")
                if not path_value:
                    raise McpCadError(
                        ErrorCode.INVALID_INPUT,
                        "Screenshot requires parameters.path.",
                        "Pass a PNG/BMP/JPG path under SOLIDWORKS_MCP_WORKSPACE_ROOTS.",
                    )
                path = self._allowed_path(str(path_value))
                view = _property_or_call(doc, "ActiveView")
                ok = _invoke(view, "SaveAs", str(path))
                if not ok:
                    raise McpCadError(
                        ErrorCode.UNSUPPORTED,
                        "Active SolidWorks view does not expose SaveAs for screenshots.",
                        (
                            "Use the SolidWorks backend with an active graphical view, "
                            "or capture through the macro bridge."
                        ),
                        {"path": str(path)},
                    )
                return {"ok": True, "backend": self.name, "operation": operation, "path": str(path)}

            raise _unsupported_phase2("appearance", operation)

        return self.dispatcher.call(f"appearance_operation:{operation}", _appearance)

    async def import_export_operation(
        self,
        operation: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = parameters or {}
        operation = operation.lower()
        if operation == "import":
            path = _required_string(params, "path")
            doc_type = params.get("document_type")
            info = await self.open_document(path, str(doc_type) if doc_type else None)
            return {
                "ok": True,
                "backend": self.name,
                "operation": operation,
                "document": info.model_dump(),
            }
        if operation == "export":
            path = _required_string(params, "path")
            export_format = str(params.get("format") or Path(path).suffix.lstrip("."))
            return await self.export_document(path, export_format, params.get("options") or {})
        if operation in {"pack_and_go", "batch_export"}:
            raise McpCadError(
                ErrorCode.UNSUPPORTED,
                f"{operation} is not implemented robustly in the Phase 2 SolidWorks backend.",
                (
                    "Use document_export for one active document, or add an allowlisted "
                    "macro/add-in workflow for production Pack and Go or batch export."
                ),
                {"operation": operation},
            )
        raise _unsupported_phase2("import_export", operation)

    async def semantic_analysis(
        self,
        analysis: str,
        detail: str = "concise",
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = parameters or {}
        analysis = analysis.lower()

        def _semantic(sw: Any) -> dict[str, Any]:
            doc = _active_doc(sw)
            inspection = inspect_active_or_document(
                doc,
                feature_limit=int(params.get("feature_limit", 250)),
                subfeature_limit=int(params.get("sub_feature_limit", 25)),
            )
            if analysis == "geometry":
                return {
                    "ok": True,
                    "backend": self.name,
                    "analysis": analysis,
                    "detail": detail,
                    "geometry": _semantic_geometry(inspection, detail),
                }
            if analysis == "feature_recognition":
                return {
                    "ok": True,
                    "backend": self.name,
                    "analysis": analysis,
                    "features": _semantic_features(inspection),
                }
            if analysis == "manufacturing_method":
                return {
                    "ok": True,
                    "backend": self.name,
                    "analysis": analysis,
                    "recommendations": _semantic_manufacturing(inspection),
                }
            if analysis == "dimension_plan":
                return {
                    "ok": True,
                    "backend": self.name,
                    "analysis": analysis,
                    "dimension_plan": _semantic_dimension_plan(inspection),
                }
            if analysis == "dimension_layout_score":
                return _semantic_layout_score(params, self.name)
            if analysis == "design_rule_check":
                return {
                    "ok": True,
                    "backend": self.name,
                    "analysis": analysis,
                    "checks": _semantic_design_checks(inspection, params),
                }
            if analysis == "dfm":
                return {
                    "ok": True,
                    "backend": self.name,
                    "analysis": analysis,
                    "geometry": _semantic_geometry(inspection, "concise"),
                    "features": _semantic_features(inspection),
                    "checks": _semantic_design_checks(inspection, params),
                    "recommendations": _semantic_manufacturing(inspection),
                }
            raise McpCadError(
                ErrorCode.UNSUPPORTED,
                f"semantic analysis '{analysis}' is not implemented.",
                "Use geometry, feature_recognition, manufacturing_method, dimension_plan, dimension_layout_score, design_rule_check, or dfm.",
                {"analysis": analysis},
            )

        return self.dispatcher.call(f"semantic_analysis:{analysis}", _semantic)

    async def routing_operation(
        self,
        operation: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise McpCadError(
            ErrorCode.UNSUPPORTED,
            f"routing.{operation} requires the optional SolidWorks Routing environment.",
            (
                "Enable the SolidWorks Routing add-in/license and add a reviewed macro/add-in "
                "bridge command for this workflow, then allowlist it before production use."
            ),
            {"operation": operation, "parameters": parameters or {}},
        )

    async def execute_macro(
        self,
        macro_path: str,
        procedure: str = "",
        module: str = "",
    ) -> dict[str, Any]:
        if not self.settings.allow_macros:
            raise McpCadError(
                ErrorCode.UNSUPPORTED,
                "Macro execution is disabled by configuration.",
                "Set SOLIDWORKS_MCP_ALLOW_MACROS=1 and configure "
                "SOLIDWORKS_MCP_MACRO_ALLOWLIST for approved procedures.",
            )
        allowed = self.settings.ensure_allowed_path(macro_path, must_exist=True)
        command_id = procedure or Path(macro_path).stem
        self._ensure_command_allowed("execute_macro", command_id=command_id)
        self._audit(
            "execute_macro",
            {"path": str(allowed), "module": module, "procedure": procedure},
        )

        def _macro(sw: Any) -> dict[str, Any]:
            if sw is None:
                raise _not_connected()
            errors = 0
            ok = bool(sw.RunMacro2(str(allowed), module, procedure, 0, errors))
            return {
                "executed": ok,
                "path": str(allowed),
                "module": module,
                "procedure": procedure,
                "errors": errors,
            }

        return self.dispatcher.call(
            "execute_macro",
            _macro,
            timeout_seconds=self.settings.com_timeout_seconds,
        )

    async def run_com_command(
        self,
        command: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._ensure_command_allowed(command)
        args = args or {}
        self._audit("run_com_command", {"command": command, "args": args})

        def _command(sw: Any) -> dict[str, Any]:
            doc = _active_doc(sw)
            if command in {"rebuild", "force_rebuild"}:
                ok = bool(
                    doc.ForceRebuild3(False)
                    if command == "force_rebuild"
                    else doc.EditRebuild3()
                )
                return {"command": command, "ok": ok}
            if command == "zoom_to_fit":
                view = _property_or_call(doc, "ActiveView")
                ok = bool(_call(view, "FrameState", 1) is not None)
                try:
                    doc.ViewZoomtofit2()
                    ok = True
                except Exception:
                    pass
                return {"command": command, "ok": ok}
            if command == "traverse_feature_tree":
                return {
                    "command": command,
                    "features": _feature_tree(doc, limit=int(args.get("limit", 250))),
                }
            if command == "get_custom_properties":
                return _get_props_inline(doc, args.get("scope", "file"), args.get("configuration"))
            raise McpCadError(
                ErrorCode.UNSUPPORTED,
                f"COM command '{command}' is not implemented in the allowlisted dispatcher.",
                "Use a supported command or route through an approved macro bridge command.",
                details={"command": command, "allowed": sorted(self.command_allowlist)},
            )

        return self.dispatcher.call(f"run_com_command:{command}", _command)

    async def macro_bridge_command(
        self,
        command: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._ensure_command_allowed(command)
        self._audit("macro_bridge_command", {"command": command, "payload": payload or {}})
        return self.macro_bridge.request(command, payload or {})

    def _ensure_command_allowed(self, command: str, *, command_id: str | None = None) -> None:
        allowed = set(self.settings.macro_allowlist) | self.command_allowlist
        if command not in allowed and (command_id is None or command_id not in allowed):
            raise McpCadError(
                ErrorCode.UNSUPPORTED,
                f"Command '{command}' is not allowlisted for production execution.",
                "Add the command to SOLIDWORKS_MCP_MACRO_ALLOWLIST only after "
                "reviewing the macro/add-in implementation.",
                details={"command": command, "command_id": command_id, "allowed": sorted(allowed)},
            )

    def _audit(self, event: str, payload: dict[str, Any]) -> None:
        record = {"ts": time.time(), "backend": self.name, "event": event, "payload": payload}
        if not self.settings.audit_log_path:
            LOGGER.info("SolidWorks audit: %s", record)
            return
        self.settings.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.settings.audit_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

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

    def _validate_drawing_paths(self, params: dict[str, Any]) -> None:
        for key in ("model_path", "template_path", "table_template"):
            value = params.get(key)
            if value:
                params[key] = str(self._allowed_path(str(value), must_exist=True))


def _dependency_status() -> dict[str, Any]:
    status: dict[str, Any] = {}
    try:
        import pythoncom  # noqa: F401
        import win32com.client  # noqa: F401

        status["pywin32_available"] = True
    except Exception as exc:
        status["pywin32_available"] = False
        status["pywin32_error"] = str(exc)
    try:
        import comtypes  # noqa: F401
        import comtypes.client  # noqa: F401

        status["comtypes_available"] = True
    except Exception as exc:
        status["comtypes_available"] = False
        status["comtypes_error"] = str(exc)
    status["com_available"] = bool(status["pywin32_available"] or status["comtypes_available"])
    return status


def _not_connected() -> McpCadError:
    return McpCadError(
        ErrorCode.NOT_CONNECTED,
        "SolidWorks is not attached.",
        "Start SolidWorks, call attach, then retry the operation.",
    )


def _active_doc(sw: Any) -> Any:
    if sw is None:
        raise _not_connected()
    doc = _first_not_none(
        _property(sw, "ActiveDoc"),
        _property(sw, "IActiveDoc2"),
        _call(sw, "GetActiveDoc"),
    )
    if doc is None:
        raise McpCadError(
            ErrorCode.INVALID_INPUT,
            "SolidWorks has no active document.",
            "Open or create a part, assembly, or drawing before calling this tool.",
        )
    return doc


def _document_info_from_model(doc: Any) -> dict[str, Any]:
    config_names = list(_call(doc, "GetConfigurationNames") or [])
    return {
        "path": _call(doc, "GetPathName"),
        "title": _call(doc, "GetTitle"),
        "document_type": normalize_document_type(_call(doc, "GetType")),
        "units": _units_summary(doc),
        "material": _call(
            doc,
            "GetMaterialPropertyName2",
            _active_configuration_name(doc) or "",
            "",
        ),
        "mass": None,
        "volume": None,
        "configurations": config_names,
        "active_configuration": _active_configuration_name(doc),
        "metadata": {
            "dirty": bool(_call(doc, "GetSaveFlag")),
            "feature_count_estimate": len(_feature_tree(doc, limit=1000)),
        },
    }


def _units_summary(doc: Any) -> str | None:
    try:
        unit_system = doc.GetUserPreferenceIntegerValue(0)
        return str(unit_system)
    except Exception:
        return None


def _active_configuration_name(doc: Any) -> str | None:
    configuration = _property_or_call(doc, "GetActiveConfiguration")
    return _first_not_none(_property(configuration, "Name"), _call(configuration, "Name"))


def _custom_property_manager(doc: Any, *, scope: str, configuration: str | None) -> Any:
    extension = _property_or_call(doc, "Extension")
    if extension is None:
        raise McpCadError(
            ErrorCode.BACKEND_FAULT,
            "Active document does not expose CustomPropertyManager.",
            "Activate a normal SolidWorks document and retry.",
        )
    if scope == "file":
        return extension.CustomPropertyManager("")
    if scope == "configuration":
        config_name = configuration or _active_configuration_name(doc) or ""
        return extension.CustomPropertyManager(config_name)
    raise McpCadError(
        ErrorCode.UNSUPPORTED,
        f"Custom property scope '{scope}' is not implemented in the COM MVP.",
        "Use scope='file' or scope='configuration'. Cut-list properties should "
        "be routed through the macro bridge/helper module.",
        details={"scope": scope},
    )


def _get_props_inline(doc: Any, scope: str, configuration: str | None) -> dict[str, Any]:
    manager = _custom_property_manager(doc, scope=scope, configuration=configuration)
    names = list(_call(manager, "GetNames") or [])
    return {
        "scope": scope,
        "configuration": configuration,
        "properties": {name: _call(manager, "Get", name) for name in names},
    }


def _feature_tree(doc: Any, *, limit: int) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    feature = _call(doc, "FirstFeature")
    while feature is not None and len(features) < limit:
        features.append(
            {
                "name": _first_not_none(_property(feature, "Name"), _call(feature, "Name")),
                "type": _call(feature, "GetTypeName2") or _call(feature, "GetTypeName"),
                "suppressed": _call(feature, "IsSuppressed"),
            }
        )
        feature = _call(feature, "GetNextFeature")
    return features


def _call(obj: Any, method: str, *args: Any) -> Any:
    if obj is None:
        return None
    try:
        candidate = getattr(obj, method)
        return candidate(*args) if callable(candidate) else candidate
    except Exception:
        return None


def _property(obj: Any, attr: str) -> Any:
    if obj is None:
        return None
    try:
        return getattr(obj, attr)
    except Exception:
        return None


def _property_or_call(obj: Any, name: str) -> Any:
    value = _property(obj, name)
    if value is None:
        return None
    if not callable(value):
        return value
    try:
        return value()
    except Exception:
        return value


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _invoke(obj: Any, method: str, *args: Any) -> bool:
    if obj is None:
        return False
    try:
        candidate = getattr(obj, method)
        if not callable(candidate):
            return candidate is not None
        candidate(*args)
        return True
    except Exception:
        return False


def _safe_attr(obj: Any, attr: str) -> Any:
    try:
        return getattr(obj, attr)
    except Exception:
        return None


def _required_string(parameters: dict[str, Any], key: str) -> str:
    value = parameters.get(key)
    if value is None or str(value).strip() == "":
        raise McpCadError(
            ErrorCode.INVALID_INPUT,
            f"Missing required parameter '{key}'.",
            f"Pass parameters.{key} with a non-empty string.",
            {"parameter": key},
        )
    return str(value)


def _unsupported_phase2(category: str, operation: str) -> McpCadError:
    return McpCadError(
        ErrorCode.UNSUPPORTED,
        f"{category}.{operation} is not implemented in the Phase 2 SolidWorks COM backend.",
        (
            "Use a supported operation, or route a reviewed workflow through the "
            "allowlisted macro bridge."
        ),
        {"category": category, "operation": operation},
    )


def _find_feature(doc: Any, name: str) -> Any:
    feature = _call(doc, "FeatureByName", name)
    if feature is not None:
        return feature
    feature = _call(doc, "FirstFeature")
    while feature is not None:
        feature_name = _first_not_none(_property(feature, "Name"), _call(feature, "Name"))
        if feature_name == name:
            return feature
        feature = _call(feature, "GetNextFeature")
    return None


def _select_object(obj: Any, mark: int = 0) -> bool:
    for method, args in (
        ("Select2", (False, mark)),
        ("Select", (False,)),
        ("Select4", (False, None)),
    ):
        result = _call(obj, method, *args)
        if result is not None:
            return bool(result)
    return False


def _set_feature_suppression(doc: Any, feature: Any, *, suppress: bool) -> bool:
    state = 0 if suppress else 2
    result = _call(feature, "SetSuppression2", state, 2, None)
    if result is not None:
        return bool(result)
    if not _select_object(feature):
        raise McpCadError(
            ErrorCode.OPERATION_FAILED,
            "Could not select the feature for suppression.",
            "Open the model in SolidWorks, ensure the feature is selectable, then retry.",
        )
    method = "EditSuppress2" if suppress else "EditUnsuppress2"
    result = _call(doc, method)
    if result is None:
        raise McpCadError(
            ErrorCode.UNSUPPORTED,
            f"Active document does not expose {method} or Feature.SetSuppression2.",
            "Use a normal part/assembly document or an allowlisted macro bridge command.",
        )
    return bool(result)


def _delete_feature(doc: Any, feature: Any) -> bool:
    if not _select_object(feature):
        raise McpCadError(
            ErrorCode.OPERATION_FAILED,
            "Could not select the feature for deletion.",
            "Open the model in SolidWorks, ensure the feature is selectable, then retry.",
        )
    for method, args in (
        ("DeleteSelection2", (1,)),
        ("DeleteSelection", (False,)),
    ):
        result = _call(doc, method, *args)
        if result is not None:
            return bool(result)
    extension = _property_or_call(doc, "Extension")
    result = _call(extension, "DeleteSelection2", 1)
    if result is not None:
        return bool(result)
    raise McpCadError(
        ErrorCode.UNSUPPORTED,
        "Active document does not expose a supported feature deletion API.",
        "Delete through SolidWorks UI/macro bridge, or retry on a standard model document.",
    )


def _selection_count(doc: Any) -> int | None:
    selection = _call(doc, "SelectionManager")
    if selection is None:
        return None
    count = _call(selection, "GetSelectedObjectCount2", -1)
    if count is None:
        count = _call(selection, "GetSelectedObjectCount")
    return int(count) if count is not None else None


def _create_extrude(doc: Any, *, operation: str, depth: float) -> dict[str, Any]:
    if _selection_count(doc) == 0:
        raise McpCadError(
            ErrorCode.INVALID_INPUT,
            "Extrude requires a preselected closed sketch or sketch contour.",
            "Select a closed sketch in SolidWorks, then retry extrude_boss/extrude_cut with depth.",
            {"operation": operation, "depth": depth},
        )
    manager = _property_or_call(doc, "FeatureManager")
    if manager is None:
        raise McpCadError(
            ErrorCode.BACKEND_FAULT,
            "Active document does not expose FeatureManager.",
            "Activate a part document and retry.",
        )
    if operation == "extrude_boss":
        feature = _call(
            manager,
            "FeatureExtrusion2",
            True,
            False,
            False,
            0,
            0,
            depth,
            0.0,
            False,
            False,
            False,
            False,
            0.0,
            0.0,
            False,
            False,
            False,
            False,
            True,
            True,
            True,
            0,
            0.0,
            False,
        )
    else:
        feature = _call(
            manager,
            "FeatureCut4",
            True,
            False,
            False,
            0,
            0,
            depth,
            0.0,
            False,
            False,
            False,
            False,
            0.0,
            0.0,
            False,
            False,
            False,
            False,
            False,
            True,
            True,
            True,
            True,
            False,
            0,
            0.0,
            False,
            False,
        )
    if feature is None:
        raise McpCadError(
            ErrorCode.OPERATION_FAILED,
            f"SolidWorks could not create {operation}.",
            (
                "Verify a closed sketch/contour is selected and the depth is valid for "
                "the active part."
            ),
            {"operation": operation, "depth": depth},
        )
    return {
        "ok": True,
        "backend": "solidworks",
        "operation": operation,
        "depth": depth,
        "feature": _feature_summary(feature),
    }


def _create_fillet(doc: Any, *, radius: float) -> dict[str, Any]:
    if _selection_count(doc) == 0:
        raise McpCadError(
            ErrorCode.INVALID_INPUT,
            "Fillet requires preselected edges or faces.",
            "Select one or more edges/faces in SolidWorks, then retry with radius.",
            {"radius": radius},
        )
    manager = _property_or_call(doc, "FeatureManager")
    feature = _call(manager, "FeatureFillet3", 195, radius, 0.0, 0, 0, 0, 0, None, None, None)
    if feature is None:
        feature = _call(manager, "FeatureFillet2", radius, 0, 0, 0, 0, 0, 0)
    if feature is None:
        raise McpCadError(
            ErrorCode.UNSUPPORTED,
            "Active SolidWorks API did not expose a compatible fillet creation method.",
            (
                "Create the fillet through UI/macro bridge, or preselect simpler edge "
                "geometry and retry."
            ),
            {"radius": radius},
        )
    return {
        "ok": True,
        "backend": "solidworks",
        "operation": "fillet",
        "radius": radius,
        "feature": _feature_summary(feature),
    }


def _create_chamfer(doc: Any, *, distance: float, angle: float) -> dict[str, Any]:
    if _selection_count(doc) == 0:
        raise McpCadError(
            ErrorCode.INVALID_INPUT,
            "Chamfer requires preselected edges or faces.",
            "Select one or more edges/faces in SolidWorks, then retry with distance.",
            {"distance": distance, "angle": angle},
        )
    manager = _property_or_call(doc, "FeatureManager")
    feature = _call(manager, "InsertFeatureChamfer", 4, 1, distance, angle, 0.0, 0.0, 0.0, 0.0)
    if feature is None:
        raise McpCadError(
            ErrorCode.UNSUPPORTED,
            "Active SolidWorks API did not expose a compatible chamfer creation method.",
            (
                "Create the chamfer through UI/macro bridge, or preselect simpler edge "
                "geometry and retry."
            ),
            {"distance": distance, "angle": angle},
        )
    return {
        "ok": True,
        "backend": "solidworks",
        "operation": "chamfer",
        "distance": distance,
        "angle": angle,
        "feature": _feature_summary(feature),
    }


def _feature_summary(feature: Any) -> dict[str, Any]:
    return {
        "name": _first_not_none(_property(feature, "Name"), _call(feature, "Name")),
        "type": _call(feature, "GetTypeName2") or _call(feature, "GetTypeName"),
        "suppressed": _call(feature, "IsSuppressed"),
    }


def _component_tree(doc: Any) -> list[dict[str, Any]]:
    components = _call(doc, "GetComponents", False)
    if components is None:
        configuration = _call(doc, "GetActiveConfiguration")
        root = _call(configuration, "GetRootComponent3", True)
        components = _call(root, "GetChildren") if root is not None else None
    return [_component_summary(component) for component in list(components or [])]


def _component_summary(component: Any) -> dict[str, Any]:
    path = _call(component, "GetPathName")
    return {
        "name": (
            _property(component, "Name2")
            or _call(component, "Name2")
            or _call(component, "Name")
        ),
        "path": path,
        "suppressed": _call(component, "IsSuppressed"),
        "visible": _safe_attr(component, "Visible"),
        "referenced_configuration": _call(component, "ReferencedConfiguration"),
    }


def _find_component(doc: Any, name: str) -> Any:
    component = _call(doc, "GetComponentByName", name)
    if component is not None:
        return component
    for candidate in _call(doc, "GetComponents", False) or []:
        candidate_name = (
            _property(candidate, "Name2")
            or _call(candidate, "Name2")
            or _call(candidate, "Name")
        )
        if candidate_name == name:
            return candidate
    return None


def _component_transform_array(component: Any) -> list[float] | None:
    transform = _property_or_call(component, "Transform2")
    values = _first_not_none(_property(transform, "ArrayData"), _call(transform, "ArrayData"))
    if values is None:
        return None
    try:
        return [float(value) for value in values]
    except TypeError:
        return None


def _create_math_transform(sw: Any, values: list[float]) -> Any:
    utility = _call(sw, "GetMathUtility")
    if utility is None:
        return None
    return _call(utility, "CreateTransform", values)


def _move_component(sw: Any, component: Any, parameters: dict[str, Any]) -> bool:
    values = _component_transform_array(component)
    if values is None or len(values) < 12:
        raise McpCadError(
            ErrorCode.UNSUPPORTED,
            "Component move requires Component.Transform2.ArrayData.",
            (
                "Use a resolved assembly component, or move it through an allowlisted "
                "macro bridge workflow."
            ),
        )
    values[9] += float(parameters.get("dx", 0.0))
    values[10] += float(parameters.get("dy", 0.0))
    values[11] += float(parameters.get("dz", 0.0))
    transform = _create_math_transform(sw, values)
    result = _call(component, "SetTransformAndSolve2", transform)
    if result is None:
        result = _call(component, "Transform2", transform)
    if result is None:
        raise McpCadError(
            ErrorCode.UNSUPPORTED,
            "Component does not expose SetTransformAndSolve2 for move.",
            "Use SolidWorks UI/macro bridge for constrained or lightweight components.",
        )
    return bool(result)


def _rotate_component(sw: Any, component: Any, parameters: dict[str, Any]) -> bool:
    import math

    angle = float(parameters.get("angle", parameters.get("angle_radians", 0.0)))
    if parameters.get("angle_degrees") is not None:
        angle = math.radians(float(parameters["angle_degrees"]))
    axis = str(parameters.get("axis", "z")).lower()
    values = _component_transform_array(component)
    if values is None or len(values) < 12:
        raise McpCadError(
            ErrorCode.UNSUPPORTED,
            "Component rotate requires Component.Transform2.ArrayData.",
            (
                "Use a resolved assembly component, or rotate it through an allowlisted "
                "macro bridge workflow."
            ),
        )
    c = math.cos(angle)
    s = math.sin(angle)
    if axis == "x":
        rotation = [1.0, 0.0, 0.0, 0.0, c, -s, 0.0, s, c]
    elif axis == "y":
        rotation = [c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c]
    elif axis == "z":
        rotation = [c, -s, 0.0, s, c, 0.0, 0.0, 0.0, 1.0]
    else:
        raise McpCadError(
            ErrorCode.INVALID_INPUT,
            f"Unsupported rotation axis '{axis}'.",
            "Use axis='x', 'y', or 'z'.",
            {"axis": axis},
        )
    values[:9] = rotation
    transform = _create_math_transform(sw, values)
    result = _call(component, "SetTransformAndSolve2", transform)
    if result is None:
        raise McpCadError(
            ErrorCode.UNSUPPORTED,
            "Component does not expose SetTransformAndSolve2 for rotate.",
            "Use SolidWorks UI/macro bridge for constrained or lightweight components.",
        )
    return bool(result)


def _set_component_suppression(component: Any, *, suppress: bool) -> bool:
    state = 0 if suppress else 2
    result = _call(component, "SetSuppression2", state)
    if result is not None:
        return bool(result)
    raise McpCadError(
        ErrorCode.UNSUPPORTED,
        "Component does not expose SetSuppression2.",
        (
            "Resolve the component in SolidWorks or route suppression through an "
            "allowlisted macro bridge command."
        ),
    )


def _show_hide_component(component: Any, *, show: bool) -> bool:
    value = 1 if show else 0
    try:
        setattr(component, "Visible", value)
        return True
    except Exception as exc:
        result = _call(component, "SetVisibility", value)
        if result is not None:
            return bool(result)
        raise McpCadError(
            ErrorCode.UNSUPPORTED,
            "Component does not expose a supported visibility API.",
            "Use a resolved assembly component or an allowlisted macro bridge command.",
        ) from exc


def _interference_detection(doc: Any) -> dict[str, Any]:
    manager = _call(doc, "InterferenceDetectionManager")
    if manager is None:
        extension = _property_or_call(doc, "Extension")
        manager = _call(extension, "InterferenceDetectionManager")
    if manager is None:
        raise McpCadError(
            ErrorCode.UNSUPPORTED,
            (
                "Active assembly does not expose InterferenceDetectionManager through "
                "this COM backend."
            ),
            "Run interference detection in SolidWorks UI or add a reviewed macro bridge command.",
        )
    result = _call(manager, "RunInterference")
    interferences = _call(manager, "GetInterferences")
    count = len(list(interferences or [])) if interferences is not None else None
    return {
        "ok": bool(result) if result is not None else True,
        "backend": "solidworks",
        "operation": "interference_detection",
        "interference_count": count,
    }


def _concise_part_inspection(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": payload.get("title"),
        "path": payload.get("path"),
        "document_type": payload.get("document_type"),
        "type_name": payload.get("type_name"),
        "configurations": payload.get("configurations", []),
        "active_configuration": payload.get("active_configuration"),
        "feature_count": payload.get("feature_count"),
        "solid_body_count": payload.get("solid_body_count"),
        "material": payload.get("material"),
        "unit_system": payload.get("unit_system"),
        "bounding_box": payload.get("bounding_box"),
        "mass_properties": payload.get("mass_properties"),
    }


def _semantic_geometry(inspection: dict[str, Any], detail: str) -> dict[str, Any]:
    geometry = {
        "bounding_box": inspection.get("bounding_box"),
        "mass_properties": inspection.get("mass_properties"),
        "solid_body_count": inspection.get("solid_body_count"),
        "surface_body_count": inspection.get("surface_body_count"),
        "unit_system": inspection.get("unit_system"),
    }
    if detail == "detailed":
        geometry["solid_bodies"] = inspection.get("solid_bodies", [])
        geometry["feature_count"] = inspection.get("feature_count")
    return geometry


def _semantic_features(inspection: dict[str, Any]) -> list[dict[str, Any]]:
    recognized: list[dict[str, Any]] = []
    for feature in inspection.get("features", []):
        feature_type = str(feature.get("type") or "").lower()
        name = feature.get("name")
        if "fillet" in feature_type:
            recognized.append({"type": "fillet", "name": name, "confidence": 0.9})
        elif "chamfer" in feature_type:
            recognized.append({"type": "chamfer", "name": name, "confidence": 0.9})
        elif "hole" in feature_type:
            recognized.append({"type": "hole", "name": name, "confidence": 0.85})
        elif "extr" in feature_type or "boss" in feature_type or "cut" in feature_type:
            recognized.append({"type": "extrude_or_cut", "name": name, "confidence": 0.8})
    if not recognized and inspection.get("solid_body_count"):
        recognized.append({"type": "solid_body", "confidence": 0.5, "source": "body_count"})
    return recognized


def _semantic_manufacturing(inspection: dict[str, Any]) -> list[dict[str, Any]]:
    features = _semantic_features(inspection)
    feature_types = {feature["type"] for feature in features}
    recommendations = [
        {
            "method": "cnc_machining",
            "confidence": 0.65,
            "reason": "SolidWorks feature/body inspection indicates a mechanical solid model.",
        }
    ]
    if {"hole", "fillet"} & feature_types:
        recommendations.append(
            {
                "method": "drilling_and_edge_finishing",
                "confidence": 0.6,
                "reason": "Recognized hole or fillet features require secondary operations.",
            }
        )
    return recommendations


def _semantic_dimension_plan(inspection: dict[str, Any]) -> list[dict[str, Any]]:
    bbox = inspection.get("bounding_box") or {}
    try:
        return [
            {"id": "overall_length", "axis": "x", "value": bbox["xmax"] - bbox["xmin"]},
            {"id": "overall_width", "axis": "y", "value": bbox["ymax"] - bbox["ymin"]},
            {"id": "overall_height", "axis": "z", "value": bbox["zmax"] - bbox["zmin"]},
        ]
    except (KeyError, TypeError):
        return []


def _semantic_design_checks(
    inspection: dict[str, Any],
    parameters: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    bbox = inspection.get("bounding_box") or {}
    min_wall = parameters.get("min_wall_thickness")
    try:
        sizes = (
            float(bbox["xmax"]) - float(bbox["xmin"]),
            float(bbox["ymax"]) - float(bbox["ymin"]),
            float(bbox["zmax"]) - float(bbox["zmin"]),
        )
    except (KeyError, TypeError, ValueError):
        sizes = None
    if sizes and min_wall is not None:
        checks.append(
            {
                "rule": "minimum_wall_proxy",
                "status": "pass" if min(sizes) >= float(min_wall) else "warning",
                "measured": min(sizes),
                "threshold": float(min_wall),
                "next_step": "Use dedicated wall-thickness analysis before release.",
            }
        )
    checks.append(
        {
            "rule": "draft_undercut_proxy",
            "status": "unknown",
            "next_step": "Use SolidWorks DFMX/analysis add-ins or a reviewed macro for production checks.",
        }
    )
    return checks


def _semantic_layout_score(parameters: dict[str, Any], backend_name: str) -> dict[str, Any]:
    dimensions = parameters.get("dimensions")
    if not isinstance(dimensions, list):
        raise McpCadError(
            ErrorCode.INVALID_INPUT,
            "dimension_layout_score requires a dimensions list.",
            "Pass dimensions as boxes with id, x, y, width, and height.",
        )
    boxes = [_semantic_layout_box(item, index) for index, item in enumerate(dimensions)]
    min_gap = float(parameters.get("min_gap", 0.0))
    issues: list[dict[str, Any]] = []
    for index, first in enumerate(boxes):
        for second in boxes[index + 1 :]:
            if _semantic_boxes_overlap(first, second, min_gap):
                issues.append({"code": "overlap", "items": [first["id"], second["id"]]})
    return {
        "ok": True,
        "backend": backend_name,
        "analysis": "dimension_layout_score",
        "score": max(0, 100 - 20 * len(issues)),
        "issues": issues,
    }


def _semantic_layout_box(item: Any, index: int) -> dict[str, Any]:
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


def _semantic_boxes_overlap(first: dict[str, Any], second: dict[str, Any], min_gap: float) -> bool:
    return not (
        first["x"] + first["width"] + min_gap <= second["x"]
        or second["x"] + second["width"] + min_gap <= first["x"]
        or first["y"] + first["height"] + min_gap <= second["y"]
        or second["y"] + second["height"] + min_gap <= first["y"]
    )
