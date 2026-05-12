from __future__ import annotations

from solidworks_mcp.backends.solidworks import backend as backend_module


class CallableComObject:
    def __call__(self):
        raise RuntimeError("COM property dispatch object was called as a method")


class FakeConfiguration(CallableComObject):
    Name = "Default"


class FakeFeature(CallableComObject):
    Name = "Boss-Extrude1"

    def GetTypeName2(self) -> str:
        return "Extrusion"

    def IsSuppressed(self) -> bool:
        return False

    def GetNextFeature(self):
        return None


class FakeExtension(CallableComObject):
    pass


class FakeDocument(CallableComObject):
    Extension = FakeExtension()

    def GetTitle(self) -> str:
        return "RealPart.SLDPRT"

    def GetPathName(self) -> str:
        return r"H:\CAD-Work\RealPart.SLDPRT"

    def GetType(self) -> int:
        return 1

    def GetConfigurationNames(self):
        return ["Default"]

    def GetActiveConfiguration(self):
        return FakeConfiguration()

    def GetMaterialPropertyName2(self, _configuration: str, _database: str):
        return "Plain Carbon Steel"

    def GetSaveFlag(self) -> bool:
        return False

    def FirstFeature(self):
        return FakeFeature()


class FakeSolidWorksApp:
    ActiveDoc = FakeDocument()


def test_active_doc_reads_com_property_without_calling_dispatch_object() -> None:
    doc = backend_module._active_doc(FakeSolidWorksApp())

    assert doc.GetTitle() == "RealPart.SLDPRT"


def test_document_info_uses_com_properties_for_extension_name_and_features() -> None:
    payload = backend_module._document_info_from_model(FakeDocument())

    assert payload["title"] == "RealPart.SLDPRT"
    assert payload["active_configuration"] == "Default"
    assert payload["metadata"]["feature_count_estimate"] == 1
