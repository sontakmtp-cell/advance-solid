"""Structured, agent-actionable errors."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    UNSUPPORTED = "unsupported"
    NOT_CONNECTED = "not_connected"
    INVALID_INPUT = "invalid_input"
    PATH_NOT_ALLOWED = "path_not_allowed"
    TIMEOUT = "timeout"
    BACKEND_BUSY = "backend_busy"
    BACKEND_FAULT = "backend_fault"
    DEPENDENCY_MISSING = "dependency_missing"
    OPERATION_FAILED = "operation_failed"


@dataclass
class McpCadError(Exception):
    code: ErrorCode
    message: str
    next_step: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": False,
            "error": {
                "code": self.code.value,
                "message": self.message,
                "next_step": self.next_step,
            },
        }
        if self.details:
            payload["error"]["details"] = self.details
        return payload


def unsupported(feature: str, backend: str, *, suggestion: str = "Switch to the solidworks backend.") -> McpCadError:
    return McpCadError(
        code=ErrorCode.UNSUPPORTED,
        message=f"{feature} is not supported by the {backend} backend.",
        next_step=suggestion,
        details={"feature": feature, "backend": backend},
    )


def error_response(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, McpCadError):
        return exc.to_dict()
    return McpCadError(
        code=ErrorCode.OPERATION_FAILED,
        message=str(exc) or exc.__class__.__name__,
        next_step="Inspect the input and backend status, then retry with a narrower operation.",
    ).to_dict()

