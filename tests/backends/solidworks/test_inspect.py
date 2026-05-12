from __future__ import annotations

import json

from solidworks_mcp.backends.solidworks.inspect import inspect_active_or_document


class CallableComObject:
    def __call__(self):
        raise RuntimeError("COM dispatch object should not be called")


class FakeConfiguration(CallableComObject):
    Name = "Default"


class FakeSubFeature(CallableComObject):
    Name = "Sketch1"

    def GetTypeName2(self) -> str:
        return "ProfileFeature"

    def GetNextSubFeature(self):
        return None


class FakeFeature(CallableComObject):
    Name = "Boss-Extrude1"

    def GetTypeName2(self) -> str:
        return "Extrusion"

    def IsSuppressed(self) -> bool:
        return False

    def GetFirstSubFeature(self):
        return FakeSubFeature()

    def GetNextFeature(self):
        return None


class FakeBody(CallableComObject):
    Name = "Body-1"

    def GetFaces(self):
        return [object(), object(), object()]

    def GetEdges(self):
        return [object(), object(), object(), object()]


class FakeMassProperty(CallableComObject):
    Mass = 2.5
    Volume = 0.001
    SurfaceArea = 0.25
    CenterOfMass = (0.1, 0.2, 0.3)
    Density = 7850

    def GetMomentOfInertia(self):
        return (1.0, 2.0, 3.0)


class FakeCustomPropertyManager(CallableComObject):
    def GetNames(self):
        return ["PartNo", "Description"]

    def Get5(self, name, _use_cached, _value, _resolved, _was_resolved):
        return (0, f"{name}-raw", f"{name}-resolved", True)


class FakeExtension(CallableComObject):
    def CustomPropertyManager(self, configuration: str):
        assert configuration == ""
        return FakeCustomPropertyManager()

    def CreateMassProperty(self):
        return FakeMassProperty()


class FakeDocument(CallableComObject):
    Extension = FakeExtension()

    def GetTitle(self) -> str:
        return "Bracket.SLDPRT"

    def GetPathName(self) -> str:
        return r"H:\CAD-Work\Bracket.SLDPRT"

    def GetType(self) -> int:
        return 1

    def GetConfigurationNames(self):
        return ("Default", "Machined")

    def GetActiveConfiguration(self):
        return FakeConfiguration()

    def FirstFeature(self):
        return FakeFeature()

    def GetBodies2(self, body_type: int, visible_only: bool):
        assert body_type == 0
        assert visible_only is False
        return [FakeBody()]

    def GetMaterialPropertyName2(self, configuration: str, database: str):
        assert configuration == "Default"
        assert database == ""
        return "Plain Carbon Steel"

    def GetUserPreferenceIntegerValue(self, preference: int):
        assert preference == 0
        return 2

    def GetPartBox(self):
        return (-1, -2, -3, 4, 5, 6)


class FakeSolidWorksApp(CallableComObject):
    ActiveDoc = FakeDocument()


def test_inspect_accepts_solidworks_app_and_returns_json_safe_payload() -> None:
    payload = inspect_active_or_document(FakeSolidWorksApp())

    assert payload["title"] == "Bracket.SLDPRT"
    assert payload["document_type"] == "part"
    assert payload["type_name"] == "Part"
    assert payload["configurations"] == ["Default", "Machined"]
    assert payload["active_configuration"] == "Default"
    assert payload["custom_properties_file"]["PartNo"]["resolved_value"] == "PartNo-resolved"
    assert payload["features"][0]["subfeatures"][0]["name"] == "Sketch1"
    assert payload["solid_bodies"][0]["face_count"] == 3
    assert payload["mass_properties"]["mass_kg"] == 2.5
    assert payload["material"] == "Plain Carbon Steel"
    assert payload["unit_system"] == {"raw": 2, "name": "MMGS (mm, g, s)"}
    assert payload["bounding_box"]["size"] == [5.0, 7.0, 9.0]

    json.dumps(payload)


def test_inspect_accepts_document_directly_and_applies_feature_limit() -> None:
    payload = inspect_active_or_document(FakeDocument(), feature_limit=0)

    assert payload["title"] == "Bracket.SLDPRT"
    assert payload["features"] == []
    assert payload["feature_count"] == 0
