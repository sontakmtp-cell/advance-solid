from __future__ import annotations

from solidworks_mcp.domain.drawing import SolidWorksDrawingService, SwDocumentType


class FakeView:
    def __init__(self, name="Drawing View1", referenced="C:/work/part.sldprt"):
        self.name = name
        self.referenced = referenced

    def GetName2(self):
        return self.name

    def GetReferencedModelName(self):
        return self.referenced


class FakeDimension:
    def GetNameForSelection(self):
        return "D1@Drawing View1"

    def GetSystemValue(self):
        return 0.025


class FakeNote:
    def __init__(self, name="TITLE", text=""):
        self.name = name
        self.text = text
        self.position = None

    def GetName(self):
        return self.name

    def GetText(self):
        return self.text

    def SetText(self, text):
        self.text = text
        return True

    def GetAnnotation(self):
        return self

    def SetPosition(self, x, y, z):
        self.position = (x, y, z)
        return True


class FakeAnnotation(FakeNote):
    def __init__(self, name="Annotation1", text="", annotation_type="note"):
        super().__init__(name, text)
        self.annotation_type = annotation_type

    def GetType(self):
        return self.annotation_type


class FakeSheet:
    def __init__(self):
        self.notes = [FakeNote("TITLE", "Old"), FakeNote("DRAWN_BY", "AI")]
        self.template = "A3.slddrt"

    def GetName(self):
        return "Sheet1"

    def GetTemplateName(self):
        return self.template

    def SetTemplateName(self, template):
        self.template = template
        return True

    def GetTemplateNotes(self):
        return self.notes


class FakeBomTable:
    def __init__(self):
        self.updated = False

    def Title(self):
        return "BOM"

    def RowCount(self):
        return 3

    def ColumnCount(self):
        return 4

    def Update(self, *_args):
        self.updated = True
        return True


class FakeDrawingDoc:
    def __init__(self):
        self.views = []
        self.notes = []
        self.sheet = FakeSheet()
        self.sheets = ["Sheet1"]
        self.bom = None
        self.active_sheet = "Sheet1"
        self.annotations = []
        self.deleted_sheets = []

    def GetType(self):
        return int(SwDocumentType.DRAWING)

    def GetTitle(self):
        return "Drawing1"

    def GetPathName(self):
        return "C:/work/drawing.slddrw"

    def CreateDrawViewFromModelView3(self, model_path, view_name, x, y, z):
        view = FakeView(view_name, model_path)
        self.views.append((view, x, y, z))
        return view

    def CreateProjectedViewAt3(self, x, y, direction):
        view = FakeView(f"Projected{direction}")
        self.views.append((view, x, y, direction))
        return view

    def CreateSectionViewAt5(self, x, y, label):
        view = FakeView(f"Section {label}")
        self.views.append((view, x, y, label))
        return view

    def CreateDetailViewAt3(self, x, y, radius, label, *args):
        view = FakeView(f"Detail {label}")
        self.views.append((view, x, y, radius, label, args))
        return view

    def CreateAuxiliaryViewAt3(self, x, y, label):
        view = FakeView(f"Auxiliary {label}")
        self.views.append((view, x, y, label))
        return view

    def AddDimension2(self, x, y, z):
        self.dimension_position = (x, y, z)
        return FakeDimension()

    def AddOrdinateDimension2(self, type_id, x, y, z):
        self.dimension_position = (type_id, x, y, z)
        return FakeDimension()

    def InsertChamferDimension2(self, x, y, z):
        self.dimension_position = (x, y, z)
        return FakeDimension()

    def InsertHoleCallout2(self, x, y, z):
        self.dimension_position = (x, y, z)
        return FakeDimension()

    def InsertNote(self, text):
        note = FakeNote("Note1", text)
        self.notes.append(note)
        return note

    def InsertBomBalloon2(self, style, size):
        balloon = FakeAnnotation("Balloon1", f"{style}:{size}", "balloon")
        self.annotations.append(balloon)
        return balloon

    def InsertSurfaceFinishSymbol3(self, symbol):
        annotation = FakeAnnotation("SurfaceFinish1", symbol, "surface_finish")
        self.annotations.append(annotation)
        return annotation

    def InsertWeldSymbol3(self, symbol):
        annotation = FakeAnnotation("Weld1", symbol, "weld")
        self.annotations.append(annotation)
        return annotation

    def InsertGTol(self, frame_text):
        annotation = FakeAnnotation("GTol1", frame_text, "gdt")
        self.annotations.append(annotation)
        return annotation

    def InsertDatumTag2(self, label):
        annotation = FakeAnnotation("Datum1", label, "datum")
        self.annotations.append(annotation)
        return annotation

    def InsertBomTable4(self, *_args):
        self.bom = FakeBomTable()
        return self.bom

    def GetCurrentSheet(self):
        return self.sheet

    def GetSheetNames(self):
        return tuple(self.sheets)

    def NewSheet4(self, name, *_args):
        self.sheets.append(name)
        return True

    def ActivateSheet(self, name):
        if name not in self.sheets:
            return False
        self.active_sheet = name
        return True

    def DeleteSheet(self, name):
        if name not in self.sheets:
            return False
        self.sheets.remove(name)
        self.deleted_sheets.append(name)
        return True


class FakeSolidWorksApp:
    def __init__(self):
        self.active_doc = FakeDrawingDoc()
        self.created_docs = []

    def ActiveDoc(self):
        return self.active_doc

    def GetUserPreferenceStringValue(self, _preference):
        return "C:/templates/default.drwdot"

    def NewDocument(self, template, *_args):
        drawing = FakeDrawingDoc()
        drawing.template = template
        self.active_doc = drawing
        self.created_docs.append(drawing)
        return drawing


def test_create_drawing_from_model_inserts_initial_view():
    app = FakeSolidWorksApp()
    service = SolidWorksDrawingService(app)

    result = service.create_drawing_from_model("C:/work/bracket.sldprt", model_view="*Isometric")

    assert result["ok"] is True
    assert result["event"] == "drawing_created"
    assert result["data"]["view"]["name"] == "*Isometric"
    assert result["data"]["model_path"] == "C:/work/bracket.sldprt"


def test_insert_projected_view_uses_direction_mapping():
    app = FakeSolidWorksApp()
    service = SolidWorksDrawingService(app)

    result = service.insert_projected_view(x=0.3, y=0.4, direction="right")

    assert result["ok"] is True
    assert result["event"] == "projected_view_inserted"
    assert result["data"]["direction"] == "right"
    assert result["data"]["view"]["name"] == "Projected2"


def test_drawing_operation_routes_all_view_subtypes():
    app = FakeSolidWorksApp()
    service = SolidWorksDrawingService(app)

    model = service.drawing_operation(
        "insert_view",
        {"view_type": "model", "model_path": "C:/work/part.sldprt", "view_name": "*Top"},
    )
    section = service.drawing_operation(
        "insert_view",
        {"view_type": "section", "x": 0.4, "y": 0.5, "label": "B"},
    )
    detail = service.drawing_operation(
        "insert_view",
        {"view_type": "detail", "x": 0.6, "y": 0.7, "label": "C", "radius": 0.03, "scale": 2.0},
    )
    auxiliary = service.drawing_operation(
        "insert_view",
        {"view_type": "auxiliary", "x": 0.8, "y": 0.9, "label": "D"},
    )

    assert model["data"]["view"]["name"] == "*Top"
    assert section["event"] == "section_view_inserted"
    assert detail["data"]["scale"] == 2.0
    assert auxiliary["data"]["view"]["name"] == "Auxiliary D"


def test_drawing_operation_routes_dimension_subtypes():
    app = FakeSolidWorksApp()
    service = SolidWorksDrawingService(app)

    smart = service.drawing_operation(
        "add_dimension",
        {"dimension_type": "smart", "x": 0.1, "y": 0.2},
    )
    ordinate = service.drawing_operation(
        "add_dimension",
        {"dimension_type": "ordinate", "ordinate_type": "vertical", "x": 0.3, "y": 0.4},
    )
    chamfer = service.drawing_operation(
        "add_dimension",
        {"dimension_type": "chamfer", "x": 0.5, "y": 0.6},
    )
    hole = service.drawing_operation(
        "add_dimension",
        {"dimension_type": "hole_callout", "x": 0.7, "y": 0.8},
    )

    assert smart["event"] == "smart_dimension_added"
    assert ordinate["event"] == "ordinate_dimension_added"
    assert chamfer["event"] == "chamfer_dimension_added"
    assert hole["event"] == "hole_callout_added"


def test_drawing_operation_routes_insert_bom():
    app = FakeSolidWorksApp()
    service = SolidWorksDrawingService(app)

    result = service.drawing_operation(
        "insert_bom",
        {"table_template": "C:/templates/bom.sldbomtbt", "x": 0.05, "y": 0.06},
    )

    assert result["ok"] is True
    assert result["event"] == "bom_inserted"
    assert result["data"]["bom"]["title"] == "BOM"
    assert result["data"]["table_template"] == "C:/templates/bom.sldbomtbt"


def test_add_note_positions_annotation_when_coordinates_supplied():
    app = FakeSolidWorksApp()
    service = SolidWorksDrawingService(app)

    result = service.add_note("CHECK FIT", x=0.1, y=0.2)

    assert result["ok"] is True
    note = app.active_doc.notes[0]
    assert note.text == "CHECK FIT"
    assert note.position == (0.1, 0.2, 0.0)


def test_drawing_operation_routes_annotation_subtypes():
    app = FakeSolidWorksApp()
    service = SolidWorksDrawingService(app)

    note = service.drawing_operation(
        "add_annotation",
        {"annotation_type": "note", "text": "CHECK FIT", "x": 0.1, "y": 0.2},
    )
    balloon = service.drawing_operation(
        "add_annotation",
        {"annotation_type": "balloon", "style": 2, "size": 3},
    )
    surface = service.drawing_operation(
        "add_annotation",
        {"annotation_type": "surface_finish", "symbol": "Ra 3.2"},
    )
    weld = service.drawing_operation(
        "add_annotation",
        {"annotation_type": "weld", "symbol": "fillet"},
    )
    gdt = service.drawing_operation(
        "add_annotation",
        {"annotation_type": "gdt", "frame_text": "|POSITION|0.1|A|"},
    )
    datum = service.drawing_operation("add_annotation", {"annotation_type": "datum", "label": "A"})

    assert note["event"] == "note_added"
    assert balloon["data"]["annotation"]["type"] == "balloon"
    assert surface["event"] == "surface_finish_added"
    assert weld["event"] == "weld_symbol_added"
    assert gdt["event"] == "gdt_added"
    assert datum["event"] == "datum_added"


def test_title_block_read_and_write_by_note_name():
    app = FakeSolidWorksApp()
    service = SolidWorksDrawingService(app)

    read_result = service.read_title_block()
    write_result = service.write_title_block({"TITLE": "Bracket", "MISSING": "ignored"})

    assert read_result["ok"] is True
    assert read_result["data"]["fields"]["TITLE"] == "Old"
    assert write_result["ok"] is True
    assert write_result["data"]["updated"] == ["TITLE"]
    assert write_result["data"]["missing"] == ["MISSING"]
    assert app.active_doc.sheet.notes[0].text == "Bracket"


def test_drawing_operation_routes_title_block_and_sheet_management():
    app = FakeSolidWorksApp()
    service = SolidWorksDrawingService(app)

    write = service.drawing_operation(
        "title_block",
        {"action": "write", "fields": {"TITLE": "Bracket"}},
    )
    sheet_add = service.drawing_operation("sheet_management", {"action": "add", "name": "Sheet2"})
    sheet_list = service.drawing_operation("sheet_management", {"action": "list"})
    sheet_activate = service.drawing_operation(
        "sheet_management",
        {"action": "activate", "name": "Sheet2"},
    )
    sheet_format = service.drawing_operation(
        "sheet_management",
        {"action": "set_format", "template_path": "B4.slddrt"},
    )
    sheet_delete = service.drawing_operation(
        "sheet_management",
        {"action": "delete", "name": "Sheet2"},
    )

    assert write["ok"] is True
    assert sheet_add["event"] == "sheet_added"
    assert sheet_list["data"]["sheets"] == ["Sheet1", "Sheet2"]
    assert sheet_activate["event"] == "sheet_activated"
    assert sheet_format["data"]["template_path"] == "B4.slddrt"
    assert sheet_delete["event"] == "sheet_deleted"


def test_drawing_operation_validates_layout_boxes():
    app = FakeSolidWorksApp()
    service = SolidWorksDrawingService(app)

    result = service.drawing_operation(
        "validate_layout",
        {
            "sheet": {"width": 1.0, "height": 0.7},
            "dimensions": [
                {"id": "D1", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.05},
                {"id": "D2", "x": 0.25, "y": 0.1, "width": 0.2, "height": 0.05},
                {"id": "D3", "x": 0.9, "y": 0.65, "width": 0.2, "height": 0.1},
            ],
        },
    )

    assert result["ok"] is True
    assert result["event"] == "layout_validated"
    assert result["data"]["score"] == 70
    assert [issue["code"] for issue in result["data"]["issues"]] == [
        "outside_sheet",
        "dimension_overlap",
    ]


def test_drawing_operation_returns_actionable_error_for_unknown_subtype():
    app = FakeSolidWorksApp()
    service = SolidWorksDrawingService(app)

    result = service.drawing_operation("insert_view", {"view_type": "broken_out"})

    assert result["ok"] is False
    assert result["error"]["code"] == "unsupported"
    assert "view_type" in result["error"]["next_step"]


def test_non_drawing_document_returns_actionable_error():
    class PartDoc:
        def GetType(self):
            return int(SwDocumentType.PART)

    app = FakeSolidWorksApp()
    app.active_doc = PartDoc()
    service = SolidWorksDrawingService(app)

    result = service.insert_model_view("C:/work/part.sldprt")

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_input"
    assert "drawing" in result["error"]["next_step"]
