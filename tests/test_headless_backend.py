from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from solidworks_mcp.backends.headless import HeadlessBackend
from solidworks_mcp.backends.headless.backend import CadDocument
from solidworks_mcp.config import Settings
from solidworks_mcp.core.errors import ErrorCode, McpCadError


class FakePoint:
    x = 1.0
    y = 2.0
    z = 3.0


class FakeBoundingBox:
    xmin = 0.0
    ymin = 0.0
    zmin = 0.0
    xmax = 10.0
    ymax = 20.0
    zmax = 30.0


class FakeShape:
    def Volume(self):
        return 6000.0

    def Area(self):
        return 2200.0

    def Center(self):
        return FakePoint()

    def BoundingBox(self):
        return FakeBoundingBox()

    def Solids(self):
        return [self]

    def Faces(self):
        return [object()] * 6

    def Edges(self):
        return [object()] * 12

    def Vertices(self):
        return [object()] * 8


class FakeWorkplane:
    def __init__(self, *_args):
        self.shape = FakeShape()

    def add(self, shape):
        self.shape = shape
        return self

    def box(self, *_args):
        return self

    def cylinder(self, *_args):
        return self

    def sphere(self, *_args):
        return self

    def rect(self, *_args):
        return self

    def circle(self, *_args):
        return self

    def extrude(self, *_args):
        return self

    def edges(self, *_args):
        return self

    def fillet(self, *_args):
        return self

    def chamfer(self, *_args):
        return self

    def val(self):
        return self.shape


class FakeCadQuery:
    __version__ = "test"
    Workplane = FakeWorkplane


class FakeImporters:
    @staticmethod
    def importStep(_path):
        return FakeShape()


class FakeExporters:
    calls = []

    @classmethod
    def export(cls, _shape, path, exportType=None, **_options):
        cls.calls.append((path, exportType))
        Path(path).write_text("exported", encoding="utf-8")


@pytest.mark.asyncio
async def test_health_reports_missing_cadquery_without_raising(monkeypatch, tmp_path: Path):
    real_import_module = importlib.import_module

    def missing_import(name: str):
        if name.startswith("cadquery"):
            raise ModuleNotFoundError(name)
        return real_import_module(name)

    monkeypatch.setattr(importlib, "import_module", missing_import)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None if name == "cadquery" else object())
    backend = HeadlessBackend(Settings(workspace_roots=[tmp_path]))

    result = await backend.health()

    assert result["ok"] is False
    assert result["dependency_status"] == "missing"
    assert "pip install" in result["next_step"]


@pytest.mark.asyncio
async def test_attach_dependency_missing_without_cadquery(
    monkeypatch,
    tmp_path: Path,
):
    real_import_module = importlib.import_module

    def missing_import(name: str):
        if name.startswith("cadquery"):
            raise ModuleNotFoundError(name)
        return real_import_module(name)

    monkeypatch.setattr(importlib, "import_module", missing_import)
    backend = HeadlessBackend(Settings(workspace_roots=[tmp_path]))

    with pytest.raises(McpCadError) as exc_info:
        await backend.attach()

    assert exc_info.value.code is ErrorCode.DEPENDENCY_MISSING
    assert "headless" in exc_info.value.next_step


@pytest.mark.asyncio
async def test_open_document_rejects_path_outside_workspace(tmp_path: Path):
    backend = HeadlessBackend(Settings(workspace_roots=[tmp_path]))
    outside = tmp_path.parent / "outside.step"
    outside.write_text("mock", encoding="utf-8")

    with pytest.raises(McpCadError) as exc_info:
        await backend.open_document(str(outside))

    assert exc_info.value.code is ErrorCode.PATH_NOT_ALLOWED


@pytest.mark.asyncio
async def test_unsupported_custom_property_scope_is_actionable(tmp_path: Path):
    backend = HeadlessBackend(Settings(workspace_roots=[tmp_path]))

    with pytest.raises(McpCadError) as exc_info:
        await backend.get_custom_properties(scope="configuration")

    assert exc_info.value.code is ErrorCode.UNSUPPORTED
    assert "solidworks backend" in exc_info.value.next_step


@pytest.mark.asyncio
async def test_capabilities_mark_solidworks_only_features_unsupported(tmp_path: Path):
    backend = HeadlessBackend(Settings(workspace_roots=[tmp_path]))

    capabilities = await backend.capabilities()

    solidworks_only = capabilities.categories["solidworks_only"]
    assert solidworks_only["feature_tree"].supported is False
    assert solidworks_only["assemblies_mates_drawings_design_tables_routing"].level == "unsupported"


@pytest.mark.asyncio
async def test_open_analyze_and_export_with_mocked_cadquery(monkeypatch, tmp_path: Path):
    real_import_module = importlib.import_module

    def fake_import(name: str):
        if name == "cadquery":
            return FakeCadQuery
        if name == "cadquery.occ_impl.importers":
            return FakeImporters
        if name == "cadquery.occ_impl.exporters":
            return FakeExporters
        return real_import_module(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    source = tmp_path / "part.step"
    source.write_text("mock step", encoding="utf-8")
    target = tmp_path / "part.stl"
    backend = HeadlessBackend(Settings(workspace_roots=[tmp_path]))

    info = await backend.open_document(str(source))
    mass = await backend.mass_properties()
    exported = await backend.export_document(str(target), "stl")

    assert info.document_type == "part"
    assert mass["volume"] == 6000.0
    assert exported["ok"] is True
    assert target.exists()


@pytest.mark.asyncio
async def test_feature_operation_routes_headless_extrude_and_fillet(
    monkeypatch,
    tmp_path: Path,
):
    real_import_module = importlib.import_module

    def fake_import(name: str):
        if name == "cadquery":
            return FakeCadQuery
        if name == "cadquery.occ_impl.importers":
            return FakeImporters
        if name == "cadquery.occ_impl.exporters":
            return FakeExporters
        return real_import_module(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    backend = HeadlessBackend(Settings(workspace_roots=[tmp_path]))

    extruded = await backend.feature_operation(
        "extrude_boss",
        {"profile": {"type": "rectangle", "width": 10, "height": 5}, "distance": 2},
    )
    filleted = await backend.feature_operation("fillet", {"radius": 0.5})

    assert extruded["operation"] == "extrude"
    assert filleted["operation"] == "fillet"


@pytest.mark.asyncio
async def test_headless_grouped_operations_return_actionable_unsupported(tmp_path: Path):
    backend = HeadlessBackend(Settings(workspace_roots=[tmp_path]))

    with pytest.raises(McpCadError) as exc_info:
        await backend.assembly_operation("list_components", {})

    assert exc_info.value.code is ErrorCode.UNSUPPORTED
    assert "solidworks backend" in exc_info.value.next_step


@pytest.mark.asyncio
async def test_import_export_operation_routes_export(monkeypatch, tmp_path: Path):
    real_import_module = importlib.import_module

    def fake_import(name: str):
        if name == "cadquery":
            return FakeCadQuery
        if name == "cadquery.occ_impl.importers":
            return FakeImporters
        if name == "cadquery.occ_impl.exporters":
            return FakeExporters
        return real_import_module(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    backend = HeadlessBackend(Settings(workspace_roots=[tmp_path]))
    await backend.feature_operation(
        "create_sketch",
        {"primitive": "box", "length": 10, "width": 5, "height": 2},
    )
    target = tmp_path / "box.step"

    result = await backend.import_export_operation(
        "export",
        {"path": str(target), "format": "step"},
    )

    assert result["ok"] is True
    assert target.exists()


@pytest.mark.asyncio
async def test_semantic_analysis_returns_headless_dfm_signals(monkeypatch, tmp_path: Path):
    real_import_module = importlib.import_module

    def fake_import(name: str):
        if name == "cadquery":
            return FakeCadQuery
        if name == "cadquery.occ_impl.importers":
            return FakeImporters
        if name == "cadquery.occ_impl.exporters":
            return FakeExporters
        return real_import_module(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    backend = HeadlessBackend(Settings(workspace_roots=[tmp_path]))
    await backend.feature_operation(
        "create_sketch",
        {"primitive": "box", "length": 10, "width": 5, "height": 2},
    )

    result = await backend.semantic_analysis(
        "dfm",
        parameters={"min_wall_thickness": 1.0},
    )

    assert result["ok"] is True
    assert result["analysis"] == "dfm"
    assert result["features"]
    assert result["checks"][0]["rule"] == "minimum_wall_proxy"


@pytest.mark.asyncio
async def test_headless_dimension_layout_score_reports_overlap(monkeypatch, tmp_path: Path):
    backend = HeadlessBackend(Settings(workspace_roots=[tmp_path]))

    with pytest.raises(McpCadError) as exc_info:
        await backend.semantic_analysis("dimension_layout_score", parameters={"dimensions": []})

    assert exc_info.value.code is ErrorCode.NOT_CONNECTED

    backend._document = CadDocument(shape=FakeShape(), workplane=FakeWorkplane())
    result = await backend.semantic_analysis(
        "dimension_layout_score",
        parameters={
            "dimensions": [
                {"id": "D1", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.05},
                {"id": "D2", "x": 0.25, "y": 0.1, "width": 0.2, "height": 0.05},
            ]
        },
    )

    assert result["score"] == 80
    assert result["issues"][0]["items"] == ["D1", "D2"]


@pytest.mark.asyncio
async def test_headless_routing_is_actionable_unsupported(tmp_path: Path):
    backend = HeadlessBackend(Settings(workspace_roots=[tmp_path]))

    with pytest.raises(McpCadError) as exc_info:
        await backend.routing_operation("create_route", {})

    assert exc_info.value.code is ErrorCode.UNSUPPORTED
    assert "Routing" in exc_info.value.next_step
