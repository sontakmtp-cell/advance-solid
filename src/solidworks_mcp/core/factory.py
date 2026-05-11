"""Backend factory and selection helpers."""

from __future__ import annotations

from solidworks_mcp.config import Settings, load_settings
from solidworks_mcp.core.backend import Backend
from solidworks_mcp.core.errors import ErrorCode, McpCadError


def create_backend(name: str | None = None, settings: Settings | None = None) -> Backend:
    settings = settings or load_settings()
    selected = (name or settings.backend).lower()
    if selected == "auto":
        selected = settings.backend.lower()
    if selected == "solidworks":
        from solidworks_mcp.backends.solidworks.backend import SolidWorksBackend

        return SolidWorksBackend(settings=settings)
    if selected == "headless":
        from solidworks_mcp.backends.headless.backend import HeadlessBackend

        return HeadlessBackend(settings=settings)
    raise McpCadError(
        code=ErrorCode.INVALID_INPUT,
        message=f"Unknown backend: {selected}",
        next_step="Use backend='solidworks', backend='headless', or backend='auto'.",
        details={"backend": selected},
    )

