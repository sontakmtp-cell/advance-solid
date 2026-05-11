"""Named pipe client for optional in-process SolidWorks macro/add-in bridge."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from solidworks_mcp.config import Settings, load_settings
from solidworks_mcp.core.errors import ErrorCode, McpCadError

LOGGER = logging.getLogger(__name__)

DEFAULT_PIPE_NAME = r"\\.\pipe\solidworks_mcp_bridge"
ALLOWED_BRIDGE_COMMANDS = {
    "execute_macro",
    "get_custom_properties",
    "set_custom_properties",
    "traverse_feature_tree",
}


@dataclass(frozen=True)
class BridgeRequest:
    id: str
    command: str
    payload: dict[str, Any]
    timeout_seconds: float


class MacroBridgeClient:
    """JSON-over-named-pipe client for an in-process SolidWorks bridge.

    The bridge is optional. It exists for operations that are safer or only
    available in-process via VSTA/.NET add-ins or short-lived macros. The server
    side must use an allowlist, bounded reads, cancellation/timeouts, and avoid a
    blocking infinite loop on the SolidWorks UI thread.
    """

    def __init__(self, settings: Settings | None = None, pipe_name: str | None = None):
        self.settings = settings or load_settings()
        self.pipe_name = pipe_name or os.getenv("SOLIDWORKS_MCP_MACRO_PIPE", DEFAULT_PIPE_NAME)

    def status(self) -> dict[str, Any]:
        return {
            "pipe_name": self.pipe_name,
            "allowed_commands": sorted(ALLOWED_BRIDGE_COMMANDS),
            "enabled": self.settings.allow_macros,
            "protocol": "single-line utf-8 JSON request/response with timeout",
        }

    def request(
        self,
        command: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        if command not in ALLOWED_BRIDGE_COMMANDS:
            raise McpCadError(
                ErrorCode.UNSUPPORTED,
                f"Macro bridge command '{command}' is not supported.",
                "Use one of the allowlisted bridge commands or implement and review "
                "a new add-in command first.",
                details={"command": command, "allowed": sorted(ALLOWED_BRIDGE_COMMANDS)},
            )
        if not self.settings.allow_macros:
            raise McpCadError(
                ErrorCode.UNSUPPORTED,
                "Macro bridge is disabled by configuration.",
                "Set SOLIDWORKS_MCP_ALLOW_MACROS=1 only for trusted workspaces "
                "and reviewed bridge commands.",
            )
        request = BridgeRequest(
            id=f"swmcp-{int(time.time() * 1000)}",
            command=command,
            payload=payload,
            timeout_seconds=timeout_seconds or self.settings.com_timeout_seconds,
        )
        return self._send_request(request)

    def _send_request(self, request: BridgeRequest) -> dict[str, Any]:
        if os.name != "nt":
            raise McpCadError(
                ErrorCode.UNSUPPORTED,
                "SolidWorks macro bridge named pipes are only supported on Windows.",
                "Run this backend on the Windows workstation hosting SolidWorks.",
                details={"os_name": os.name},
            )
        try:
            import win32file  # type: ignore[import-not-found]
            import win32pipe  # type: ignore[import-not-found]
        except Exception as exc:
            raise McpCadError(
                ErrorCode.DEPENDENCY_MISSING,
                "pywin32 win32file/win32pipe is required for named pipe macro bridge IPC.",
                "Install the solidworks extra on Windows: "
                "pip install 'solidworks-mcp[solidworks]'.",
                details={"exception": str(exc)},
            ) from exc

        deadline = time.monotonic() + request.timeout_seconds
        handle = None
        try:
            while True:
                try:
                    handle = win32file.CreateFile(
                        self.pipe_name,
                        win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                        0,
                        None,
                        win32file.OPEN_EXISTING,
                        0,
                        None,
                    )
                    break
                except Exception as exc:
                    if time.monotonic() >= deadline:
                        raise McpCadError(
                            ErrorCode.TIMEOUT,
                            f"Timed out connecting to macro bridge pipe {self.pipe_name}.",
                            "Start the SolidWorks VSTA/.NET bridge add-in, "
                            "verify the pipe name, then retry.",
                            details={"pipe_name": self.pipe_name, "exception": str(exc)},
                        ) from exc
                    time.sleep(0.1)
            try:
                win32pipe.SetNamedPipeHandleState(
                    handle,
                    win32pipe.PIPE_READMODE_MESSAGE,
                    None,
                    None,
                )
            except Exception:
                LOGGER.debug("Could not set pipe read mode; continuing", exc_info=True)
            raw = json.dumps(
                {
                    "id": request.id,
                    "command": request.command,
                    "payload": request.payload,
                    "timeout_seconds": request.timeout_seconds,
                },
                separators=(",", ":"),
            ).encode("utf-8") + b"\n"
            win32file.WriteFile(handle, raw)
            chunks: list[bytes] = []
            while time.monotonic() < deadline:
                _err, chunk = win32file.ReadFile(handle, 65536)
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
            else:
                raise McpCadError(
                    ErrorCode.TIMEOUT,
                    f"Macro bridge command '{request.command}' timed out.",
                    "Cancel the bridge operation in SolidWorks if possible, then "
                    "retry with a smaller request.",
                    details={
                        "command": request.command,
                        "timeout_seconds": request.timeout_seconds,
                    },
                )
            line = b"".join(chunks).split(b"\n", 1)[0].decode("utf-8")
            response = json.loads(line)
            if not response.get("ok", False):
                raise McpCadError(
                    ErrorCode.OPERATION_FAILED,
                    f"Macro bridge command '{request.command}' failed.",
                    "Inspect bridge response details, then retry after correcting "
                    "the active document or payload.",
                    details=response,
                )
            return response
        finally:
            if handle is not None:
                try:
                    win32file.CloseHandle(handle)
                except Exception:
                    LOGGER.debug("Could not close macro bridge pipe handle", exc_info=True)
