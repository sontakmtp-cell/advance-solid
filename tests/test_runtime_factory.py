from __future__ import annotations

from pathlib import Path

from solidworks_mcp.config import Settings
from solidworks_mcp.tools import runtime


def test_default_backend_factory_reuses_backend_instances(
    monkeypatch,
    tmp_path: Path,
) -> None:
    created: list[str] = []

    class FakeBackend:
        name = "solidworks"

    def fake_create_backend(name: str, settings: Settings):
        created.append(name)
        return FakeBackend()

    monkeypatch.setattr(
        "solidworks_mcp.core.factory.create_backend",
        fake_create_backend,
    )
    settings = Settings(backend="solidworks", workspace_roots=[tmp_path])
    factory = runtime.default_backend_factory(settings)

    first = factory("auto")
    second = factory("auto")
    explicit = factory("solidworks")

    assert first is second
    assert second is explicit
    assert created == ["solidworks"]

