# MCP tools/list contract: e2e test

## What this verifies

- The MCP `initialize` handshake against `POST /mcp` returns HTTP 200. The service is stateless and answers
  no `Mcp-Session-Id` response header.
- A subsequent MCP `tools/list` call, sent with any dummy `Mcp-Session-Id` header value, returns HTTP 200 and a
  JSON-RPC `result` containing a non-empty `tools` array.
- The `tools` array contains an entry with `name="web_search"`.
- The `web_search` entry's `inputSchema.properties` advertises a `query` parameter (required) and a `limit`
  parameter.
- The `tools` array contains an entry with `name="web_read"`.
- The `web_read` entry's `inputSchema.properties` advertises a `url` parameter (required) and the optional
  `include_links`, `link_filter`, `heavy_mode` parameters.

This test does NOT exercise SearXNG or any upstream extraction tier - it only verifies the MCP server's
self-description. No outbound HTTPS is required.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string.

Check the ascend-web-hunter server is reachable.

```bash
curl -fsS http://127.0.0.1:7021/health
```

Expect HTTP 200 with `status` `ok`, `service` `ascend-web-hunter` and a non-empty `version`.

## Reset state

None. `tools/list` is a stateless read of the MCP server's tool registry.

## Run

Two steps.

```bash
cd docs/api/request/AscendAI
```

**Step 1.** Send the MCP `initialize` handshake. Expect HTTP 200 with no `Mcp-Session-Id` response header
(the service is stateless; verified by full header dump).

**PowerShell:**

```powershell
curl.exe -fsS -i -X POST http://127.0.0.1:7021/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"e2e","version":"0.1.0"}}}'
```

**Unix:**

```bash
curl -fsS -i -X POST http://127.0.0.1:7021/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"e2e","version":"0.1.0"}}}'
```

No `Mcp-Session-Id` is emitted (the service is stateless), so any dummy value is used as the `mcp_session_id`
env-var in the next step.

**Step 2.** Send the `tools/list` call with a dummy session ID injected:

```bash
bru run "web-hunter/testing/mcp-list-tools.yml" --env ascend-local --env-var "mcp_session_id=00000000000000000000000000000000"
```

## Expected

Step 1 returns HTTP 200 with no `Mcp-Session-Id` response header (the service is stateless).

Step 2 returns HTTP 200. The JSON-RPC response body matches:

- `result.tools` is a non-empty array.
- Some entry has `name` equal to `"web_search"`. Call that entry `T_search`.
  - `T_search.inputSchema.properties.query` exists.
  - `T_search.inputSchema.required` is an array containing `"query"`.
  - `T_search.inputSchema.properties.limit` exists.
- Some entry has `name` equal to `"web_read"`. Call that entry `T_read`.
  - `T_read.inputSchema.properties.url` exists.
  - `T_read.inputSchema.required` is an array containing `"url"`.
  - `T_read.inputSchema.properties.include_links` exists.
  - `T_read.inputSchema.properties.link_filter` exists.
  - `T_read.inputSchema.properties.heavy_mode` exists.

## Fixtures

None.

## Concurrency

`tools/list` is a stateless read of the MCP server's tool registry. It writes no Redis key, reaches no upstream
service, and counts against no rate limit window, because the library limits only `tools/call`. Safe beside every
other spec.

- Serial: false
