# SolidWorks MCP Server

MCP server chạy qua stdio để AI agent thao tác CAD bằng một API thống nhất với hai backend:

- `solidworks`: điều khiển SolidWorks trên Windows qua Python COM Automation, kèm scaffold bridge named pipe cho macro/add-in chạy in-process khi cần.
- `headless`: backend offline cho B-Rep/file exchange cơ bản, dùng CadQuery/OCP nếu được cài; khi thiếu dependency sẽ trả lỗi `unsupported` rõ ràng.

MVP tập trung vào status/health, document open/save/info/rebuild/export, custom properties, mass/material, headless import/analyze/export cơ bản, smoke tests và evaluation read-only.

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

- Main: `pyproject.toml`, `README.md`, `src/solidworks_mcp/config.py`, `src/solidworks_mcp/core/`, `src/solidworks_mcp/schemas/`, project layout, test harness.
- SolidWorks COM Bridge + IPC: `src/solidworks_mcp/backends/solidworks/`, `src/solidworks_mcp/bridges/solidworks_macro/`.
- Custom Properties + BOM: `src/solidworks_mcp/helpers/`.
- Headless 3D Backend: `src/solidworks_mcp/backends/headless/`.
- MCP Tools + Docs/Test: `src/solidworks_mcp/server.py`, `src/solidworks_mcp/tools/`, `docs/`, `evaluations/`, tool tests.
- Drawing & Annotation: `src/solidworks_mcp/domain/drawing.py` and drawing-specific backend helpers/tests.

## Local Run

```powershell
python -m pip install -e .[dev]
python -m solidworks_mcp.server
```

For SolidWorks COM support on Windows:

```powershell
python -m pip install -e .[solidworks,dev]
$env:SOLIDWORKS_MCP_BACKEND = "solidworks"
$env:SOLIDWORKS_MCP_WORKSPACE_ROOTS = "H:\MCP-AutoCAD"
python -m solidworks_mcp.server
```

For headless CAD:

```powershell
python -m pip install -e .[headless,dev]
$env:SOLIDWORKS_MCP_BACKEND = "headless"
python -m solidworks_mcp.server
```

## MCP Client Config

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "python",
      "args": ["-m", "solidworks_mcp.server"],
      "env": {
        "SOLIDWORKS_MCP_BACKEND": "headless",
        "SOLIDWORKS_MCP_WORKSPACE_ROOTS": "H:\\MCP-AutoCAD",
        "SOLIDWORKS_MCP_ALLOW_MACROS": "false"
      }
    }
  }
}
```

## Key Design Notes

- COM Automation is the primary SolidWorks control path. The named pipe bridge is only for allowlisted in-process commands where COM cannot safely reach the needed API surface.
- File and macro operations are restricted to allowlisted workspace roots from `SOLIDWORKS_MCP_WORKSPACE_ROOTS`.
- Headless backend does not claim SolidWorks parity. SolidWorks-only features return `unsupported` with a next-step hint.
- Tool outputs default to concise JSON-compatible dictionaries and can expose more detail via schema flags.

## References

- MCP Python SDK and FastMCP: https://github.com/modelcontextprotocol/python-sdk
- SOLIDWORKS API Help, `IModelDoc2` members and `IModelDocExtension::SaveAs`: https://help.solidworks.com/2025/english/api/sldworksapi/

## Additional Docs

- [Architecture](docs/architecture.md)
- [Usage](docs/usage.md)
- [Tool mapping](docs/tools.md)
- [Read-only smoke evaluations](evaluations/read_only_smoke.xml)
- [MCP client config example](examples/mcp_client_config.json)
