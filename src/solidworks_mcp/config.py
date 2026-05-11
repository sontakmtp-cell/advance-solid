"""Runtime configuration for the SolidWorks MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_HARD_TIMEOUT_SECONDS = 120.0


def _split_paths(value: str | None) -> list[Path]:
    if not value:
        return [Path.cwd()]
    return [Path(part).expanduser().resolve() for part in value.split(os.pathsep) if part.strip()]


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    backend: str = field(default_factory=lambda: os.getenv("SOLIDWORKS_MCP_BACKEND", "headless"))
    workspace_roots: list[Path] = field(
        default_factory=lambda: _split_paths(os.getenv("SOLIDWORKS_MCP_WORKSPACE_ROOTS"))
    )
    allow_macros: bool = field(default_factory=lambda: _env_bool("SOLIDWORKS_MCP_ALLOW_MACROS"))
    macro_allowlist: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            item.strip()
            for item in os.getenv(
                "SOLIDWORKS_MCP_MACRO_ALLOWLIST",
                "get_custom_properties,set_custom_properties,traverse_feature_tree",
            ).split(",")
            if item.strip()
        )
    )
    com_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("SOLIDWORKS_MCP_COM_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
    )
    com_hard_timeout_seconds: float = field(
        default_factory=lambda: float(
            os.getenv("SOLIDWORKS_MCP_COM_HARD_TIMEOUT", DEFAULT_HARD_TIMEOUT_SECONDS)
        )
    )
    log_level: str = field(default_factory=lambda: os.getenv("SOLIDWORKS_MCP_LOG_LEVEL", "INFO"))
    audit_log_path: Path | None = field(
        default_factory=lambda: (
            Path(os.getenv("SOLIDWORKS_MCP_AUDIT_LOG")).expanduser().resolve()
            if os.getenv("SOLIDWORKS_MCP_AUDIT_LOG")
            else None
        )
    )

    def ensure_allowed_path(self, path: str | Path, *, must_exist: bool = False) -> Path:
        candidate = Path(path).expanduser().resolve()
        if must_exist and not candidate.exists():
            raise ValueError(f"Path does not exist: {candidate}")
        for root in self.workspace_roots:
            try:
                candidate.relative_to(root)
                return candidate
            except ValueError:
                continue
        roots = ", ".join(str(root) for root in self.workspace_roots)
        raise ValueError(f"Path is outside allowed workspace roots: {candidate}. Allowed roots: {roots}")


def load_settings() -> Settings:
    return Settings()

