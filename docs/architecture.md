# SolidWorks MCP Architecture

## Product Shape

The server is agent-centric rather than a thin wrapper around SolidWorks COM. Tools are grouped around workflows an AI agent needs: discover backend capability, open or inspect a model, export it, read BOM metadata, run drawing/modeling workflows, and receive actionable unsupported errors when the selected backend is wrong.

## Component Responsibilities

```text
MCP client
  |
  | stdio transport
  v
solidworks_mcp.server
  |
  +-- tools/registry.py
  |   Validates schemas, declares tool annotations, selects backend, formats errors.
  |
  +-- core/backend.py
  |   Shared backend contract for SolidWorks and headless CAD.
  |
  +-- backends/solidworks/
  |   Full Windows SolidWorks backend over COM Automation.
  |
  +-- bridges/solidworks_macro/
  |   Optional named-pipe bridge scaffold for in-process macro/add-in commands.
  |
  +-- backends/headless/
  |   Offline B-Rep/file exchange backend using CadQuery/OCP when installed.
  |
  +-- helpers/
      Custom properties, BOM, material, and configuration helpers.
```

## Control Flow

Primary SolidWorks path:

```text
AI agent -> MCP stdio -> FastMCP tool -> SolidWorksBackend
  -> SolidWorksComDispatcher -> pywin32/comtypes COM Automation
  -> SolidWorks process
```

Optional in-process bridge:

```text
AI agent -> MCP stdio -> FastMCP tool -> SolidWorksBackend
  -> MacroBridgeClient -> Windows named pipe JSON request
  -> VSTA/.NET add-in or short VBA bridge -> SolidWorks API
```

COM direct is the primary control path. The named pipe bridge is not a substitute name for COM; it is reserved for allowlisted tasks that need in-process SolidWorks API behavior.

Headless path:

```text
AI agent -> MCP stdio -> FastMCP tool -> HeadlessBackend
  -> CadQuery/OCP import/model/analyze/export
```

## COM Dispatcher

`SolidWorksComDispatcher` owns COM attachment and call execution. It initializes COM in an STA worker, serializes COM calls, retries common server-busy failures, returns actionable timeout errors, and marshals COM-like objects into JSON-safe values. Hard cancellation of a hung COM call is not guaranteed in Python, so the dispatcher isolates calls on a worker boundary and tells the agent when restart/reattach is the next realistic recovery step.

## Macro Bridge

The macro bridge uses line-delimited JSON over a named pipe. It is disabled by default and uses command allowlists plus workspace path restrictions. The scaffold includes:

- `named_pipe_client.py`
- `sample_bridge.cs` for VSTA/.NET add-in style async listening
- `sample_bridge.bas` as a short VBA reference with warnings against UI-thread blocking loops

Initial allowlisted commands are `execute_macro`, `get_custom_properties`, `set_custom_properties`, and `traverse_feature_tree`.

## Custom Properties And BOM

The helper modules isolate SolidWorks metadata quirks:

- file/configuration/cut-list custom properties
- assembly BOM traversal and quantity grouping
- mass properties through `ModelDocExtension.CreateMassProperty`
- material get/set
- configuration list/create/delete/activate/rename

This keeps metadata/BOM workflows stable for agents instead of scattering COM calls across tools.

## Tool List

MVP direct tools:

- `system_backend_info`
- `system_capabilities`
- `system_health`
- `system_attach`
- `document_open`
- `document_save`
- `document_info`
- `document_rebuild`
- `document_export`
- `custom_properties_get`
- `custom_properties_set`
- `bom_read`
- `mass_properties`
- `material_info`

Safety-sensitive system tools:

- `system_execute_macro`
- `system_run_com_command`

Roadmap workflow tools:

- `configurations`
- `feature_operation`
- `assembly_operation`
- `drawing_operation`
- `appearance_operation`
- `import_export_operation`
- `semantic_analysis`
- `routing_operation`

## Phase Plan

Phase 1 MVP, implemented here:

- stdio MCP server and backend abstraction
- config, path allowlist, structured errors
- SolidWorks attach/status/health and basic document operations
- COM dispatcher with STA/retry/timeout behavior
- optional macro bridge scaffold
- custom properties/BOM/material/configuration helpers
- headless import/analyze/export scaffold
- smoke tests and read-only evaluations

Phase 2:

- richer sketch/feature creation
- assembly insert component and mates
- drawing view/dimension/annotation workflows wired through tools
- real SolidWorks integration tests on a licensed workstation

Phase 3:

- semantic CAD, DFM, dimension plan validation
- Pack and Go, advanced BOM, design tables
- optional Routing/Piping module gated by add-in/license capability

## Technical Risks

- Real SolidWorks COM signatures vary by version and need workstation validation.
- Hung COM calls cannot always be killed cleanly from Python; recovery may require restart/reattach.
- The macro bridge needs a production add-in implementation before long-running in-process workflows are safe.
- Headless CadQuery/OCP behavior must be tested with representative STEP/IGES files.
- This workspace currently lacks a normal Python environment with `pydantic`, `mcp`, and `pytest`, so runtime/import tests could not be completed here.

