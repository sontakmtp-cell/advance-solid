// Minimal VSTA/.NET named-pipe scaffold for the SolidWorks MCP macro bridge.
// Run pipe waits off the UI-critical path; marshal SolidWorks API calls as needed
// by your add-in architecture. This file is a scaffold, not production security.

using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

public sealed class SolidWorksMcpPipeBridge
{
    private static readonly HashSet<string> Allowed = new HashSet<string>
    {
        "execute_macro",
        "get_custom_properties",
        "set_custom_properties",
        "traverse_feature_tree"
    };

    private readonly object _swApp;
    private readonly string _pipeName;

    public SolidWorksMcpPipeBridge(object swApp, string pipeName = "solidworks_mcp_bridge")
    {
        _swApp = swApp;
        _pipeName = pipeName;
    }

    public async Task RunOnceAsync(CancellationToken cancellationToken)
    {
        using var pipe = new NamedPipeServerStream(
            _pipeName,
            PipeDirection.InOut,
            1,
            PipeTransmissionMode.Message,
            PipeOptions.Asynchronous);

        await pipe.WaitForConnectionAsync(cancellationToken).ConfigureAwait(false);
        using var reader = new StreamReader(pipe);
        using var writer = new StreamWriter(pipe) { AutoFlush = true };

        string? line = await reader.ReadLineAsync().ConfigureAwait(false);
        if (line == null)
        {
            return;
        }

        using JsonDocument request = JsonDocument.Parse(line);
        string id = request.RootElement.GetProperty("id").GetString() ?? "";
        string command = request.RootElement.GetProperty("command").GetString() ?? "";

        object response;
        if (!Allowed.Contains(command))
        {
            response = new { ok = false, id, error = "unsupported", next_step = "Use an allowlisted bridge command." };
        }
        else
        {
            response = ExecuteAllowlisted(command, request.RootElement.GetProperty("payload"));
        }

        await writer.WriteLineAsync(JsonSerializer.Serialize(response)).ConfigureAwait(false);
    }

    private object ExecuteAllowlisted(string command, JsonElement payload)
    {
        // TODO: Implement reviewed SolidWorks API calls here.
        // Keep each command bounded by timeout/cancellation from the caller.
        return new
        {
            ok = false,
            command,
            error = "not_implemented",
            next_step = "Implement this command in the VSTA/.NET add-in and keep it allowlisted."
        };
    }
}
