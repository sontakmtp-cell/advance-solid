# SolidWorks MCP Server

An MCP server that lets AI agents operate SolidWorks and headless CAD workflows through a unified stdio API.

The server supports two backend modes:

- `solidworks`: controls SolidWorks on Windows through Python COM automation, with an optional named-pipe macro/add-in bridge for allowlisted in-process API calls.
- `headless`: runs offline CAD/file-exchange workflows with CadQuery/OCP when installed. Unsupported SolidWorks-only operations return explicit `unsupported` errors with next-step hints.

The current implementation covers backend status and health, document open/save/info/rebuild/export, custom properties, BOM, mass/material, configuration helpers, part inspection, Phase 2 workflow operation groups, Phase 3 semantic analysis, routing placeholders, smoke tests, and read-only evaluation coverage.

## Architecture

```text
MCP client
  |
  | stdio JSON-RPC
  v
FastMCP server (solidworks_mcp.server)
  |
  +-- tool layer (validation, formatting, hints)
  |
  +-- backend abstraction (core/backend.py)
      |
      +-- SolidWorks backend
      |   +-- COM dispatcher: Python -> COM Automation API -> SolidWorks
      |   +-- optional macro bridge: Python -> named pipe -> VBA/VSTA/.NET bridge -> SolidWorks API
      |
      +-- Headless backend
          +-- CadQuery/OCP/pythonOCC-style B-Rep operations and file exchange
```

## Ownership Map

- Main project: `pyproject.toml`, `README.md`, `src/solidworks_mcp/config.py`, `src/solidworks_mcp/core/`, `src/solidworks_mcp/schemas/`, project layout, and test harness.
- SolidWorks COM bridge and IPC: `src/solidworks_mcp/backends/solidworks/`, `src/solidworks_mcp/bridges/solidworks_macro/`.
- Custom properties and BOM helpers: `src/solidworks_mcp/helpers/`.
- Headless backend: `src/solidworks_mcp/backends/headless/`.
- MCP tools, docs, and tests: `src/solidworks_mcp/server.py`, `src/solidworks_mcp/tools/`, `docs/`, `evaluations/`.
- Drawing and annotation domain logic: `src/solidworks_mcp/domain/drawing.py`.

## Local Setup

Install the package with development dependencies:

```powershell
python -m pip install -e ".[dev]"
```

For SolidWorks COM support on Windows:

```powershell
python -m pip install -e ".[solidworks,dev]"
$env:SOLIDWORKS_MCP_BACKEND = "solidworks"
$env:SOLIDWORKS_MCP_WORKSPACE_ROOTS = "H:\MCP-AutoCAD"
solidworks-mcp
```

For headless CAD workflows:

```powershell
python -m pip install -e ".[headless,dev]"
$env:SOLIDWORKS_MCP_BACKEND = "headless"
solidworks-mcp
```

The server speaks MCP over stdio, so it is normally launched by an MCP client rather than used as an interactive terminal program.

## MCP Client Config

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "solidworks-mcp",
      "env": {
        "SOLIDWORKS_MCP_BACKEND": "solidworks",
        "SOLIDWORKS_MCP_WORKSPACE_ROOTS": "H:\\MCP-AutoCAD",
        "SOLIDWORKS_MCP_ALLOW_MACROS": "false"
      }
    }
  }
}
```

For offline/headless workflows:

```json
{
  "mcpServers": {
    "solidworks-headless": {
      "command": "solidworks-mcp",
      "env": {
        "SOLIDWORKS_MCP_BACKEND": "headless",
        "SOLIDWORKS_MCP_WORKSPACE_ROOTS": "H:\\MCP-AutoCAD"
      }
    }
  }
}
```

## Environment Variables

- `SOLIDWORKS_MCP_BACKEND`: selects `headless` or `solidworks`. Default: `headless`.
- `SOLIDWORKS_MCP_WORKSPACE_ROOTS`: OS path-separated allowlist for file operations. Default: current working directory.
- `SOLIDWORKS_MCP_ALLOW_MACROS`: enables allowlisted macro execution when supported by the SolidWorks backend.
- `SOLIDWORKS_MCP_MACRO_ALLOWLIST`: comma-separated macro command allowlist. Defaults to `get_custom_properties,set_custom_properties,traverse_feature_tree`.
- `SOLIDWORKS_MCP_MACRO_PIPE`: Windows named pipe used by the optional macro bridge. Default: `\\.\pipe\solidworks_mcp_bridge`.
- `SOLIDWORKS_MCP_COM_TIMEOUT` and `SOLIDWORKS_MCP_COM_HARD_TIMEOUT`: control SolidWorks COM operation timeouts.
- `SOLIDWORKS_MCP_LOG_LEVEL`: runtime log level. Default: `INFO`.
- `SOLIDWORKS_MCP_AUDIT_LOG`: optional audit log path for tool/backend activity.

## Tool Groups

- System: `system_backend_info`, `system_capabilities`, `system_health`, `system_attach`, `system_execute_macro`, `system_run_com_command`.
- Documents: `document_open`, `document_save`, `document_info`, `document_rebuild`, `document_export`.
- Metadata: `custom_properties_get`, `custom_properties_set`, `bom_read`, `mass_properties`, `material_info`, `configurations`.
- Part inspection: `part_inspect`.
- Workflow operations: `feature_operation`, `assembly_operation`, `drawing_operation`, `appearance_operation`, `import_export_operation`.
- Analysis and routing: `semantic_analysis`, `routing_operation`.

Grouped workflow tools use a stable `{operation, parameters}` envelope. Backends may return `unsupported` when an operation is not available in the selected backend.

## Macro Bridge

The macro bridge is optional scaffolding for commands that must execute inside the SolidWorks process. The default control path remains Python COM automation.

Bridge requests use one UTF-8 JSON object per line over a Windows named pipe. Production bridge implementations should keep their own command allowlist, avoid blocking the SolidWorks UI thread, and add workstation-appropriate authentication, audit logging, request size limits, and payload validation.

## Testing

Run the unit test suite with:

```powershell
python -m pytest
```

Tests that require a licensed SolidWorks workstation should be run in an environment where SolidWorks COM automation is available. Headless tests should either install the `headless` extra or expect explicit `unsupported` responses when CadQuery/OCP is unavailable.

## Example Calls

Inspect the active SolidWorks part:

```json
{
  "backend": "solidworks",
  "detail": "concise",
  "feature_limit": 100,
  "include_custom_properties": true
}
```

List a part feature tree:

```json
{
  "backend": "solidworks",
  "operation": "list_tree",
  "parameters": {
    "include_suppressed": true,
    "max_depth": 5
  }
}
```

Create a drawing from a model:

```json
{
  "backend": "solidworks",
  "operation": "create_from_model",
  "parameters": {
    "model_path": "H:\\CAD-Work\\bracket.SLDPRT",
    "template": "A3 landscape",
    "sheet_name": "Sheet1"
  }
}
```

Run a basic DFM analysis:

```json
{
  "backend": "solidworks",
  "analysis": "dfm",
  "detail": "concise",
  "parameters": {
    "min_wall_thickness": 1.5
  }
}
```

Export the active model:

```json
{
  "backend": "headless",
  "path": "H:\\MCP-AutoCAD\\out\\bracket.stl",
  "format": "stl",
  "options": {
    "tolerance": 0.01
  }
}
```

## Design Notes

- COM automation is the primary SolidWorks control path. The named-pipe bridge is reserved for allowlisted in-process commands where COM cannot safely reach the required API surface.
- File and macro operations are restricted to allowlisted workspace roots from `SOLIDWORKS_MCP_WORKSPACE_ROOTS`.
- The headless backend does not claim SolidWorks parity. SolidWorks-only features return `unsupported` with a next-step hint.
- Tool outputs default to concise JSON-compatible dictionaries and can expose more detail through schema flags.
- `part_inspect` integrates the former `inspect_part_v2.py` workflow as a read-only SolidWorks inspection tool for the active part.
- Phase 3 semantic analysis provides heuristic review signals and should not be treated as release-grade engineering approval without SolidWorks-side verification.

## References

- MCP Python SDK and FastMCP: https://github.com/modelcontextprotocol/python-sdk
- SOLIDWORKS API Help, `IModelDoc2` members and `IModelDocExtension::SaveAs`: https://help.solidworks.com/2025/english/api/sldworksapi/

## Additional Docs

- [Architecture](docs/architecture.md)
- [Usage](docs/usage.md)
- [Tool mapping](docs/tools.md)
- [Read-only smoke evaluations](evaluations/read_only_smoke.xml)
- [MCP client config example](examples/mcp_client_config.json)
