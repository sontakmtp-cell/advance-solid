from __future__ import annotations

import time
from pathlib import Path

import pytest

from solidworks_mcp.backends.solidworks import dispatcher as dispatcher_module
from solidworks_mcp.backends.solidworks.dispatcher import SolidWorksComDispatcher
from solidworks_mcp.config import Settings
from solidworks_mcp.core.errors import ErrorCode, McpCadError


class FakePythonCom:
    def __init__(self) -> None:
        self.initialized = 0
        self.uninitialized = 0
        self.pumped = 0

    def CoInitialize(self) -> None:
        self.initialized += 1

    def CoUninitialize(self) -> None:
        self.uninitialized += 1

    def PumpWaitingMessages(self) -> None:
        self.pumped += 1


class FakeComError(Exception):
    def __init__(self, hresult: int, message: str = "call rejected") -> None:
        super().__init__(hresult, message)
        self.hresult = hresult


class FakeDocument:
    def GetTitle(self) -> str:
        return "Part1"

    def GetPathName(self) -> str:
        return r"C:\workspace\Part1.SLDPRT"

    def GetType(self) -> int:
        return 1


class FakeSolidWorks:
    Visible = False
    ActiveDoc = FakeDocument()

    def RevisionNumber(self) -> str:
        return "34.0"

    def VersionHistory(self) -> str:
        return "SolidWorks 2026"


class FakeWin32Client:
    def __init__(self, app: FakeSolidWorks) -> None:
        self.app = app

    def GetActiveObject(self, _prog_id: str) -> FakeSolidWorks:
        return self.app


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        workspace_roots=[tmp_path],
        com_timeout_seconds=0.2,
        com_hard_timeout_seconds=1.0,
    )


def test_dispatcher_attach_uses_sta_and_marshals_app_info(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
):
    fake_pythoncom = FakePythonCom()
    fake_app = FakeSolidWorks()
    monkeypatch.setattr(dispatcher_module, "_import_pythoncom", lambda: fake_pythoncom)
    monkeypatch.setattr(
        dispatcher_module,
        "_import_win32_client",
        lambda: FakeWin32Client(fake_app),
    )

    dispatcher = SolidWorksComDispatcher(settings)
    try:
        result = dispatcher.attach()
    finally:
        dispatcher.stop()

    assert result["attached"] is True
    assert result["revision"] == "34.0"
    assert result["active_document_title"] == "Part1"
    assert fake_pythoncom.initialized == 1


def test_dispatcher_retries_common_server_busy_errors(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
):
    fake_pythoncom = FakePythonCom()
    monkeypatch.setattr(dispatcher_module, "_import_pythoncom", lambda: fake_pythoncom)
    dispatcher = SolidWorksComDispatcher(settings)
    dispatcher._sw_app = object()
    attempts = {"count": 0}

    def flaky(_app: object) -> dict[str, int]:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise FakeComError(dispatcher_module.RPC_E_CALL_REJECTED)
        return {"attempts": attempts["count"]}

    try:
        result = dispatcher.call("flaky", flaky, retry_attempts=1)
    finally:
        dispatcher.stop()

    assert result == {"attempts": 2}
    assert fake_pythoncom.pumped >= 1


def test_dispatcher_soft_timeout_is_actionable(monkeypatch: pytest.MonkeyPatch, settings: Settings):
    fake_pythoncom = FakePythonCom()
    monkeypatch.setattr(dispatcher_module, "_import_pythoncom", lambda: fake_pythoncom)
    dispatcher = SolidWorksComDispatcher(settings)
    dispatcher._sw_app = object()

    def slow(_app: object) -> dict[str, bool]:
        time.sleep(0.5)
        return {"ok": True}

    with pytest.raises(McpCadError) as error:
        dispatcher.call("slow_operation", slow, timeout_seconds=0.05)
    dispatcher.stop()

    assert error.value.code == ErrorCode.TIMEOUT
    assert "restart SolidWorks" in error.value.next_step
    assert error.value.details["operation"] == "slow_operation"


def test_marshal_com_object_returns_stable_dict():
    payload = dispatcher_module.marshal_com_value(FakeDocument())

    assert payload == {
        "com_object": "FakeDocument",
        "GetTitle": "Part1",
        "GetPathName": r"C:\workspace\Part1.SLDPRT",
        "GetType": 1,
    }
