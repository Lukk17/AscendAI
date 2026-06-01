# MCP tools/list discovery: e2e test

## What this verifies

- `POST /mcp` with a JSON-RPC `initialize` payload returns HTTP 200 and a response carrying the `Mcp-Session-Id`
  header (FastMCP's session handshake).
- `POST /mcp` with `method="tools/list"` (carrying the captured `Mcp-Session-Id` header) returns HTTP 200 and a
  JSON-RPC response body whose `result.tools` array advertises the memory tools.
- The advertised tool names include at least one entry matching `*insert*` and one matching `*search*`
  (case-insensitive). This proves the MCP server is up, the FastMCP `@mcp.tool()` registrations are wired, and the
  tool discovery contract works end-to-end.
- **No Qdrant write occurs.** `tools/list` is a pure protocol probe.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string.

Check the AscendMemory server is reachable and ready.

```powershell
curl -fsS http://localhost:7020/health
```

Expect HTTP 200 with `{"status":"ok"}`.

## Reset state

None. `tools/list` is read-only.

## Run

```powershell
cd docs/api/request/AscendAI
```

**Step 1.** Open an MCP session via the `initialize` handshake. Capture the `Mcp-Session-Id` value from the
response headers.

```powershell
curl.exe -fsS -i -X POST http://localhost:7020/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},\"clientInfo\":{\"name\":\"e2e\",\"version\":\"0.1.0\"}}}"
```

Look for `Mcp-Session-Id: <uuid>` in the response. Use that UUID as the value of the `mcp_session_id` env-var in
the next step.

**Step 2.** Send the `tools/list` call with the captured session ID injected.

```powershell
bru run "memory/testing/mcp-list-tools.yml" --env ascend-local --env-var "mcp_session_id=<paste UUID from step 1>"
```

## Expected

The `initialize` call returns HTTP 200 with an `Mcp-Session-Id: <uuid>` response header.

The `mcp-list-tools.yml` call returns HTTP 200. The JSON-RPC `result` object matches:

- `result.tools` is a non-empty array.
- At least one entry's `name` contains the substring `"insert"` (case-insensitive).
- At least one entry's `name` contains the substring `"search"` (case-insensitive).
- Each entry has an `inputSchema` object whose `properties` advertises a `user_id` field (every memory tool is
  user-scoped).

## Fixtures

None.
