"""Read-only SolidWorks document inspection helpers.

The functions in this module intentionally avoid filesystem access and do not
modify the active SolidWorks document. They accept either a SolidWorks
application object or a model document object and return JSON-safe dictionaries.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from solidworks_mcp.backends.solidworks.constants import normalize_document_type


UNIT_SYSTEM_NAMES = {
    0: "MKS (m, kg, s)",
    1: "CGS (cm, g, s)",
    2: "MMGS (mm, g, s)",
    3: "IPS (inch, lbm, s)",
    4: "Custom",
}


def inspect_active_or_document(
    sw_or_doc: Any,
    *,
    feature_limit: int = 200,
    subfeature_limit: int = 20,
) -> dict[str, Any]:
    """Inspect a SolidWorks app or document through read-only COM calls."""

    doc = _resolve_document(sw_or_doc)
    if doc is None:
        return {"active_doc": None}

    active_configuration = _active_configuration_name(doc)
    document_type = _call(doc, "GetType")
    extension = _get(doc, "Extension")

    result: dict[str, Any] = {
        "title": _json_safe(_call(doc, "GetTitle")),
        "path": _json_safe(_call(doc, "GetPathName")),
        "document_type": normalize_document_type(document_type),
        "type_name": _document_type_name(document_type),
        "configurations": _list_or_empty(_call(doc, "GetConfigurationNames")),
        "active_configuration": active_configuration,
        "custom_properties_file": _file_custom_properties(extension),
        "features": _feature_tree(
            doc,
            feature_limit=max(0, feature_limit),
            subfeature_limit=max(0, subfeature_limit),
        ),
        "solid_bodies": _solid_bodies(doc),
        "mass_properties": _mass_properties(doc, extension),
        "material": _material(doc, active_configuration),
        "unit_system": _unit_system_summary(doc),
        "bounding_box": _bounding_box(doc),
    }
    result["feature_count"] = len(result["features"])
    result["solid_body_count"] = len(result["solid_bodies"])
    return _json_safe(result)


def _resolve_document(sw_or_doc: Any) -> Any:
    if sw_or_doc is None:
        return None
    active_doc = _get(sw_or_doc, "ActiveDoc")
    if active_doc is not None:
        return active_doc
    active_doc = _get(sw_or_doc, "IActiveDoc2")
    if active_doc is not None:
        return active_doc
    active_doc = _call(sw_or_doc, "GetActiveDoc")
    if active_doc is not None:
        return active_doc
    if _call(sw_or_doc, "GetTitle") is not None or _call(sw_or_doc, "GetPathName") is not None:
        return sw_or_doc
    return None


def _document_type_name(type_value: Any) -> str:
    normalized = normalize_document_type(type_value)
    if normalized == "part":
        return "Part"
    if normalized == "assembly":
        return "Assembly"
    if normalized == "drawing":
        return "Drawing"
    return "Unknown"


def _active_configuration_name(doc: Any) -> str | None:
    configuration = _call(doc, "GetActiveConfiguration")
    return _json_safe(_get(configuration, "Name"))


def _file_custom_properties(extension: Any) -> dict[str, Any]:
    if extension is None:
        return {}
    manager = _call(extension, "CustomPropertyManager", "")
    if manager is None:
        return {}
    names = _list_or_empty(_call(manager, "GetNames"))
    properties: dict[str, Any] = {}
    for name in names:
        value = ""
        resolved = ""
        was_resolved = False
        result = _call(manager, "Get5", name, False, value, resolved, was_resolved)
        if isinstance(result, tuple):
            properties[str(name)] = {
                "value": _json_safe(result[1] if len(result) > 1 else value),
                "resolved_value": _json_safe(result[2] if len(result) > 2 else resolved),
                "was_resolved": _json_safe(result[3] if len(result) > 3 else was_resolved),
            }
            continue
        fallback = _call(manager, "Get", name)
        properties[str(name)] = {"value": _json_safe(fallback), "resolved_value": None}
    return properties


def _feature_tree(doc: Any, *, feature_limit: int, subfeature_limit: int) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    feature = _call(doc, "FirstFeature")
    while feature is not None and len(features) < feature_limit:
        item = _feature_info(feature)
        subfeatures = _subfeatures(feature, subfeature_limit)
        if subfeatures:
            item["subfeatures"] = subfeatures
        features.append(item)
        feature = _call(feature, "GetNextFeature")
    return features


def _subfeatures(feature: Any, limit: int) -> list[dict[str, Any]]:
    subfeatures: list[dict[str, Any]] = []
    subfeature = _call(feature, "GetFirstSubFeature")
    while subfeature is not None and len(subfeatures) < limit:
        subfeatures.append(_feature_info(subfeature, include_suppressed=False))
        subfeature = _call(subfeature, "GetNextSubFeature")
    return subfeatures


def _feature_info(feature: Any, *, include_suppressed: bool = True) -> dict[str, Any]:
    info = {
        "name": _json_safe(_get(feature, "Name")),
        "type": _json_safe(_call(feature, "GetTypeName2") or _call(feature, "GetTypeName")),
    }
    if include_suppressed:
        info["suppressed"] = _json_safe(_call(feature, "IsSuppressed"))
    return info


def _solid_bodies(doc: Any) -> list[dict[str, Any]]:
    bodies = _call(doc, "GetBodies2", 0, False)
    result: list[dict[str, Any]] = []
    for body in _list_or_empty(bodies):
        faces = _call(body, "GetFaces")
        edges = _call(body, "GetEdges")
        result.append(
            {
                "name": _json_safe(_get(body, "Name")),
                "face_count": _count_or_none(faces),
                "edge_count": _count_or_none(edges),
            }
        )
    return result


def _mass_properties(doc: Any, extension: Any) -> dict[str, Any] | None:
    mass_property = _call(extension, "CreateMassProperty") if extension is not None else None
    if mass_property is not None:
        return {
            "mass_kg": _json_safe(_get(mass_property, "Mass")),
            "volume_m3": _json_safe(_get(mass_property, "Volume")),
            "surface_area_m2": _json_safe(_get(mass_property, "SurfaceArea")),
            "center_of_mass": _json_safe(_get(mass_property, "CenterOfMass")),
            "density": _json_safe(_get(mass_property, "Density")),
            "moment_of_inertia": _json_safe(_call(mass_property, "GetMomentOfInertia")),
        }
    raw = _call(doc, "GetMassProperties")
    if raw is None:
        return None
    return {"raw": _json_safe(raw)}


def _material(doc: Any, active_configuration: str | None) -> Any:
    return _json_safe(_call(doc, "GetMaterialPropertyName2", active_configuration or "", ""))


def _unit_system_summary(doc: Any) -> dict[str, Any] | None:
    value = _call(doc, "GetUserPreferenceIntegerValue", 0)
    if value is None:
        return None
    try:
        key = int(value)
    except (TypeError, ValueError):
        return {"raw": _json_safe(value), "name": "Unknown"}
    return {"raw": key, "name": UNIT_SYSTEM_NAMES.get(key, f"Unknown ({key})")}


def _bounding_box(doc: Any) -> dict[str, Any] | None:
    box = _call(doc, "GetPartBox") or _call(doc, "GetBox")
    values = _list_or_empty(box)
    if len(values) < 6:
        return None
    try:
        mins = [float(values[0]), float(values[1]), float(values[2])]
        maxs = [float(values[3]), float(values[4]), float(values[5])]
    except (TypeError, ValueError):
        return {"raw": _json_safe(values[:6])}
    return {
        "min": mins,
        "max": maxs,
        "size": [maxs[index] - mins[index] for index in range(3)],
    }


def _call(obj: Any, method: str, *args: Any) -> Any:
    if obj is None:
        return None
    try:
        candidate = getattr(obj, method)
    except Exception:
        return None
    if not callable(candidate):
        return candidate if not args else None
    try:
        return candidate(*args)
    except Exception:
        return None


def _get(obj: Any, attr: str) -> Any:
    if obj is None:
        return None
    try:
        return getattr(obj, attr)
    except Exception:
        return None


def _list_or_empty(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (str, bytes, dict)):
        return []
    if isinstance(value, Iterable):
        try:
            return list(value)
        except Exception:
            return []
    return []


def _count_or_none(value: Any) -> int | None:
    items = _list_or_empty(value)
    return len(items) if items or value is not None else None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(_json_safe(key)): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)
