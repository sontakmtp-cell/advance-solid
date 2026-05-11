"""SolidWorks drawing and annotation service helpers.

This module is intentionally thin around the SolidWorks COM API. The owning
backend supplies an already-attached SolidWorks application/document object; the
service performs defensive COM calls, marshals COM-ish objects into concise
dicts, and returns actionable error payloads instead of leaking COM exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any, Iterable

from solidworks_mcp.core.errors import ErrorCode, McpCadError, error_response


class SwDocumentType(IntEnum):
    PART = 1
    ASSEMBLY = 2
    DRAWING = 3


class SwProjectedViewDirection(IntEnum):
    LEFT = 1
    RIGHT = 2
    TOP = 3
    BOTTOM = 4
    ISOMETRIC = 7


PROJECTED_DIRECTIONS: dict[str, SwProjectedViewDirection] = {
    "left": SwProjectedViewDirection.LEFT,
    "right": SwProjectedViewDirection.RIGHT,
    "top": SwProjectedViewDirection.TOP,
    "bottom": SwProjectedViewDirection.BOTTOM,
    "isometric": SwProjectedViewDirection.ISOMETRIC,
}


@dataclass(frozen=True)
class DrawingServiceOptions:
    backend_name: str = "solidworks"
    default_template: str | None = None


class SolidWorksDrawingService:
    """High-level drawing operations for a SolidWorks COM backend."""

    def __init__(self, sw_app: Any, options: DrawingServiceOptions | None = None) -> None:
        self.sw_app = sw_app
        self.options = options or DrawingServiceOptions()

    def create_drawing_from_model(
        self,
        model_path: str,
        *,
        template_path: str | None = None,
        model_view: str = "*Front",
        x: float = 0.25,
        y: float = 0.25,
    ) -> dict[str, Any]:
        """Create a drawing document and insert the first model view."""

        def operation() -> dict[str, Any]:
            template = template_path or self.options.default_template or self._default_drawing_template()
            if not template:
                raise self._failure(
                    ErrorCode.INVALID_INPUT,
                    "No drawing template was supplied and SolidWorks did not return a default template.",
                    "Pass template_path or configure a default drawing template in SolidWorks.",
                    {"model_path": model_path},
                )

            drawing = self._call_any(self.sw_app, ("NewDocument",), template, 0, 0.0, 0.0)
            if drawing is None:
                raise self._failure(
                    ErrorCode.OPERATION_FAILED,
                    "SolidWorks did not create a drawing document.",
                    "Verify the drawing template path, then retry create_drawing_from_model.",
                    {"template_path": template},
                )

            view = self._create_model_view(drawing, model_path, model_view, x, y)
            return self._ok(
                "drawing_created",
                document=self._document_summary(drawing),
                view=self._view_summary(view),
                template_path=template,
                model_path=model_path,
            )

        return self._run(operation)

    def insert_model_view(
        self,
        model_path: str,
        *,
        view_name: str = "*Front",
        x: float = 0.25,
        y: float = 0.25,
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Insert a model view into the active or supplied drawing."""

        def operation() -> dict[str, Any]:
            drawing = self._drawing_doc(drawing_doc)
            view = self._create_model_view(drawing, model_path, view_name, x, y)
            return self._ok("model_view_inserted", view=self._view_summary(view), model_path=model_path)

        return self._run(operation)

    def insert_projected_view(
        self,
        *,
        x: float,
        y: float,
        direction: str = "right",
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Insert a projected view from the currently selected drawing view."""

        def operation() -> dict[str, Any]:
            drawing = self._drawing_doc(drawing_doc)
            direction_id = PROJECTED_DIRECTIONS.get(direction.lower())
            if direction_id is None:
                raise self._failure(
                    ErrorCode.INVALID_INPUT,
                    f"Unknown projected view direction '{direction}'.",
                    "Use one of: left, right, top, bottom, isometric.",
                    {"direction": direction},
                )
            view = self._call_any(
                drawing,
                ("CreateProjectedViewAt3", "CreateProjectedViewAt2"),
                x,
                y,
                int(direction_id),
            )
            return self._ok("projected_view_inserted", view=self._view_summary(view), direction=direction)

        return self._run(operation)

    def insert_section_view(
        self,
        *,
        label: str,
        x: float,
        y: float,
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Insert a section view from a preselected section line."""

        def operation() -> dict[str, Any]:
            drawing = self._drawing_doc(drawing_doc)
            view = self._call_any(
                drawing,
                ("CreateSectionViewAt5", "CreateSectionViewAt4", "CreateSectionViewAt3"),
                x,
                y,
                label,
            )
            return self._ok("section_view_inserted", view=self._view_summary(view), label=label)

        return self._run(operation)

    def insert_detail_view(
        self,
        *,
        label: str,
        x: float,
        y: float,
        radius: float,
        scale: float | None = None,
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Insert a detail view from a preselected circular/detail profile."""

        def operation() -> dict[str, Any]:
            drawing = self._drawing_doc(drawing_doc)
            args: tuple[Any, ...] = (x, y, radius, label) if scale is None else (x, y, radius, label, scale)
            view = self._call_any(drawing, ("CreateDetailViewAt3", "CreateDetailViewAt2"), *args)
            return self._ok(
                "detail_view_inserted",
                view=self._view_summary(view),
                label=label,
                radius=radius,
                scale=scale,
            )

        return self._run(operation)

    def insert_auxiliary_view(
        self,
        *,
        label: str,
        x: float,
        y: float,
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Insert an auxiliary view from a preselected edge/reference."""

        def operation() -> dict[str, Any]:
            drawing = self._drawing_doc(drawing_doc)
            view = self._call_any(drawing, ("CreateAuxiliaryViewAt3", "CreateAuxiliaryViewAt2"), x, y, label)
            return self._ok("auxiliary_view_inserted", view=self._view_summary(view), label=label)

        return self._run(operation)

    def add_smart_dimension(
        self,
        *,
        x: float,
        y: float,
        z: float = 0.0,
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Add a smart dimension for the current selection."""

        return self._add_dimension("smart_dimension_added", ("AddDimension2", "AddDimension"), (x, y, z), drawing_doc)

    def add_ordinate_dimension(
        self,
        *,
        x: float,
        y: float,
        ordinate_type: str = "horizontal",
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Add an ordinate dimension for the current selection."""

        type_id = 1 if ordinate_type.lower() == "horizontal" else 2
        return self._add_dimension(
            "ordinate_dimension_added",
            ("AddOrdinateDimension2", "AddOrdinateDimension"),
            (type_id, x, y, 0.0),
            drawing_doc,
            ordinate_type=ordinate_type,
        )

    def add_chamfer_dimension(
        self,
        *,
        x: float,
        y: float,
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Add a chamfer dimension for the current selection."""

        return self._add_dimension(
            "chamfer_dimension_added",
            ("InsertChamferDimension2", "InsertChamferDimension"),
            (x, y, 0.0),
            drawing_doc,
        )

    def add_hole_callout(
        self,
        *,
        x: float,
        y: float,
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Add a hole callout for the current hole selection."""

        return self._add_dimension("hole_callout_added", ("InsertHoleCallout2", "InsertHoleCallout"), (x, y, 0.0), drawing_doc)

    def add_note(
        self,
        text: str,
        *,
        x: float | None = None,
        y: float | None = None,
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Add a drawing note annotation."""

        def operation() -> dict[str, Any]:
            drawing = self._drawing_doc(drawing_doc)
            note = self._call_any(drawing, ("InsertNote",), text)
            if x is not None and y is not None and note is not None:
                annotation = self._get_attr(note, "GetAnnotation")
                if callable(annotation):
                    annotation = annotation()
                if annotation is not None:
                    self._call_optional(annotation, ("SetPosition", "SetPosition2"), x, y, 0.0)
            return self._ok("note_added", annotation=self._annotation_summary(note), text=text)

        return self._run(operation)

    def add_balloon(
        self,
        *,
        x: float | None = None,
        y: float | None = None,
        style: int = 1,
        size: int = 1,
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Add a BOM balloon for the current selection."""

        def operation() -> dict[str, Any]:
            drawing = self._drawing_doc(drawing_doc)
            balloon = self._call_any(drawing, ("InsertBomBalloon2", "InsertBomBalloon"), style, size)
            self._position_annotation(balloon, x, y)
            return self._ok("balloon_added", annotation=self._annotation_summary(balloon), style=style, size=size)

        return self._run(operation)

    def add_surface_finish(
        self,
        symbol: str,
        *,
        x: float | None = None,
        y: float | None = None,
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Add a surface finish symbol for the current selection."""

        return self._add_annotation(
            "surface_finish_added",
            ("InsertSurfaceFinishSymbol3", "InsertSurfaceFinishSymbol2", "InsertSurfaceFinishSymbol"),
            (symbol,),
            x,
            y,
            drawing_doc,
            symbol=symbol,
        )

    def add_weld_symbol(
        self,
        symbol: str,
        *,
        x: float | None = None,
        y: float | None = None,
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Add a weld symbol for the current selection."""

        return self._add_annotation(
            "weld_symbol_added",
            ("InsertWeldSymbol3", "InsertWeldSymbol2", "InsertWeldSymbol"),
            (symbol,),
            x,
            y,
            drawing_doc,
            symbol=symbol,
        )

    def add_geometric_tolerance(
        self,
        frame_text: str,
        *,
        x: float | None = None,
        y: float | None = None,
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Add a GD&T frame annotation."""

        return self._add_annotation(
            "gdt_added",
            ("InsertGTol", "InsertGtol", "InsertGeometricTolerance"),
            (frame_text,),
            x,
            y,
            drawing_doc,
            frame_text=frame_text,
        )

    def add_datum(
        self,
        label: str,
        *,
        x: float | None = None,
        y: float | None = None,
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Add a datum feature symbol."""

        return self._add_annotation(
            "datum_added",
            ("InsertDatumTag2", "InsertDatumTag"),
            (label,),
            x,
            y,
            drawing_doc,
            label=label,
        )

    def insert_bom(
        self,
        *,
        table_template: str | None = None,
        x: float = 0.02,
        y: float = 0.02,
        anchor_type: int = 1,
        bom_type: int = 1,
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Insert a BOM table into the active drawing."""

        def operation() -> dict[str, Any]:
            drawing = self._drawing_doc(drawing_doc)
            table = self._call_any(
                drawing,
                ("InsertBomTable4", "InsertBomTable3", "InsertBomTable2"),
                table_template or "",
                x,
                y,
                anchor_type,
                bom_type,
            )
            return self._ok("bom_inserted", bom=self._table_summary(table), table_template=table_template)

        return self._run(operation)

    def update_bom(self, *, table: Any | None = None, drawing_doc: Any | None = None) -> dict[str, Any]:
        """Update/rebuild a BOM table."""

        def operation() -> dict[str, Any]:
            target = table or self._first_table(self._drawing_doc(drawing_doc))
            if target is None:
                raise self._failure(
                    ErrorCode.INVALID_INPUT,
                    "No BOM table was supplied or found in the active drawing.",
                    "Insert a BOM first or pass the table object from the backend context.",
                )
            self._call_optional(target, ("UpdateTableAnnotation", "UpdateFeature", "Update"), True)
            return self._ok("bom_updated", bom=self._table_summary(target))

        return self._run(operation)

    def read_title_block(self, *, drawing_doc: Any | None = None) -> dict[str, Any]:
        """Read editable title block notes from the current sheet."""

        def operation() -> dict[str, Any]:
            sheet = self._current_sheet(self._drawing_doc(drawing_doc))
            notes = self._sheet_notes(sheet)
            fields = {
                self._safe_string(self._call_optional(note, ("GetName", "Name"))) or f"note_{index + 1}": self._safe_string(
                    self._call_optional(note, ("GetText", "GetText2", "Text"))
                )
                for index, note in enumerate(notes)
            }
            return self._ok("title_block_read", sheet=self._sheet_summary(sheet), fields=fields)

        return self._run(operation)

    def write_title_block(
        self,
        fields: dict[str, str],
        *,
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Write title block note text by note name."""

        def operation() -> dict[str, Any]:
            sheet = self._current_sheet(self._drawing_doc(drawing_doc))
            notes = self._sheet_notes(sheet)
            updated: list[str] = []
            missing = set(fields)
            for note in notes:
                name = self._safe_string(self._call_optional(note, ("GetName", "Name")))
                if name in fields:
                    self._call_optional(note, ("SetText", "SetText2"), fields[name])
                    updated.append(name)
                    missing.discard(name)
            return self._ok(
                "title_block_updated",
                sheet=self._sheet_summary(sheet),
                updated=updated,
                missing=sorted(missing),
            )

        return self._run(operation)

    def list_sheets(self, *, drawing_doc: Any | None = None) -> dict[str, Any]:
        """List drawing sheets."""

        def operation() -> dict[str, Any]:
            drawing = self._drawing_doc(drawing_doc)
            names = self._as_list(self._call_any(drawing, ("GetSheetNames",)))
            return self._ok("sheets_listed", sheets=names, count=len(names))

        return self._run(operation)

    def add_sheet(
        self,
        name: str,
        *,
        template_path: str | None = None,
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Add a drawing sheet."""

        def operation() -> dict[str, Any]:
            drawing = self._drawing_doc(drawing_doc)
            result = self._call_any(drawing, ("NewSheet4", "NewSheet3", "NewSheet"), name, 0, 0, 1.0, 1.0, False, template_path or "")
            if result is False:
                raise self._failure(
                    ErrorCode.OPERATION_FAILED,
                    f"SolidWorks rejected sheet creation for '{name}'.",
                    "Check that the sheet name is unique and the sheet format path is valid.",
                    {"sheet": name, "template_path": template_path},
                )
            return self._ok("sheet_added", sheet=name, template_path=template_path)

        return self._run(operation)

    def activate_sheet(self, name: str, *, drawing_doc: Any | None = None) -> dict[str, Any]:
        """Activate an existing drawing sheet."""

        def operation() -> dict[str, Any]:
            drawing = self._drawing_doc(drawing_doc)
            result = self._call_any(drawing, ("ActivateSheet",), name)
            if result is False:
                raise self._failure(
                    ErrorCode.OPERATION_FAILED,
                    f"SolidWorks could not activate sheet '{name}'.",
                    "Call list_sheets and retry with an existing sheet name.",
                    {"sheet": name},
                )
            return self._ok("sheet_activated", sheet=name)

        return self._run(operation)

    def delete_sheet(self, name: str, *, drawing_doc: Any | None = None) -> dict[str, Any]:
        """Delete a drawing sheet."""

        def operation() -> dict[str, Any]:
            drawing = self._drawing_doc(drawing_doc)
            result = self._call_any(drawing, ("DeleteSheet",), name)
            if result is False:
                raise self._failure(
                    ErrorCode.OPERATION_FAILED,
                    f"SolidWorks could not delete sheet '{name}'.",
                    "Call list_sheets and retry with an existing non-active sheet name.",
                    {"sheet": name},
                )
            return self._ok("sheet_deleted", sheet=name)

        return self._run(operation)

    def set_sheet_format(
        self,
        *,
        template_path: str,
        drawing_doc: Any | None = None,
    ) -> dict[str, Any]:
        """Apply a sheet format/template to the current sheet."""

        def operation() -> dict[str, Any]:
            sheet = self._current_sheet(self._drawing_doc(drawing_doc))
            result = self._call_any(sheet, ("SetTemplateName", "SetSheetFormatName"), template_path)
            if result is False:
                raise self._failure(
                    ErrorCode.OPERATION_FAILED,
                    "SolidWorks rejected the sheet format update.",
                    "Verify the template path exists and is accessible to SolidWorks.",
                    {"template_path": template_path},
                )
            return self._ok("sheet_format_updated", sheet=self._sheet_summary(sheet), template_path=template_path)

        return self._run(operation)

    def _add_dimension(
        self,
        event: str,
        method_names: tuple[str, ...],
        args: tuple[Any, ...],
        drawing_doc: Any | None,
        **extra: Any,
    ) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            drawing = self._drawing_doc(drawing_doc)
            dimension = self._call_any(drawing, method_names, *args)
            return self._ok(event, dimension=self._dimension_summary(dimension), **extra)

        return self._run(operation)

    def _add_annotation(
        self,
        event: str,
        method_names: tuple[str, ...],
        args: tuple[Any, ...],
        x: float | None,
        y: float | None,
        drawing_doc: Any | None,
        **extra: Any,
    ) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            drawing = self._drawing_doc(drawing_doc)
            annotation = self._call_any(drawing, method_names, *args)
            self._position_annotation(annotation, x, y)
            return self._ok(event, annotation=self._annotation_summary(annotation), **extra)

        return self._run(operation)

    def _run(self, operation: Any) -> dict[str, Any]:
        try:
            return operation()
        except Exception as exc:  # COM libraries expose several exception classes.
            return error_response(exc)

    def _drawing_doc(self, drawing_doc: Any | None = None) -> Any:
        doc = drawing_doc or self._active_doc()
        if doc is None:
            raise self._failure(
                ErrorCode.NOT_CONNECTED,
                "No active SolidWorks document is available.",
                "Attach to SolidWorks and open or create a drawing document.",
            )
        doc_type = self._call_optional(doc, ("GetType",))
        if doc_type not in (None, int(SwDocumentType.DRAWING), SwDocumentType.DRAWING):
            raise self._failure(
                ErrorCode.INVALID_INPUT,
                "The active SolidWorks document is not a drawing.",
                "Activate a drawing document or call create_drawing_from_model first.",
                {"document_type": doc_type},
            )
        return doc

    def _active_doc(self) -> Any | None:
        return self._call_optional(self.sw_app, ("ActiveDoc", "IActiveDoc2", "GetActiveDoc"))

    def _default_drawing_template(self) -> str | None:
        # swDefaultTemplateDrawing is stable as enum value 3 across the API.
        value = self._call_optional(self.sw_app, ("GetUserPreferenceStringValue",), 3)
        return self._safe_string(value)

    def _create_model_view(self, drawing: Any, model_path: str, view_name: str, x: float, y: float) -> Any:
        if not model_path:
            raise self._failure(
                ErrorCode.INVALID_INPUT,
                "model_path is required to insert a drawing view.",
                "Pass the absolute model path from an allowlisted workspace.",
            )
        path = str(Path(model_path))
        return self._call_any(
            drawing,
            ("CreateDrawViewFromModelView3", "CreateDrawViewFromModelView2"),
            path,
            view_name,
            x,
            y,
            0.0,
        )

    def _current_sheet(self, drawing: Any) -> Any:
        sheet = self._call_any(drawing, ("GetCurrentSheet",))
        if sheet is None:
            raise self._failure(
                ErrorCode.OPERATION_FAILED,
                "SolidWorks did not return a current drawing sheet.",
                "Activate a sheet and retry the sheet/title block operation.",
            )
        return sheet

    def _first_table(self, drawing: Any) -> Any | None:
        views = self._as_list(self._call_optional(drawing, ("GetViews",)))
        for view in views:
            tables = self._as_list(self._call_optional(view, ("GetTableAnnotations",)))
            if tables:
                return tables[0]
        return None

    def _sheet_notes(self, sheet: Any) -> list[Any]:
        for method_name in ("GetTemplateNotes", "GetNotes", "GetAnnotations"):
            notes = self._call_optional(sheet, (method_name,))
            if notes is not None:
                return self._as_list(notes)
        return []

    def _position_annotation(self, obj: Any, x: float | None, y: float | None) -> None:
        if x is None or y is None or obj is None:
            return
        annotation = self._call_optional(obj, ("GetAnnotation",)) or obj
        self._call_optional(annotation, ("SetPosition", "SetPosition2"), x, y, 0.0)

    def _call_any(self, obj: Any, method_names: Iterable[str], *args: Any) -> Any:
        for method_name in method_names:
            member = self._get_attr(obj, method_name)
            if member is None:
                continue
            try:
                return member(*args) if callable(member) else member
            except TypeError as exc:
                last_type_error = exc
                continue
            except Exception:
                raise
        names = ", ".join(method_names)
        raise self._failure(
            ErrorCode.UNSUPPORTED,
            f"The required SolidWorks drawing API member is not available: {names}.",
            "Use the SolidWorks backend with a compatible SolidWorks API version or route through the macro bridge.",
            {"members": list(method_names)},
        ) from locals().get("last_type_error")

    def _call_optional(self, obj: Any, method_names: Iterable[str], *args: Any) -> Any | None:
        if obj is None:
            return None
        for method_name in method_names:
            member = self._get_attr(obj, method_name)
            if member is None:
                continue
            try:
                return member(*args) if callable(member) else member
            except TypeError:
                continue
            except Exception:
                return None
        return None

    @staticmethod
    def _get_attr(obj: Any, name: str) -> Any | None:
        try:
            return getattr(obj, name)
        except Exception:
            return None

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        try:
            return list(value)
        except TypeError:
            return [value]

    @staticmethod
    def _safe_string(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value or None
        return str(value)

    def _ok(self, event: str, **data: Any) -> dict[str, Any]:
        return {"ok": True, "backend": self.options.backend_name, "event": event, "data": self._jsonish(data)}

    def _failure(
        self,
        code: ErrorCode,
        message: str,
        next_step: str,
        details: dict[str, Any] | None = None,
    ) -> McpCadError:
        return McpCadError(code=code, message=message, next_step=next_step, details=details)

    def _document_summary(self, doc: Any) -> dict[str, Any]:
        return {
            "title": self._safe_string(self._call_optional(doc, ("GetTitle", "Title"))),
            "path": self._safe_string(self._call_optional(doc, ("GetPathName", "PathName"))),
            "type": self._call_optional(doc, ("GetType",)),
        }

    def _view_summary(self, view: Any) -> dict[str, Any]:
        if view is None:
            return {}
        return {
            "name": self._safe_string(self._call_optional(view, ("GetName2", "GetName", "Name"))),
            "scale": self._call_optional(view, ("ScaleDecimal", "GetScaleDecimal")),
            "referenced_document": self._safe_string(
                self._call_optional(view, ("GetReferencedModelName", "ReferencedDocument"))
            ),
        }

    def _annotation_summary(self, annotation: Any) -> dict[str, Any]:
        if annotation is None:
            return {}
        return {
            "name": self._safe_string(self._call_optional(annotation, ("GetName", "Name"))),
            "type": self._safe_string(self._call_optional(annotation, ("GetType", "Type"))),
        }

    def _dimension_summary(self, dimension: Any) -> dict[str, Any]:
        if dimension is None:
            return {}
        return {
            "name": self._safe_string(self._call_optional(dimension, ("GetNameForSelection", "GetName", "Name"))),
            "value": self._call_optional(dimension, ("GetSystemValue3", "GetSystemValue", "SystemValue")),
        }

    def _table_summary(self, table: Any) -> dict[str, Any]:
        if table is None:
            return {}
        return {
            "title": self._safe_string(self._call_optional(table, ("Title", "GetTitle"))),
            "row_count": self._call_optional(table, ("RowCount", "GetRowCount")),
            "column_count": self._call_optional(table, ("ColumnCount", "GetColumnCount")),
        }

    def _sheet_summary(self, sheet: Any) -> dict[str, Any]:
        return {
            "name": self._safe_string(self._call_optional(sheet, ("GetName", "Name"))),
            "template": self._safe_string(self._call_optional(sheet, ("GetTemplateName", "GetSheetFormatName"))),
        }

    def _jsonish(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): self._jsonish(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._jsonish(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return self._safe_string(value)

