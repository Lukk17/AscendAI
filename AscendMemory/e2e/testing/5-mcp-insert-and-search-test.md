# MCP insert and search round-trip: e2e test

## What this verifies

- `POST /mcp` with `method="tools/call"` and `name="memory_insert"` for `user_id="frostyMemoryMcpInsertSearchTest"`
  with text `"My favourite city is Helsinki"` returns HTTP 200 and a JSON-RPC success envelope (`result.content`
  carries the tool's structured return).
- `POST /mcp` with `method="tools/call"` and `name="memory_search"` for the same `user_id` with query
  `"Where do I like to live?"` returns HTTP 200 and at least one structured memory entry whose `memory` field
  contains `"Helsinki"` (case-insensitive).
- Validates that the FastMCP tool layer (`memory_insert`, `memory_search`) is wired to the same memory client as
  REST — a memory inserted via MCP is retrievable via MCP for the same user.
- Both MCP calls share one `Mcp-Session-Id` captured from a single `initialize` handshake.

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

Check Qdrant is reachable.

```powershell
curl -fsS http://localhost:6333/readyz
```

Expect HTTP 200.

## Reset state

Wipe the dedicated test user so the search at the end of the run reflects only what this test inserts.

```powershell
curl -fsS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostyMemoryMcpInsertSearchTest"
```

Expect HTTP 200 with `{"status":"success", ...}`.

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
the next steps.

**Step 2.** Insert the canary memory via MCP.

```powershell
bru run "memory/testing/mcp-insert.yml" --env ascend-local --env-var "mcp_session_id=<paste UUID from step 1>"
```

**Step 3.** Search via MCP for a semantically related query.

```powershell
bru run "memory/testing/mcp-search.yml" --env ascend-local --env-var "mcp_session_id=<paste UUID from step 1>"
```

## Expected

The `initialize` call returns HTTP 200 with an `Mcp-Session-Id: <uuid>` response header.

`mcp-insert.yml` returns HTTP 200. The JSON-RPC response body has a `result` object (no `error` field). The
`result.content` (FastMCP's structured tool return) describes ≥ 1 memory operation — the array is non-empty.

`mcp-search.yml` returns HTTP 200. The JSON-RPC response body has a `result` object whose structured content
contains a non-empty list of memory entries. At least one entry:

- Has a `memory` field (string) containing `"Helsinki"` (case-insensitive).
- Has a `user_id` field equal to `"frostyMemoryMcpInsertSearchTest"`.
- Has a `score` field that is a finite number > 0.

## Fixtures

None.
