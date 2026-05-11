' Minimal VBA scaffold for short-lived manual testing only.
' Prefer a VSTA/.NET add-in for async named-pipe waits and cancellation.

Option Explicit

Sub SolidWorksMcpBridge_RunOnce()
    ' VBA should not run a long blocking pipe listener on the SolidWorks UI thread.
    ' Use this macro only to dispatch a reviewed, short command that was already
    ' passed through the Python-side allowlist and path sandbox.
    MsgBox "SolidWorks MCP bridge scaffold: implement reviewed allowlisted commands in VSTA/.NET for production."
End Sub
