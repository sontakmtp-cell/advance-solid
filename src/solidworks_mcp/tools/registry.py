"""FastMCP tool definitions and backend mapping."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from solidworks_mcp.core.errors import ErrorCode, McpCadError
from solidworks_mcp.schemas.documents import (
    BackendSelectInput,
    DocumentInfoInput,
    ExportDocumentInput,
    OpenDocumentInput,
    RebuildInput,
    SaveDocumentInput,
)
from solidworks_mcp.schemas.modeling import (
    AppearanceOperationInput,
    AssemblyOperationInput,
    DrawingOperationInput,
    FeatureOperationInput,
    RoutingOperationInput,
    SemanticAnalysisInput,
)
from solidworks_mcp.schemas.properties import (
    BomInput,
    ConfigurationInput,
    CustomPropertiesInput,
    MaterialInput,
    SetCustomPropertiesInput,
)
from solidworks_mcp.tools.runtime import BackendFactory, call_optional_backend_method, run_tool


@dataclass(frozen=True)
class ToolMeta:
    name: str
    description: str
    read_only: bool
    idempotent: bool
    destructive: bool = False
    open_world: bool = True

    def annotations(self) -> dict[str, bool]:
        return {
            "readOnlyHint": self.read_only,
            "idempotentHint": self.idempotent,
            "destructiveHint": self.destructive,
            "openWorldHint": self.open_world,
        }


@dataclass
class InMemoryMcp:
    """Small FastMCP-compatible registry used by unit tests when mcp is absent."""

    name: str = "solidworks-mcp"
    tools: dict[str, Callable[..., Any]] = field(default_factory=dict)
    tool_metadata: dict[str, ToolMeta] = field(default_factory=dict)

    def tool(self, name: str | None = None, description: str | None = None, **kwargs: Any) -> Callable:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or func.__name__
            self.tools[tool_name] = func
            meta = kwargs.pop("_solidworks_meta", None)
            if meta is not None:
                self.tool_metadata[tool_name] = meta
            return func

        return decorator


def _register(mcp: Any, meta: ToolMeta, func: Callable[..., Any]) -> None:
    annotations = meta.annotations()
    try:
        from mcp.types import ToolAnnotations

        tool_annotations: Any = ToolAnnotations(**annotations)
    except Exception:  # pragma: no cover - depends on installed mcp SDK version.
        tool_annotations = annotations

    kwargs = {
        "name": meta.name,
        "description": meta.description,
        "_solidworks_meta": meta,
    }
    try:
        mcp.tool(annotations=tool_annotations, **kwargs)(func)
    except TypeError:
        kwargs.pop("_solidworks_meta", None)
        try:
            mcp.tool(annotations=tool_annotations, **kwargs)(func)
        except TypeError:
            mcp.tool(name=meta.name, description=meta.description)(func)


def register_all_tools(mcp: Any, backend_factory: BackendFactory) -> Any:
    """Register all agent-facing SolidWorks MCP tools."""

    async def system_backend_info(backend: str = "auto", response_format: str = "json") -> Any:
        request = BackendSelectInput(backend=backend, response_format=response_format)
        return await run_tool(request, backend_factory, lambda b, _r: b.backend_info())

    _register(
        mcp,
        ToolMeta(
            "system_backend_info",
            "Return selected backend identity, runtime constraints, and operational notes.",
            read_only=True,
            idempotent=True,
        ),
        system_backend_info,
    )

    async def system_capabilities(backend: str = "auto", response_format: str = "json") -> Any:
        request = BackendSelectInput(backend=backend, response_format=response_format)
        return await run_tool(request, backend_factory, lambda b, _r: b.capabilities())

    _register(
        mcp,
        ToolMeta(
            "system_capabilities",
            "Return capability map so an agent can choose SolidWorks or headless workflows correctly.",
            read_only=True,
            idempotent=True,
        ),
        system_capabilities,
    )

    async def system_health(backend: str = "auto", response_format: str = "json") -> Any:
        request = BackendSelectInput(backend=backend, response_format=response_format)
        return await run_tool(request, backend_factory, lambda b, _r: b.health())

    _register(
        mcp,
        ToolMeta(
            "system_health",
            "Check backend connection health, dependencies, version/license signals, and next actions.",
            read_only=True,
            idempotent=True,
        ),
        system_health,
    )

    async def system_attach(backend: str = "auto", response_format: str = "json") -> Any:
        request = BackendSelectInput(backend=backend, response_format=response_format)
        return await run_tool(request, backend_factory, lambda b, _r: b.attach())

    _register(
        mcp,
        ToolMeta(
            "system_attach",
            "Attach to or initialize the selected backend runtime.",
            read_only=False,
            idempotent=True,
        ),
        system_attach,
    )

    async def system_execute_macro(
        macro_path: str,
        backend: str = "auto",
        procedure: str = "",
        module: str = "",
        response_format: str = "json",
    ) -> Any:
        request = BackendSelectInput(backend=backend, response_format=response_format)

        async def operation(b: Any, _r: BackendSelectInput) -> Any:
            if not macro_path:
                raise McpCadError(
                    ErrorCode.INVALID_INPUT,
                    "macro_path is required.",
                    "Pass an allowlisted macro path under SOLIDWORKS_MCP_WORKSPACE_ROOTS.",
                )
            return await call_optional_backend_method(
                b, "execute_macro", "system.execute_macro", macro_path, procedure, module
            )

        return await run_tool(
            request,
            backend_factory,
            operation,
        )

    _register(
        mcp,
        ToolMeta(
            "system_execute_macro",
            "Execute an allowlisted SolidWorks macro through the selected backend when production policy permits it.",
            read_only=False,
            idempotent=False,
            destructive=True,
        ),
        system_execute_macro,
    )

    async def system_run_com_command(
        command: str,
        backend: str = "auto",
        args: dict[str, Any] | None = None,
        response_format: str = "json",
    ) -> Any:
        request = BackendSelectInput(backend=backend, response_format=response_format)

        async def operation(b: Any, _r: BackendSelectInput) -> Any:
            if not command:
                raise McpCadError(
                    ErrorCode.INVALID_INPUT,
                    "command is required.",
                    "Pass a backend allowlisted command such as rebuild, force_rebuild, zoom_to_fit, or traverse_feature_tree.",
                )
            return await call_optional_backend_method(
                b, "run_com_command", f"system.run_com_command:{command}", command, args or {}
            )

        return await run_tool(
            request,
            backend_factory,
            operation,
        )

    _register(
        mcp,
        ToolMeta(
            "system_run_com_command",
            "Run an allowlisted SolidWorks COM command through the backend dispatcher.",
            read_only=False,
            idempotent=False,
            destructive=True,
        ),
        system_run_com_command,
    )

    async def document_open(
        path: str,
        backend: str = "auto",
        document_type: str | None = None,
        read_only: bool = False,
        response_format: str = "json",
    ) -> Any:
        request = OpenDocumentInput(
            backend=backend,
            path=path,
            document_type=document_type,
            read_only=read_only,
            response_format=response_format,
        )
        return await run_tool(
            request,
            backend_factory,
            lambda b, r: b.open_document(r.path, r.document_type),
        )

    _register(
        mcp,
        ToolMeta(
            "document_open",
            "Open/import a part, assembly, drawing, or exchange file from an allowlisted workspace path.",
            read_only=False,
            idempotent=True,
        ),
        document_open,
    )

    async def document_save(
        backend: str = "auto", path: str | None = None, response_format: str = "json"
    ) -> Any:
        request = SaveDocumentInput(backend=backend, path=path, response_format=response_format)
        return await run_tool(request, backend_factory, lambda b, r: b.save_document(r.path))

    _register(
        mcp,
        ToolMeta(
            "document_save",
            "Save the active document, optionally to an allowlisted target path.",
            read_only=False,
            idempotent=True,
        ),
        document_save,
    )

    async def document_info(
        backend: str = "auto",
        path: str | None = None,
        detail: str = "concise",
        response_format: str = "json",
    ) -> Any:
        request = DocumentInfoInput(
            backend=backend, path=path, detail=detail, response_format=response_format
        )
        return await run_tool(
            request,
            backend_factory,
            lambda b, r: b.document_info(r.path, r.detail),
        )

    _register(
        mcp,
        ToolMeta(
            "document_info",
            "Read concise or detailed document metadata, units, material, mass, and configurations.",
            read_only=True,
            idempotent=True,
        ),
        document_info,
    )

    async def document_rebuild(
        backend: str = "auto", force: bool = False, response_format: str = "json"
    ) -> Any:
        request = RebuildInput(backend=backend, force=force, response_format=response_format)
        return await run_tool(request, backend_factory, lambda b, r: b.rebuild(r.force))

    _register(
        mcp,
        ToolMeta(
            "document_rebuild",
            "Rebuild or force rebuild the active model.",
            read_only=False,
            idempotent=False,
        ),
        document_rebuild,
    )

    async def document_export(
        path: str,
        format: str,
        backend: str = "auto",
        options: dict[str, Any] | None = None,
        response_format: str = "json",
    ) -> Any:
        request = ExportDocumentInput(
            backend=backend,
            path=path,
            format=format,
            options=options or {},
            response_format=response_format,
        )
        return await run_tool(
            request,
            backend_factory,
            lambda b, r: b.export_document(r.path, r.format, r.options),
        )

    _register(
        mcp,
        ToolMeta(
            "document_export",
            "Export the active/loaded document to STEP, IGES, STL, PDF, DXF/DWG, 3MF, or native formats.",
            read_only=False,
            idempotent=True,
        ),
        document_export,
    )

    async def custom_properties_get(
        backend: str = "auto",
        scope: str = "file",
        configuration: str | None = None,
        response_format: str = "json",
    ) -> Any:
        request = CustomPropertiesInput(
            backend=backend, scope=scope, configuration=configuration, response_format=response_format
        )
        return await run_tool(
            request,
            backend_factory,
            lambda b, r: b.get_custom_properties(r.scope, r.configuration),
        )

    _register(
        mcp,
        ToolMeta(
            "custom_properties_get",
            "Read file, configuration, or cut-list custom properties for BOM/metadata workflows.",
            read_only=True,
            idempotent=True,
        ),
        custom_properties_get,
    )

    async def custom_properties_set(
        properties: dict[str, Any],
        backend: str = "auto",
        scope: str = "file",
        configuration: str | None = None,
        replace: bool = False,
        response_format: str = "json",
    ) -> Any:
        request = SetCustomPropertiesInput(
            backend=backend,
            scope=scope,
            configuration=configuration,
            properties=properties,
            replace=replace,
            response_format=response_format,
        )
        return await run_tool(
            request,
            backend_factory,
            lambda b, r: b.set_custom_properties(r.properties, r.scope, r.configuration),
        )

    _register(
        mcp,
        ToolMeta(
            "custom_properties_set",
            "Set file, configuration, or cut-list custom properties through backend metadata helpers.",
            read_only=False,
            idempotent=True,
        ),
        custom_properties_set,
    )

    async def bom_read(
        backend: str = "auto", source: str = "active_document", response_format: str = "json"
    ) -> Any:
        request = BomInput(backend=backend, source=source, response_format=response_format)
        return await run_tool(
            request,
            backend_factory,
            lambda b, r: call_optional_backend_method(b, "read_bom", "bom.read", r.source),
        )

    _register(
        mcp,
        ToolMeta(
            "bom_read",
            "Read BOM rows from the active document, assembly, or drawing when supported.",
            read_only=True,
            idempotent=True,
        ),
        bom_read,
    )

    async def mass_properties(backend: str = "auto", response_format: str = "json") -> Any:
        request = BackendSelectInput(backend=backend, response_format=response_format)
        return await run_tool(request, backend_factory, lambda b, _r: b.mass_properties())

    _register(
        mcp,
        ToolMeta(
            "mass_properties",
            "Read mass, volume, center of mass, and inertia for the active model.",
            read_only=True,
            idempotent=True,
        ),
        mass_properties,
    )

    async def material_info(
        backend: str = "auto", material: str | None = None, response_format: str = "json"
    ) -> Any:
        request = MaterialInput(backend=backend, material=material, response_format=response_format)
        return await run_tool(request, backend_factory, lambda b, r: b.material_info(r.material))

    _register(
        mcp,
        ToolMeta(
            "material_info",
            "Get material info, or set material when a material name is supplied and supported.",
            read_only=False,
            idempotent=True,
        ),
        material_info,
    )

    async def configurations(
        action: str,
        backend: str = "auto",
        name: str | None = None,
        new_name: str | None = None,
        response_format: str = "json",
    ) -> Any:
        request = ConfigurationInput(
            backend=backend,
            action=action,
            name=name,
            new_name=new_name,
            response_format=response_format,
        )
        return await run_tool(
            request,
            backend_factory,
            lambda b, r: call_optional_backend_method(
                b, "configurations", "configurations", r.action, r.name, r.new_name
            ),
        )

    _register(
        mcp,
        ToolMeta(
            "configurations",
            "List, create, delete, activate, or rename model configurations when supported.",
            read_only=False,
            idempotent=False,
            destructive=True,
        ),
        configurations,
    )

    async def feature_operation(
        operation: str,
        backend: str = "auto",
        parameters: dict[str, Any] | None = None,
        response_format: str = "json",
    ) -> Any:
        request = FeatureOperationInput(
            backend=backend,
            operation=operation,
            parameters=parameters or {},
            response_format=response_format,
        )
        return await run_tool(
            request,
            backend_factory,
            lambda b, r: call_optional_backend_method(
                b, "feature_operation", f"feature.{r.operation}", r.operation, r.parameters
            ),
        )

    _register(
        mcp,
        ToolMeta(
            "feature_operation",
            "Run part modeling operations such as sketch, extrude, fillet, chamfer, tree, or suppression.",
            read_only=False,
            idempotent=False,
        ),
        feature_operation,
    )

    async def assembly_operation(
        operation: str,
        backend: str = "auto",
        parameters: dict[str, Any] | None = None,
        response_format: str = "json",
    ) -> Any:
        request = AssemblyOperationInput(
            backend=backend,
            operation=operation,
            parameters=parameters or {},
            response_format=response_format,
        )
        return await run_tool(
            request,
            backend_factory,
            lambda b, r: call_optional_backend_method(
                b, "assembly_operation", f"assembly.{r.operation}", r.operation, r.parameters
            ),
        )

    _register(
        mcp,
        ToolMeta(
            "assembly_operation",
            "Run assembly operations such as insert component, mates, component tree, interference, or exploded view.",
            read_only=False,
            idempotent=False,
        ),
        assembly_operation,
    )

    async def drawing_operation(
        operation: str,
        backend: str = "auto",
        parameters: dict[str, Any] | None = None,
        response_format: str = "json",
    ) -> Any:
        request = DrawingOperationInput(
            backend=backend,
            operation=operation,
            parameters=parameters or {},
            response_format=response_format,
        )
        return await run_tool(
            request,
            backend_factory,
            lambda b, r: call_optional_backend_method(
                b, "drawing_operation", f"drawing.{r.operation}", r.operation, r.parameters
            ),
        )

    _register(
        mcp,
        ToolMeta(
            "drawing_operation",
            "Run drawing workflows such as create drawing, insert views, dimensions, annotations, BOM, or sheets.",
            read_only=False,
            idempotent=False,
        ),
        drawing_operation,
    )

    async def appearance_operation(
        operation: str,
        backend: str = "auto",
        parameters: dict[str, Any] | None = None,
        response_format: str = "json",
    ) -> Any:
        request = AppearanceOperationInput(
            backend=backend,
            operation=operation,
            parameters=parameters or {},
            response_format=response_format,
        )
        return await run_tool(
            request,
            backend_factory,
            lambda b, r: call_optional_backend_method(
                b, "appearance_operation", f"appearance.{r.operation}", r.operation, r.parameters
            ),
        )

    _register(
        mcp,
        ToolMeta(
            "appearance_operation",
            "Set display appearance, show/hide state, section view, named view, zoom, or screenshot.",
            read_only=False,
            idempotent=False,
        ),
        appearance_operation,
    )

    async def import_export_operation(
        operation: str,
        backend: str = "auto",
        parameters: dict[str, Any] | None = None,
        response_format: str = "json",
    ) -> Any:
        allowed = {"import", "export", "pack_and_go", "batch_export"}
        if operation not in allowed:
            return {
                "ok": False,
                "error": {
                    "code": "invalid_input",
                    "message": f"operation must be one of {sorted(allowed)}",
                    "next_step": "Use document_open for import, document_export for export, or a supported import/export operation.",
                },
            }
        request = BackendSelectInput(backend=backend, response_format=response_format)
        return await run_tool(
            request,
            backend_factory,
            lambda b, _r: call_optional_backend_method(
                b, "import_export_operation", f"import_export.{operation}", operation, parameters or {}
            ),
        )

    _register(
        mcp,
        ToolMeta(
            "import_export_operation",
            "Run higher-level import/export workflows such as Pack and Go or batch export when supported.",
            read_only=False,
            idempotent=False,
        ),
        import_export_operation,
    )

    async def semantic_analysis(
        analysis: str,
        backend: str = "auto",
        detail: str = "concise",
        parameters: dict[str, Any] | None = None,
        response_format: str = "json",
    ) -> Any:
        request = SemanticAnalysisInput(
            backend=backend,
            analysis=analysis,
            detail=detail,
            parameters=parameters or {},
            response_format=response_format,
        )
        return await run_tool(
            request,
            backend_factory,
            lambda b, r: call_optional_backend_method(
                b, "semantic_analysis", f"semantic.{r.analysis}", r.analysis, r.detail, r.parameters
            ),
        )

    _register(
        mcp,
        ToolMeta(
            "semantic_analysis",
            "Analyze geometry, feature intent, dimension plans, design rules, or basic DFM signals.",
            read_only=True,
            idempotent=True,
        ),
        semantic_analysis,
    )

    async def routing_operation(
        operation: str,
        backend: str = "auto",
        parameters: dict[str, Any] | None = None,
        response_format: str = "json",
    ) -> Any:
        request = RoutingOperationInput(
            backend=backend,
            operation=operation,
            parameters=parameters or {},
            response_format=response_format,
        )
        return await run_tool(
            request,
            backend_factory,
            lambda b, r: call_optional_backend_method(
                b, "routing_operation", f"routing.{r.operation}", r.operation, r.parameters
            ),
        )

    _register(
        mcp,
        ToolMeta(
            "routing_operation",
            "Run optional SolidWorks Routing/Piping workflows such as routes, fittings, specs, isometrics, or piping BOM.",
            read_only=False,
            idempotent=False,
        ),
        routing_operation,
    )

    return mcp
