# SolidWorks Macro Bridge Scaffold

This optional bridge is for commands that must execute in the SolidWorks process.
The primary backend path remains Python COM Automation. The bridge path is:

`Python MCP server -> Windows named pipe -> VSTA/.NET add-in or short macro bridge -> SolidWorks API`

Protocol:

- Pipe name defaults to `\\.\pipe\solidworks_mcp_bridge`.
- Request and response are one UTF-8 JSON object per line.
- Requests include `id`, `command`, `payload`, and `timeout_seconds`.
- The bridge must allowlist commands. Initial commands are `execute_macro`,
  `get_custom_properties`, `set_custom_properties`, and `traverse_feature_tree`.
- The listener must not run an infinite blocking wait on the SolidWorks UI thread.
  Use a VSTA/.NET add-in with async pipe waits, cancellation tokens, and marshal
  API work back to the appropriate SolidWorks context.

The sample files are intentionally small scaffolds. Production bridges should add
authentication appropriate to the workstation, audit logging, request size limits,
and stricter payload validation.
