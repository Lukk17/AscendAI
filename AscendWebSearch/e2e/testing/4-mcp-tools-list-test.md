# MCP tools/list contract: e2e test

## What this verifies

- The MCP `initialize` handshake against `POST /mcp` returns HTTP 200 and an `Mcp-Session-Id` response header
  whose value is a UUID string.
- A subsequent MCP `tools/list` call, sent with the captured `Mcp-Session-Id` header, returns HTTP 200 and a
  JSON-RPC `result` containing a non-empty `tools` array.
- The `tools` array contains an entry with `name="web_search"`.
- The `web_search` entry's `inputSchema.properties` advertises a `query` parameter (required) and a `limit`
  parameter.
- The `tools` array contains an entry with `name="web_read"`.
- The `web_read` entry's `inputSchema.properties` advertises a `url` parameter (required) and the optional
  `include_links`, `link_filter`, `heavy_mode` parameters.

This test does NOT exercise SearXNG or any upstream extraction tier — it only verifies the MCP server's
self-description. No outbound HTTPS is required.

## Prerequisites

Check Bruno CLI is installed.

```powershell
bru --version
```

Expect a version string.

Check the AscendWebSearch server is reachable.

```powershell
curl -fsS http://localhost:7021/health
```

Expect HTTP 200 with `{"status":"ok"}`.

## Reset state

None. `tools/list` is a stateless read of the MCP server's tool registry.

## Run

Two steps.

```powershell
cd docs/api/request/AscendAI
```

**Step 1.** Open an MCP session via the `initialize` handshake. Capture the `Mcp-Session-Id` value from the
response headers.

```powershell
curl.exe -fsS -i -X POST http://localhost:7021/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\",\"capabilities\":{},\"clientInfo\":{\"name\":\"e2e\",\"version\":\"0.1.0\"}}}"
```

Look for `Mcp-Session-Id: <uuid>` in the response. Use that UUID as the value of the `mcp_session_id` env-var in
the next step.

**Step 2.** Send the `tools/list` call with the captured session ID injected:

```powershell
bru run "web-search/testing/mcp-list-tools.yml" --env ascend-local --env-var "mcp_session_id=<paste UUID from step 1>"
```

## Expected

Step 1 returns HTTP 200 and the response headers include an `Mcp-Session-Id` line whose value is a
UUID-formatted string.

Step 2 returns HTTP 200. The JSON-RPC response body matches:

- `result.tools` is a non-empty array.
- Some entry has `name` equal to `"web_search"`. Call that entry `T_search`.
  - `T_search.inputSchema.properties.query` exists.
  - `T_search.inputSchema.required` is an array containing `"query"`.
  - `T_search.inputSchema.properties.limit` exists.
- Some entry has `name` equal to `"web_read"`. Call that entry `T_read`.
  - `T_read.inputSchema.properties.url` exists.
  - `T_read.inputSchema.required` is an array containing `"url"`.
  - `T_read.inputSchema.properties` also advertises at least one of `include_links`, `link_filter`,
    `heavy_mode`.

## Fixtures

None.
