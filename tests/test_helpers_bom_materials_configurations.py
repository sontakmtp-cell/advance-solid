from __future__ import annotations

import pytest

from solidworks_mcp.core.errors import ErrorCode, McpCadError
from solidworks_mcp.helpers.bom import mass_properties, read_bom
from solidworks_mcp.helpers.configurations import (
    activate_configuration,
    create_configuration,
    delete_configuration,
    list_configurations,
    manage_configuration,
    rename_configuration,
)
from solidworks_mcp.helpers.materials import get_material_info, material_info, set_material
from solidworks_mcp.helpers.properties import SW_CUSTOM_INFO_TEXT, SW_CUSTOM_PROPERTY_REPLACE_VALUE


class FakePropertyManager:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def GetNames(self):
        return list(self.values)

    def Get6(self, name, use_cached):
        value = self.values.get(name)
        return 1, value, value, True, False

    def Add3(self, name, property_type, value, option):
        assert property_type == SW_CUSTOM_INFO_TEXT
        assert option == SW_CUSTOM_PROPERTY_REPLACE_VALUE
        self.values[name] = value
        return 1


class FakeExtension:
    def __init__(self, props=None, mass=None):
        self.manager = FakePropertyManager(props)
        self.mass = mass

    def CustomPropertyManager(self, configuration):
        return self.manager

    def CreateMassProperty(self):
        return self.mass


class FakeMass:
    Mass = 2.5
    Volume = 10.0
    SurfaceArea = 12.0
    CenterOfMass = [1.0, 2.0, 3.0]
    MomentOfInertia = [1, 0, 0, 1, 0, 1]


class FakePart:
    def __init__(self, path, title, props=None):
        self.path = path
        self.title = title
        self.Extension = FakeExtension(props, FakeMass())
        self.material = "Plain Carbon Steel"

    def GetPathName(self):
        return self.path

    def GetTitle(self):
        return self.title

    def GetMaterialPropertyName2(self, configuration, database):
        return self.material

    def SetMaterialPropertyName2(self, configuration, database, material):
        self.material = material
        return 1


class FakeComponent:
    def __init__(self, name, model=None, children=None, configuration="Default", suppressed=False):
        self.Name2 = name
        self.model = model
        self.children = children or []
        self.ReferencedConfiguration = configuration
        self.suppressed = suppressed

    def GetChildren(self):
        return self.children

    def GetModelDoc2(self):
        return self.model

    def GetSuppression(self):
        return self.suppressed


class FakeConfiguration:
    def __init__(self, name, root=None):
        self.Name = name
        self.root = root

    def GetRootComponent3(self, include_hidden):
        return self.root


class FakeConfigurationManager:
    def __init__(self, root=None):
        self.configs = {"Default": FakeConfiguration("Default", root)}
        self.ActiveConfiguration = self.configs["Default"]

    def AddConfiguration3(self, name, comment, alternate_name, options):
        self.configs[name] = FakeConfiguration(name)
        return self.configs[name]

    def GetConfigurationByName(self, name):
        return self.configs.get(name)


class FakeAssembly:
    def __init__(self, root=None):
        self.ConfigurationManager = FakeConfigurationManager(root)
        self.deleted = []
        self.active = "Default"

    def GetConfigurationNames(self):
        return list(self.ConfigurationManager.configs)

    def DeleteConfiguration2(self, name):
        self.deleted.append(name)
        self.ConfigurationManager.configs.pop(name, None)
        return True

    def ShowConfiguration2(self, name):
        self.active = name
        self.ConfigurationManager.ActiveConfiguration = self.ConfigurationManager.configs[name]
        return True


def test_read_bom_groups_components_by_path_and_configuration():
    part = FakePart("C:/work/bracket.sldprt", "bracket", {"PartNo": "BR-1"})
    root = FakeComponent("root", children=[FakeComponent("bracket-1", part), FakeComponent("bracket-2", part)])
    assembly = FakeAssembly(root)

    result = read_bom(assembly)

    assert result["ok"] is True
    assert result["row_count"] == 1
    assert result["rows"][0]["quantity"] == 2
    assert result["rows"][0]["properties"]["PartNo"]["value"] == "BR-1"


def test_mass_properties_reads_extension_mass_object():
    part = FakePart("C:/work/bracket.sldprt", "bracket")

    result = mass_properties(part)

    assert result["mass"] == 2.5
    assert result["center_of_mass"] == [1.0, 2.0, 3.0]


def test_material_info_get_and_set():
    part = FakePart("C:/work/bracket.sldprt", "bracket")

    assert get_material_info(part)["material"] == "Plain Carbon Steel"
    set_result = set_material(part, "AISI 304")
    assert set_result["ok"] is True
    assert material_info(part)["material"] == "AISI 304"


def test_configuration_lifecycle_helpers():
    assembly = FakeAssembly()

    create_configuration(assembly, "As Machined")
    assert "As Machined" in list_configurations(assembly)["configurations"]
    activate_configuration(assembly, "As Machined")
    assert assembly.active == "As Machined"
    rename_configuration(assembly, "As Machined", "As Welded")
    assert assembly.ConfigurationManager.configs["As Machined"].Name == "As Welded"
    delete_configuration(assembly, "As Machined")
    assert assembly.deleted == ["As Machined"]


def test_manage_configuration_rejects_unknown_action():
    with pytest.raises(McpCadError) as exc:
        manage_configuration(FakeAssembly(), "duplicate")

    assert exc.value.code == ErrorCode.INVALID_INPUT
