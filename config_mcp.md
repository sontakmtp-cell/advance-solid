
  [mcp_servers.solidworks-mcp]
  command = "H:\\MCP-AutoCAD\\.venv\\Scripts\\python.exe"
  args = ["-m", "solidworks_mcp.server"]

  [mcp_servers.solidworks-mcp.env]
  SOLIDWORKS_MCP_BACKEND = "solidworks"
  SOLIDWORKS_MCP_WORKSPACE_ROOTS = "H:\\MCP-AutoCAD;H:\\CAD-Work"
  SOLIDWORKS_MCP_ALLOW_MACROS = "false"
  SOLIDWORKS_MCP_COM_TIMEOUT = "30"
  SOLIDWORKS_MCP_COM_HARD_TIMEOUT = "120"

  [mcp_servers.solidworks-mcp.tools.system_execute_macro]
  approval_mode = "approve"

  [mcp_servers.solidworks-mcp.tools.system_run_com_command]
  approval_mode = "approve"

  [mcp_servers.solidworks-mcp.tools.document_open]
  approval_mode = "approve"

  [mcp_servers.solidworks-mcp.tools.document_save]
  approval_mode = "approve"

  [mcp_servers.solidworks-mcp.tools.document_rebuild]
  approval_mode = "approve"

  [mcp_servers.solidworks-mcp.tools.document_export]
  approval_mode = "approve"

  [mcp_servers.solidworks-mcp.tools.custom_properties_set]
  approval_mode = "approve"

  [mcp_servers.solidworks-mcp.tools.feature_operation]
  approval_mode = "approve"

  [mcp_servers.solidworks-mcp.tools.assembly_operation]
  approval_mode = "approve"

  [mcp_servers.solidworks-mcp.tools.drawing_operation]
  approval_mode = "approve"

  [mcp_servers.solidworks-mcp.tools.appearance_operation]
  approval_mode = "approve"

  [mcp_servers.solidworks-mcp.tools.import_export_operation]
  approval_mode = "approve"

  [mcp_servers.solidworks-mcp.tools.routing_operation]
  approval_mode = "approve"
