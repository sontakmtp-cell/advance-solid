"""STA COM dispatcher for SolidWorks Automation API calls."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from solidworks_mcp.config import Settings
from solidworks_mcp.core.errors import ErrorCode, McpCadError

LOGGER = logging.getLogger(__name__)

RPC_E_CALL_REJECTED = -2147418111
RPC_E_SERVERFAULT = -2147417851
RPC_E_SERVERCALL_RETRYLATER = -2147417846
RPC_E_DISCONNECTED = -2147417848
SERVER_BUSY_HRESULTS = {
    RPC_E_CALL_REJECTED,
    RPC_E_SERVERFAULT,
    RPC_E_SERVERCALL_RETRYLATER,
    RPC_E_DISCONNECTED,
}


@dataclass(frozen=True)
class ComCallOptions:
    timeout_seconds: float
    retry_attempts: int = 4
    retry_delay_seconds: float = 0.35
    hard_timeout_seconds: float | None = None


@dataclass
class ComTask:
    name: str
    func: Callable[[Any], Any]
    options: ComCallOptions
    result_queue: "queue.Queue[tuple[bool, Any]]"


class SolidWorksComDispatcher:
    """Serialize SolidWorks COM calls on one STA worker thread.

    SolidWorks COM objects must be created and used from a COM-initialized STA.
    The dispatcher owns that STA thread and runs every COM operation there.
    A soft timeout returns an actionable MCP error when the worker is busy or a
    call hangs. Python cannot safely abort an in-flight COM call; callers should
    restart SolidWorks or recreate the backend when the hard timeout is exceeded.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._tasks: "queue.Queue[ComTask | None]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._stop_requested = threading.Event()
        self._busy_since: float | None = None
        self._busy_operation: str | None = None
        self._last_attach_error: str | None = None
        self._sw_app: Any | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_requested.clear()
        self._started.clear()
        self._thread = threading.Thread(
            target=self._worker_main,
            name="solidworks-com-sta",
            daemon=True,
        )
        self._thread.start()
        if not self._started.wait(timeout=5.0):
            raise McpCadError(
                ErrorCode.BACKEND_FAULT,
                "SolidWorks COM worker did not initialize in time.",
                "Check pywin32/comtypes installation and retry attach.",
            )
        if self._last_attach_error and not self._thread.is_alive():
            raise McpCadError(
                ErrorCode.DEPENDENCY_MISSING,
                "SolidWorks COM worker exited during initialization.",
                "Install pywin32 on Windows, then retry attach.",
                details={"error": self._last_attach_error},
            )

    def stop(self) -> None:
        self._stop_requested.set()
        self._tasks.put(None)

    def status(self) -> dict[str, Any]:
        busy_for = time.monotonic() - self._busy_since if self._busy_since else 0.0
        return {
            "worker_alive": bool(self._thread and self._thread.is_alive()),
            "connected": self._sw_app is not None,
            "busy_operation": self._busy_operation,
            "busy_for_seconds": round(busy_for, 3),
            "last_attach_error": self._last_attach_error,
        }

    def call(
        self,
        name: str,
        func: Callable[[Any], Any],
        *,
        timeout_seconds: float | None = None,
        retry_attempts: int = 4,
    ) -> Any:
        self.start()
        timeout = timeout_seconds or self.settings.com_timeout_seconds
        retry_delay = min(0.35, timeout / (retry_attempts + 2)) if retry_attempts >= 0 else 0.35
        options = ComCallOptions(
            timeout_seconds=timeout,
            retry_attempts=retry_attempts,
            retry_delay_seconds=retry_delay,
            hard_timeout_seconds=self.settings.com_hard_timeout_seconds,
        )
        result_queue: "queue.Queue[tuple[bool, Any]]" = queue.Queue(maxsize=1)
        self._tasks.put(ComTask(name=name, func=func, options=options, result_queue=result_queue))
        try:
            ok, payload = result_queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise McpCadError(
                ErrorCode.TIMEOUT,
                f"SolidWorks COM operation '{name}' did not finish within {timeout:.1f}s.",
                "Retry after checking SolidWorks UI for modal dialogs. If the backend "
                "remains busy, restart SolidWorks and reattach.",
                details={
                    "operation": name,
                    "soft_timeout_seconds": timeout,
                    "hard_timeout_seconds": options.hard_timeout_seconds,
                    "worker_status": self.status(),
                },
            ) from exc
        if ok:
            return payload
        raise payload

    def attach(self, *, create_if_missing: bool = False, visible: bool = True) -> dict[str, Any]:
        def _attach(_: Any) -> dict[str, Any]:
            sw = self._get_or_create_solidworks(create_if_missing=create_if_missing)
            if visible:
                try:
                    sw.Visible = True
                except Exception:
                    LOGGER.debug("Could not set SolidWorks visibility", exc_info=True)
            self._sw_app = sw
            return self._app_info(sw)

        return self.call(
            "attach",
            _attach,
            timeout_seconds=max(10.0, self.settings.com_timeout_seconds),
        )

    def require_app(self) -> Any:
        if self._sw_app is None:
            raise McpCadError(
                ErrorCode.NOT_CONNECTED,
                "SolidWorks is not attached.",
                "Call solidworks attach/status first, or start SolidWorks and retry.",
            )
        return self._sw_app

    def marshal(self, value: Any, *, max_depth: int = 2) -> Any:
        return marshal_com_value(value, max_depth=max_depth)

    def _worker_main(self) -> None:
        pythoncom = None
        try:
            pythoncom = _import_pythoncom()
            pythoncom.CoInitialize()
            self._started.set()
            while not self._stop_requested.is_set():
                task = self._tasks.get()
                if task is None:
                    break
                self._busy_operation = task.name
                self._busy_since = time.monotonic()
                try:
                    result = self._run_with_retry(task)
                    task.result_queue.put((True, marshal_com_value(result)))
                except Exception as exc:
                    task.result_queue.put((False, self._to_mcp_error(task.name, exc)))
                finally:
                    self._busy_operation = None
                    self._busy_since = None
                    _pump_waiting_messages(pythoncom)
        except Exception as exc:
            self._last_attach_error = str(exc)
            LOGGER.exception("SolidWorks COM worker failed")
            self._started.set()
        finally:
            try:
                if pythoncom:
                    pythoncom.CoUninitialize()
            except Exception:
                LOGGER.debug("COM uninitialize failed", exc_info=True)

    def _run_with_retry(self, task: ComTask) -> Any:
        last_exc: Exception | None = None
        for attempt in range(task.options.retry_attempts + 1):
            try:
                return task.func(self._sw_app)
            except Exception as exc:
                last_exc = exc
                if not _is_server_busy_error(exc) or attempt >= task.options.retry_attempts:
                    raise
                delay = task.options.retry_delay_seconds * (attempt + 1)
                LOGGER.info("SolidWorks COM busy during %s; retrying in %.2fs", task.name, delay)
                time.sleep(delay)
                try:
                    _pump_waiting_messages(_import_pythoncom())
                except Exception:
                    pass
        if last_exc:
            raise last_exc
        raise RuntimeError("COM retry loop exited without result")

    def _get_or_create_solidworks(self, *, create_if_missing: bool) -> Any:
        try:
            win32_client = _import_win32_client()
            try:
                return win32_client.GetActiveObject("SldWorks.Application")
            except Exception:
                if not create_if_missing:
                    raise
                return win32_client.Dispatch("SldWorks.Application")
        except Exception as win32_exc:
            self._last_attach_error = str(win32_exc)
            raise _dependency_or_attach_error(win32_exc) from win32_exc

    def _app_info(self, sw: Any) -> dict[str, Any]:
        return {
            "attached": True,
            "visible": _safe_getattr(sw, "Visible"),
            "revision": _safe_call(sw, "RevisionNumber"),
            "version": _safe_call(sw, "VersionHistory") or _safe_call(sw, "RevisionNumber"),
            "active_document_title": _safe_call(_safe_call(sw, "ActiveDoc"), "GetTitle"),
        }

    def _to_mcp_error(self, operation: str, exc: Exception) -> McpCadError:
        if isinstance(exc, McpCadError):
            return exc
        if _is_server_busy_error(exc):
            return McpCadError(
                ErrorCode.BACKEND_BUSY,
                f"SolidWorks rejected or faulted COM call '{operation}' because "
                "the application is busy.",
                "Close modal dialogs, wait for rebuilds to finish, then retry. "
                "If this repeats, restart SolidWorks and reattach.",
                details={"operation": operation, "exception": _exception_details(exc)},
            )
        return McpCadError(
            ErrorCode.BACKEND_FAULT,
            f"SolidWorks COM operation '{operation}' failed: {exc}",
            "Check the active document and input paths, then retry with a narrower operation.",
            details={"operation": operation, "exception": _exception_details(exc)},
        )


def marshal_com_value(value: Any, *, max_depth: int = 2) -> Any:
    """Convert COM-ish values into JSON-safe primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): marshal_com_value(v, max_depth=max_depth - 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [marshal_com_value(item, max_depth=max_depth - 1) for item in value]
    if max_depth <= 0:
        return repr(value)
    for attr in ("GetTitle", "GetPathName", "GetType"):
        if hasattr(value, attr):
            payload: dict[str, Any] = {"com_object": value.__class__.__name__}
            for method in ("GetTitle", "GetPathName", "GetType"):
                method_value = _safe_call(value, method)
                if method_value is not None:
                    payload[method] = marshal_com_value(method_value, max_depth=max_depth - 1)
            return payload
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)


def _import_pythoncom() -> Any:
    try:
        import pythoncom  # type: ignore[import-not-found]

        return pythoncom
    except Exception as exc:
        try:
            import comtypes  # type: ignore[import-not-found]

            return _ComtypesApartmentAdapter(comtypes)
        except Exception as comtypes_exc:
            raise McpCadError(
                ErrorCode.DEPENDENCY_MISSING,
                "pywin32 pythoncom or comtypes is required for the SolidWorks COM backend.",
                "Install the solidworks extra on Windows: "
                "pip install 'solidworks-mcp[solidworks]'.",
                details={
                    "dependency": "pythoncom|comtypes",
                    "pythoncom_exception": str(exc),
                    "comtypes_exception": str(comtypes_exc),
                },
            ) from comtypes_exc


def _import_win32_client() -> Any:
    try:
        import win32com.client  # type: ignore[import-not-found]

        return win32com.client
    except Exception as exc:
        try:
            import comtypes.client  # type: ignore[import-not-found]

            return _ComtypesClientAdapter(comtypes.client)
        except Exception as comtypes_exc:
            raise McpCadError(
                ErrorCode.DEPENDENCY_MISSING,
                "pywin32 win32com.client or comtypes.client is required for SolidWorks COM attach.",
                "Install the solidworks extra on Windows: "
                "pip install 'solidworks-mcp[solidworks]'.",
                details={
                    "dependency": "win32com.client|comtypes.client",
                    "win32com_exception": str(exc),
                    "comtypes_exception": str(comtypes_exc),
                },
            ) from comtypes_exc


class _ComtypesApartmentAdapter:
    def __init__(self, comtypes_module: Any):
        self._comtypes = comtypes_module

    def CoInitialize(self) -> None:
        self._comtypes.CoInitialize()

    def CoUninitialize(self) -> None:
        self._comtypes.CoUninitialize()

    def PumpWaitingMessages(self) -> None:
        # comtypes has no direct equivalent to pythoncom.PumpWaitingMessages.
        return None


class _ComtypesClientAdapter:
    def __init__(self, client_module: Any):
        self._client = client_module

    def GetActiveObject(self, prog_id: str) -> Any:
        return self._client.GetActiveObject(prog_id)

    def Dispatch(self, prog_id: str) -> Any:
        return self._client.CreateObject(prog_id)


def _dependency_or_attach_error(exc: Exception) -> McpCadError:
    if isinstance(exc, McpCadError):
        return exc
    return McpCadError(
        ErrorCode.NOT_CONNECTED,
        f"Could not attach to a running SolidWorks instance: {exc}",
        "Start SolidWorks manually, ensure the COM server is registered, then call attach again.",
        details={"exception": _exception_details(exc)},
    )


def _exception_details(exc: Exception) -> dict[str, Any]:
    hresult = getattr(exc, "hresult", None)
    if hresult is None and getattr(exc, "args", None):
        for arg in exc.args:
            if isinstance(arg, int):
                hresult = arg
                break
    return {
        "type": exc.__class__.__name__,
        "message": str(exc),
        "hresult": hresult,
    }


def _is_server_busy_error(exc: Exception) -> bool:
    details = _exception_details(exc)
    hresult = details.get("hresult")
    message = str(exc).lower()
    return hresult in SERVER_BUSY_HRESULTS or any(
        marker in message
        for marker in (
            "call was rejected by callee",
            "server threw an exception",
            "server busy",
            "retry later",
            "application is busy",
        )
    )


def _safe_call(obj: Any, method: str, *args: Any) -> Any:
    if obj is None:
        return None
    try:
        candidate = getattr(obj, method)
        return candidate(*args) if callable(candidate) else candidate
    except Exception:
        return None


def _safe_getattr(obj: Any, attr: str) -> Any:
    try:
        return getattr(obj, attr)
    except Exception:
        return None


def _pump_waiting_messages(pythoncom: Any) -> None:
    try:
        pythoncom.PumpWaitingMessages()
    except Exception:
        pass
