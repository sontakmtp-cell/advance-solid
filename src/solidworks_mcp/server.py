"""SolidWorks MCP stdio server entrypoint."""

from __future__ import annotations

from typing import Any

from solidworks_mcp.config import Settings, load_settings
from solidworks_mcp.tools.registry import InMemoryMcp, register_all_tools
from solidworks_mcp.tools.runtime import BackendFactory, default_backend_factory


def create_mcp_server(
    *,
    backend_factory: BackendFactory | None = None,
    settings: Settings | None = None,
    force_in_memory: bool = False,
) -> Any:
    """Create and register the SolidWorks FastMCP server.

    Tests can pass ``force_in_memory=True`` to inspect registration without the
    optional MCP runtime installed.
    """

    settings = settings or load_settings()
    factory = backend_factory or default_backend_factory(settings)

    if force_in_memory:
        mcp: Any = InMemoryMcp("solidworks-mcp")
    else:
        try:
            from mcp.server.fastmcp import FastMCP

            mcp = FastMCP("solidworks-mcp")
        except ImportError:
            mcp = InMemoryMcp("solidworks-mcp")

    return register_all_tools(mcp, factory)


def main() -> None:
    """Run the MCP server over stdio transport."""

    mcp = create_mcp_server()
    run = getattr(mcp, "run", None)
    if run is None:
        raise RuntimeError("FastMCP runtime is not installed. Install package dependency 'mcp'.")
    run()


if __name__ == "__main__":
    main()
