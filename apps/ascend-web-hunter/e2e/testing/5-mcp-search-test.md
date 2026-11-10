# MCP web_search happy path: e2e test

## What this verifies

- The MCP `initialize` handshake against `POST /mcp` returns HTTP 200. The service is stateless and answers
  no `Mcp-Session-Id` response header.
- A subsequent MCP `tools/call` for `web_search` with `arguments={"query": "OpenStreetMap", "limit": 3}` returns
  HTTP 200 and a JSON-RPC `result`.
- The `result` carries the search hits twice: in MCP's standard `content` array, as an entry with `type="text"`, and
  in `structuredContent.result`. See Expected for how the runner reads them.
- The decoded payload is a list of 1 to 3 search results. Each result has `title`, `url`, `content` fields, matching
  the same contract as the REST `/api/v1/web/search` endpoint (the two paths share `SearxngClient.search`).
- The list is not empty, which proves the tool call actually ran against SearXNG rather than returning an empty
  stub.

An empty result list is BLOCKED only when upstream SearXNG itself returns 0 results for the same query. In every
other case an empty result list fails this test, and it is never a PASS. The reason: SearXNG collects results from
external search engines, and those engines can refuse every request from this address. The service returns only
what it parses from SearXNG, so then it also answers with an empty list and the service is not at fault. The
upstream check in Prerequisites sends the same query as the test call straight to SearXNG and tells the two cases
apart. When it prints `0 results`, mark the run BLOCKED, the same rule as spec 2
([2-search-happy-path-test.md](2-search-happy-path-test.md)). When it prints a non-zero count and the tool call
still answers an empty list, the verdict is FAIL. What the upstream engines return is out of scope.

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

Check the SearXNG backend is reachable from the host.

```bash
curl -fsS "http://localhost:9020/search?q=test&format=html"
```

Expect HTTP 200 with HTML content.

Check that the SearXNG upstream engines return results for the same query the test call sends (`OpenStreetMap`,
language `en-US`, the language the service sends). This query goes to every enabled engine and prints the result
count and the number of engines that did not answer.

PowerShell:

```powershell
$json = curl -fsS "http://localhost:9020/search?q=OpenStreetMap&language=en-US&format=json" | ConvertFrom-Json; "$($json.results.Count) results, $($json.unresponsive_engines.Count) blocked engines"
```

Unix:

```bash
curl -fsS "http://localhost:9020/search?q=OpenStreetMap&language=en-US&format=json" | "$(command -v python3 || command -v python)" -c "import json, sys; d = json.load(sys.stdin); print(f\"{len(d.get('results', []))} results, {len(d.get('unresponsive_engines', []))} blocked engines\")"
```

Expect a non-zero results count. If it prints `0 results`, the upstream engines refuse this address. The service
is healthy, but this test cannot reach its happy path. Mark the run BLOCKED, not FAIL, and run it again when an
upstream engine answers.

## Reset state

The MCP `tools/call` for `web_search` is read-only against SearXNG and writes no search state. It does count
against the caller's rate limit window, which lives in Redis under one key per caller and tool:
`LIMITS:LIMITER/ascend-web-hunter/<caller address>/web_search/<limit>/1/minute`. `<limit>` is the
`RATE_LIMIT_DEFAULT` count (1200 by default). `<caller address>` is the address the container sees for a call from
the host, the gateway of the compose network, which differs from host to host. A window left nearly full by an
earlier run can answer the tool call with a `rate_limited: ` tool error, so delete the key before the run.

List the key first (a read, it deletes nothing) to get the exact key on this host.

```bash
docker exec redis redis-cli --scan --pattern "LIMITS:LIMITER/ascend-web-hunter/*/web_search/*"
```

Expect no line (no window open) or one line naming the key. When the scan printed no line, skip the next step.
Otherwise delete that exact key: replace `<key the scan printed>` with the whole line, unchanged.

```bash
docker exec redis redis-cli DEL "<key the scan printed>"
```

Expect `1`.

## Run

Two steps. From the repository root:

```bash
cd docs/api/request/AscendAI
```

**Step 1.** Send the MCP `initialize` handshake. Expect HTTP 200 with no `Mcp-Session-Id` response header
(the service is stateless; verified by full header dump). The answer is a server-sent event stream
(`Content-Type: text/event-stream`), not a plain JSON body: the JSON-RPC result sits on the `data:` line of the
event, so read it there.

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

**Step 2.** Send the `tools/call` with a dummy session ID injected:

```bash
bru run "web-hunter/testing/mcp-search.yml" --env ascend-local --env-var "mcp_session_id=00000000000000000000000000000000"
```

## Expected

Step 1 returns HTTP 200 with no `Mcp-Session-Id` response header (the service is stateless).

Step 2 returns HTTP 200. The body is a server-sent event whose `data:` line holds the JSON-RPC response, and that
response matches:

- `result.isError` is either absent or equal to `false`.
- The result payload carries the search hits in FastMCP's two shapes. The service answers both in one result
  (measured 2026-11-07: `structuredContent.result` and a `content` entry of `type` `text` hold the same list), and
  the runner decodes the first one it finds:
  - **Structured shape:** `result.structuredContent.result` is a JSON array of ≥ 1 result objects.
  - **Text shape:** `result.content` is an array with at least one entry whose `type="text"` and whose `text`
    field, when parsed as JSON, is an array of ≥ 1 result objects.
- Every result object in the decoded array has:
  - `title` is a non-empty string.
  - `url` is a non-empty string starting with `http://` or `https://`.
  - `content` is a string (may be empty for entries whose engine did not return a snippet, but the field MUST
    be present).
- The decoded array length is in `[1, 3]` (honours the `limit=3` argument).
- An empty decoded array fails the test. When the upstream check in Prerequisites printed `0 results`, the verdict
  is BLOCKED instead, as What this verifies describes.

The service waits at most `SEARCH_TIMEOUT` (10 s by default) for SearXNG. A tool error after about 10 s means the
upstream engines are too slow. Check SearXNG health before declaring FAIL.

## Fixtures

None.

## Concurrency

Writes no `session:*`, tier-memory, crawl or recipe key. The tool call writes only SearXNG's own cache, out of
process, and the caller's `web_search` rate limit window, which its reset deletes and which no other spec of this
suite uses. Safe beside every other spec.

- Serial: false
