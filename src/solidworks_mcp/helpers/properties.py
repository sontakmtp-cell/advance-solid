"""Custom property helpers for SolidWorks-like COM objects.

The functions in this module intentionally use duck typing. SolidWorks COM
objects, VSTA bridge DTOs, and tests can all provide the small method surface
used here without importing pywin32.
"""

from __future__ import annotations

from typing import Any, Iterable

from solidworks_mcp.core.errors import ErrorCode, McpCadError


SW_CUSTOM_INFO_TEXT = 30
SW_CUSTOM_PROPERTY_REPLACE_VALUE = 2


def _warning(message: str) -> str:
    return message


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        value = getattr(obj, name)
    except Exception:
        return default
    return value if value is not None else default


def _call(obj: Any, method: str, *args: Any) -> Any:
    fn = _get_attr(obj, method)
    if not callable(fn):
        raise McpCadError(
            ErrorCode.OPERATION_FAILED,
            f"Object does not expose {method}().",
            "Use the SolidWorks backend with an active document, or provide a bridge object that implements this method.",
            {"method": method},
        )
    return fn(*args)


def _normalise_names(raw_names: Any) -> list[str]:
    if raw_names is None:
        return []
    if isinstance(raw_names, str):
        return [raw_names]
    try:
        return [str(name) for name in raw_names if str(name)]
    except TypeError:
        return []


def _property_manager(model: Any, scope: str, configuration: str | None = None, cut_list_id: str | None = None) -> tuple[Any, list[str]]:
    warnings: list[str] = []
    scope_key = scope.lower()

    if scope_key in {"file", "document"}:
        extension = _get_attr(model, "Extension")
        if extension is None:
            raise McpCadError(
                ErrorCode.OPERATION_FAILED,
                "Document does not expose Extension.CustomPropertyManager.",
                "Open a SolidWorks model document before reading custom properties.",
            )
        return _call(extension, "CustomPropertyManager", ""), warnings

    if scope_key in {"configuration", "config"}:
        if not configuration:
            raise McpCadError(
                ErrorCode.INVALID_INPUT,
                "A configuration name is required for configuration custom properties.",
                "Retry with configuration set to an existing configuration name.",
            )
        extension = _get_attr(model, "Extension")
        if extension is None:
            raise McpCadError(
                ErrorCode.OPERATION_FAILED,
                "Document does not expose Extension.CustomPropertyManager.",
                "Open a SolidWorks model document before reading custom properties.",
            )
        return _call(extension, "CustomPropertyManager", configuration), warnings

    if scope_key in {"cut_list", "cut-list", "cutlist"}:
        manager = find_cut_list_property_manager(model, cut_list_id)
        if manager is None:
            raise McpCadError(
                ErrorCode.UNSUPPORTED,
                "No cut-list property manager was found on the active document.",
                "Use a weldment part with an updated cut list, or read file/configuration properties instead.",
                {"cut_list_id": cut_list_id},
            )
        if cut_list_id is None:
            warnings.append(_warning("No cut_list_id was provided; using the first available cut-list folder."))
        return manager, warnings

    raise McpCadError(
        ErrorCode.INVALID_INPUT,
        f"Unsupported custom property scope '{scope}'.",
        "Use one of: file, configuration, cut_list.",
        {"scope": scope},
    )


def find_cut_list_property_manager(model: Any, cut_list_id: str | None = None) -> Any | None:
    """Return a cut-list CustomPropertyManager from a part document, if present."""

    try:
        feature = model.FirstFeature()
    except Exception:
        return None

    while feature is not None:
        try:
            type_name = feature.GetTypeName2()
        except Exception:
            type_name = ""
        try:
            name = feature.Name
        except Exception:
            name = None

        if type_name in {"CutListFolder", "SolidBodyFolder"} and (cut_list_id in {None, name}):
            specific = None
            try:
                specific = feature.GetSpecificFeature2()
            except Exception:
                specific = None
            manager = _get_attr(specific, "CustomPropertyManager") or _get_attr(feature, "CustomPropertyManager")
            if manager is not None:
                return manager() if callable(manager) else manager

        try:
            feature = feature.GetNextFeature()
        except Exception:
            return None
    return None


def _read_property(manager: Any, name: str) -> tuple[dict[str, Any], str | None]:
    warnings: list[str] = []

    for method in ("Get6", "Get5", "Get4"):
        fn = _get_attr(manager, method)
        if not callable(fn):
            continue
        try:
            result = fn(name, False)
        except TypeError:
            result = fn(name)
        except Exception as exc:
            return {
                "name": name,
                "value": None,
                "resolved_value": None,
                "was_resolved": False,
                "linked": False,
            }, f"Could not read property '{name}' via {method}: {exc}"

        if isinstance(result, tuple):
            values = list(result)
            raw = values[1] if len(values) > 1 else None
            resolved = values[2] if len(values) > 2 else raw
            was_resolved = bool(values[3]) if len(values) > 3 else resolved is not None
            linked = bool(values[4]) if len(values) > 4 else False
        else:
            raw = result
            resolved = result
            was_resolved = result is not None
            linked = False
        return {
            "name": name,
            "value": raw,
            "resolved_value": resolved,
            "was_resolved": was_resolved,
            "linked": linked,
        }, None

    try:
        value = manager.Get(name)
        return {
            "name": name,
            "value": value,
            "resolved_value": value,
            "was_resolved": value is not None,
            "linked": False,
        }, None
    except Exception:
        warnings.append(f"CustomPropertyManager does not support Get6/Get5/Get4/Get for '{name}'.")

    return {
        "name": name,
        "value": None,
        "resolved_value": None,
        "was_resolved": False,
        "linked": False,
    }, warnings[0]


def get_custom_properties(
    model: Any,
    scope: str = "file",
    configuration: str | None = None,
    cut_list_id: str | None = None,
    names: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Read custom properties from file, configuration, or cut-list scope."""

    manager, warnings = _property_manager(model, scope, configuration, cut_list_id)
    selected_names = list(names) if names is not None else _normalise_names(_call(manager, "GetNames"))
    properties: dict[str, dict[str, Any]] = {}

    for name in selected_names:
        item, warning = _read_property(manager, str(name))
        properties[str(name)] = item
        if warning:
            warnings.append(_warning(warning))

    return {
        "ok": True,
        "scope": scope,
        "configuration": configuration,
        "cut_list_id": cut_list_id,
        "count": len(properties),
        "properties": properties,
        "warnings": warnings,
    }


def _set_one_property(manager: Any, name: str, value: Any) -> tuple[bool, str | None]:
    text_value = "" if value is None else str(value)

    set2 = _get_attr(manager, "Set2")
    if callable(set2):
        try:
            result = set2(name, text_value)
            if result in {False, -1}:
                return False, f"SolidWorks rejected Set2 for property '{name}'."
            return True, None
        except Exception:
            pass

    add3 = _get_attr(manager, "Add3")
    if callable(add3):
        try:
            result = add3(name, SW_CUSTOM_INFO_TEXT, text_value, SW_CUSTOM_PROPERTY_REPLACE_VALUE)
            if result in {False, -1}:
                return False, f"SolidWorks rejected Add3 for property '{name}'."
            return True, None
        except Exception as exc:
            return False, f"Could not write property '{name}' via Add3: {exc}"

    return False, f"CustomPropertyManager does not support Set2/Add3 for property '{name}'."


def set_custom_properties(
    model: Any,
    properties: dict[str, Any],
    scope: str = "file",
    configuration: str | None = None,
    cut_list_id: str | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Set custom properties and optionally remove absent properties when possible."""

    if not properties:
        raise McpCadError(
            ErrorCode.INVALID_INPUT,
            "No custom properties were provided.",
            "Retry with at least one property name/value pair.",
        )

    manager, warnings = _property_manager(model, scope, configuration, cut_list_id)
    written: list[str] = []
    failed: dict[str, str] = {}

    existing_names = set(_normalise_names(_call(manager, "GetNames")))
    if replace:
        delete = _get_attr(manager, "Delete2")
        if callable(delete):
            for name in sorted(existing_names - set(properties)):
                try:
                    delete(name)
                except Exception as exc:
                    warnings.append(_warning(f"Could not delete omitted property '{name}': {exc}"))
        else:
            warnings.append(_warning("replace=True requested, but CustomPropertyManager does not support Delete2."))

    for name, value in properties.items():
        success, warning = _set_one_property(manager, str(name), value)
        if success:
            written.append(str(name))
        else:
            failed[str(name)] = warning or "Write failed."

    return {
        "ok": not failed,
        "scope": scope,
        "configuration": configuration,
        "cut_list_id": cut_list_id,
        "written": written,
        "failed": failed,
        "warnings": warnings,
        "next_step": None
        if not failed
        else "Inspect failed property names, confirm the document is writable, then retry only those properties.",
    }
