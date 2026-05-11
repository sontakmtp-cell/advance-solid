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
from solidworks_mcp.bridges.solidworks_macro.named_pipe_client import MacroBridgeClient
from solidworks_mcp.config import Settings, load_settings
from solidworks_mcp.core.backend import Backend
from solidworks_mcp.core.errors import ErrorCode, McpCadError
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
                    "feature_tree": partial,
                    "drawings": partial,
                    "assemblies": partial,
                    "routing": optional,
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
            extension = _call(doc, "Extension")
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
            extension = _call(doc, "Extension")
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
            names = list(manager.GetNames() or [])
            props: dict[str, Any] = {}
            for name in names:
                value = ""
                resolved = ""
                was_resolved = False
                try:
                    result = manager.Get5(name, False, value, resolved, was_resolved)
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
                try:
                    manager.Add3(key, SW_CUSTOM_INFO_TEXT, text, SW_CUSTOM_PROPERTY_REPLACE_VALUE)
                except Exception:
                    manager.Set2(key, text)
                written[key] = text
            return {"scope": scope, "configuration": configuration, "written": written}

        return self.dispatcher.call("set_custom_properties", _set)

    async def mass_properties(self) -> dict[str, Any]:
        def _mass(sw: Any) -> dict[str, Any]:
            doc = _active_doc(sw)
            extension = _call(doc, "Extension")
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
                view = _call(doc, "ActiveView")
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
    doc = sw.ActiveDoc
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
    configuration = _call(doc, "GetActiveConfiguration")
    return _call(configuration, "Name") or _safe_attr(configuration, "Name")


def _custom_property_manager(doc: Any, *, scope: str, configuration: str | None) -> Any:
    extension = _call(doc, "Extension")
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
    names = list(manager.GetNames() or [])
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
                "name": _call(feature, "Name") or _safe_attr(feature, "Name"),
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


def _safe_attr(obj: Any, attr: str) -> Any:
    try:
        return getattr(obj, attr)
    except Exception:
        return None
