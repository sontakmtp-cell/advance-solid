from __future__ import annotations

import pytest

from solidworks_mcp.core.errors import ErrorCode, McpCadError
from solidworks_mcp.helpers.properties import get_custom_properties, set_custom_properties


class FakeCustomPropertyManager:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.deleted = []

    def GetNames(self):
        return list(self.values)

    def Get6(self, name, use_cached):
        value = self.values.get(name)
        return 1, value, value.upper() if isinstance(value, str) else value, True, False

    def Set2(self, name, value):
        self.values[name] = value
        return 1

    def Delete2(self, name):
        self.deleted.append(name)
        self.values.pop(name, None)
        return 1


class FakeExtension:
    def __init__(self):
        self.managers = {
            "": FakeCustomPropertyManager({"PartNo": "P-100", "Description": "Bracket"}),
            "Default": FakeCustomPropertyManager({"Finish": "Black"}),
        }

    def CustomPropertyManager(self, configuration):
        return self.managers[configuration]


class FakeModel:
    def __init__(self):
        self.Extension = FakeExtension()


class FakeCutListFeature:
    Name = "Cut-List-Item1"

    def __init__(self):
        self.manager = FakeCustomPropertyManager({"Length": "120"})

    def GetTypeName2(self):
        return "CutListFolder"

    def GetSpecificFeature2(self):
        return self

    def CustomPropertyManager(self):
        return self.manager

    def GetNextFeature(self):
        return None


class FakeCutListModel(FakeModel):
    def __init__(self):
        super().__init__()
        self.feature = FakeCutListFeature()

    def FirstFeature(self):
        return self.feature


def test_get_file_custom_properties_reads_resolved_values():
    result = get_custom_properties(FakeModel())

    assert result["ok"] is True
    assert result["count"] == 2
    assert result["properties"]["PartNo"]["resolved_value"] == "P-100"


def test_set_configuration_properties_replaces_omitted_names():
    model = FakeModel()
    result = set_custom_properties(
        model,
        {"Finish": "Zinc"},
        scope="configuration",
        configuration="Default",
        replace=True,
    )

    assert result["ok"] is True
    assert result["written"] == ["Finish"]
    assert model.Extension.managers["Default"].values["Finish"] == "Zinc"


def test_cut_list_properties_use_feature_property_manager():
    result = get_custom_properties(FakeCutListModel(), scope="cut_list", cut_list_id="Cut-List-Item1")

    assert result["ok"] is True
    assert result["properties"]["Length"]["value"] == "120"


def test_configuration_scope_requires_configuration_name():
    with pytest.raises(McpCadError) as exc:
        get_custom_properties(FakeModel(), scope="configuration")

    assert exc.value.code == ErrorCode.INVALID_INPUT
