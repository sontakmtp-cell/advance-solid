# SolidWorks MCP Usage

This server exposes an agent-centric MCP interface for SolidWorks and headless CAD backends over stdio.

## Run Locally

Install the package in a Python environment:

```powershell
python -m pip install -e ".[dev]"
```

For SolidWorks COM automation on Windows:

```powershell
python -m pip install -e ".[solidworks]"
```

For the headless backend:

```powershell
python -m pip install -e ".[headless]"
```

Start the stdio server:

```powershell
solidworks-mcp
```

Do not run this directly in a normal terminal for manual testing unless you expect it to wait on stdin. Use an MCP client or a test harness.

## Environment

`SOLIDWORKS_MCP_BACKEND` selects `headless` or `solidworks`. Default: `headless`.

`SOLIDWORKS_MCP_WORKSPACE_ROOTS` is an OS path-separated allowlist for file operations. Default: current working directory.

`SOLIDWORKS_MCP_ALLOW_MACROS` enables macro execution only when the SolidWorks backend implements the allowlisted bridge commands.

`SOLIDWORKS_MCP_MACRO_ALLOWLIST` defaults to `get_custom_properties,set_custom_properties,traverse_feature_tree`.

`SOLIDWORKS_MCP_COM_TIMEOUT` and `SOLIDWORKS_MCP_COM_HARD_TIMEOUT` control SolidWorks COM operation timeouts.

## MCP Client Config

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "solidworks-mcp",
      "env": {
        "SOLIDWORKS_MCP_BACKEND": "solidworks",
        "SOLIDWORKS_MCP_WORKSPACE_ROOTS": "H:\\\\MCP-AutoCAD;H:\\\\CAD-Work"
      }
    }
  }
}
```

For offline B-Rep exchange workflows:

```json
{
  "mcpServers": {
    "solidworks-headless": {
      "command": "solidworks-mcp",
      "env": {
        "SOLIDWORKS_MCP_BACKEND": "headless",
        "SOLIDWORKS_MCP_WORKSPACE_ROOTS": "H:\\\\MCP-AutoCAD"
      }
    }
  }
}
```

## Tool Groups

System tools: `system_backend_info`, `system_capabilities`, `system_health`, `system_attach`, `system_execute_macro`, `system_run_com_command`.

Document tools: `document_open`, `document_save`, `document_info`, `document_rebuild`, `document_export`.

Metadata tools: `custom_properties_get`, `custom_properties_set`, `bom_read`, `mass_properties`, `material_info`, `configurations`.

Inspection tools: `part_inspect`.

Roadmap workflow tools: `feature_operation`, `assembly_operation`, `drawing_operation`, `appearance_operation`, `import_export_operation`, `semantic_analysis`, `routing_operation`.

Roadmap tools delegate to backend methods when implemented. If the selected backend cannot support an operation, the tool returns an `unsupported` error with a next step. Headless backends must not claim SolidWorks-only capabilities such as feature tree editing, drawing sheets, mates, Hole Wizard, design tables, Pack and Go, or Routing.

## Example Calls

Read backend status:

```json
{
  "backend": "auto"
}
```

Open a STEP file in the selected backend:

```json
{
  "path": "H:\\\\MCP-AutoCAD\\\\examples\\\\bracket.step",
  "document_type": "part",
  "backend": "headless"
}
```

Export the active model:

```json
{
  "path": "H:\\\\MCP-AutoCAD\\\\out\\\\bracket.stl",
  "format": "stl",
  "backend": "headless",
  "options": {
    "tolerance": 0.01
  }
}
```

Inspect the active SolidWorks part:

```json
{
  "backend": "solidworks",
  "detail": "concise",
  "feature_limit": 100,
  "include_custom_properties": true
}
```

Ask SolidWorks for a drawing view operation:

```json
{
  "backend": "solidworks",
  "operation": "insert_view",
  "parameters": {
    "model_path": "H:\\\\CAD-Work\\\\bracket.SLDPRT",
    "view": "front"
  }
}
```

## Phase 2 Workflow Examples

List a part feature tree before deciding what to edit:

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

Create a basic extrude from an existing sketch:

```json
{
  "backend": "solidworks",
  "operation": "extrude_boss",
  "parameters": {
    "sketch": "Sketch1",
    "depth": 0.025,
    "direction": "blind",
    "merge_result": true,
    "name": "Mounting Boss"
  }
}
```

Read an assembly component tree:

```json
{
  "backend": "solidworks",
  "operation": "list_components",
  "parameters": {
    "recursive": true,
    "include_suppressed": false
  }
}
```

Add an assembly mate:

```json
{
  "backend": "solidworks",
  "operation": "add_mate",
  "parameters": {
    "mate_type": "coincident",
    "entities": ["Bracket-1/Front Plane", "Base-1/Top Plane"],
    "alignment": "aligned"
  }
}
```

Create a drawing from a model and insert a view:

```json
{
  "backend": "solidworks",
  "operation": "create_from_model",
  "parameters": {
    "model_path": "H:\\\\CAD-Work\\\\bracket.SLDPRT",
    "template": "A3 landscape",
    "sheet_name": "Sheet1"
  }
}
```

```json
{
  "backend": "solidworks",
  "operation": "insert_view",
  "parameters": {
    "model_path": "H:\\\\CAD-Work\\\\bracket.SLDPRT",
    "view": "isometric",
    "x": 0.22,
    "y": 0.16,
    "scale": "1:2"
  }
}
```

Add a drawing note or smart dimension:

```json
{
  "backend": "solidworks",
  "operation": "add_annotation",
  "parameters": {
    "annotation_type": "note",
    "text": "DEBURR ALL EDGES",
    "x": 0.04,
    "y": 0.03
  }
}
```

```json
{
  "backend": "solidworks",
  "operation": "add_dimension",
  "parameters": {
    "dimension_type": "smart",
    "entities": ["View1/Edge1", "View1/Edge2"],
    "placement": {"x": 0.14, "y": 0.08}
  }
}
```

Control display or capture a viewport:

```json
{
  "backend": "solidworks",
  "operation": "named_view",
  "parameters": {
    "name": "isometric",
    "activate": true
  }
}
```

```json
{
  "backend": "solidworks",
  "operation": "screenshot",
  "parameters": {
    "path": "H:\\\\MCP-AutoCAD\\\\out\\\\bracket-view.png",
    "width": 1600,
    "height": 1000
  }
}
```

Use workflow import/export only when a single `document_open` or `document_export` call is not enough:

```json
{
  "backend": "solidworks",
  "operation": "pack_and_go",
  "parameters": {
    "destination": "H:\\\\CAD-Work\\\\release-package",
    "include_drawings": true,
    "include_simulation": false,
    "flatten": false
  }
}
```

For headless workflows, expect SolidWorks-only operations such as drawings, mates, and feature tree edits to return `unsupported`. Start with `system_capabilities` when the correct backend is unclear.
