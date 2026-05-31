# MCP web_search happy path: e2e test

## What this verifies

**Note on upstream availability**: SearXNG aggregates from external search engines that rate-limit and CAPTCHA-block per IP. Empty result arrays are an acceptable PASS — they prove the MCP layer + service-to-SearXNG plumbing is healthy. Upstream engine content guarantees are out of scope.


- The MCP `initialize` handshake against `POST /mcp` returns HTTP 200 and an `Mcp-Session-Id` response header
  whose value is a UUID string.
- A subsequent MCP `tools/call` for `web_search` with `arguments={"query": "OpenStreetMap", "limit": 3}` returns
  HTTP 200 and a JSON-RPC `result`.
- The `result` carries the search hits in MCP's standard `content` array. At least one `content` entry has
  `type="text"` (or a structured payload — see Expected for the dual-shape acceptance).
- The decoded payload is a list of ≥ 1 search results. Each result has `title`, `url`, `content` fields, matching
  the same contract as the REST `/api/v1/web/search` endpoint (the two paths share `SearxngClient.search`).
  actually executed against SearXNG rather than returning an empty stub.

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

Check the SearXNG backend is reachable from the host.

```powershell
curl -fsS "http://localhost:9020/search?q=test&format=html"
```

Expect HTTP 200 with HTML content.

## Reset state

None. The MCP `tools/call` for `web_search` is read-only against SearXNG; the host does not write persisted
state.

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

**Step 2.** Send the `tools/call` with the captured session ID injected:

```powershell
bru run "web-search/testing/mcp-search.yml" --env ascend-local --env-var "mcp_session_id=<paste UUID from step 1>"
```

## Expected

Step 1 returns HTTP 200 and the response headers include an `Mcp-Session-Id` line whose value is a
UUID-formatted string.

Step 2 returns HTTP 200. The JSON-RPC response body matches:

- `result.isError` is either absent or equal to `false`.
- The result payload carries the search hits in one of FastMCP's two supported shapes — the runner accepts
  either:
  - **Structured shape:** `result.structuredContent.result` is a JSON array of ≥ 1 result objects, OR
  - **Text shape:** `result.content` is an array with at least one entry whose `type="text"` and whose `text`
    field, when parsed as JSON, is an array of ≥ 1 result objects.
- Every result object in the decoded array has:
  - `title` is a non-empty string.
  - `url` is a non-empty string starting with `http://` or `https://`.
  - `content` is a string (may be empty for entries whose engine did not return a snippet, but the field MUST
    be present).
- The decoded array length is in `[1, 3]` (honours the `limit=3` argument).

Total call duration is typically 1–5 s. A duration > 30 s indicates upstream engines are timing out — investigate
SearXNG health before declaring FAIL.

## Fixtures

None.
