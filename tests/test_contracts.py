from solidworks_mcp.config import load_settings
from solidworks_mcp.core.errors import ErrorCode, McpCadError
from solidworks_mcp.schemas.documents import DocumentInfo


def test_settings_allow_workspace_path():
    settings = load_settings()
    assert settings.ensure_allowed_path(settings.workspace_roots[0]).exists()


def test_error_payload_is_actionable():
    error = McpCadError(ErrorCode.UNSUPPORTED, "x", "Do y")
    payload = error.to_dict()
    assert payload["ok"] is False
    assert payload["error"]["next_step"] == "Do y"


def test_document_info_defaults():
    info = DocumentInfo()
    assert info.document_type == "unknown"
    assert info.configurations == []

