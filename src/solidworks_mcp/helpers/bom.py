"""BOM and mass property helpers for SolidWorks-like documents."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from solidworks_mcp.core.errors import ErrorCode, McpCadError
from solidworks_mcp.helpers.properties import get_custom_properties


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        value = getattr(obj, name)
    except Exception:
        return default
    return value if value is not None else default


def _call_if_present(obj: Any, method: str, *args: Any) -> Any:
    fn = _get_attr(obj, method)
    if callable(fn):
        return fn(*args)
    return None


def _doc_path(model: Any) -> str | None:
    for method in ("GetPathName",):
        try:
            value = getattr(model, method)()
            if value:
                return str(value)
        except Exception:
            pass
    return _get_attr(model, "path")


def _doc_title(model: Any) -> str | None:
    try:
        title = model.GetTitle()
        if title:
            return str(title)
    except Exception:
        pass
    return _get_attr(model, "title")


def mass_properties(model: Any) -> dict[str, Any]:
    """Return concise mass properties from ModelDocExtension.CreateMassProperty."""

    extension = _get_attr(model, "Extension")
    if extension is None:
        raise McpCadError(
            ErrorCode.OPERATION_FAILED,
            "Document does not expose mass property APIs.",
            "Open a part or assembly in the SolidWorks backend, then retry mass_properties.",
        )

    mass = _call_if_present(extension, "CreateMassProperty")
    if mass is None:
        raise McpCadError(
            ErrorCode.UNSUPPORTED,
            "Mass properties are unavailable for this document.",
            "Rebuild the model and retry with a part or assembly document.",
        )

    warnings: list[str] = []

    def read(name: str) -> Any:
        value = _get_attr(mass, name)
        if callable(value):
            try:
                return value()
            except Exception as exc:
                warnings.append(f"Could not read mass property {name}: {exc}")
                return None
        return value

    return {
        "ok": True,
        "document": {"title": _doc_title(model), "path": _doc_path(model)},
        "mass": read("Mass"),
        "volume": read("Volume"),
        "surface_area": read("SurfaceArea"),
        "center_of_mass": read("CenterOfMass"),
        "moment_of_inertia": read("MomentOfInertia"),
        "principal_axes": read("PrincipalAxesOfInertia"),
        "warnings": warnings,
    }


def _component_children(component: Any) -> list[Any]:
    children = _call_if_present(component, "GetChildren")
    if children is None:
        children = _get_attr(component, "children", [])
    try:
        return list(children or [])
    except TypeError:
        return []


def _component_model(component: Any) -> Any:
    return _call_if_present(component, "GetModelDoc2") or _get_attr(component, "model")


def _component_name(component: Any) -> str | None:
    try:
        return str(component.Name2)
    except Exception:
        return _get_attr(component, "name")


def _component_configuration(component: Any) -> str | None:
    for name in ("ReferencedConfiguration", "referenced_configuration", "configuration"):
        value = _get_attr(component, name)
        if value:
            return str(value)
    return None


def _is_suppressed(component: Any) -> bool:
    state = _call_if_present(component, "GetSuppression")
    if state is None:
        return bool(_get_attr(component, "suppressed", False))
    if isinstance(state, bool):
        return state
    # SolidWorks swComponentSuppressed is 0; resolved/lightweight states are non-zero.
    return int(state) == 0


def _walk_components(component: Any) -> list[Any]:
    rows = [component]
    for child in _component_children(component):
        rows.extend(_walk_components(child))
    return rows


def _root_component(model: Any) -> Any | None:
    configuration_manager = _get_attr(model, "ConfigurationManager")
    active_config = _get_attr(configuration_manager, "ActiveConfiguration")
    if active_config is not None:
        try:
            root = active_config.GetRootComponent3(True)
            if root is not None:
                return root
        except Exception:
            pass
    return _get_attr(model, "root_component")


def read_bom(model: Any, include_suppressed: bool = False, include_properties: bool = True) -> dict[str, Any]:
    """Read a lightweight assembly BOM by traversing the component tree."""

    root = _root_component(model)
    if root is None:
        raise McpCadError(
            ErrorCode.UNSUPPORTED,
            "BOM traversal requires an assembly root component.",
            "Open an assembly document or use a drawing BOM table reader when available.",
        )

    warnings: list[str] = []
    grouped: dict[tuple[str | None, str | None], dict[str, Any]] = {}
    quantities: defaultdict[tuple[str | None, str | None], int] = defaultdict(int)

    for component in _walk_components(root):
        if component is root:
            continue
        if _is_suppressed(component) and not include_suppressed:
            continue

        component_model = _component_model(component)
        path = _doc_path(component_model) if component_model is not None else None
        config = _component_configuration(component)
        key = (path or _component_name(component), config)
        quantities[key] += 1

        if key not in grouped:
            props: dict[str, Any] = {}
            if include_properties and component_model is not None:
                try:
                    props = get_custom_properties(component_model, scope="file")["properties"]
                except Exception as exc:
                    warnings.append(f"Could not read custom properties for {_component_name(component)}: {exc}")
            grouped[key] = {
                "item": len(grouped) + 1,
                "component": _component_name(component),
                "path": path,
                "configuration": config,
                "quantity": 0,
                "properties": props,
            }

    for key, quantity in quantities.items():
        grouped[key]["quantity"] = quantity

    rows = sorted(grouped.values(), key=lambda row: row["item"])
    return {
        "ok": True,
        "source": "assembly_component_tree",
        "row_count": len(rows),
        "rows": rows,
        "warnings": warnings,
    }
