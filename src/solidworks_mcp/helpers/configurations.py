"""Configuration management helpers for SolidWorks-like documents."""

from __future__ import annotations

from typing import Any

from solidworks_mcp.core.errors import ErrorCode, McpCadError


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        value = getattr(obj, name)
    except Exception:
        return default
    return value if value is not None else default


def _configuration_manager(model: Any) -> Any:
    manager = _get_attr(model, "ConfigurationManager")
    if manager is None:
        raise McpCadError(
            ErrorCode.UNSUPPORTED,
            "Configuration manager is unavailable for this document.",
            "Use a SolidWorks part or assembly document with configuration support.",
        )
    return manager


def list_configurations(model: Any) -> dict[str, Any]:
    """List configurations and active configuration name."""

    warnings: list[str] = []
    names: list[str] = []

    try:
        raw_names = model.GetConfigurationNames()
        names = [str(name) for name in raw_names or []]
    except Exception:
        configs = _get_attr(model, "configurations", {})
        if isinstance(configs, dict):
            names = [str(name) for name in configs]
        else:
            try:
                names = [str(name) for name in configs]
            except TypeError:
                names = []
        warnings.append("Read configurations from generic attributes instead of SolidWorks API.")

    manager = _get_attr(model, "ConfigurationManager")
    active = None
    active_config = _get_attr(manager, "ActiveConfiguration")
    if active_config is not None:
        active = _get_attr(active_config, "Name")
    active = active or _get_attr(model, "active_configuration")

    return {
        "ok": True,
        "count": len(names),
        "configurations": names,
        "active": active,
        "warnings": warnings,
    }


def create_configuration(model: Any, name: str, comment: str = "") -> dict[str, Any]:
    if not name or not name.strip():
        raise McpCadError(ErrorCode.INVALID_INPUT, "Configuration name is required.", "Retry with a non-empty name.")

    manager = _configuration_manager(model)
    add = _get_attr(manager, "AddConfiguration3")
    if not callable(add):
        raise McpCadError(
            ErrorCode.UNSUPPORTED,
            "Creating configurations is not supported by this backend object.",
            "Use the SolidWorks backend with ModelDoc2.ConfigurationManager.AddConfiguration3 support.",
        )
    created = add(name, comment, "", 0)
    return {"ok": created is not None and created is not False, "configuration": name, "warnings": []}


def delete_configuration(model: Any, name: str) -> dict[str, Any]:
    if not name or not name.strip():
        raise McpCadError(ErrorCode.INVALID_INPUT, "Configuration name is required.", "Retry with a non-empty name.")

    delete = _get_attr(model, "DeleteConfiguration2")
    if not callable(delete):
        raise McpCadError(
            ErrorCode.UNSUPPORTED,
            "Deleting configurations is not supported by this backend object.",
            "Use the SolidWorks backend with ModelDoc2.DeleteConfiguration2 support.",
        )
    result = delete(name)
    return {
        "ok": result is not False,
        "deleted": name,
        "warnings": [] if result is not False else [f"SolidWorks rejected deletion of configuration '{name}'."],
    }


def activate_configuration(model: Any, name: str) -> dict[str, Any]:
    if not name or not name.strip():
        raise McpCadError(ErrorCode.INVALID_INPUT, "Configuration name is required.", "Retry with a non-empty name.")

    show = _get_attr(model, "ShowConfiguration2")
    if not callable(show):
        raise McpCadError(
            ErrorCode.UNSUPPORTED,
            "Activating configurations is not supported by this backend object.",
            "Use the SolidWorks backend with ModelDoc2.ShowConfiguration2 support.",
        )
    result = show(name)
    return {
        "ok": result is not False,
        "active": name,
        "warnings": [] if result is not False else [f"SolidWorks rejected activation of configuration '{name}'."],
    }


def rename_configuration(model: Any, name: str, new_name: str) -> dict[str, Any]:
    if not name or not name.strip() or not new_name or not new_name.strip():
        raise McpCadError(
            ErrorCode.INVALID_INPUT,
            "Both current and new configuration names are required.",
            "Retry with name and new_name set.",
        )

    manager = _configuration_manager(model)
    get_by_name = _get_attr(manager, "GetConfigurationByName")
    config = get_by_name(name) if callable(get_by_name) else None
    if config is None:
        raise McpCadError(
            ErrorCode.OPERATION_FAILED,
            f"Configuration '{name}' was not found.",
            "List configurations, then retry with an existing configuration name.",
            {"name": name},
        )

    try:
        config.Name = new_name
    except Exception as exc:
        raise McpCadError(
            ErrorCode.OPERATION_FAILED,
            f"Could not rename configuration '{name}'.",
            "Confirm the target name is unique and the document is writable.",
            {"name": name, "new_name": new_name, "cause": str(exc)},
        ) from exc

    return {"ok": True, "renamed": {"from": name, "to": new_name}, "warnings": []}


def manage_configuration(
    model: Any,
    action: str,
    name: str | None = None,
    new_name: str | None = None,
) -> dict[str, Any]:
    """Dispatch configuration operations from the schema-level action enum."""

    if action == "list":
        return list_configurations(model)
    if action == "create":
        return create_configuration(model, name or "")
    if action == "delete":
        return delete_configuration(model, name or "")
    if action == "activate":
        return activate_configuration(model, name or "")
    if action == "rename":
        return rename_configuration(model, name or "", new_name or "")
    raise McpCadError(
        ErrorCode.INVALID_INPUT,
        f"Unknown configuration action '{action}'.",
        "Use one of: list, create, delete, activate, rename.",
        {"action": action},
    )
