"""Backend abstraction shared by SolidWorks COM and headless implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol

from solidworks_mcp.schemas.common import CapabilityMap
from solidworks_mcp.schemas.documents import DocumentInfo


class Backend(ABC):
    name: str

    @abstractmethod
    async def backend_info(self) -> dict[str, Any]:
        """Return backend identity, runtime, and operational constraints."""

    @abstractmethod
    async def capabilities(self) -> CapabilityMap:
        """Return capability map with supported and unsupported operations."""

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        """Return connection and dependency health."""

    @abstractmethod
    async def attach(self) -> dict[str, Any]:
        """Attach or initialize backend runtime."""

    @abstractmethod
    async def open_document(self, path: str, document_type: str | None = None) -> DocumentInfo:
        """Open or import a document."""

    @abstractmethod
    async def save_document(self, path: str | None = None) -> dict[str, Any]:
        """Save the current document."""

    @abstractmethod
    async def document_info(self, path: str | None = None, detail: str = "concise") -> DocumentInfo:
        """Return information about the active or specified document."""

    @abstractmethod
    async def rebuild(self, force: bool = False) -> dict[str, Any]:
        """Rebuild the active model."""

    @abstractmethod
    async def export_document(self, path: str, format: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Export active or loaded document to an exchange format."""

    @abstractmethod
    async def get_custom_properties(self, scope: str = "file", configuration: str | None = None) -> dict[str, Any]:
        """Return custom properties for file/configuration/cut-list scope."""

    @abstractmethod
    async def set_custom_properties(
        self,
        properties: dict[str, Any],
        scope: str = "file",
        configuration: str | None = None,
    ) -> dict[str, Any]:
        """Set custom properties for file/configuration/cut-list scope."""

    @abstractmethod
    async def mass_properties(self) -> dict[str, Any]:
        """Return mass, volume, center of mass, and inertia details when available."""

    @abstractmethod
    async def material_info(self, material: str | None = None) -> dict[str, Any]:
        """Get or set material information depending on backend support."""

    async def unsupported(self, feature: str) -> dict[str, Any]:
        from solidworks_mcp.core.errors import unsupported

        raise unsupported(feature, self.name)


class BackendFactory(Protocol):
    def __call__(self) -> Backend:
        ...

