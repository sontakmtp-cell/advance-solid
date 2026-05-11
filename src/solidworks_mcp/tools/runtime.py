"""Runtime helpers for MCP tool registration and backend selection."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from solidworks_mcp.config import Settings, load_settings
from solidworks_mcp.core.backend import Backend
from solidworks_mcp.core.errors import ErrorCode, McpCadError, error_response
from solidworks_mcp.schemas.common import Capability, CapabilityMap, ResponseFormat


class UnavailableBackend(Backend):
    """Backend placeholder used when implementation dependencies are not installed yet."""

    def __init__(self, name: str, reason: str):
        self.name = name
        self._reason = reason

    async def backend_info(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "available": False,
            "reason": self._reason,
            "next_step": (
                "Install the requested backend extras or switch SOLIDWORKS_MCP_BACKEND "
                "to a backend that is available in this environment."
            ),
        }

    async def capabilities(self) -> CapabilityMap:
        return CapabilityMap(
            backend=self.name,
            categories={
                "system": {
                    "backend_info": Capability(supported=True, level="partial"),
                    "health": Capability(supported=True, level="partial"),
                }
            },
        )

    async def health(self) -> dict[str, Any]:
        return {
            "ok": False,
            "backend": self.name,
            "status": "unavailable",
            "reason": self._reason,
            "next_step": "Install backend dependencies, then retry system_attach.",
        }

    async def attach(self) -> dict[str, Any]:
        raise McpCadError(
            ErrorCode.DEPENDENCY_MISSING,
            f"{self.name} backend is not available: {self._reason}",
            "Install the backend implementation/dependencies or choose another backend.",
        )

    async def open_document(self, path: str, document_type: str | None = None) -> Any:
        return await self.unsupported("document.open")

    async def save_document(self, path: str | None = None) -> dict[str, Any]:
        return await self.unsupported("document.save")

    async def document_info(self, path: str | None = None, detail: str = "concise") -> Any:
        return await self.unsupported("document.info")

    async def rebuild(self, force: bool = False) -> dict[str, Any]:
        return await self.unsupported("document.rebuild")

    async def export_document(
        self, path: str, format: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self.unsupported("document.export")

    async def get_custom_properties(
        self, scope: str = "file", configuration: str | None = None
    ) -> dict[str, Any]:
        return await self.unsupported("custom_properties.get")

    async def set_custom_properties(
        self,
        properties: dict[str, Any],
        scope: str = "file",
        configuration: str | None = None,
    ) -> dict[str, Any]:
        return await self.unsupported("custom_properties.set")

    async def mass_properties(self) -> dict[str, Any]:
        return await self.unsupported("mass_properties")

    async def material_info(self, material: str | None = None) -> dict[str, Any]:
        return await self.unsupported("material_info")


BackendFactory = Callable[[str], Backend]


def default_backend_factory(settings: Settings | None = None) -> BackendFactory:
    settings = settings or load_settings()

    def create(backend_name: str) -> Backend:
        selected = settings.backend if backend_name == "auto" else backend_name
        try:
            from solidworks_mcp.core.factory import create_backend

            return create_backend(selected, settings=settings)
        except Exception as exc:  # pragma: no cover - depends on optional backend modules/deps.
            return UnavailableBackend(selected, str(exc))

    return create


def normalize_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict) and "ok" in value:
        return value
    if isinstance(value, dict):
        return {"ok": True, "data": value}
    return {"ok": True, "data": {"value": value}}


def to_markdown(payload: dict[str, Any]) -> str:
    if not payload.get("ok", True):
        error = payload.get("error", {})
        return (
            f"Error: {error.get('message', 'Operation failed')}\n\n"
            f"Next step: {error.get('next_step', 'Inspect the request and retry.')}"
        )
    backend = payload.get("backend") or payload.get("data", {}).get("backend")
    lines = ["OK"]
    if backend:
        lines.append(f"Backend: {backend}")
    data = payload.get("data", {})
    for key, value in data.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def format_payload(payload: dict[str, Any], response_format: ResponseFormat | str) -> dict[str, Any] | str:
    value = response_format.value if isinstance(response_format, ResponseFormat) else str(response_format)
    if value == ResponseFormat.MARKDOWN.value:
        return to_markdown(payload)
    return payload


def validation_error_payload(
    exc: ValidationError, response_format: ResponseFormat | str = ResponseFormat.JSON
) -> dict[str, Any] | str:
    return format_payload(
        error_response(
            McpCadError(
                ErrorCode.INVALID_INPUT,
                "Tool input failed schema validation.",
                "Fix the fields reported in details and retry.",
                {"validation_errors": exc.errors()},
            )
        ),
        response_format,
    )


async def run_tool(
    request: Any,
    backend_factory: BackendFactory,
    operation: Callable[[Backend, Any], Awaitable[Any]],
) -> dict[str, Any] | str:
    try:
        backend = backend_factory(getattr(request, "backend", "auto"))
        result = await operation(backend, request)
        payload = normalize_payload(result)
        payload.setdefault("backend", getattr(backend, "name", None))
        return format_payload(payload, getattr(request, "response_format", ResponseFormat.JSON))
    except ValidationError as exc:
        return validation_error_payload(
            exc, getattr(request, "response_format", ResponseFormat.JSON)
        )
    except Exception as exc:
        response_format = getattr(request, "response_format", ResponseFormat.JSON)
        return format_payload(error_response(exc), response_format)


async def call_optional_backend_method(
    backend: Backend,
    method_name: str,
    feature_name: str,
    *args: Any,
    **kwargs: Any,
) -> Any:
    method = getattr(backend, method_name, None)
    if method is None:
        return await backend.unsupported(feature_name)
    result = method(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result
