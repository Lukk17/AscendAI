# MCP tools/list contract: e2e test

## What this verifies

- The PaddleOCR MCP server (mounted at `POST /` via FastMCP and reachable on `POST /mcp/`) accepts the standard
  `initialize` handshake and returns an `Mcp-Session-Id` header.
- A follow-up `tools/list` JSON-RPC call returns HTTP 200 with a `result.tools` array.
- That array contains an entry with `name="ocr_process"`.
- The `ocr_process` entry's `inputSchema.properties` advertises `file_path` (required) and `lang` (optional).

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string.

Check the PaddleOCR server is reachable.

```powershell
curl -fsS http://localhost:7022/health
```

Expect HTTP 200 with `"status":"ok"` in the body.

## Reset state

None. `tools/list` is a read-only protocol probe.

## Run

```powershell
cd docs/api/request/AscendAI
```

**Step 1.** Open an MCP session via the `initialize` handshake. Capture the `Mcp-Session-Id` value from the response headers.

```powershell
curl.exe -fsS -i -X POST http://localhost:7022/mcp/ -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},\"clientInfo\":{\"name\":\"e2e\",\"version\":\"0.1.0\"}}}"
```

Look for `Mcp-Session-Id: <uuid>` in the response. Use that UUID as the value of the `mcp_session_id` env-var in the next step.

**Step 2.** Send the `tools/list` call with the captured session ID injected:

```powershell
bru run "paddle-ocr/testing/mcp-list-tools.yml" --env ascend-local --env-var "mcp_session_id=<paste UUID from step 1>"
```

## Expected

- `initialize` returns HTTP 200 with a non-empty `Mcp-Session-Id` header.
- `mcp-list-tools.yml` returns HTTP 200.
- The JSON-RPC `result.tools` array contains an entry with `name="ocr_process"`.
- That entry's `inputSchema.properties` includes a key `file_path` and a key `lang`.
- That entry's `inputSchema.required` array contains `"file_path"`.

## Fixtures

None.
