"""Material helper functions for SolidWorks-like model documents."""

from __future__ import annotations

from typing import Any

from solidworks_mcp.core.errors import ErrorCode, McpCadError


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        value = getattr(obj, name)
    except Exception:
        return default
    return value if value is not None else default


def _call_any(obj: Any, names: tuple[str, ...], *args: Any) -> tuple[Any, str | None]:
    for name in names:
        fn = _get_attr(obj, name)
        if callable(fn):
            return fn(*args), name
    return None, None


def get_material_info(model: Any, configuration: str | None = None, database: str = "") -> dict[str, Any]:
    """Return material assignment for a part-like model."""

    warnings: list[str] = []
    config = configuration or ""
    material, method = _call_any(model, ("GetMaterialPropertyName2", "GetMaterialPropertyName"), config, database)
    if method is None:
        material = _get_attr(model, "material")
        if material is None:
            raise McpCadError(
                ErrorCode.UNSUPPORTED,
                "Material information is unavailable for this document.",
                "Use a SolidWorks part document or provide a backend object exposing GetMaterialPropertyName2.",
            )
        warnings.append("Read material from a mock/generic material attribute instead of SolidWorks API.")

    visual = _get_attr(model, "MaterialVisualProperties") or _get_attr(model, "material_visual_properties")
    return {
        "ok": True,
        "configuration": configuration,
        "database": database or None,
        "material": material or None,
        "appearance": visual,
        "warnings": warnings,
    }


def set_material(
    model: Any,
    material: str,
    configuration: str | None = None,
    database: str = "",
) -> dict[str, Any]:
    """Set material using the SolidWorks part material API when available."""

    if not material or not str(material).strip():
        raise McpCadError(
            ErrorCode.INVALID_INPUT,
            "Material name is required.",
            "Retry with a non-empty SolidWorks material name such as 'Plain Carbon Steel'.",
        )

    config = configuration or ""
    warnings: list[str] = []
    _, method = _call_any(model, ("SetMaterialPropertyName2", "SetMaterialPropertyName"), config, database, str(material))
    if method is None:
        if hasattr(model, "material"):
            setattr(model, "material", str(material))
            warnings.append("Set material on a mock/generic material attribute instead of SolidWorks API.")
        else:
            raise McpCadError(
                ErrorCode.UNSUPPORTED,
                "This document does not expose a writable material API.",
                "Use a SolidWorks part document, then retry set_material.",
            )

    return {
        "ok": True,
        "configuration": configuration,
        "database": database or None,
        "material": str(material),
        "warnings": warnings,
    }


def material_info(
    model: Any,
    material: str | None = None,
    configuration: str | None = None,
    database: str = "",
) -> dict[str, Any]:
    """Get material when material is omitted; otherwise set and return the new assignment."""

    if material is None:
        return get_material_info(model, configuration=configuration, database=database)
    result = set_material(model, material, configuration=configuration, database=database)
    current = get_material_info(model, configuration=configuration, database=database)
    result["current"] = current.get("material")
    result["warnings"].extend(current.get("warnings", []))
    return result
