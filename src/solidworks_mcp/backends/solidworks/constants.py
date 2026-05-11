"""Small SolidWorks API constant subset used by the COM backend.

Values match common SolidWorks API enum values. The backend keeps these local so
the MCP server can run on machines without SolidWorks type libraries installed.
"""

from __future__ import annotations

from pathlib import Path


SW_DOC_PART = 1
SW_DOC_ASSEMBLY = 2
SW_DOC_DRAWING = 3

SW_OPEN_SILENT = 1
SW_OPEN_READ_ONLY = 2

SW_SAVE_AS_CURRENT_VERSION = 0
SW_SAVE_AS_OPTIONS_SILENT = 1

SW_CUSTOM_INFO_TEXT = 30
SW_CUSTOM_PROPERTY_REPLACE_VALUE = 2

DOCUMENT_TYPES = {
    "part": SW_DOC_PART,
    "assembly": SW_DOC_ASSEMBLY,
    "drawing": SW_DOC_DRAWING,
}

DOCUMENT_TYPE_NAMES = {
    SW_DOC_PART: "part",
    SW_DOC_ASSEMBLY: "assembly",
    SW_DOC_DRAWING: "drawing",
}

EXTENSION_DOCUMENT_TYPES = {
    ".sldprt": SW_DOC_PART,
    ".sldasm": SW_DOC_ASSEMBLY,
    ".slddrw": SW_DOC_DRAWING,
}

EXPORT_EXTENSIONS = {
    "sldprt": ".sldprt",
    "sldasm": ".sldasm",
    "slddrw": ".slddrw",
    "step": ".step",
    "iges": ".igs",
    "pdf": ".pdf",
    "dxf": ".dxf",
    "dwg": ".dwg",
    "stl": ".stl",
    "3mf": ".3mf",
    "x_t": ".x_t",
    "x_b": ".x_b",
}


def infer_document_type(path: str | Path, explicit: str | None = None) -> int:
    if explicit and explicit in DOCUMENT_TYPES:
        return DOCUMENT_TYPES[explicit]
    suffix = Path(path).suffix.lower()
    return EXTENSION_DOCUMENT_TYPES.get(suffix, SW_DOC_PART)


def normalize_document_type(type_value: object) -> str:
    try:
        return DOCUMENT_TYPE_NAMES.get(int(type_value), "unknown")
    except (TypeError, ValueError):
        return "unknown"
