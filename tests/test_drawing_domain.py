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


class FakeSheet:
    def __init__(self):
        self.notes = [FakeNote("TITLE", "Old"), FakeNote("DRAWN_BY", "AI")]

    def GetName(self):
        return "Sheet1"

    def GetTemplateName(self):
        return "A3.slddrt"

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

    def AddDimension2(self, x, y, z):
        self.dimension_position = (x, y, z)
        return FakeDimension()

    def InsertNote(self, text):
        note = FakeNote("Note1", text)
        self.notes.append(note)
        return note

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


def test_add_note_positions_annotation_when_coordinates_supplied():
    app = FakeSolidWorksApp()
    service = SolidWorksDrawingService(app)

    result = service.add_note("CHECK FIT", x=0.1, y=0.2)

    assert result["ok"] is True
    note = app.active_doc.notes[0]
    assert note.text == "CHECK FIT"
    assert note.position == (0.1, 0.2, 0.0)


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

