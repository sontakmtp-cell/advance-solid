from __future__ import annotations

from typing import Any

import pytest

from solidworks_mcp.core.backend import Backend
from solidworks_mcp.core.errors import unsupported
from solidworks_mcp.schemas.common import Capability, CapabilityMap
from solidworks_mcp.schemas.documents import DocumentInfo
from solidworks_mcp.server import create_mcp_server


class FakeBackend(Backend):
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    async def backend_info(self) -> dict[str, Any]:
        self.record("backend_info")
        return {"backend": self.name, "version": "test"}

    async def capabilities(self) -> CapabilityMap:
        self.record("capabilities")
        return CapabilityMap(
            backend=self.name,
            categories={"document": {"info": Capability(supported=True, level="full")}},
        )

    async def health(self) -> dict[str, Any]:
        self.record("health")
        return {"ok": True, "backend": self.name}

    async def attach(self) -> dict[str, Any]:
        self.record("attach")
        return {"attached": True}

    async def open_document(self, path: str, document_type: str | None = None) -> DocumentInfo:
        self.record("open_document", path, document_type)
        return DocumentInfo(path=path, document_type=document_type or "unknown")

    async def save_document(self, path: str | None = None) -> dict[str, Any]:
        self.record("save_document", path)
        return {"saved": True, "path": path}

    async def document_info(self, path: str | None = None, detail: str = "concise") -> DocumentInfo:
        self.record("document_info", path, detail)
        return DocumentInfo(path=path, title="Fixture", document_type="part", material="Steel")

    async def rebuild(self, force: bool = False) -> dict[str, Any]:
        self.record("rebuild", force)
        return {"rebuilt": True, "force": force}

    async def export_document(
        self, path: str, format: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.record("export_document", path, format, options)
        return {"exported": True, "path": path, "format": format}

    async def get_custom_properties(
        self, scope: str = "file", configuration: str | None = None
    ) -> dict[str, Any]:
        self.record("get_custom_properties", scope, configuration)
        return {"properties": {"PartNo": "P-100"}}

    async def set_custom_properties(
        self,
        properties: dict[str, Any],
        scope: str = "file",
        configuration: str | None = None,
    ) -> dict[str, Any]:
        self.record("set_custom_properties", properties, scope, configuration)
        return {"updated": sorted(properties)}

    async def mass_properties(self) -> dict[str, Any]:
        self.record("mass_properties")
        return {"mass": 1.25, "volume": 2.5}

    async def material_info(self, material: str | None = None) -> dict[str, Any]:
        self.record("material_info", material)
        return {"material": material or "Steel"}

    async def read_bom(self, source: str) -> dict[str, Any]:
        self.record("read_bom", source)
        return {"rows": [{"item": 1, "part_number": "P-100"}]}

    async def feature_operation(self, operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
        self.record("feature_operation", operation, parameters)
        return {"operation": operation, "accepted": True}

    async def inspect_part(self, **kwargs: Any) -> dict[str, Any]:
        self.record("inspect_part", **kwargs)
        return {"title": "Fixture", "document_type": "part", "feature_count": 2}

    async def unsupported(self, feature: str) -> dict[str, Any]:
        raise unsupported(feature, self.name)


@pytest.fixture
def fake_backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def mcp(fake_backend: FakeBackend):
    return create_mcp_server(
        backend_factory=lambda _backend_name: fake_backend,
        force_in_memory=True,
    )


def test_registers_expected_tool_groups(mcp) -> None:
    expected = {
        "system_backend_info",
        "system_capabilities",
        "system_health",
        "system_attach",
        "system_execute_macro",
        "system_run_com_command",
        "document_open",
        "document_save",
        "document_info",
        "document_rebuild",
        "document_export",
        "custom_properties_get",
        "custom_properties_set",
        "bom_read",
        "mass_properties",
        "material_info",
        "configurations",
        "feature_operation",
        "assembly_operation",
        "drawing_operation",
        "appearance_operation",
        "import_export_operation",
        "semantic_analysis",
        "part_inspect",
        "routing_operation",
    }
    assert expected.issubset(mcp.tools)


def test_tool_annotations_are_recorded(mcp) -> None:
    assert mcp.tool_metadata["document_info"].read_only is True
    assert mcp.tool_metadata["document_save"].read_only is False
    assert mcp.tool_metadata["configurations"].destructive is True


@pytest.mark.asyncio
async def test_document_open_maps_to_backend(fake_backend: FakeBackend, mcp) -> None:
    result = await mcp.tools["document_open"](
        path="H:\\MCP-AutoCAD\\fixtures\\part.step",
        document_type="part",
        backend="headless",
    )

    assert result["ok"] is True
    assert result["data"]["path"].endswith("part.step")
    assert fake_backend.calls[-1] == (
        "open_document",
        ("H:\\MCP-AutoCAD\\fixtures\\part.step", "part"),
        {},
    )


@pytest.mark.asyncio
async def test_custom_properties_set_maps_to_backend(fake_backend: FakeBackend, mcp) -> None:
    result = await mcp.tools["custom_properties_set"](
        properties={"PartNo": "P-200"},
        scope="configuration",
        configuration="Default",
    )

    assert result["ok"] is True
    assert fake_backend.calls[-1] == (
        "set_custom_properties",
        ({"PartNo": "P-200"}, "configuration", "Default"),
        {},
    )


@pytest.mark.asyncio
async def test_optional_bom_method_maps_when_available(fake_backend: FakeBackend, mcp) -> None:
    result = await mcp.tools["bom_read"](source="assembly")

    assert result["ok"] is True
    assert result["data"]["rows"][0]["part_number"] == "P-100"
    assert fake_backend.calls[-1] == ("read_bom", ("assembly",), {})


@pytest.mark.asyncio
async def test_roadmap_tool_maps_to_backend_method(fake_backend: FakeBackend, mcp) -> None:
    result = await mcp.tools["feature_operation"](
        operation="list_tree",
        parameters={"include_suppressed": True},
    )

    assert result["ok"] is True
    assert fake_backend.calls[-1] == (
        "feature_operation",
        ("list_tree", {"include_suppressed": True}),
        {},
    )


@pytest.mark.asyncio
async def test_assembly_operation_maps_to_optional_backend_method(
    fake_backend: FakeBackend, mcp, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def assembly_operation(operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
        fake_backend.record("assembly_operation", operation, parameters)
        return {"operation": operation, "component_count": 3}

    monkeypatch.setattr(fake_backend, "assembly_operation", assembly_operation, raising=False)

    result = await mcp.tools["assembly_operation"](
        operation="list_components",
        parameters={"recursive": True, "include_suppressed": False},
    )

    assert result["ok"] is True
    assert result["data"]["component_count"] == 3
    assert fake_backend.calls[-1] == (
        "assembly_operation",
        ("list_components", {"recursive": True, "include_suppressed": False}),
        {},
    )


@pytest.mark.asyncio
async def test_drawing_operation_maps_to_optional_backend_method(
    fake_backend: FakeBackend, mcp, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def drawing_operation(operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
        fake_backend.record("drawing_operation", operation, parameters)
        return {"operation": operation, "view": parameters.get("view")}

    monkeypatch.setattr(fake_backend, "drawing_operation", drawing_operation, raising=False)

    result = await mcp.tools["drawing_operation"](
        operation="insert_view",
        parameters={"model_path": "H:\\CAD-Work\\bracket.SLDPRT", "view": "front"},
    )

    assert result["ok"] is True
    assert result["data"]["view"] == "front"
    assert fake_backend.calls[-1] == (
        "drawing_operation",
        ("insert_view", {"model_path": "H:\\CAD-Work\\bracket.SLDPRT", "view": "front"}),
        {},
    )


@pytest.mark.asyncio
async def test_appearance_operation_maps_to_optional_backend_method(
    fake_backend: FakeBackend, mcp, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def appearance_operation(operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
        fake_backend.record("appearance_operation", operation, parameters)
        return {"operation": operation, "activated": parameters.get("activate", False)}

    monkeypatch.setattr(fake_backend, "appearance_operation", appearance_operation, raising=False)

    result = await mcp.tools["appearance_operation"](
        operation="named_view",
        parameters={"name": "isometric", "activate": True},
    )

    assert result["ok"] is True
    assert result["data"]["activated"] is True
    assert fake_backend.calls[-1] == (
        "appearance_operation",
        ("named_view", {"name": "isometric", "activate": True}),
        {},
    )


@pytest.mark.asyncio
async def test_import_export_operation_maps_to_optional_backend_method(
    fake_backend: FakeBackend, mcp, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def import_export_operation(operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
        fake_backend.record("import_export_operation", operation, parameters)
        return {"operation": operation, "queued": 2}

    monkeypatch.setattr(fake_backend, "import_export_operation", import_export_operation, raising=False)

    result = await mcp.tools["import_export_operation"](
        operation="batch_export",
        parameters={"format": "step", "destination": "H:\\CAD-Work\\exchange"},
    )

    assert result["ok"] is True
    assert result["data"]["queued"] == 2
    assert fake_backend.calls[-1] == (
        "import_export_operation",
        ("batch_export", {"format": "step", "destination": "H:\\CAD-Work\\exchange"}),
        {},
    )


@pytest.mark.asyncio
async def test_part_inspect_maps_to_backend_method(fake_backend: FakeBackend, mcp) -> None:
    result = await mcp.tools["part_inspect"](
        detail="concise",
        include_bodies=False,
        feature_limit=25,
    )

    assert result["ok"] is True
    assert result["data"]["feature_count"] == 2
    assert fake_backend.calls[-1] == (
        "inspect_part",
        (),
        {
            "detail": "concise",
            "include_features": True,
            "include_sub_features": True,
            "include_bodies": False,
            "include_custom_properties": True,
            "feature_limit": 25,
            "sub_feature_limit": 50,
        },
    )


@pytest.mark.asyncio
async def test_semantic_analysis_maps_to_optional_backend_method(
    fake_backend: FakeBackend, mcp, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def semantic_analysis(
        analysis: str,
        detail: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        fake_backend.record("semantic_analysis", analysis, detail, parameters)
        return {"analysis": analysis, "score": 80}

    monkeypatch.setattr(fake_backend, "semantic_analysis", semantic_analysis, raising=False)

    result = await mcp.tools["semantic_analysis"](
        analysis="dfm",
        detail="concise",
        parameters={"min_wall_thickness": 1.5},
    )

    assert result["ok"] is True
    assert result["data"]["score"] == 80
    assert fake_backend.calls[-1] == (
        "semantic_analysis",
        ("dfm", "concise", {"min_wall_thickness": 1.5}),
        {},
    )


@pytest.mark.asyncio
async def test_routing_operation_maps_to_optional_backend_method(
    fake_backend: FakeBackend, mcp, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def routing_operation(operation: str, parameters: dict[str, Any]) -> dict[str, Any]:
        fake_backend.record("routing_operation", operation, parameters)
        return {"operation": operation, "status": "planned"}

    monkeypatch.setattr(fake_backend, "routing_operation", routing_operation, raising=False)

    result = await mcp.tools["routing_operation"](
        operation="pipe_spec",
        parameters={"spec": "CS150"},
    )

    assert result["ok"] is True
    assert result["data"]["status"] == "planned"
    assert fake_backend.calls[-1] == (
        "routing_operation",
        ("pipe_spec", {"spec": "CS150"}),
        {},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "operation"),
    [
        ("assembly_operation", "list_components"),
        ("drawing_operation", "insert_view"),
        ("appearance_operation", "named_view"),
        ("import_export_operation", "batch_export"),
        ("semantic_analysis", "geometry"),
        ("routing_operation", "piping_bom"),
    ],
)
async def test_unsupported_optional_backend_tool_returns_actionable_error(
    mcp, tool_name: str, operation: str
) -> None:
    kwargs = {"analysis": operation} if tool_name == "semantic_analysis" else {"operation": operation}
    result = await mcp.tools[tool_name](**kwargs)

    assert result["ok"] is False
    assert result["error"]["code"] == "unsupported"
    assert result["error"]["next_step"]


@pytest.mark.asyncio
async def test_grouped_tool_validation_error_is_actionable(mcp) -> None:
    result = await mcp.tools["drawing_operation"](operation="not_a_drawing_operation")

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_input"
    assert result["error"]["details"]["validation_errors"]


@pytest.mark.asyncio
async def test_schema_validation_error_is_actionable(mcp) -> None:
    result = await mcp.tools["document_export"](
        path="H:\\MCP-AutoCAD\\out\\part.bad",
        format="unsupported_format",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_input"
    assert result["error"]["details"]["validation_errors"]
