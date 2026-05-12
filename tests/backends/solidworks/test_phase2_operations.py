from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from solidworks_mcp.backends.solidworks.backend import SolidWorksBackend
from solidworks_mcp.config import Settings
from solidworks_mcp.core.errors import ErrorCode, McpCadError


class FakeDispatcher:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.operations: list[str] = []

    def call(self, operation: str, func: Any, **_kwargs: Any) -> Any:
        self.operations.append(operation)
        return func(self.app)


class FakeFeature:
    def __init__(self, name: str, next_feature: "FakeFeature | None" = None) -> None:
        self.Name = name
        self.next_feature = next_feature
        self.suppression_state: int | None = None

    def GetTypeName2(self) -> str:
        return "Extrusion"

    def IsSuppressed(self) -> bool:
        return self.suppression_state == 0

    def GetNextFeature(self) -> "FakeFeature | None":
        return self.next_feature

    def SetSuppression2(self, state: int, *_args: Any) -> bool:
        self.suppression_state = state
        return True


class FakeComponent:
    def __init__(self, name: str) -> None:
        self.Name2 = name
        self.Visible = 1
        self.suppression_state: int | None = None

    def GetPathName(self) -> str:
        return rf"H:\workspace\{self.Name2}.SLDPRT"

    def IsSuppressed(self) -> bool:
        return self.suppression_state == 0

    def ReferencedConfiguration(self) -> str:
        return "Default"

    def SetSuppression2(self, state: int) -> bool:
        self.suppression_state = state
        return True


class FakeDocument:
    def __init__(self) -> None:
        self.feature2 = FakeFeature("Cut-Extrude1")
        self.feature1 = FakeFeature("Boss-Extrude1", self.feature2)
        self.components = [FakeComponent("Bracket-1"), FakeComponent("Pin-1")]
        self.inserted: list[tuple[str, float, float, float]] = []

    def FirstFeature(self) -> FakeFeature:
        return self.feature1

    def FeatureByName(self, name: str) -> FakeFeature | None:
        for feature in (self.feature1, self.feature2):
            if feature.Name == name:
                return feature
        return None

    def GetComponents(self, _top_level_only: bool) -> list[FakeComponent]:
        return self.components

    def GetComponentByName(self, name: str) -> FakeComponent | None:
        for component in self.components:
            if component.Name2 == name:
                return component
        return None

    def AddComponent5(self, path: str, *_args: Any) -> FakeComponent:
        x, y, z = _args[-3:]
        self.inserted.append((path, x, y, z))
        component = FakeComponent(Path(path).stem + "-1")
        self.components.append(component)
        return component


class FakeDrawingNote:
    def __init__(self, text: str) -> None:
        self.text = text
        self.position: tuple[float, float, float] | None = None

    def GetName(self) -> str:
        return "Note1"

    def GetType(self) -> str:
        return "note"

    def GetAnnotation(self) -> "FakeDrawingNote":
        return self

    def SetPosition(self, x: float, y: float, z: float) -> bool:
        self.position = (x, y, z)
        return True


class FakeDrawingDocument:
    def __init__(self) -> None:
        self.notes: list[FakeDrawingNote] = []

    def GetType(self) -> int:
        return 3

    def InsertNote(self, text: str) -> FakeDrawingNote:
        note = FakeDrawingNote(text)
        self.notes.append(note)
        return note


class FakeSolidWorks:
    def __init__(self, doc: Any) -> None:
        self.ActiveDoc = doc


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def backend(workspace: Path) -> SolidWorksBackend:
    doc = FakeDocument()
    backend = SolidWorksBackend(
        Settings(
            workspace_roots=[workspace],
            com_timeout_seconds=0.2,
            com_hard_timeout_seconds=1.0,
        )
    )
    backend.dispatcher = FakeDispatcher(FakeSolidWorks(doc))  # type: ignore[assignment]
    return backend


@pytest.mark.asyncio
async def test_feature_list_tree_maps_to_dispatcher(backend: SolidWorksBackend) -> None:
    result = await backend.feature_operation("list_tree", {"limit": 10})

    assert result["ok"] is True
    assert [feature["name"] for feature in result["features"]] == [
        "Boss-Extrude1",
        "Cut-Extrude1",
    ]


@pytest.mark.asyncio
async def test_feature_suppress_and_unsuppress_by_name(backend: SolidWorksBackend) -> None:
    suppressed = await backend.feature_operation("suppress", {"name": "Boss-Extrude1"})
    unsuppressed = await backend.feature_operation("unsuppress", {"name": "Boss-Extrude1"})

    assert suppressed["ok"] is True
    assert unsuppressed["ok"] is True
    assert suppressed["feature"] == "Boss-Extrude1"


@pytest.mark.asyncio
async def test_assembly_list_components(backend: SolidWorksBackend) -> None:
    result = await backend.assembly_operation("list_components")

    assert result["ok"] is True
    assert [component["name"] for component in result["components"]] == [
        "Bracket-1",
        "Pin-1",
    ]


@pytest.mark.asyncio
async def test_insert_component_validates_path(
    backend: SolidWorksBackend,
    workspace: Path,
) -> None:
    component_path = workspace / "Part1.SLDPRT"
    component_path.write_text("fake", encoding="utf-8")

    result = await backend.assembly_operation(
        "insert_component",
        {"path": str(component_path), "x": 1, "y": 2, "z": 3},
    )

    assert result["ok"] is True
    assert result["component"]["name"] == "Part1-1"


@pytest.mark.asyncio
async def test_insert_component_rejects_path_outside_workspace(
    backend: SolidWorksBackend,
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "outside.SLDPRT"
    outside.write_text("fake", encoding="utf-8")

    with pytest.raises(McpCadError) as error:
        await backend.assembly_operation("insert_component", {"path": str(outside)})

    assert error.value.code == ErrorCode.PATH_NOT_ALLOWED


@pytest.mark.asyncio
async def test_drawing_operation_routes_to_domain_service(workspace: Path) -> None:
    drawing = FakeDrawingDocument()
    backend = SolidWorksBackend(
        Settings(
            workspace_roots=[workspace],
            com_timeout_seconds=0.2,
            com_hard_timeout_seconds=1.0,
        )
    )
    backend.dispatcher = FakeDispatcher(FakeSolidWorks(drawing))  # type: ignore[assignment]

    result = await backend.drawing_operation(
        "add_annotation",
        {"annotation_type": "note", "text": "CHECK FIT", "x": 0.1, "y": 0.2},
    )

    assert result["ok"] is True
    assert result["event"] == "note_added"
    assert drawing.notes[0].text == "CHECK FIT"
    assert drawing.notes[0].position == (0.1, 0.2, 0.0)


@pytest.mark.asyncio
async def test_drawing_operation_validates_model_path(
    backend: SolidWorksBackend,
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "outside.SLDPRT"
    outside.write_text("fake", encoding="utf-8")

    with pytest.raises(McpCadError) as error:
        await backend.drawing_operation("insert_view", {"model_path": str(outside)})

    assert error.value.code == ErrorCode.PATH_NOT_ALLOWED
